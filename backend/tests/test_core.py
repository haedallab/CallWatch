"""Unit + integration tests. Run from backend/:  pytest -q"""
import os
import tempfile

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp())
os.environ.setdefault("WARM_FEATURED", "0")
os.environ["DEMO_MODE"] = "1"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.services import align, demo, edgar, guidance, pipeline, scoring  # noqa: E402

NVDA_STYLE = """Outlook
NVIDIA's outlook for the third quarter of fiscal 2025 is as follows:
Revenue is expected to be $32.5 billion, plus or minus 2%.
GAAP and non-GAAP gross margins are expected to be 74.4% and 75.0%, respectively, plus or minus 50 basis points.
GAAP and non-GAAP operating expenses are expected to be approximately $4.3 billion and $3.0 billion, respectively.
"""


def by_metric(items, metric, basis=None):
    return [i for i in items if i["metric"] == metric and (basis is None or i["basis"] == basis)]


# ---- extraction ---------------------------------------------------------------------------
def test_plus_minus_and_respectively():
    items = guidance.extract_rules(NVDA_STYLE)
    rev = by_metric(items, "revenue")[0]
    assert rev["low"] == pytest.approx(31.85e9) and rev["high"] == pytest.approx(33.15e9)
    assert rev["quarter"] == 3 and rev["fiscal_year"] == 2025
    gm = by_metric(items, "gross_margin", "non-GAAP")[0]
    assert (gm["low"], gm["high"]) == (pytest.approx(74.5), pytest.approx(75.5))
    assert by_metric(items, "operating_expenses", "GAAP")[0]["mid"] == pytest.approx(4.3e9)


def test_historical_sentences_ignored():
    items = guidance.extract_rules("Revenue for the quarter was $30.0 billion, up 122% from a year ago.")
    assert items == []


def test_ranges_scale_growth_and_basis():
    s = ("For the full year 2025, we expect revenue growth of 10% to 12% and adjusted EPS of $5.20 to $5.40. "
         "We expect capital expenditures between $4 and $4.5 billion for fiscal 2026.")
    items = guidance.extract_rules(s)
    g = by_metric(items, "revenue")[0]
    assert g["kind"] == "growth_yoy" and g["basis"] == "unspecified" and g["fiscal_year"] == 2025
    assert by_metric(items, "eps")[0]["basis"] == "non-GAAP"
    cap = by_metric(items, "capex")[0]
    assert cap["low"] == pytest.approx(4e9) and cap["high"] == pytest.approx(4.5e9) and cap["fiscal_year"] == 2026


def test_spoken_timeframe_carries_and_intro_ignored():
    s = ("Welcome to the third quarter earnings call.\nFor the fourth quarter we expect revenue between "
         "$5.0 billion and $5.2 billion.\nWe expect non-GAAP gross margin of 61% to 62%.")
    gm = by_metric(guidance.extract_rules(s), "gross_margin")[0]
    assert gm["quarter"] == 4


def test_llm_items_must_be_grounded(monkeypatch):
    fake = {"items": [
        {"metric": "revenue", "basis": "GAAP", "kind": "level", "low": 5e9, "high": 5.2e9, "period_type": "Q",
         "quote": "For the fourth quarter we expect revenue between $5.0 billion and $5.2 billion."},
        {"metric": "eps", "basis": "GAAP", "kind": "level", "low": 9.0, "high": 9.0, "period_type": "Q",
         "quote": "We expect EPS of $9.00."},  # not in text -> dropped
        {"metric": "revenue", "basis": "GAAP", "kind": "level", "low": 7e9, "high": 7e9, "period_type": "Q",
         "quote": "For the fourth quarter we expect revenue between $5.0 billion and $5.2 billion."},  # wrong number
    ]}
    monkeypatch.setattr(guidance.llm, "enabled", lambda: True)
    monkeypatch.setattr(guidance.llm, "complete_json", lambda *a, **k: fake)
    text = "For the fourth quarter we expect revenue between $5.0 billion and $5.2 billion."
    out = guidance.extract_llm(text)
    assert len(out) == 1 and out[0]["mid"] == pytest.approx(5.1e9)


# ---- XBRL / calendar / verdict -------------------------------------------------------------
def test_q4_and_ytd_derivation_from_demo_facts():
    facts = demo.DemoSource.facts(demo.company("NBLU").cik)
    s = edgar.quarterly_and_annual(facts, "revenue")
    q4 = [q for q in s["Q"] if q["end"].endswith("-12-31")]
    assert q4 and all(q["derived"] for q in q4)
    cap = edgar.quarterly_and_annual(facts, "capex")
    assert len(cap["Q"]) >= 6  # cash-flow quarters exist only via YTD differences


def test_fiscal_calendar_52_week_year():
    co = demo.company("KAIA")
    rev = edgar.quarterly_and_annual(co.facts(), "revenue")
    cal = align.FiscalCalendar(rev["FY"], [r["end"] for r in rev["Q"]])
    last_fy = rev["FY"][-1]
    assert cal.label(cal.year_of(align._d(last_fy["end"]))) == f"FY{align._d(last_fy['end']).year}"


@pytest.mark.parametrize("actual,status,fav", [(5.3e9, "above", True), (5.1e9, "within", None), (4.9e9, "below", False)])
def test_verdict_range(actual, status, fav):
    it = {"metric": "revenue", "kind": "level", "low": 5.0e9, "high": 5.2e9, "mid": 5.1e9}
    v = align.verdict(it, actual)
    assert v["status"] == status and v["favorable"] == fav


def test_verdict_cost_direction():
    it = {"metric": "operating_expenses", "kind": "level", "low": 1e9, "high": 1e9, "mid": 1e9}
    v = align.verdict(it, 0.9e9)
    assert v["status"] == "below" and v["favorable"] is True and v["kept"]


def test_credibility_score_bounds():
    items = [{"status": "within", "kept": True, "favorable": None, "surprise": 0.2, "surprise_unit": "%"}] * 3 + \
            [{"status": "below", "kept": False, "favorable": False, "surprise": -5.0, "surprise_unit": "%"}]
    s = scoring.credibility(items)
    assert s["hit_rate"] == 0.75 and 0 <= s["score"] <= 100


# ---- end-to-end ---------------------------------------------------------------------------
def test_pipeline_styles_are_recovered():
    scores = {t: pipeline.analyze(t, src=demo.DemoSource, use_llm=False)["score"] for t in demo.COMPANIES}
    assert scores["KAIA"]["style"].startswith("보수적")
    assert scores["HNRT"]["score"] < 60 < scores["NBLU"]["score"]


def test_api_flow():
    c = TestClient(app)
    assert c.get("/health").json()["mode"] == "demo"
    r = c.post("/api/analyze/NBLU").json()
    assert r["guidance"] and r["prices"]
    s = c.get("/api/portfolio/summary").json()
    assert "NBLU" not in s["missing"]
    qa = c.post("/api/qa", json={"ticker": "NBLU", "question": "revenue guidance"}).json()
    assert qa["citations"]
    assert c.get("/api/document", params={"url": "http://169.254.169.254/"}).status_code == 400
    assert c.put("/api/portfolio", json=[{"ticker": "ZZZZ"}]).status_code == 422


def test_real_press_release_noise_is_not_guidance():
    from app.services import guidance
    noise = [
        "Preferred stock, $0.001 par value per share, 100 shares authorized; no shares issued and outstanding 0 0.",
        "Total constant currency revenues of $96.7 billion for the quarter ended December 31, 2024 increased $10.6 billion.",
        "Full-year revenue rose 142% to a record $115.2 billion.",
        "As previously disclosed (1), fourth quarter 2025 results included a notable item of $1.2 billion.",
        "Revenues excluding hedging effect $ 280,876 $ 307,158 $ (1,953) $ 309,111 9 % (1) % 10 %",
    ]
    for s in noise:
        assert guidance.extract_rules("Outlook\n" + s, {"period_type": "Q", "from_heading": True}) == [], s
    g = guidance.extract_rules("we expect to invest approximately $75 billion in capital expenditures in 2025.")
    assert g and g[0]["metric"] == "capex" and g[0]["period_type"] == "FY" and g[0]["fiscal_year"] == 2025

"""Unit + integration tests. Run from backend/:  pytest -q"""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import align, edgar, guidance, pipeline, scoring

from .real_sec import FixtureSource, nvda_facts

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
def test_q4_is_derived_from_the_fiscal_year_total():
    s = edgar.quarterly_and_annual(nvda_facts(), "revenue")
    q4 = next(q for q in s["Q"] if q["end"] == "2026-01-25")
    assert q4["derived"] and q4["value"] == pytest.approx(215938e6 - 44062e6 - 46743e6 - 57006e6)  # $68.1B reported


def test_fiscal_calendar_52_week_year():
    rev = edgar.quarterly_and_annual(nvda_facts(), "revenue")
    cal = align.FiscalCalendar(rev["FY"], [r["end"] for r in rev["Q"]])
    # NVIDIA's fiscal 2026 ended on the last Sunday of January 2026
    assert cal.label(cal.year_of(align._d("2026-01-25"))) == "FY2026"
    assert cal.label(cal.year_of(align._d("2026-04-26"))) == "FY2027"


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
def _gaap(rep, metric):
    """The headline outlook bullet per quarter (e.g. 'Revenue is expected to be ...')."""
    return {g["period"]["label"]: g for g in rep["guidance"]
            if g["metric"] == metric and g["basis"] in ("GAAP", "unspecified") and g.get("period")
            and "expected to be" in g["quote"] and "H20" not in g["quote"][:20]}


def test_nvidia_guidance_against_reported_results():
    """Five real NVIDIA outlooks (Q1 FY26 - Q1 FY27) aligned with what the 10-Q/10-K later reported."""
    rep = pipeline.analyze("NVDA", n_events=5, use_llm=False, with_evidence=False, src=FixtureSource)
    rev = _gaap(rep, "revenue")
    assert {p: g["status"] for p, g in rev.items()} == {
        "FY2026 Q1": "above", "FY2026 Q2": "above", "FY2026 Q3": "above", "FY2026 Q4": "above", "FY2027 Q1": "above"}
    assert rev["FY2026 Q1"]["low"] == pytest.approx(42.14e9) and rev["FY2026 Q1"]["actual"] == pytest.approx(44062e6)
    gm = _gaap(rep, "gross_margin")
    assert gm["FY2026 Q1"]["status"] == "below"          # $4.5B H20 charge: 60.5% vs 70.6% guided
    assert gm["FY2026 Q3"]["status"] == "within"         # 73.4% vs 73.3% +/- 50bp
    assert gm["FY2027 Q1"]["status"] == "within"
    opex = _gaap(rep, "operating_expenses")
    assert opex["FY2026 Q3"]["status"] == "within" and opex["FY2026 Q1"]["favorable"] is True
    nongaap = [g for g in rep["guidance"] if g["basis"] == "non-GAAP" and g["metric"] == "gross_margin"]
    assert nongaap and all(g["basis_mismatch"] for g in nongaap)  # never scored against GAAP XBRL
    h20 = [g for g in rep["guidance"] if "loss in H20 revenue" in g["quote"] and g["metric"] == "revenue"
           and g["low"] < 1e10]
    assert all(g["status"] == "unverifiable" for g in h20)  # "$8.0B H20 loss" is not a revenue forecast
    assert rep["score"]["score"] is not None and rep["score"]["style"].startswith("정확")  # live site shows the same
    assert rep["events"][0]["webcast_url"] == "https://investor.nvidia.com"


def test_api_flow():
    c = TestClient(app)
    assert c.get("/health").json()["mode"] == "live"
    r = c.post("/api/analyze/NVDA?events=5&use_llm=false&evidence=false").json()
    assert r["guidance"] and r["ticker"] == "NVDA"
    c.put("/api/portfolio", json=[{"ticker": "NVDA"}])
    s = c.get("/api/portfolio/summary").json()
    assert "NVDA" not in s["missing"]
    qa = c.post("/api/qa", json={"ticker": "NVDA", "question": "revenue outlook"}).json()
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


def test_segment_guidance_is_reference_only():
    from app.services.guidance import segment_of
    assert segment_of("we expect Intelligent Cloud revenue to grow between 26% and 27%") == "Intelligent Cloud"
    assert segment_of("We expect Data Center revenue of $30 billion") == "Data Center"
    assert segment_of("Revenue is expected to be $43.0 billion, plus or minus 2%.") is None
    assert segment_of("NVIDIA's revenue is expected to be $43.0 billion") is None
    assert segment_of("Total revenue of $58.0 to $61.0 billion") is None


def test_call_transcript_results_vs_expectations_are_not_guidance():
    from app.services.guidance import extract_rules, segment_of
    for s in ["M365 commercial products revenue increased 13%, significantly ahead of expectations driven by higher-than-expected sales.",
              "Operating expenses increased 5%, lower than expected, and operating margins increased 2 points to 45%.",
              "Roughly 40% will be recognized in revenue in the next 12 months, up 21% year-over-year."]:
        assert extract_rules(s) == [], s
    assert segment_of("In Azure, we expect Q3 revenue growth to be between 31% and 32%") == "Azure"
    assert segment_of("M365 commercial cloud revenue growth should be between 14% and 15%") == "M365"
    assert segment_of("Lilly anticipates 2026 revenue of $80 billion") is None


def test_table_rows_naming_the_metric_are_not_segments():
    from app.services.guidance import segment_of
    assert segment_of("Earnings per share (non-GAAP) $22.50 to $24.00") is None
    assert segment_of("Earnings per Share (reported) $22.05 to $23.55") is None

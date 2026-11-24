"""End-to-end company analysis: EDGAR events + transcripts -> guidance -> alignment -> prices -> score."""
from __future__ import annotations

import logging
import time
from datetime import date, timedelta

import pandas as pd

from .. import db
from ..config import settings
from . import edgar, guidance, llm, prices, rag, scoring, transcripts
from .align import Actuals, FiscalCalendar, align_item
from .metrics import METRICS, label

log = logging.getLogger(__name__)

CHART_METRICS = ["revenue", "gross_margin", "operating_margin", "eps", "operating_expenses", "capex",
                 "operating_income", "net_income"]


class LiveSource:
    """Real data: SEC EDGAR + yfinance/Stooq + stored transcripts."""
    mode = "live"
    resolve = staticmethod(edgar.resolve)
    facts = staticmethod(edgar.companyfacts)
    events = staticmethod(lambda cik, n: edgar.earnings_events(cik, limit=n))
    press_release = staticmethod(edgar.press_release)
    filing_for_period = staticmethod(edgar.filing_for_period)
    transcripts = staticmethod(transcripts.all_transcripts)
    closes = staticmethod(prices.closes)

    @staticmethod
    def filing_text(url: str) -> str:
        return edgar.mdna_section(edgar.document_text(url))


def _evidence(src, filing: dict, item: dict) -> list[dict]:
    try:
        text = src.filing_text(filing["url"])
    except edgar.EdgarError:
        return []
    chunks = [{"text": c} for c in rag.chunk_text(text, size=450, overlap=80)]
    q = " ".join(METRICS[item["metric"]]["keywords"][:3]) + " " + item["quote"]
    return [{"text": h["text"][:900], "score": h["score"], "form": filing["form"], "url": filing["url"],
             "filing_date": filing["filing_date"]} for h in rag.rank(q, chunks, k=2)]


def analyze(ticker: str, n_events: int = 8, use_llm: bool = True, with_evidence: bool = True,
            src=None, progress=None, user_id: str | None = None, store_key: str | None = None) -> dict:
    src = src or LiveSource
    t0 = time.time()

    def step(key: str, msg: str, pct: float):
        if progress:
            progress({"step": key, "message": msg, "pct": round(pct, 3)})

    step("resolve", f"{ticker.upper()} 기업 식별 (SEC CIK)", 0.02)
    info = src.resolve(ticker)
    cik = info["cik"]
    warnings: list[str] = []
    step("facts", "XBRL 재무 데이터 불러오기", 0.06)
    facts = src.facts(cik)
    if not facts:
        warnings.append("XBRL companyfacts가 없어 실적 정렬이 제한됩니다.")
    act = Actuals(facts)
    rev = act.series("revenue")
    cal = FiscalCalendar(rev["FY"], [r["end"] for r in rev["Q"]])

    # 1) guidance sources ---------------------------------------------------------------
    step("events", "실적발표(8-K Item 2.02) 목록 찾기", 0.12)
    events = src.events(cik, n_events)
    step("events", f"실적발표 {len(events)}건 확인", 0.15)
    items: list[dict] = []
    corpus: list[dict] = []
    for i, ev in enumerate(events, start=1):
        step("extract", f"{ev['date']} 보도자료에서 가이던스 찾기 ({i}/{len(events)})", 0.15 + 0.45 * i / max(len(events), 1))
        pr = None
        try:
            pr = src.press_release(cik, ev["accession"])
        except edgar.EdgarError as e:
            warnings.append(f"{ev['date']} 보도자료 수집 실패: {e}")
        ev["press_release_url"] = pr["url"] if pr else ev["url"]
        ev["has_outlook"] = bool(pr and pr["outlook"])
        if pr:
            src_text = pr["outlook"] or pr["text"]
            default_tf = {"period_type": "Q", "relative": "current", "text": "", "assumed": True,
                          "from_heading": bool(pr["outlook"])}
            head_tf = guidance.timeframe(pr["outlook"][:250]) if pr["outlook"] else None
            if head_tf:  # e.g. "2025 Guidance" / "Outlook for the first quarter of fiscal 2026"
                default_tf = {**head_tf, "from_heading": True}
            found = guidance.extract(src_text, ticker=info["ticker"], event_date=ev["date"],
                                     source="8-K 보도자료 (Ex-99.1)", source_url=pr["url"],
                                     use_llm=use_llm, default_tf=default_tf)
            for ex in pr.get("extras") or []:
                more = guidance.extract(ex["outlook"] or ex["text"], ticker=info["ticker"], event_date=ev["date"],
                                        source="8-K 첨부자료 (Ex-99)", source_url=ex["url"], use_llm=use_llm,
                                        default_tf=default_tf | {"from_heading": bool(ex["outlook"])})
                found += more
                ev["has_outlook"] = ev["has_outlook"] or bool(ex["outlook"])
                corpus += [{"text": c, "source": "8-K 첨부자료", "date": ev["date"], "url": ex["url"]}
                           for c in rag.chunk_text(ex["text"])[:40]]
            items += found
            ev["n_guidance"] = len(found)
            corpus += [{"text": c, "source": "8-K 보도자료", "date": ev["date"], "url": pr["url"]}
                       for c in rag.chunk_text(pr["text"])[:60]]
    trs = src.transcripts(info["ticker"], user_id)
    if trs:
        step("extract", f"어닝콜 트랜스크립트 {len(trs)}건 읽기", 0.62)
    for tr in trs:
        found = guidance.extract(tr["text"], ticker=info["ticker"], event_date=tr["call_date"],
                                 source="어닝콜 트랜스크립트", source_url="", use_llm=use_llm)
        for f in found:
            f["transcript_id"] = tr["id"]
        items += found
        corpus += [{"text": c, "source": "어닝콜 트랜스크립트", "date": tr["call_date"], "url": ""}
                   for c in rag.chunk_text(tr["text"])]
    items = guidance.dedupe(items)

    # 2) alignment ------------------------------------------------------------------------
    step("align", f"가이던스 {len(items)}건을 회계기간·XBRL 실적과 맞추기", 0.68)
    filings_cache: dict[str, dict | None] = {}
    for it in items:
        it.update(align_item(it, cal, act))
        p = it.get("period")
        if p and it["status"] in ("above", "within", "below"):
            if p["end"] not in filings_cache:
                filings_cache[p["end"]] = src.filing_for_period(cik, p["end"])
            f = filings_cache[p["end"]]
            it["filing"] = f
            if f and with_evidence:
                it["evidence"] = _evidence(src, f, it)
            # outcome revealed at the first earnings release after the period end
            nxt = next((e for e in events if e["date"] > p["end"]), None)
            it["realization_event"] = nxt["date"] if nxt else None
    for f in filings_cache.values():
        if f:
            try:
                txt = src.filing_text(f["url"])
                corpus += [{"text": c, "source": f"{f['form']} MD&A", "date": f["filing_date"], "url": f["url"]}
                           for c in rag.chunk_text(txt)[:80]]
            except edgar.EdgarError:
                pass

    # 3) prices / event study ----------------------------------------------------------------
    step("prices", "주가 반응(이벤트 스터디) 계산", 0.86)
    price_rows: list[dict] = []
    start = (date.fromisoformat(events[0]["date"]) - timedelta(days=260)).isoformat() if events else prices.default_start()
    try:
        px = src.closes(info["ticker"], start)
        bench = src.closes(settings.benchmark, start)
    except Exception as e:  # pragma: no cover - provider failure
        px = bench = pd.Series(dtype=float)
        warnings.append(f"주가 수집 실패: {e}")
    if px.empty or bench.empty:
        warnings.append("주가 데이터를 가져오지 못해 이벤트 스터디를 생략했습니다.")
    else:
        for ev in events:
            ev["reaction"] = prices.event_study(px, bench, ev["date"], ev.get("after_close", True))
        ev_by_date = {e["date"]: e for e in events}
        for it in items:
            if it.get("event_date") in ev_by_date:
                it["announcement"] = ev_by_date[it["event_date"]].get("reaction")
            elif it.get("event_date"):
                it["announcement"] = prices.event_study(px, bench, it["event_date"], True)
            if it.get("realization_event") in ev_by_date:
                it["realization"] = ev_by_date[it["realization_event"]].get("reaction")
        df = pd.concat({"close": px, "bench": bench}, axis=1).dropna()
        price_rows = [{"date": d.strftime("%Y-%m-%d"), "close": round(float(r.close), 4),
                       "bench": round(float(r.bench), 4)} for d, r in df.iterrows()]

    # 4) actual series for charts ----------------------------------------------------------------
    actuals = {}
    for m in CHART_METRICS:
        try:
            s = act.series(m)
        except KeyError:
            continue
        if s["Q"] or s["FY"]:
            actuals[m] = {
                "label": label(m),
                "Q": [{"end": r["end"], "value": r["value"], "derived": r["derived"],
                       "label": _qlabel(cal, r["end"])} for r in s["Q"][-16:]],
                "FY": [{"end": r["end"], "value": r["value"], "label": f"FY{cal.label_year(date.fromisoformat(r['end']))}"}
                       for r in s["FY"][-6:]],
            }

    step("score", "경영진 신뢰도 점수 계산", 0.96)
    report = {
        "ticker": info["ticker"], "name": info["title"], "cik": cik, "mode": src.mode,
        "generated_at": time.strftime("%Y-%m-%d %H:%M"), "elapsed_sec": round(time.time() - t0, 1),
        "llm": settings.llm_label if (use_llm and llm.enabled()) else "rule-based",
        "events": events, "guidance": sorted(items, key=lambda x: (x["event_date"], x["metric"])),
        "score": scoring.credibility(items), "market_response": scoring.market_response(items),
        "actuals": actuals, "prices": price_rows, "warnings": warnings,
    }
    key = store_key or f"{src.mode}:{info['ticker']}"
    report["personal"] = key.count(":") >= 2  # built with this user's own transcripts
    db.save_report(key, report)
    db.cache_set(f"corpus:{key.lower()}", corpus)
    return report


def _qlabel(cal: FiscalCalendar, end: str) -> str:
    found = cal.quarter_of(date.fromisoformat(end))
    return cal.label(*found) if found else end

"""SEC EDGAR connector (free, no key; requires a descriptive User-Agent).

Endpoints used
  https://www.sec.gov/files/company_tickers.json              ticker -> CIK
  https://data.sec.gov/submissions/CIK##########.json         filing index (8-K items, 10-Q/10-K)
  https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json  XBRL actuals
  https://www.sec.gov/Archives/edgar/data/<cik>/<acc>/...     filing documents / exhibits

SEC fair-access policy: <= 10 requests/second. We throttle to ~8/s and cache everything.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from datetime import date, datetime, timedelta

import httpx
from bs4 import BeautifulSoup

from .. import db
from ..config import settings
from .metrics import METRICS

log = logging.getLogger(__name__)

_HEADERS = {"User-Agent": settings.sec_user_agent, "Accept-Encoding": "gzip, deflate"}
_throttle_lock = threading.Lock()
_last_call = [0.0]
_MIN_INTERVAL = 0.125


class EdgarError(RuntimeError):
    pass


def _get(url: str, as_json: bool = True, retries: int = 3):
    for attempt in range(retries):
        with _throttle_lock:
            wait = _MIN_INTERVAL - (time.time() - _last_call[0])
            if wait > 0:
                time.sleep(wait)
            _last_call[0] = time.time()
        try:
            r = httpx.get(url, headers=_HEADERS, timeout=30, follow_redirects=True)
        except httpx.HTTPError as e:
            if attempt == retries - 1:
                raise EdgarError(f"SEC 연결 실패: {e}") from e
            time.sleep(1.5 * (attempt + 1))
            continue
        if r.status_code == 200:
            return r.json() if as_json else r.text
        if r.status_code in (429, 503):
            time.sleep(2 ** (attempt + 1))
            continue
        if r.status_code == 404:
            return None
        raise EdgarError(f"SEC HTTP {r.status_code}: {url}")
    raise EdgarError(f"SEC 요청 한도 초과: {url}")


def _cached(key: str, fn, ttl_hours: float):
    hit = db.cache_get(key, max_age_hours=ttl_hours)
    if hit is not None:
        return hit
    val = fn()
    if val is not None:
        db.cache_set(key, val)
    return val


# ---- ticker / CIK -------------------------------------------------------------

def ticker_map() -> dict[str, dict]:
    def load():
        raw = _get("https://www.sec.gov/files/company_tickers.json")
        return {
            v["ticker"].upper(): {"cik": str(v["cik_str"]).zfill(10), "title": v["title"]}
            for v in (raw or {}).values()
        }

    return _cached("sec:tickers", load, ttl_hours=24 * 7)


def resolve(ticker: str) -> dict:
    t = ticker.upper().strip().replace(".", "-")
    m = ticker_map().get(t)
    if not m:
        raise EdgarError(f"EDGAR에서 '{ticker}' 티커를 찾지 못했습니다 (미국 상장 SEC 제출 기업만 지원).")
    return {"ticker": t, **m}


def search(q: str, limit: int = 10) -> list[dict]:
    q = q.strip().upper()
    if not q:
        return []
    out = []
    for t, v in ticker_map().items():
        title = v["title"].upper()
        if t.startswith(q) or q in title:
            score = 0 if t == q else 1 if t.startswith(q) else 2
            out.append((score, len(t), {"ticker": t, "title": v["title"], "cik": v["cik"]}))
    out.sort(key=lambda x: (x[0], x[1]))
    return [o[2] for o in out[:limit]]


# ---- submissions -----------------------------------------------------------------

def submissions(cik: str) -> dict:
    return _cached(f"sec:subs:{cik}", lambda: _get(f"https://data.sec.gov/submissions/CIK{cik}.json"),
                   ttl_hours=settings.cache_ttl_hours)


def _recent_rows(subs: dict) -> list[dict]:
    r = subs.get("filings", {}).get("recent", {})
    n = len(r.get("form", []))
    keys = ["form", "filingDate", "reportDate", "accessionNumber", "primaryDocument", "items", "acceptanceDateTime"]
    return [{k: (r.get(k) or [""] * n)[i] for k in keys} for i in range(n)]


def _doc_url(cik: str, accession: str, doc: str) -> str:
    return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/{doc}"


def earnings_events(cik: str, limit: int = 8) -> list[dict]:
    """8-K filings with Item 2.02 (Results of Operations) = earnings release dates."""
    rows = [r for r in _recent_rows(submissions(cik)) if r["form"] == "8-K" and "2.02" in (r["items"] or "")]
    out = []
    for r in rows[:limit]:
        acc_time = r.get("acceptanceDateTime") or ""
        after_close = True
        try:
            # acceptanceDateTime is UTC; 20:00 UTC ~= 16:00 ET (EDT) / 15:00 ET (EST)
            ts = datetime.fromisoformat(acc_time.replace("Z", "+00:00"))
            after_close = ts.hour >= 20 or ts.hour < 13
        except ValueError:
            pass
        out.append({
            "date": r["filingDate"],
            "accession": r["accessionNumber"],
            "after_close": after_close,
            "url": _doc_url(cik, r["accessionNumber"], r["primaryDocument"]),
        })
    return sorted(out, key=lambda e: e["date"])


def periodic_filings(cik: str) -> list[dict]:
    rows = [r for r in _recent_rows(submissions(cik)) if r["form"] in ("10-Q", "10-K")]
    return [{
        "form": r["form"], "filing_date": r["filingDate"], "period": r["reportDate"],
        "accession": r["accessionNumber"], "url": _doc_url(cik, r["accessionNumber"], r["primaryDocument"]),
    } for r in rows]


def filing_for_period(cik: str, period_end: str, tolerance_days: int = 10) -> dict | None:
    pe = date.fromisoformat(period_end)
    best = None
    for f in periodic_filings(cik):
        if not f["period"]:
            continue
        d = abs((date.fromisoformat(f["period"]) - pe).days)
        if d <= tolerance_days and (best is None or d < best[0]):
            best = (d, f)
    return best[1] if best else None


# ---- documents ---------------------------------------------------------------------

def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "ix:header", "head"]):
        tag.decompose()
    for br in soup.find_all(["br", "p", "div", "tr", "li", "h1", "h2", "h3", "h4", "table"]):
        br.append("\n")
    text = soup.get_text(" ")
    text = re.sub(r"[ \t\xa0]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


def document_text(url: str, max_chars: int = 600_000) -> str:
    def load():
        html = _get(url, as_json=False)
        return html_to_text(html)[:max_chars] if html else ""

    return _cached(f"sec:doc:{url}", load, ttl_hours=24 * 30) or ""


_EX99 = re.compile(r"ex[-_]?99[-_.]?0?1|ex991|exhibit[-_]?99|ex99", re.I)


def press_release(cik: str, accession: str) -> dict | None:
    """Return {url, text, outlook} for the Ex-99.1 earnings press release of an 8-K."""
    base = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/"
    idx = _cached(f"sec:idx:{accession}", lambda: _get(base + "index.json"), ttl_hours=24 * 30)
    items = (idx or {}).get("directory", {}).get("item", [])
    htm = [i for i in items if i.get("name", "").lower().endswith((".htm", ".html", ".txt"))
           and not i["name"].lower().startswith(accession.replace("-", ""))]
    pick = next((i for i in htm if _EX99.search(i["name"])), None)
    if pick is None and htm:
        pick = max(htm, key=lambda i: int(i.get("size") or 0))
    if pick is None:
        return None
    url = base + pick["name"]
    text = document_text(url)
    return {"url": url, "text": text, "outlook": outlook_section(text)}


_OUTLOOK_HEAD = re.compile(
    r"\n\s*(?:business |financial |fiscal \d{4} |full[- ]year |quarterly )?(outlook|guidance)\b[^\n]{0,80}\n", re.I)
_STOP_HEAD = re.compile(
    r"\n\s*(conference call|webcast|non-gaap (?:financial )?(?:measures|information)|about [A-Z][^\n]{0,40}\n|"
    r"forward[- ]looking statements|safe harbor|use of non-gaap|recent highlights|reconciliation)[^\n]{0,60}\n", re.I)


def outlook_section(text: str, max_chars: int = 4000) -> str:
    m = _OUTLOOK_HEAD.search(text)
    if not m:
        return ""
    chunk = text[m.start(): m.start() + max_chars]
    stop = _STOP_HEAD.search(chunk, 40)
    return (chunk[: stop.start()] if stop else chunk).strip()


_MDNA = re.compile(r"management.{0,3}s discussion and analysis", re.I)
_QQD = re.compile(r"quantitative and qualitative disclosures? about market risk", re.I)


def mdna_section(text: str) -> str:
    """Best-effort MD&A slice (skip the table-of-contents hit)."""
    hits = [m.start() for m in _MDNA.finditer(text)]
    if not hits:
        return text
    start = hits[1] if len(hits) > 1 else hits[0]
    end_m = _QQD.search(text, start + 500)
    end = end_m.start() if end_m else min(len(text), start + 120_000)
    sec = text[start:end]
    return sec if len(sec) > 2000 else text


# ---- XBRL company facts -----------------------------------------------------------------

def companyfacts(cik: str) -> dict:
    return _cached(
        f"sec:facts:{cik}",
        lambda: _get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"),
        ttl_hours=settings.cache_ttl_hours,
    ) or {}


def _days(a: str, b: str) -> int:
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def raw_series(facts: dict, concepts: list[str], unit: str) -> list[dict]:
    """Duration facts merged across concepts (first concept wins), original filing kept."""
    gaap = facts.get("facts", {}).get("us-gaap", {})
    seen: dict[tuple, dict] = {}
    for c in concepts:
        for f in gaap.get(c, {}).get("units", {}).get(unit, []):
            if "start" not in f or f.get("form", "").split("/")[0] not in ("10-Q", "10-K"):
                continue
            key = (f["start"], f["end"])
            prev = seen.get(key)
            if prev is None:
                seen[key] = {**f, "concept": c}
            elif prev["concept"] == c and f.get("filed", "") < prev.get("filed", ""):
                seen[key] = {**f, "concept": c}
    return list(seen.values())


def quarterly_and_annual(facts: dict, metric: str) -> dict[str, list[dict]]:
    """Return {'Q': [...], 'FY': [...]} with Q4 / cash-flow quarters derived from YTD differences."""
    spec = METRICS[metric]
    unit = "USD/shares" if spec["kind"] == "per_share" else "USD"
    rows = raw_series(facts, spec.get("concepts", []), unit)
    q, fy, ytd_by_start = {}, [], {}
    for f in rows:
        d = _days(f["start"], f["end"])
        rec = {"start": f["start"], "end": f["end"], "value": float(f["val"]), "form": f.get("form"),
               "filed": f.get("filed"), "accn": f.get("accn"), "concept": f["concept"], "derived": False}
        if 80 <= d <= 100:
            q[f["end"]] = rec
        if 350 <= d <= 380:
            fy.append(rec)
        if 80 <= d <= 380:
            ytd_by_start.setdefault(f["start"], []).append(rec)
    # derive missing quarters from consecutive YTD values sharing the same fiscal-year start
    for start, recs in ytd_by_start.items():
        recs = sorted({r["end"]: r for r in recs}.values(), key=lambda r: r["end"])
        prev = None
        for r in recs:
            if prev is not None and not any(abs(_days(e, r["end"])) <= 5 for e in q):
                qd = _days(prev["end"], r["end"])
                if 80 <= qd <= 100:
                    q[r["end"]] = {**r, "start": (date.fromisoformat(prev["end"]) + timedelta(days=1)).isoformat(),
                                   "value": r["value"] - prev["value"], "derived": True}
            prev = r
    # last resort for Q4: FY minus the three reported quarters inside that fiscal year
    for y in fy:
        inside = [r for e, r in q.items() if y["start"] <= r["start"] and r["end"] <= y["end"]]
        if len(inside) == 3 and not any(abs(_days(e, y["end"])) <= 5 for e in q):
            last = max(inside, key=lambda r: r["end"])
            q[y["end"]] = {**y, "start": (date.fromisoformat(last["end"]) + timedelta(days=1)).isoformat(),
                           "value": y["value"] - sum(r["value"] for r in inside), "derived": True}
    return {"Q": sorted(q.values(), key=lambda r: r["end"]), "FY": sorted(fy, key=lambda r: r["end"])}

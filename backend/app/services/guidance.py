"""Forward-guidance extraction: deterministic rule engine + optional LLM, cross-validated.

Every item keeps the verbatim quote and its character span so the UI can highlight it,
and every LLM item must be grounded in the source text (no quote -> dropped).
"""
from __future__ import annotations

import hashlib
import json
import logging
import re

from . import llm
from .metrics import KEYWORD_ORDER, METRICS, label

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------------------
# sentence splitting
# ---------------------------------------------------------------------------------------
_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"'(\[])|\n+|(?<=:)\s+(?=[A-Z])")


def sentences(text: str) -> list[tuple[int, int, str]]:
    out, pos = [], 0
    for m in list(_SPLIT.finditer(text)) + [None]:
        end = m.start() if m else len(text)
        raw = text[pos:end]
        s = raw.strip()
        if len(s) > 8:
            st = pos + (len(raw) - len(raw.lstrip()))
            out.append((st, st + len(s), s))
        pos = m.end() if m else len(text)
    return out


# ---------------------------------------------------------------------------------------
# cues, timeframe, basis
# ---------------------------------------------------------------------------------------
_FWD = re.compile(
    r"\b(expect(?:s|ed|ing)?|anticipat(?:e|es|ed|ing)|outlook|guidance|guid(?:e|ing)|forecast(?:s|ing)?|"
    r"project(?:s|ed|ing)?|we see|target(?:ing|s)?|plan(?:s)? to|will be|should be|to be in the range|"
    r"is likely|estimate(?:s|d)?)\b", re.I)
_PAST_ONLY = re.compile(r"\b(was|were|grew|came in|reported|delivered|achieved|ended the quarter)\b", re.I)

_ORD = {"first": 1, "1st": 1, "second": 2, "2nd": 2, "third": 3, "3rd": 3, "fourth": 4, "4th": 4}
_Q_WORD = re.compile(r"\b(first|second|third|fourth|1st|2nd|3rd|4th)\s+(?:fiscal\s+)?quarter(?:\s+of\s+(?:fiscal\s+(?:year\s+)?)?(?:FY)?\s*'?(\d{2,4}))?", re.I)
_Q_CODE = re.compile(r"\bQ([1-4])\s*(?:FY|F)?\s*'?(\d{2,4})?\b", re.I)
_Q_REL = re.compile(r"\b(next|coming|current|this|upcoming)\s+(?:fiscal\s+)?quarter\b", re.I)
_FY = re.compile(
    r"\b(?:full[- ]year(?:\s+(?:of\s+)?(?:fiscal\s+)?'?(\d{4}))?|for the (?:full )?(?:fiscal )?year(?:\s+(\d{4}))?|annual|fiscal(?: year)?\s*'?(\d{2,4})|FY\s*'?(\d{2,4})|"
    r"calendar(?: year)?\s*(\d{4})|(\d{4})\s+(?:outlook|guidance))\b", re.I)
_HALF = re.compile(r"\b(second half|first half|H1|H2|back half)\b", re.I)


def _year(s: str | None) -> int | None:
    if not s:
        return None
    y = int(s)
    return 2000 + y if y < 100 else y


def timeframe(s: str) -> dict | None:
    if _HALF.search(s):
        return {"period_type": "H", "text": _HALF.search(s).group(0)}
    m = _Q_WORD.search(s)
    if m:
        return {"period_type": "Q", "quarter": _ORD[m.group(1).lower()], "fiscal_year": _year(m.group(2)),
                "text": m.group(0)}
    m = _Q_CODE.search(s)
    if m:
        return {"period_type": "Q", "quarter": int(m.group(1)), "fiscal_year": _year(m.group(2)), "text": m.group(0)}
    m = _Q_REL.search(s)
    if m:
        rel = "next" if m.group(1).lower() in ("next", "coming", "upcoming") else "current"
        return {"period_type": "Q", "relative": rel, "text": m.group(0)}
    m = _FY.search(s)
    if m:
        y = next((g for g in m.groups() if g), None)
        return {"period_type": "FY", "fiscal_year": _year(y), "text": m.group(0)}
    return None


def basis(s: str) -> str:
    low = s.lower()
    if re.search(r"non[- ]?gaap|adjusted|excluding", low):
        return "non-GAAP"
    if re.search(r"\bgaap\b", low):
        return "GAAP"
    return "unspecified"


# ---------------------------------------------------------------------------------------
# numbers
# ---------------------------------------------------------------------------------------
_NUM = re.compile(
    r"(?P<cur>\$)?\s?(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"(?:\s*(?P<scale>billion|million|thousand)\b|(?P<sc2>bn|B|M|K)\b)?"
    r"\s*(?P<pct>%|percent\b|percentage points?\b|basis points?\b|bps\b)?")
_SCALE = {"billion": 1e9, "bn": 1e9, "b": 1e9, "million": 1e6, "m": 1e6, "thousand": 1e3, "k": 1e3}
_RANGE_JOIN = re.compile(r"^\s*(?:to|-|–|—|and|through)\s*$", re.I)
_PM = re.compile(r"(?:plus or minus|\+/-|±)\s*(\d+(?:\.\d+)?)\s*(%|percent|basis points?|bps)", re.I)
_NEG = re.compile(r"\b(decline|decrease|down|lower|contract|shrink)\w*", re.I)
_GROWTH = re.compile(r"\b(grow|growth|increase|up|rise|decline|decrease|down|year[- ]over[- ]year|y/y|yoy)\w*", re.I)


def _tokens(seg: str) -> list[dict]:
    toks = []
    for m in _NUM.finditer(seg):
        raw = m.group("num")
        v = float(raw.replace(",", ""))
        pct = (m.group("pct") or "").lower()
        scale = (m.group("scale") or m.group("sc2") or "").lower()
        cur = bool(m.group("cur"))
        # skip years, quarter numbers and other bare integers
        if not cur and not pct and not scale:
            continue
        if pct.startswith(("basis", "bps")):
            typ, v = "pct", v / 100
        elif pct:
            typ = "pct"
        else:
            typ = "usd"
            v *= _SCALE.get(scale, 1)
        toks.append({"v": v, "typ": typ, "scaled": bool(scale), "start": m.start(), "end": m.end(),
                     "bps": pct.startswith(("basis", "bps"))})
    # scale propagation: "$4.2 to $4.4 billion"
    for a, b in zip(toks, toks[1:]):
        if a["typ"] == b["typ"] == "usd" and not a["scaled"] and b["scaled"] and \
                _RANGE_JOIN.match(seg[a["end"]: b["start"]].replace("$", "")):
            a["v"] *= _infer_scale(seg[b["start"]: b["end"]])
            a["scaled"] = True
    return toks


def _infer_scale(tok_text: str) -> float:
    m = _NUM.search(tok_text)
    s = ((m.group("scale") or m.group("sc2") or "") if m else "").lower()
    return _SCALE.get(s, 1)


def parse_values(seg: str, metric: str, ctx: str) -> dict | None:
    kind_m = METRICS[metric]["kind"]
    toks = _tokens(seg)
    pm = _PM.search(seg)
    toks = [t for t in toks if not (pm and pm.start() <= t["start"] < pm.end())]
    if not toks:
        return None
    is_growth = kind_m in ("amount", "per_share") and bool(_GROWTH.search(seg)) and \
        any(t["typ"] == "pct" for t in toks) and not any(t["typ"] == "usd" for t in toks)
    want = "pct" if (kind_m == "ratio" or is_growth) else "usd"
    cand = [t for t in toks if t["typ"] == want and not t["bps"]]
    if not cand:
        return None
    first = cand[0]
    low = high = first["v"]
    if len(cand) > 1:
        between = seg[first["end"]: cand[1]["start"]].replace("$", "")
        if _RANGE_JOIN.match(between):
            high = cand[1]["v"]
    if kind_m == "amount" and want == "usd" and max(low, high) < 1e5:
        return None  # "$5" for an amount metric is almost certainly not the guided level
    if kind_m == "per_share" and max(low, high) > 1e3:
        return None
    if pm and low == high:
        tol = float(pm.group(1))
        unit = pm.group(2).lower()
        if unit.startswith(("basis", "bps")):
            low, high = low - tol / 100, high + tol / 100
        elif want == "pct" and kind_m == "ratio":
            low, high = low - tol, high + tol
        else:
            low, high = low * (1 - tol / 100), high * (1 + tol / 100)
    if is_growth and _NEG.search(seg) and low > 0:
        low, high = -high, -low
    low, high = sorted((low, high))
    unit = "%" if want == "pct" else ("USD/share" if kind_m == "per_share" else "USD")
    return {"kind": "growth_yoy" if is_growth else ("ratio" if kind_m == "ratio" else "level"),
            "low": round(low, 6), "high": round(high, 6), "mid": round((low + high) / 2, 6), "unit": unit}


# ---------------------------------------------------------------------------------------
# metric mentions
# ---------------------------------------------------------------------------------------
def _kw_regex() -> list[tuple[str, re.Pattern]]:
    out = []
    for key in KEYWORD_ORDER:
        kws = sorted(METRICS[key]["keywords"], key=len, reverse=True)
        out.append((key, re.compile(r"\b(" + "|".join(re.escape(k) for k in kws) + r")\b", re.I)))
    return out


_KW = _kw_regex()


def metric_mentions(s: str) -> list[tuple[int, int, str]]:
    taken: list[tuple[int, int, str]] = []
    for key, rx in _KW:
        for m in rx.finditer(s):
            if any(not (m.end() <= a or m.start() >= b) for a, b, _ in taken):
                continue
            taken.append((m.start(), m.end(), key))
    return sorted(taken)


def _item_id(*parts) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:12]


# ---------------------------------------------------------------------------------------
# rule engine
# ---------------------------------------------------------------------------------------
def extract_rules(text: str, default_tf: dict | None = None) -> list[dict]:
    items: list[dict] = []
    ctx_tf = default_tf
    for start, end, s in sentences(text):
        tf = timeframe(s)
        if tf and not re.search(r"\d+(\.\d+)?\s*(%|percent|billion|million)|\$\d", s):
            if _FWD.search(s):  # e.g. "Outlook for the third quarter of fiscal 2025" (not "Welcome to the Q3 call")
                ctx_tf = {**tf, "from_heading": True}
            continue
        if not _FWD.search(s) and not (ctx_tf and ctx_tf.get("from_heading")):
            continue
        if _PAST_ONLY.search(s) and not _FWD.search(s):
            continue
        mentions = [m for m in metric_mentions(s) if not METRICS[m[2]].get("helper")]
        if not mentions:
            continue
        use_tf = tf or ctx_tf
        if tf and tf.get("period_type") != "H":  # spoken guidance: the period carries to the next sentences
            ctx_tf = {**tf, "from_heading": bool(ctx_tf and ctx_tf.get("from_heading"))}
        # "GAAP and non-GAAP X are expected to be A and B, respectively"
        if re.search(r"respectively", s, re.I) and re.search(r"gaap and non-gaap", s, re.I) and len(mentions) >= 1:
            key = mentions[0][2]
            seg = s[mentions[0][1]:]
            toks = [t for t in _tokens(seg) if not t["bps"]]
            want = "pct" if METRICS[key]["kind"] == "ratio" else "usd"
            vals = [t for t in toks if t["typ"] == want][:2]
            pm = _PM.search(seg)
            for b, t in zip(("GAAP", "non-GAAP"), vals):
                pv = _point(t["v"], pm, key, want)
                if pv:
                    items.append(_mk(key, b, pv, use_tf, s, start, end, "rule"))
            continue
        for i, (ms, me, key) in enumerate(mentions):
            nxt = mentions[i + 1][0] if i + 1 < len(mentions) else len(s)
            seg = s[ms:nxt]
            pv = parse_values(seg, key, s)
            if pv is None and i == 0:
                pv = parse_values(s[:ms], key, s)  # "74.5% gross margin"
            if pv:
                prev_end = mentions[i - 1][1] if i else 0
                b = basis(s[max(prev_end, ms - 40):me])
                if b == "unspecified" and re.search(r"(gaap|adjusted) basis", seg, re.I):
                    b = basis(seg)
                if b == "unspecified" and len(mentions) == 1:
                    b = basis(s)
                items.append(_mk(key, b, pv, use_tf, s, start, end, "rule"))
    return dedupe(items)


def _point(v: float, pm, key: str, want: str) -> dict | None:
    kind_m = METRICS[key]["kind"]
    low = high = v
    if pm:
        tol, u = float(pm.group(1)), pm.group(2).lower()
        if u.startswith(("basis", "bps")):
            low, high = v - tol / 100, v + tol / 100
        elif want == "pct":
            low, high = v - tol, v + tol
        else:
            low, high = v * (1 - tol / 100), v * (1 + tol / 100)
    if want == "usd" and kind_m == "amount" and v < 1e5:
        return None
    unit = "%" if want == "pct" else ("USD/share" if kind_m == "per_share" else "USD")
    kind = "ratio" if kind_m == "ratio" else "level"
    return {"kind": kind, "low": round(low, 6), "high": round(high, 6), "mid": round(v, 6), "unit": unit}


def _mk(key, b, pv, tf, quote, start, end, how) -> dict:
    tf = dict(tf or {"period_type": "Q", "relative": "current", "text": "", "assumed": True})
    tf.pop("from_heading", None)
    return {
        "metric": key, "metric_label": label(key), "basis": b, **pv,
        "period_type": tf.get("period_type", "Q"), "quarter": tf.get("quarter"),
        "fiscal_year": tf.get("fiscal_year"), "relative": tf.get("relative"),
        "timeframe_text": tf.get("text", ""), "timeframe_assumed": bool(tf.get("assumed")),
        "quote": quote, "span": [start, end], "extractor": how,
    }


def dedupe(items: list[dict]) -> list[dict]:
    out: list[dict] = []
    for it in items:
        dup = next((o for o in out if o["metric"] == it["metric"] and o["basis"] == it["basis"]
                    and o["kind"] == it["kind"] and o["period_type"] == it["period_type"]
                    and o.get("quarter") == it.get("quarter")
                    and abs(o["mid"] - it["mid"]) <= 0.005 * max(abs(o["mid"]), 1e-9)), None)
        if dup is None:
            out.append(it)
        elif it["extractor"] != dup["extractor"]:
            dup["extractor"] = "rule+llm"
    return out


# ---------------------------------------------------------------------------------------
# LLM engine (grounded)
# ---------------------------------------------------------------------------------------
LLM_SYSTEM = """You extract quantitative FORWARD-LOOKING guidance from earnings materials.
Return JSON: {"items": [ ... ]}. Each item:
  metric: one of %s
  basis: "GAAP" | "non-GAAP" | "unspecified"
  kind: "level" | "growth_yoy" | "ratio"   (ratio = margins in percent)
  low, high: numbers in ABSOLUTE units (USD, not millions; percent as e.g. 74.5). Single value -> low = high.
             Apply "plus or minus" tolerances to produce low/high.
  period_type: "Q" | "FY" | "H"
  quarter: 1-4 or null; fiscal_year: e.g. 2025 or null; relative: "current" | "next" | null
  quote: the EXACT sentence copied verbatim from the text (required).
Only include statements about FUTURE periods with explicit numbers. Never include historical results.
Never invent numbers. Output JSON only.""" % ", ".join(k for k, v in METRICS.items() if not v.get("helper"))


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def extract_llm(text: str) -> list[dict]:
    if not llm.enabled():
        return []
    raw = llm.complete_json(LLM_SYSTEM, f"TEXT:\n{text[:24000]}")
    if not raw:
        return []
    items = raw.get("items", []) if isinstance(raw, dict) else raw
    norm_text = _norm(text)
    out = []
    for it in items or []:
        try:
            key = it["metric"]
            if key not in METRICS or METRICS[key].get("helper"):
                continue
            q = (it.get("quote") or "").strip()
            pos = norm_text.find(_norm(q)[:80]) if q else -1
            if pos < 0:
                log.info("LLM item dropped (quote not grounded): %s", q[:80])
                continue
            low, high = sorted((float(it["low"]), float(it.get("high", it["low"]))))
            # numbers must be traceable: re-parse the quote and require overlap
            rule = parse_values(q, key, q)
            if rule and abs(rule["mid"] - (low + high) / 2) > 0.05 * max(abs(rule["mid"]), 1e-9) and \
                    it.get("kind") != "growth_yoy":
                log.info("LLM item dropped (numbers disagree with quote): %s", q[:80])
                continue
            start = text.lower().find(q[:40].lower())
            span = [start, start + len(q)] if start >= 0 else [0, 0]
            kind = it.get("kind") or "level"
            unit = "%" if kind in ("ratio", "growth_yoy") else (
                "USD/share" if METRICS[key]["kind"] == "per_share" else "USD")
            tf = {"period_type": it.get("period_type") or "Q", "quarter": it.get("quarter"),
                  "fiscal_year": it.get("fiscal_year"), "relative": it.get("relative"), "text": ""}
            if not (tf["quarter"] or tf["fiscal_year"] or tf["relative"]):
                tf.update({"relative": "current", "assumed": True})
            out.append(_mk(key, it.get("basis") or "unspecified",
                           {"kind": kind, "low": low, "high": high, "mid": (low + high) / 2, "unit": unit},
                           tf, q, span[0], span[1], "llm"))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def extract(text: str, *, ticker: str, event_date: str, source: str, source_url: str = "",
            use_llm: bool = True, default_tf: dict | None = None) -> list[dict]:
    items = extract_rules(text, default_tf)
    if use_llm:
        for it in extract_llm(text):
            items.append(it)
        items = dedupe(items)
    for it in items:
        it.update({"ticker": ticker.upper(), "event_date": event_date, "source": source, "source_url": source_url})
        it["id"] = _item_id(ticker, event_date, source, it["metric"], it["basis"], it["period_type"],
                            it.get("quarter"), round(it["mid"], 4))
    return items


def to_json(items: list[dict]) -> str:
    return json.dumps(items, ensure_ascii=False, indent=2)

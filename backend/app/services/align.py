"""Align each guidance item to (1) the fiscal period it refers to, (2) the XBRL actual for that
period, (3) the 10-Q/10-K text that reports it, and (4) the market reaction when it was revealed.
"""
from __future__ import annotations

from datetime import date, timedelta

from .edgar import quarterly_and_annual
from .metrics import DIRECTION, GAAP_SENSITIVE, METRICS

# tolerance for POINT guidance (ranges use their own bounds)
POINT_TOL = {"amount": 0.02, "per_share": 0.01, "ratio": 0.5, "growth_yoy": 1.0}

STATUS_KO = {"above": "상회", "within": "부합", "below": "하회", "pending": "대기", "unverifiable": "검증불가"}


def _d(s: str) -> date:
    return date.fromisoformat(s)


# ---------------------------------------------------------------------------------------
# fiscal calendar
# ---------------------------------------------------------------------------------------
class FiscalCalendar:
    def __init__(self, fy_periods: list[dict], quarter_ends: list[str]):
        fys = sorted({(p["start"], p["end"]) for p in fy_periods}, key=lambda x: x[1])
        self.years: list[tuple[date, date]] = [(_d(a), _d(b)) for a, b in fys]
        if not self.years and quarter_ends:  # no 10-K yet: assume calendar year
            y = _d(quarter_ends[-1]).year
            self.years = [(date(y, 1, 1), date(y, 12, 31))]
        if not self.years:
            y = date.today().year
            self.years = [(date(y, 1, 1), date(y, 12, 31))]
        # extrapolate 2 years forward
        for _ in range(2):
            s, e = self.years[-1]
            if (e + timedelta(days=1)).day == 1:  # calendar month-end fiscal year
                nm = date(e.year + 1, e.month, 1)
                ne = (date(nm.year + (nm.month == 12), nm.month % 12 + 1, 1) - timedelta(days=1))
            else:  # 52/53-week year
                ne = e + timedelta(days=364)
            self.years.append((e + timedelta(days=1), ne))
        self.q_ends = sorted(_d(q) for q in quarter_ends)

    @staticmethod
    def label_year(end: date) -> int:
        return end.year - 1 if end.month == 1 and end.day <= 7 else end.year

    def year_of(self, d: date) -> tuple[date, date] | None:
        for s, e in self.years:
            if s - timedelta(days=3) <= d <= e + timedelta(days=7):
                return s, e
        return None

    def year_by_label(self, fy: int) -> tuple[date, date] | None:
        return next(((s, e) for s, e in self.years if self.label_year(e) == fy), None)

    def quarter_window(self, fy: tuple[date, date], q: int) -> tuple[date, date]:
        s, e = fy
        span = (e - s).days + 1
        qs = s + timedelta(days=round((q - 1) * span / 4))
        qe = s + timedelta(days=round(q * span / 4) - 1) if q < 4 else e
        # snap to a real reported quarter end when we have one
        real = [x for x in self.q_ends if abs((x - qe).days) <= 10]
        if real:
            qe = real[0]
        return qs, qe

    def quarter_of(self, d: date) -> tuple[tuple[date, date], int] | None:
        fy = self.year_of(d)
        if not fy:
            return None
        for q in range(1, 5):
            qs, qe = self.quarter_window(fy, q)
            if qs - timedelta(days=5) <= d <= qe + timedelta(days=5):
                return fy, q
        return fy, 4

    def label(self, fy: tuple[date, date], q: int | None = None) -> str:
        y = self.label_year(fy[1])
        return f"FY{y} Q{q}" if q else f"FY{y}"


def resolve_period(item: dict, cal: FiscalCalendar) -> dict | None:
    ev = _d(item["event_date"])
    pt = item.get("period_type")
    if pt == "Q":
        q, fy_label = item.get("quarter"), item.get("fiscal_year")
        if q and fy_label:
            fy = cal.year_by_label(fy_label)
            if not fy:
                return None
        elif q:
            fy = None
            for cand in cal.years:
                qs, qe = cal.quarter_window(cand, q)
                if qe >= ev - timedelta(days=10):
                    fy = cand
                    break
            if not fy:
                return None
        else:
            # "current/next quarter" or unspecified -> quarter in progress at the event date
            found = cal.quarter_of(ev)
            if not found:
                return None
            fy, q = found
        qs, qe = cal.quarter_window(fy, q)
        return {"type": "Q", "start": qs.isoformat(), "end": qe.isoformat(), "label": cal.label(fy, q)}
    if pt == "FY":
        fy = cal.year_by_label(item["fiscal_year"]) if item.get("fiscal_year") else cal.year_of(ev)
        if not fy:
            return None
        return {"type": "FY", "start": fy[0].isoformat(), "end": fy[1].isoformat(), "label": cal.label(fy)}
    return None


# ---------------------------------------------------------------------------------------
# actuals
# ---------------------------------------------------------------------------------------
class Actuals:
    """Per-metric quarterly / annual series from XBRL, incl. derived ratios."""

    def __init__(self, facts: dict):
        self.facts = facts
        self._cache: dict[str, dict] = {}

    def series(self, metric: str) -> dict[str, list[dict]]:
        if metric in self._cache:
            return self._cache[metric]
        spec = METRICS[metric]
        if spec["kind"] == "ratio":
            num, den = self.series(spec["numerator"]), self.series(spec["denominator"])
            if spec["numerator"] == "gross_profit" and not num["Q"] and not num["FY"]:
                num = self._gross_profit_fallback()
            out = {}
            for k in ("Q", "FY"):
                dmap = {r["end"]: r for r in den[k]}
                out[k] = []
                for r in num[k]:
                    d = dmap.get(r["end"])
                    if d and d["value"]:
                        out[k].append({**r, "value": r["value"] / d["value"] * 100,
                                       "derived": r["derived"] or d["derived"]})
            self._cache[metric] = out
        else:
            self._cache[metric] = quarterly_and_annual(self.facts, metric)
        return self._cache[metric]

    def _gross_profit_fallback(self) -> dict:
        rev, cor = self.series("revenue"), self.series("cost_of_revenue")
        out = {}
        for k in ("Q", "FY"):
            cmap = {r["end"]: r for r in cor[k]}
            out[k] = [{**r, "value": r["value"] - cmap[r["end"]]["value"], "derived": True}
                      for r in rev[k] if r["end"] in cmap]
        return out

    def find(self, metric: str, ptype: str, end: str, tol: int = 10) -> dict | None:
        recs = self.series(metric)["Q" if ptype == "Q" else "FY"]
        e = _d(end)
        best = min(recs, key=lambda r: abs((_d(r["end"]) - e).days), default=None)
        if best and abs((_d(best["end"]) - e).days) <= tol:
            return best
        return None

    def latest_end(self, ptype: str = "Q") -> str | None:
        recs = self.series("revenue")["Q" if ptype == "Q" else "FY"]
        return recs[-1]["end"] if recs else None


# ---------------------------------------------------------------------------------------
# verdict
# ---------------------------------------------------------------------------------------
def verdict(item: dict, actual: float) -> dict:
    kind = item["kind"]
    low, high, mid = item["low"], item["high"], item["mid"]
    mkind = METRICS[item["metric"]]["kind"]
    if kind in ("ratio", "growth_yoy"):
        surprise = actual - mid
        surprise_unit = "pp"
        tol = POINT_TOL[kind]
    else:
        surprise = (actual - mid) / abs(mid) * 100 if mid else 0.0
        surprise_unit = "%"
        tol = POINT_TOL[mkind] * (abs(mid) if mkind == "amount" else 1)
        if mkind == "per_share":
            tol = max(0.01, abs(mid) * 0.01)
    is_range = high - low > 1e-9 * max(abs(mid), 1)
    if is_range:
        # ranges are quoted rounded ("$18.0 to $18.1 billion"): allow half a rounding step at the edges
        edge = 0.0 if kind == "growth_yoy" or mkind != "amount" else 0.003 * abs(mid)
        status = "above" if actual > high + edge else "below" if actual < low - edge else "within"
        pos = (actual - low) / (high - low)
    else:
        status = "above" if actual > mid + tol else "below" if actual < mid - tol else "within"
        pos = None
    direction = DIRECTION.get(item["metric"], 0)
    favorable = None if status == "within" or direction == 0 else (
        (status == "above") == (direction > 0))
    kept = status == "within" or bool(favorable)
    return {"status": status, "status_ko": STATUS_KO[status], "actual": actual,
            "surprise": round(surprise, 3), "surprise_unit": surprise_unit,
            "range_position": None if pos is None else round(pos, 3), "favorable": favorable, "kept": kept}


def align_item(item: dict, cal: FiscalCalendar, act: Actuals, today: date | None = None) -> dict:
    today = today or date.today()
    notes = []
    if item.get("timeframe_assumed"):
        notes.append("기간 표현이 없어 발표 시점에 진행 중인 분기로 가정")
    if item["basis"] == "non-GAAP" and item["metric"] in GAAP_SENSITIVE:
        notes.append("Non-GAAP 가이던스를 GAAP(XBRL) 실적과 비교 - 참고용, 신뢰도 점수에서 제외")
    period = resolve_period(item, cal)
    if item.get("segment"):
        notes.append(f"사업부문({item['segment']}) 가이던스 — 회사 전체 XBRL 실적과 1:1 비교할 수 없어 참고로만 표시")
        return {"period": period, "notes": notes, "basis_mismatch": False,
                "status": "unverifiable", "status_ko": STATUS_KO["unverifiable"]}
    base = {"period": period, "notes": notes, "basis_mismatch": item["basis"] == "non-GAAP"
            and item["metric"] in GAAP_SENSITIVE}
    if period is None:
        notes.append("반기(H1/H2) 또는 해석 불가한 기간 표현")
        return {**base, "status": "unverifiable", "status_ko": STATUS_KO["unverifiable"]}
    rec = act.find(item["metric"], period["type"], period["end"])
    if rec is None:
        latest = act.latest_end(period["type"]) or "0000-01-01"
        if period["end"] > latest or _d(period["end"]) + timedelta(days=60) > today:
            return {**base, "status": "pending", "status_ko": STATUS_KO["pending"],
                    **_progress(item, period, act, today)}
        notes.append("해당 기간의 XBRL 실적 값을 찾지 못함")
        return {**base, "status": "unverifiable", "status_ko": STATUS_KO["unverifiable"]}
    value = rec["value"]
    if item["kind"] == "growth_yoy":
        prev_end = (_d(rec["end"]) - timedelta(days=364)).isoformat()
        prev = act.find(item["metric"], period["type"], prev_end, tol=12)
        if not prev or not prev["value"]:
            notes.append("전년 동기 실적이 없어 성장률 계산 불가")
            return {**base, "status": "unverifiable", "status_ko": STATUS_KO["unverifiable"]}
        value = (rec["value"] / prev["value"] - 1) * 100
    if rec.get("derived"):
        notes.append("분기 값이 누적(YTD) 차감으로 계산됨")
    v = verdict(item, value)
    # a level that misses by more than half almost always means the wrong period or a non-guidance number
    if item["kind"] != "growth_yoy" and item.get("unit") != "%" and v.get("surprise") is not None \
            and abs(v["surprise"]) > 50:
        notes.append(f"실제 {value:,.4g}와 {abs(v['surprise']):.0f}% 차이 — 기간·단위가 다르게 잡혔을 가능성이 커 판정에서 제외")
        return {**base, "status": "unverifiable", "status_ko": STATUS_KO["unverifiable"], "actual": value}
    return {**base, **v, "actual_source": {
        "concept": rec.get("concept"), "form": rec.get("form"), "accn": rec.get("accn"),
        "filed": rec.get("filed"), "period_end": rec["end"], "derived": rec.get("derived", False)}}


def _progress(item: dict, period: dict, act: Actuals, today: date) -> dict:
    """For in-progress annual level guidance: YTD actual vs. elapsed share of the year."""
    if period["type"] != "FY" or item["kind"] != "level" or METRICS[item["metric"]]["kind"] != "amount":
        return {}
    s, e = _d(period["start"]), _d(period["end"])
    qs = [r for r in act.series(item["metric"])["Q"] if s <= _d(r["end"]) <= e]
    if not qs:
        return {}
    ytd = sum(r["value"] for r in qs)
    elapsed = min(1.0, ((_d(qs[-1]["end"]) - s).days + 1) / ((e - s).days + 1))
    prog = ytd / item["mid"] if item["mid"] else 0
    return {"progress": {"ytd": ytd, "through": qs[-1]["end"], "progress_pct": round(prog * 100, 1),
                         "elapsed_pct": round(elapsed * 100, 1),
                         "on_track": prog >= 0.9 * elapsed}}

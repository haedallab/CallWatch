"""Management credibility score - transparent, rule-based, reproducible.

Only verified, basis-comparable items count.
  hit_rate  = share of items whose promise was kept (within range, or beaten on the favourable side)
  severity  = mean |surprise| of misses (unfavourable side), capped at 10% / 3pp
  score     = 100 * (0.7 * hit_rate + 0.3 * (1 - severity_norm))
  style     = conservative (beats > 60% of the time), aggressive (misses > 30%), on-target otherwise
"""
from __future__ import annotations

import statistics as st


def credibility(items: list[dict]) -> dict:
    ver = [i for i in items if i.get("status") in ("above", "within", "below") and not i.get("basis_mismatch")]
    pending = sum(1 for i in items if i.get("status") == "pending")
    unver = sum(1 for i in items if i.get("status") == "unverifiable")
    ref_only = sum(1 for i in items if i.get("basis_mismatch") and i.get("status") in ("above", "within", "below"))
    base = {"n_total": len(items), "n_verified": len(ver), "n_pending": pending, "n_unverifiable": unver,
            "n_reference_only": ref_only}
    if not ver:
        return {**base, "score": None, "grade": "데이터 부족", "style": "판단 보류", "hit_rate": None,
                "beat_share": None, "miss_share": None, "mean_surprise_pct": None, "explain": "검증 가능한 가이던스가 아직 없습니다."}
    kept = [i for i in ver if i["kept"]]
    misses = [i for i in ver if not i["kept"]]
    beats = [i for i in ver if i.get("favorable") is True]

    def sev(i):
        cap = 3.0 if i.get("surprise_unit") == "pp" else 10.0
        return min(abs(i["surprise"]), cap) / cap

    severity = st.mean(sev(i) for i in misses) if misses else 0.0
    hit = len(kept) / len(ver)
    score = round(100 * (0.7 * hit + 0.3 * (1 - severity)))
    beat_share, miss_share = len(beats) / len(ver), len(misses) / len(ver)
    pct = [i["surprise"] for i in ver if i.get("surprise_unit") == "%"]
    style = ("보수적 (Sandbagger)" if beat_share > 0.6 else
             "공격적 (Over-promiser)" if miss_share > 0.3 else "정확 (On-target)")
    grade = "높음" if score >= 80 else "보통" if score >= 60 else "주의"
    return {**base, "score": score, "grade": grade, "style": style, "hit_rate": round(hit, 3),
            "beat_share": round(beat_share, 3), "miss_share": round(miss_share, 3),
            "mean_surprise_pct": round(st.mean(pct), 2) if pct else None,
            "explain": (f"검증된 {len(ver)}건 중 {len(kept)}건 약속 이행(적중률 {hit:.0%}), "
                        f"유리한 방향 상회 {len(beats)}건, 불리한 방향 이탈 {len(misses)}건.")}


def market_response(items: list[dict]) -> dict:
    """Average abnormal reaction on the day the outcome became public, by status."""
    out = {}
    for key in ("kept", "missed"):
        grp = [i for i in items if i.get("status") in ("above", "within", "below")
               and (i["kept"] if key == "kept" else not i["kept"])
               and (i.get("realization") or {}).get("car_m1p1") is not None]
        vals = [i["realization"]["car_m1p1"] for i in grp]
        out[key] = {"n": len(vals), "avg_car_m1p1": round(st.mean(vals), 2) if vals else None}
    return out


def portfolio(reports: list[dict], weights: dict[str, float]) -> dict:
    rows = []
    for r in reports:
        s = r.get("score", {})
        rows.append({"ticker": r["ticker"], "name": r.get("name", ""), "weight": weights.get(r["ticker"], 0.0),
                     "score": s.get("score"), "grade": s.get("grade"), "style": s.get("style"),
                     "n_verified": s.get("n_verified", 0), "n_pending": s.get("n_pending", 0),
                     "hit_rate": s.get("hit_rate")})
    scored = [x for x in rows if x["score"] is not None]
    tw = sum(x["weight"] or 0 for x in scored)
    if scored:
        wavg = (sum(x["score"] * (x["weight"] or 0) for x in scored) / tw) if tw else st.mean(x["score"] for x in scored)
    else:
        wavg = None
    return {"companies": rows, "weighted_score": round(wavg, 1) if wavg is not None else None,
            "n_companies": len(rows), "n_scored": len(scored)}

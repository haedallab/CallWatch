"""Offline demo data source - FICTIONAL companies, synthetic numbers.

Used when DEMO_MODE=1 or when SEC EDGAR is unreachable (e.g. presentation Wi-Fi).
It mimics the real sources closely (XBRL concept names, 10-Q 3-month + YTD facts, 10-K annual
facts without a Q4 fact, cash-flow items reported YTD only, 8-K Ex-99.1 'Outlook' sections,
an earnings-call transcript) so the *real* extraction/alignment engine runs end-to-end.
"""
from __future__ import annotations

import random
from datetime import date, timedelta

import numpy as np
import pandas as pd

TODAY = date.today()

COMPANIES = {
    "KAIA": {"name": "Kaia Semiconductor (가상 기업)", "fy": "jan", "style": "sandbag", "rev0": 9.0e9,
             "g": 0.06, "gm": 64.0, "opex_share": 0.17, "shares": 2.45e9, "capex": 0.04,
             "rev_concept": "Revenues", "fmt": "pm"},
    "NBLU": {"name": "Nubiz Cloud (가상 기업)", "fy": "dec", "style": "accurate", "rev0": 1.15e9,
             "g": 0.035, "gm": 72.0, "opex_share": 0.50, "shares": 3.1e8, "capex": 0.06,
             "rev_concept": "RevenueFromContractWithCustomerExcludingAssessedTax", "fmt": "range_m"},
    "HNRT": {"name": "Hanaro Retail Tech (가상 기업)", "fy": "jun", "style": "aggressive", "rev0": 4.2e9,
             "g": 0.015, "gm": 38.0, "opex_share": 0.22, "shares": 8.0e8, "capex": 0.05,
             "rev_concept": "Revenues", "fmt": "q_code"},
    "ORBT": {"name": "Orbit Motors (가상 기업)", "fy": "dec", "style": "mixed", "rev0": 6.5e9,
             "g": 0.025, "gm": 21.0, "opex_share": 0.12, "shares": 1.2e9, "capex": 0.09,
             "rev_concept": "RevenueFromContractWithCustomerExcludingAssessedTax", "fmt": "fy_growth"},
}
BIAS = {"sandbag": 0.045, "accurate": 0.0, "aggressive": -0.035, "mixed": 0.005}


# ---------------------------------------------------------------------------------------
# calendars
# ---------------------------------------------------------------------------------------
def _last_sunday_jan(y: int) -> date:
    d = date(y, 1, 31)
    return d - timedelta(days=(d.weekday() + 1) % 7)


def _fy_bounds(kind: str, label_year: int) -> tuple[date, date]:
    if kind == "dec":
        return date(label_year, 1, 1), date(label_year, 12, 31)
    if kind == "jun":
        return date(label_year - 1, 7, 1), date(label_year, 6, 30)
    end = _last_sunday_jan(label_year)
    return _last_sunday_jan(label_year - 1) + timedelta(days=1), end


def _quarters(kind: str, fy_label: int) -> list[tuple[date, date]]:
    s, e = _fy_bounds(kind, fy_label)
    if kind == "jan":
        out, cur = [], s
        for q in range(4):
            qe = e if q == 3 else cur + timedelta(days=90)
            out.append((cur, qe))
            cur = qe + timedelta(days=1)
        return out
    return [(_add_months(s, 3 * q), _add_months(s, 3 * (q + 1)) - timedelta(days=1)) for q in range(4)]


def _add_months(d: date, n: int) -> date:
    m = d.month - 1 + n
    return date(d.year + m // 12, m % 12 + 1, 1)


def _fmt_money(v: float) -> str:
    return f"${v / 1e9:.2f} billion" if v >= 1e9 else f"${v / 1e6:.0f} million"


# ---------------------------------------------------------------------------------------
# synthetic company
# ---------------------------------------------------------------------------------------
class _Company:
    def __init__(self, ticker: str):
        self.t = ticker
        self.c = COMPANIES[ticker]
        self.rng = random.Random(sum(map(ord, ticker)) * 31 + 7)
        self._build()

    def _build(self):
        c, rng = self.c, self.rng
        quarters = []
        for fy in range(TODAY.year - 2, TODAY.year + 2):
            for qi, (qs, qe) in enumerate(_quarters(c["fy"], fy), start=1):
                quarters.append({"fy": fy, "q": qi, "start": qs, "end": qe})
        quarters = [q for q in quarters if q["end"] >= date(TODAY.year - 2, 7, 1)]
        # reported = quarter end + 35d already passed; keep one in-progress quarter
        self.reported = [q for q in quarters if q["end"] + timedelta(days=35) <= TODAY]
        self.current = next(q for q in quarters if q["end"] + timedelta(days=35) > TODAY)
        self.next_q = quarters[quarters.index(self.current) + 1]
        rev = c["rev0"]
        for q in self.reported + [self.current]:
            rev *= 1 + c["g"] + rng.gauss(0, 0.015)
            gm = c["gm"] + rng.gauss(0, 0.8)
            opex = rev * c["opex_share"] * (1 + rng.gauss(0, 0.03))
            op = rev * gm / 100 - opex
            ni = op * 0.82
            q.update(rev=rev, gm=gm, gp=rev * gm / 100, opex=opex, op=op, ni=ni,
                     eps=ni / c["shares"], capex=rev * c["capex"] * (1 + rng.gauss(0, 0.1)))
        # guidance for each quarter, issued at the earnings release of the previous quarter
        bias = BIAS[c["style"]]
        for q in self.reported + [self.current]:
            b = bias + (rng.gauss(0, 0.025) if c["style"] == "mixed" else rng.gauss(0, 0.008))
            if c["style"] == "aggressive" and rng.random() < 0.35:
                b = rng.uniform(-0.005, 0.01)
            q["g_rev"] = q["rev"] / (1 + b)
            q["g_gm"] = q["gm"] - b * 30 + rng.gauss(0, 0.2)
            q["g_opex"] = q["opex"] * (1 + rng.gauss(0, 0.015))
            q["g_eps_lo"] = q["eps"] / (1 + b) * 0.97
            q["g_eps_hi"] = q["eps"] / (1 + b) * 1.01
            q["g_om_lo"] = (q["op"] / q["rev"] * 100) - b * 40 - 0.6
            q["g_om_hi"] = q["g_om_lo"] + 1.0
        self.events = []
        for i, q in enumerate(self.reported):
            target = self.reported[i + 1] if i + 1 < len(self.reported) else self.current
            ev_date = q["end"] + timedelta(days=28)
            while ev_date.weekday() >= 5:
                ev_date += timedelta(days=1)
            self.events.append({"date": ev_date.isoformat(), "accession": f"demo-{self.t}-{i:02d}",
                                "after_close": True, "reported": q, "target": target,
                                "url": f"demo://{self.t}/8-K/{ev_date.isoformat()}"})

    # ---- XBRL --------------------------------------------------------------------------
    def facts(self) -> dict:
        c = self.c
        concepts = {c["rev_concept"]: "rev", "GrossProfit": "gp", "OperatingExpenses": "opex",
                    "OperatingIncomeLoss": "op", "NetIncomeLoss": "ni"}
        gaap: dict = {}
        by_fy: dict[int, list[dict]] = {}
        for q in self.reported:
            by_fy.setdefault(q["fy"], []).append(q)

        def add(concept, unit, start, end, val, form, filed, fy, fp):
            gaap.setdefault(concept, {"units": {}})["units"].setdefault(unit, []).append(
                {"start": start.isoformat(), "end": end.isoformat(), "val": round(val, 4 if unit != "USD" else 0),
                 "accn": f"demo-{self.t}-{end.isoformat()}", "fy": fy, "fp": fp, "form": form,
                 "filed": filed.isoformat()})

        for fy, qs in by_fy.items():
            fy_start = _fy_bounds(c["fy"], fy)[0]
            for q in qs:
                filed = q["end"] + timedelta(days=35 if q["q"] < 4 else 55)
                ytd = [x for x in qs if x["q"] <= q["q"]]
                if q["q"] < 4:
                    for con, k in concepts.items():
                        add(con, "USD", q["start"], q["end"], q[k], "10-Q", filed, fy, f"Q{q['q']}")
                        if q["q"] > 1:
                            add(con, "USD", fy_start, q["end"], sum(x[k] for x in ytd), "10-Q", filed, fy, f"Q{q['q']}")
                    add("EarningsPerShareDiluted", "USD/shares", q["start"], q["end"], q["eps"], "10-Q", filed, fy,
                        f"Q{q['q']}")
                    # cash-flow items: YTD only, like real 10-Qs
                    add("PaymentsToAcquirePropertyPlantAndEquipment", "USD", fy_start, q["end"],
                        sum(x["capex"] for x in ytd), "10-Q", filed, fy, f"Q{q['q']}")
                else:
                    for con, k in concepts.items():
                        add(con, "USD", fy_start, q["end"], sum(x[k] for x in ytd), "10-K", filed, fy, "FY")
                    add("EarningsPerShareDiluted", "USD/shares", fy_start, q["end"], sum(x["eps"] for x in ytd),
                        "10-K", filed, fy, "FY")
                    add("PaymentsToAcquirePropertyPlantAndEquipment", "USD", fy_start, q["end"],
                        sum(x["capex"] for x in ytd), "10-K", filed, fy, "FY")
        return {"cik": self.cik, "entityName": self.c["name"], "facts": {"us-gaap": gaap}}

    @property
    def cik(self) -> str:
        return str(9_000_000_000 + sum(map(ord, self.t))).zfill(10)

    # ---- press releases ----------------------------------------------------------------------
    def _qname(self, q) -> str:
        return ["first", "second", "third", "fourth"][q["q"] - 1]

    def press_release(self, ev: dict) -> dict:
        c, r, t = self.c, ev["reported"], ev["target"]
        name = c["name"].split(" (")[0]
        prev_rev = r["rev"] / (1 + c["g"])
        lines = [
            f"{name} Reports Financial Results for the {self._qname(r).title()} Quarter of Fiscal {r['fy']}",
            "",
            f"Revenue was {_fmt_money(r['rev'])}, up {((r['rev'] / prev_rev) - 1) * 100:.0f}% from the previous quarter.",
            f"GAAP gross margin was {r['gm']:.1f}% and GAAP earnings per diluted share were ${r['eps']:.2f}.",
            f"\"We delivered a solid quarter and continue to invest for growth,\" said the Chief Executive Officer of {name}.",
            "",
        ]
        fmt = c["fmt"]
        tq = self._qname(t)
        if fmt == "pm":
            lines += ["Outlook", "",
                      f"{name}'s outlook for the {tq} quarter of fiscal {t['fy']} is as follows:",
                      f"Revenue is expected to be {_fmt_money(t['g_rev'])}, plus or minus 2%.",
                      f"GAAP and non-GAAP gross margins are expected to be {t['g_gm']:.1f}% and {t['g_gm'] + 1.2:.1f}%, "
                      f"respectively, plus or minus 50 basis points.",
                      f"GAAP operating expenses are expected to be approximately {_fmt_money(t['g_opex'])}."]
        elif fmt == "range_m":
            lo, hi = t["g_rev"] * 0.99, t["g_rev"] * 1.01
            lines += ["Business Outlook", "",
                      f"For the {tq} quarter of fiscal {t['fy']}, the company expects:",
                      f"Total revenue between {_fmt_money(lo)} and {_fmt_money(hi)}.",
                      f"Non-GAAP diluted EPS between ${t['g_eps_lo']:.2f} and ${t['g_eps_hi']:.2f}.",
                      f"GAAP operating margin is expected to be {t['g_om_lo']:.1f}% to {t['g_om_hi']:.1f}%."]
        elif fmt == "q_code":
            lo, hi = t["g_rev"] * 0.985, t["g_rev"] * 1.015
            yy = str(t["fy"])[2:]
            lines += ["Guidance", "",
                      f"For Q{t['q']} FY{yy}, we expect revenue in the range of ${lo / 1e9:.2f} to ${hi / 1e9:.2f} billion.",
                      f"We expect GAAP diluted EPS of ${t['g_eps_lo']:.2f} to ${t['g_eps_hi']:.2f} for Q{t['q']} FY{yy}.",
                      f"Operating margin for Q{t['q']} FY{yy} is expected to be {t['g_om_lo']:.1f}% to {t['g_om_hi']:.1f}%."]
        else:  # fy_growth
            lines += ["Outlook", "",
                      f"For the {tq} quarter of {t['fy']}, revenue is expected to be {_fmt_money(t['g_rev'])}, plus or minus 3%.",
                      f"We expect GAAP gross margin of {t['g_gm'] - 0.5:.1f}% to {t['g_gm'] + 0.5:.1f}% for the {tq} quarter."]
            if t["q"] == 1:
                fy = t["fy"]
                fyq = [q for q in self.reported + [self.current] if q["fy"] == fy]
                prev = [q for q in self.reported if q["fy"] == fy - 1]
                if len(prev) == 4:
                    est = sum(q["g_rev"] for q in fyq) + (4 - len(fyq)) * fyq[-1]["g_rev"] * 1.02
                    g = (est / sum(q["rev"] for q in prev) - 1) * 100
                    lines.append(f"For the full year {fy}, we expect revenue growth of {g - 1:.0f}% to {g + 1:.0f}% "
                                 f"year-over-year.")
                cap = sum(q["rev"] * self.c["capex"] for q in fyq) * 4 / max(len(fyq), 1)
                lines.append(f"We plan capital expenditures of approximately {_fmt_money(cap)} for fiscal {fy}.")
        lines += ["", "Conference Call and Webcast",
                  f"{name} will host a conference call today to discuss these results.",
                  "", "Forward-Looking Statements",
                  "This press release contains forward-looking statements that involve risks and uncertainties."]
        text = "\n".join(lines)
        from .edgar import outlook_section

        return {"url": ev["url"], "text": text, "outlook": outlook_section(text)}

    def mdna(self, q) -> str:
        name = self.c["name"].split(" (")[0]
        paras = [
            "Management's Discussion and Analysis of Financial Condition and Results of Operations",
            f"Overview. {name} designs and sells products through direct and channel partners worldwide. "
            "Our fiscal year and quarters are described in Note 1 of the condensed consolidated financial statements.",
            f"Revenue. Revenue for the {self._qname(q)} quarter of fiscal {q['fy']} was {_fmt_money(q['rev'])}, "
            f"compared with guidance and prior-period levels, driven primarily by higher unit volumes and pricing.",
            f"Gross margin. Gross margin was {q['gm']:.1f}% for the quarter, reflecting product mix and "
            "manufacturing cost changes.",
            f"Operating expenses. Operating expenses were {_fmt_money(q['opex'])}, reflecting headcount growth "
            "and compensation-related costs.",
            f"Net income and earnings per share. Net income was {_fmt_money(q['ni'])}, or ${q['eps']:.2f} per diluted share.",
            f"Liquidity. Purchases of property and equipment were {_fmt_money(q['capex'])} in the quarter.",
            "Critical accounting estimates are described in our most recent Annual Report on Form 10-K.",
        ]
        return "\n\n".join(paras)


_CACHE: dict[str, _Company] = {}


def company(t: str) -> _Company:
    if t not in _CACHE:
        _CACHE[t] = _Company(t)
    return _CACHE[t]


def _transcript(t: str) -> list[dict]:
    if t != "ORBT":
        return []
    co = company(t)
    ev = co.events[-1]
    tq, nq = co.current, co.next_q
    text = f"""Operator: Good afternoon and welcome to the Orbit Motors earnings conference call (fictional demo transcript).

Chief Financial Officer: Thank you. Revenue for the quarter was {_fmt_money(ev['reported']['rev'])}, ahead of our plan.
Looking ahead, for the {co._qname(tq)} quarter we expect revenue to be {_fmt_money(tq['g_rev'] * 1.005)}, plus or minus 3%.
We expect operating margin in the range of {tq['op'] / tq['rev'] * 100 - 0.8:.1f}% to {tq['op'] / tq['rev'] * 100 + 0.4:.1f}% for the {co._qname(tq)} quarter.
In the second half we expect gross margin to improve by roughly 150 basis points as the new plant ramps.
We continue to target capital expenditures of approximately {_fmt_money(tq['capex'] * 4)} for fiscal {tq['fy']}.

Question-and-Answer Session

Analyst: Can you talk about pricing pressure in the {co._qname(nq)} quarter?
Chief Executive Officer: We see pricing stabilizing. We expect adjusted EPS to be ${tq['eps'] * 0.98:.2f} to ${tq['eps'] * 1.04:.2f} for the {co._qname(tq)} quarter.
Analyst: Thank you.
"""
    return [{"id": f"demo:{t}:{ev['date']}", "ticker": t, "call_date": ev["date"], "source": "demo", "text": text}]


def _prices(t: str, start: str) -> pd.Series:
    days = pd.bdate_range(start=start, end=TODAY.isoformat())
    rng = np.random.default_rng(sum(map(ord, t)) * 17)
    mkt = np.random.default_rng(42).normal(0.0004, 0.009, len(days))
    if t == "SPY":
        r = mkt
    else:
        co = company(t)
        r = 0.0002 + 1.15 * mkt + rng.normal(0, 0.016, len(days))
        for ev in co.events:
            rep = ev["reported"]
            surprise = rep["rev"] / rep["g_rev"] - 1
            pos = days.searchsorted(pd.Timestamp(ev["date"]), side="right")
            if pos < len(days):
                r[pos] += 1.6 * surprise + rng.normal(0, 0.01)
    px = 100 * np.exp(np.cumsum(r))
    return pd.Series(px, index=days)


class DemoSource:
    mode = "demo"

    @staticmethod
    def resolve(ticker: str) -> dict:
        t = ticker.upper()
        if t not in COMPANIES:
            from .edgar import EdgarError

            raise EdgarError(f"데모 모드에서는 가상 기업 {', '.join(COMPANIES)}만 분석할 수 있습니다.")
        return {"ticker": t, "cik": company(t).cik, "title": COMPANIES[t]["name"]}

    @staticmethod
    def facts(cik: str) -> dict:
        t = next(k for k in COMPANIES if company(k).cik == cik)
        return company(t).facts()

    @staticmethod
    def events(cik: str, n: int) -> list[dict]:
        t = next(k for k in COMPANIES if company(k).cik == cik)
        return [{k: v for k, v in e.items() if k not in ("reported", "target")} for e in company(t).events[-n:]]

    @staticmethod
    def press_release(cik: str, accession: str) -> dict:
        t = accession.split("-")[1]
        ev = next(e for e in company(t).events if e["accession"] == accession)
        return company(t).press_release(ev)

    @staticmethod
    def filing_for_period(cik: str, period_end: str) -> dict | None:
        t = next(k for k in COMPANIES if company(k).cik == cik)
        pe = date.fromisoformat(period_end)
        q = min(company(t).reported, key=lambda x: abs((x["end"] - pe).days))
        if abs((q["end"] - pe).days) > 10:
            return None
        form = "10-K" if q["q"] == 4 else "10-Q"
        filed = q["end"] + timedelta(days=55 if q["q"] == 4 else 35)
        return {"form": form, "filing_date": filed.isoformat(), "period": q["end"].isoformat(),
                "accession": f"demo-{t}-{q['end']}", "url": f"demo://{t}/{form}/{q['end'].isoformat()}"}

    @staticmethod
    def filing_text(url: str) -> str:
        return document(url)

    @staticmethod
    def transcripts(ticker: str) -> list[dict]:
        from .transcripts import all_transcripts

        return _transcript(ticker.upper()) + all_transcripts(ticker)

    @staticmethod
    def closes(ticker: str, start: str) -> pd.Series:
        return _prices(ticker.upper(), start)


def document(url: str) -> str:
    """Resolve demo:// URLs to text (press releases and MD&A)."""
    _, _, rest = url.partition("demo://")
    t, kind, d = rest.split("/")
    co = company(t)
    if kind == "8-K":
        ev = next(e for e in co.events if e["date"] == d)
        return co.press_release(ev)["text"]
    q = next(x for x in co.reported if x["end"].isoformat() == d)
    return co.mdna(q)


def search(q: str) -> list[dict]:
    q = q.upper()
    return [{"ticker": t, "title": c["name"], "cik": company(t).cik}
            for t, c in COMPANIES.items() if q in t or q in c["name"].upper()]


DEMO_PORTFOLIO = [
    {"ticker": "KAIA", "weight": 0.35, "shares": 120, "note": "AI 반도체 (가상)"},
    {"ticker": "NBLU", "weight": 0.25, "shares": 300, "note": "클라우드 SaaS (가상)"},
    {"ticker": "ORBT", "weight": 0.25, "shares": 200, "note": "전기차 (가상)"},
    {"ticker": "HNRT", "weight": 0.15, "shares": 500, "note": "리테일 테크 (가상)"},
]


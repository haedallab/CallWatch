"""Offline fixture built from real SEC EDGAR data (NVIDIA, CIK 0001045810).

Values are copied from NVIDIA's XBRL companyfacts (10-Q/10-K, 3-month and fiscal-year durations) and the
"Outlook" sections of its 8-K Ex-99.1 earnings releases for Q4 FY2025 - Q4 FY2026. Only the pieces the
pipeline reads are kept, so the tests exercise the real code paths without network access.
"""
from __future__ import annotations

import pandas as pd

from app.services import edgar, transcripts

NVDA_CIK = "0001045810"
COMPANIES = {  # ticker -> (cik, title) as in SEC company_tickers.json
    "NVDA": (NVDA_CIK, "NVIDIA CORP"),
    "LLY": ("0000059478", "ELI LILLY & Co"),
    "MSFT": ("0000789019", "MICROSOFT CORP"),
    "AAPL": ("0000320193", "Apple Inc."),
    "C": ("0000831001", "CITIGROUP INC"),
}

# (start, end, value, accession, fy, fp, form, filed)
_Q = [  # fiscal quarters: FY2025 Q1-Q3, FY2026 Q1-Q3, FY2027 Q1 (Q4 is derived from the FY total)
    ("2024-01-29", "2024-04-28", "0001045810-24-000124", "2025", "Q1", "10-Q", "2024-05-29"),
    ("2024-04-29", "2024-07-28", "0001045810-24-000264", "2025", "Q2", "10-Q", "2024-08-28"),
    ("2024-07-29", "2024-10-27", "0001045810-24-000316", "2025", "Q3", "10-Q", "2024-11-20"),
    ("2025-01-27", "2025-04-27", "0001045810-25-000116", "2026", "Q1", "10-Q", "2025-05-28"),
    ("2025-04-28", "2025-07-27", "0001045810-25-000209", "2026", "Q2", "10-Q", "2025-08-27"),
    ("2025-07-28", "2025-10-26", "0001045810-25-000230", "2026", "Q3", "10-Q", "2025-11-19"),
    ("2026-01-26", "2026-04-26", "0001045810-26-000052", "2027", "Q1", "10-Q", "2026-05-20"),
]
_FY = [
    ("2024-01-29", "2025-01-26", "0001045810-25-000023", "2025", "FY", "10-K", "2025-02-26"),
    ("2025-01-27", "2026-01-25", "0001045810-26-000021", "2026", "FY", "10-K", "2026-02-25"),
]
_VALUES = {  # concept: (unit, [quarters in _Q order], [fiscal years in _FY order])
    "Revenues": ("USD", [26044e6, 30040e6, 35082e6, 44062e6, 46743e6, 57006e6, 81615e6], [130497e6, 215938e6]),
    "GrossProfit": ("USD", [20406e6, 22574e6, 26156e6, 26668e6, 33853e6, 41849e6, 61157e6], [97858e6, 153463e6]),
    "OperatingExpenses": ("USD", [3497e6, 3932e6, 4287e6, 5030e6, 5413e6, 5839e6, 7621e6], [16405e6, 23076e6]),
    "OperatingIncomeLoss": ("USD", [16909e6, 18642e6, 21869e6, 21638e6, 28440e6, 36010e6, 53536e6], [81453e6, 130387e6]),
    "NetIncomeLoss": ("USD", [14881e6, 16599e6, 19309e6, 18775e6, 26422e6, 31910e6, 58321e6], [72880e6, 120067e6]),
    "EarningsPerShareDiluted": ("USD/shares", [5.98, 0.67, 0.78, 0.76, 1.08, 1.30, 2.39], [2.94, 4.90]),
}


def nvda_facts() -> dict:
    gaap = {}
    for concept, (unit, q, fy) in _VALUES.items():
        rows = []
        for (start, end, accn, fyr, fp, form, filed), val in list(zip(_Q, q)) + list(zip(_FY, fy)):
            rows.append({"start": start, "end": end, "val": val, "accn": accn, "fy": int(fyr), "fp": fp,
                         "form": form, "filed": filed})
        gaap[concept] = {"units": {unit: rows}}
    return {"cik": int(NVDA_CIK), "entityName": "NVIDIA CORP", "facts": {"us-gaap": gaap}}


# 8-K Item 2.02 earnings releases: (filing date, accession, release file, outlook bullets as published)
RELEASES = [
    ("2025-02-26", "0001045810-25-000021", "q4fy25pr.htm", "first quarter of fiscal 2026", [
        "Revenue is expected to be $43.0 billion, plus or minus 2%.",
        "GAAP and non-GAAP gross margins are expected to be 70.6% and 71.0%, respectively, plus or minus 50 basis points.",
        "GAAP and non-GAAP operating expenses are expected to be approximately $5.2 billion and $3.6 billion, respectively.",
    ]),
    ("2025-05-28", "0001045810-25-000115", "q1fy26pr.htm", "second quarter of fiscal 2026", [
        "Revenue is expected to be $45.0 billion, plus or minus 2%. This outlook reflects a loss in H20 revenue of "
        "approximately $8.0 billion due to the recent export control limitations.",
        "GAAP and non-GAAP gross margins are expected to be 71.8% and 72.0%, respectively, plus or minus 50 basis points.",
        "GAAP and non-GAAP operating expenses are expected to be approximately $5.7 billion and $4.0 billion, respectively.",
    ]),
    ("2025-08-27", "0001045810-25-000207", "q2fy26pr.htm", "third quarter of fiscal 2026", [
        "Revenue is expected to be $54.0 billion, plus or minus 2%. The company has not assumed any H20 shipments to "
        "China in the outlook.",
        "GAAP and non-GAAP gross margins are expected to be 73.3% and 73.5%, respectively, plus or minus 50 basis points.",
        "GAAP and non-GAAP operating expenses are expected to be approximately $5.9 billion and $4.2 billion, respectively.",
    ]),
    ("2025-11-19", "0001045810-25-000228", "q3fy26pr.htm", "fourth quarter of fiscal 2026", [
        "Revenue is expected to be $65.0 billion, plus or minus 2%.",
        "GAAP and non-GAAP gross margins are expected to be 74.8% and 75.0%, respectively, plus or minus 50 basis points.",
        "GAAP and non-GAAP operating expenses are expected to be approximately $6.7 billion and $5.0 billion, respectively.",
    ]),
    ("2026-02-25", "0001045810-26-000019", "q4fy26pr.htm", "first quarter of fiscal 2027", [
        "Revenue is expected to be $78.0 billion, plus or minus 2%. NVIDIA is not assuming any Data Center compute "
        "revenue from China in its outlook.",
        "GAAP and non-GAAP gross margins are expected to be 74.9% and 75.0%, respectively, plus or minus 50 basis points.",
        "GAAP and non-GAAP operating expenses are expected to be approximately $7.7 billion and $7.5 billion, respectively.",
    ]),
]
WEBCAST = ("NVIDIA will conduct a conference call with analysts and investors to discuss its results today. "
           "A live webcast (listen-only mode) of the conference call will be accessible at NVIDIA's investor "
           "relations website, https://investor.nvidia.com.")


def _url(acc: str, doc: str) -> str:
    return f"https://www.sec.gov/Archives/edgar/data/1045810/{acc.replace('-', '')}/{doc}"


def release_text(period: str, bullets: list[str]) -> str:
    return ("Outlook\nNVIDIA's outlook for the " + period + " is as follows:\n"
            + "\n".join("• " + b for b in bullets) + "\n\nConference Call and Webcast Information\n" + WEBCAST)


class FixtureSource:
    """Same interface as pipeline.LiveSource, served from the fixture above."""
    mode = "live"

    @staticmethod
    def resolve(ticker: str) -> dict:
        t = ticker.upper().strip().replace(".", "-")
        if t not in COMPANIES:
            raise edgar.EdgarError(f"EDGAR에서 '{ticker}' 티커를 찾지 못했습니다 (미국 상장 SEC 제출 기업만 지원).")
        cik, title = COMPANIES[t]
        return {"ticker": t, "cik": cik, "title": title}

    @staticmethod
    def search(q: str, limit: int = 10) -> list[dict]:
        q = q.strip().upper()
        return [{"ticker": t, "title": v[1], "cik": v[0]} for t, v in COMPANIES.items() if q in t or q in v[1].upper()][:limit]

    @staticmethod
    def facts(cik: str) -> dict:
        return nvda_facts() if cik == NVDA_CIK else {}

    @staticmethod
    def events(cik: str, n: int) -> list[dict]:
        if cik != NVDA_CIK:
            return []
        rows = [{"date": d, "accession": acc, "after_close": True, "url": _url(acc, doc)}
                for d, acc, doc, _, _ in RELEASES]
        return rows[-n:]

    @staticmethod
    def press_release(cik: str, accession: str) -> dict | None:
        for d, acc, doc, period, bullets in RELEASES:
            if acc == accession:
                text = release_text(period, bullets)
                return {"url": _url(acc, doc), "text": text, "outlook": edgar.outlook_section(text), "extras": [],
                        "webcast": edgar.webcast_links(text)}
        return None

    @staticmethod
    def filing_for_period(cik: str, period_end: str) -> dict | None:
        return None

    @staticmethod
    def filing_text(url: str) -> str:
        return ""

    transcripts = staticmethod(transcripts.all_transcripts)

    @staticmethod
    def closes(ticker: str, start: str) -> pd.Series:
        return pd.Series(dtype=float)  # prices are not part of the fixture

"""Parse holdings typed or pasted by the user (CSV, TSV, broker app copy-paste, free text).

Accepted per line, in any order: a ticker (AAPL, BRK.B) or 6-digit KRX code, an optional quantity
("10", "10주", "12.5 shares") and an optional weight ("25%"). Header rows and blank lines are skipped.
"""
from __future__ import annotations

import csv
import io
import re

KR_CODE = re.compile(r"^(?:A)?(\d{6})$")
TICKER = re.compile(r"^[A-Z]{1,5}(?:[.-][A-Z]{1,2})?$")
NUM = re.compile(r"^[-+]?\d{1,3}(?:,\d{3})*(?:\.\d+)?$|^[-+]?\d+(?:\.\d+)?$")
HEADER_WORDS = {"TICKER", "SYMBOL", "종목", "종목명", "티커", "수량", "SHARES", "QTY", "QUANTITY", "WEIGHT", "비중",
                "NAME", "코드", "종목코드", "평가금액", "보유수량"}
STOP = {"USD", "KRW", "US", "KR", "ETF", "INC", "CORP", "CO", "LTD", "THE", "CLASS", "A", "B", "주", "SHARES"}


def _cells(line: str) -> list[str]:
    if "\t" in line:
        return [c.strip() for c in line.split("\t")]
    if "," in line and not re.search(r"\d,\d{3}", line):
        return [c.strip() for c in next(csv.reader(io.StringIO(line)))]
    return line.split()


def parse(text: str, limit: int = 30) -> tuple[list[dict], list[dict]]:
    rows: dict[str, dict] = {}
    skipped: list[dict] = []
    for n, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        cells = [c for c in _cells(line) if c]
        if cells and all(c.upper().strip(":") in HEADER_WORDS for c in cells[:2]):
            continue
        ticker = market = None
        shares = weight = None
        words = []
        for c in cells:
            tok = c.strip().strip("()[]")
            up = tok.upper()
            if up.endswith("%") and NUM.match(up[:-1].strip()):
                weight = float(up[:-1].replace(",", "")) / 100
                continue
            qty = re.sub(r"(주|SHARES?|SH|株)$", "", up).strip()
            if ticker and shares is None and NUM.match(qty):
                shares = float(qty.replace(",", ""))
                continue
            m = KR_CODE.match(up)
            if not ticker and m:
                ticker, market = m.group(1), "KR"
                continue
            if not ticker and TICKER.match(up) and up not in STOP:
                ticker, market = up.replace("-", "."), "US"
                continue
            if not NUM.match(qty):
                words.append(tok)
        if not ticker:
            skipped.append({"line": n, "text": line[:80], "reason": "티커(예: AAPL) 또는 6자리 종목코드를 찾지 못했습니다."})
            continue
        r = rows.setdefault(ticker, {"ticker": ticker, "market": market, "shares": None, "weight": None,
                                     "name": " ".join(words)[:40] or None})
        if shares is not None:
            r["shares"] = (r["shares"] or 0) + shares
        if weight is not None:
            r["weight"] = weight
    out = list(rows.values())
    if len(out) > limit:
        skipped += [{"line": None, "text": r["ticker"], "reason": f"최대 {limit}종목까지 등록할 수 있습니다."} for r in out[limit:]]
        out = out[:limit]
    return out, skipped

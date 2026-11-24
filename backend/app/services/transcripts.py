"""Earnings-call transcript sources.

1. Uploaded / pasted by the user (stored in DB)               -> always available
2. Local files: data/transcripts/<TICKER>/<YYYY-MM-DD>.txt      -> e.g. Kaggle Motley Fool dump
3. API Ninjas earnings-transcript endpoint (API_NINJAS_KEY)     -> optional
"""
from __future__ import annotations

import re
from pathlib import Path

import httpx

from .. import db
from ..config import settings

_DATE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def local_transcripts(ticker: str) -> list[dict]:
    folder = settings.data_dir / "transcripts" / ticker.upper()
    out = []
    if folder.exists():
        for p in sorted(folder.glob("*.txt")):
            m = _DATE.search(p.name)
            if m:
                out.append({"id": f"file:{p.name}", "ticker": ticker.upper(), "call_date": m.group(1),
                            "source": "local-file", "text": p.read_text(encoding="utf-8", errors="ignore")})
    return out


PUBLIC = "public"  # transcripts the operator published for everyone (feed the shared analyses)


def all_transcripts(ticker: str, user_id: str | None = "local") -> list[dict]:
    mine = db.list_transcripts(ticker, user_id) if user_id and user_id != PUBLIC else []
    rows = db.list_transcripts(ticker, PUBLIC) + mine + local_transcripts(ticker)
    return sorted(rows, key=lambda r: r["call_date"])


def fetch_api_ninjas(ticker: str, year: int, quarter: int, user_id: str = "local") -> dict | None:
    if not settings.api_ninjas_key:
        return None
    r = httpx.get(
        "https://api.api-ninjas.com/v1/earningstranscript",
        params={"ticker": ticker.upper(), "year": year, "quarter": quarter},
        headers={"X-Api-Key": settings.api_ninjas_key},
        timeout=30,
    )
    if r.status_code != 200:
        return None
    data = r.json()
    if isinstance(data, list):
        data = data[0] if data else {}
    text = data.get("transcript") or ""
    call_date = (data.get("date") or "")[:10]
    if not text or not call_date:
        return None
    db.save_transcript(ticker, call_date, "api-ninjas", text, user_id)
    return {"ticker": ticker.upper(), "call_date": call_date, "source": "api-ninjas", "text": text}


_QA = re.compile(r"\n\s*(questions?[- ]and[- ]answers?|q\s*&\s*a session|question-and-answer session)", re.I)


def split_sections(text: str) -> list[tuple[str, int, int]]:
    """Return [(section, start, end)] - 'prepared' remarks vs 'qa'."""
    m = _QA.search(text)
    if not m:
        return [("prepared", 0, len(text))]
    return [("prepared", 0, m.start()), ("qa", m.start(), len(text))]

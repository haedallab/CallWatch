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


# ---- operator import from a company IR page / PDF ---------------------------------------
_PRIVATE = ("localhost", "127.", "10.", "192.168.", "169.254.", "0.", "[::1]", "metadata")


def fetch_text(url: str, max_bytes: int = 15_000_000) -> str:
    """Download a public transcript (PDF or HTML) and return plain text. Operator-only caller."""
    import io
    from urllib.parse import urlparse

    from bs4 import BeautifulSoup

    host = (urlparse(url).hostname or "").lower()
    if not url.startswith("https://") or not host or host.startswith(_PRIVATE) or host.endswith(".internal"):
        raise ValueError("공개 https 주소만 가져올 수 있습니다.")
    r = httpx.get(url, timeout=40, follow_redirects=True,
                  headers={"User-Agent": "Mozilla/5.0 (CallWatch transcript import)"})
    r.raise_for_status()
    if len(r.content) > max_bytes:
        raise ValueError("파일이 너무 큽니다.")
    ctype = r.headers.get("content-type", "")
    if "pdf" in ctype or r.content[:4] == b"%PDF":
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(r.content))
        text = "\n".join((p.extract_text() or "") for p in reader.pages)
    else:
        soup = BeautifulSoup(r.text, "html.parser")
        for t in soup(["script", "style", "nav", "header", "footer"]):
            t.decompose()
        text = soup.get_text("\n")
    text = re.sub(r"[ \t\xa0]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()

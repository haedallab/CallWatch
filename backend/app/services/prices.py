"""Daily prices (yfinance, Stooq fallback) and a market-model event study."""
from __future__ import annotations

import io
import logging
from datetime import date, timedelta

import httpx
import numpy as np
import pandas as pd

from .. import db
from ..config import settings

log = logging.getLogger(__name__)

WINDOWS = {"car_0": (0, 0), "car_m1p1": (-1, 1), "car_0p5": (0, 5), "car_0p20": (0, 20)}


def _yf(ticker: str, start: str) -> pd.Series:
    import yfinance as yf

    df = yf.download(ticker, start=start, progress=False, auto_adjust=True, threads=False)
    if df is None or df.empty:
        return pd.Series(dtype=float)
    close = df["Close"]
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    close.index = pd.to_datetime(close.index).tz_localize(None)
    return close.dropna()


def _stooq(ticker: str, start: str) -> pd.Series:
    sym = ticker.lower().replace("-", ".") + ".us"
    r = httpx.get(f"https://stooq.com/q/d/l/?s={sym}&i=d", timeout=20)
    if r.status_code != 200 or "Date" not in r.text[:50]:
        return pd.Series(dtype=float)
    df = pd.read_csv(io.StringIO(r.text), parse_dates=["Date"]).set_index("Date")
    return df.loc[df.index >= pd.Timestamp(start), "Close"].dropna()


def closes(ticker: str, start: str) -> pd.Series:
    key = f"px:{ticker.upper()}:{start}"
    hit = db.cache_get(key, max_age_hours=12)
    if hit:
        s = pd.Series({pd.Timestamp(d): v for d, v in hit})
        return s.sort_index()
    s = pd.Series(dtype=float)
    for fn in (_yf, _stooq):
        try:
            s = fn(ticker, start)
        except Exception as e:  # network / provider errors
            log.warning("price source %s failed for %s: %s", fn.__name__, ticker, e)
        if not s.empty:
            break
    if not s.empty:
        db.cache_set(key, [[d.strftime("%Y-%m-%d"), float(v)] for d, v in s.items()])
    return s


def event_study(px: pd.Series, bench: pd.Series, event_date: str, after_close: bool = True) -> dict:
    """Cumulative abnormal returns around an event (market model, fallback market-adjusted)."""
    df = pd.concat({"r": px.pct_change(), "m": bench.pct_change()}, axis=1).dropna()
    if df.empty:
        return {}
    d = pd.Timestamp(event_date)
    idx = df.index
    pos = idx.searchsorted(d, side="right" if after_close else "left")
    if pos >= len(idx):
        return {"pending": True}
    est = df.iloc[max(0, pos - 130): max(0, pos - 10)]
    if len(est) >= 60:
        beta, alpha = np.polyfit(est["m"], est["r"], 1)
        model = "market model"
    else:
        alpha, beta, model = 0.0, 1.0, "market-adjusted"
    ar = df["r"] - (alpha + beta * df["m"])
    out = {"reaction_date": idx[pos].strftime("%Y-%m-%d"), "beta": round(float(beta), 3), "model": model}
    for name, (a, b) in WINDOWS.items():
        lo, hi = pos + a, pos + b
        if lo < 0 or hi >= len(idx):
            out[name] = None
        else:
            out[name] = round(float(ar.iloc[lo: hi + 1].sum()) * 100, 2)
    out["raw_1d"] = round(float(df["r"].iloc[pos]) * 100, 2)
    return out


def price_frame(ticker: str, start: str) -> pd.DataFrame:
    px = closes(ticker, start)
    bench = closes(settings.benchmark, start)
    if px.empty:
        return pd.DataFrame()
    df = pd.concat({"close": px, "bench": bench}, axis=1).dropna()
    return df


def default_start(years: int = 3) -> str:
    return (date.today() - timedelta(days=365 * years + 200)).isoformat()

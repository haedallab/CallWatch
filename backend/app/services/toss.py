"""Toss Securities (토스증권) Open API connector - READ ONLY.

Docs: https://developers.tossinvest.com  ·  spec: https://openapi.tossinvest.com/openapi-docs/latest/openapi.json
  POST /oauth2/token            client_credentials (form-urlencoded) -> access_token, expires_in
  GET  /api/v1/accounts         -> result[].accountSeq / accountNo / accountType
  GET  /api/v1/holdings         header X-Tossinvest-Account: <accountSeq>
  GET  /api/v1/exchange-rate    baseCurrency / quoteCurrency

Operational facts that shape this module
  * Only ONE access token is valid per client; re-issuing invalidates the previous one -> cache it.
  * Calls are accepted only from allow-listed public IPs (set in Toss WTS > Settings > Open API).
  * There is no sandbox; this module never calls order endpoints.
  * Monetary values arrive as strings; rates are fractions (0.1179 = 11.79%).
"""
from __future__ import annotations

import threading
import time

import httpx

from .. import db
from ..config import settings

BASE = "https://openapi.tossinvest.com"
_lock = threading.Lock()


class TossError(RuntimeError):
    def __init__(self, message: str, code: str = "toss-error", status: int = 502, hint: str = ""):
        super().__init__(message)
        self.code, self.status, self.hint = code, status, hint


def configured() -> bool:
    return bool(settings.toss_client_id and settings.toss_client_secret)


def _num(v) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def public_ip() -> str | None:
    """The server's outbound IP - this is what must be registered in Toss' IP allow-list."""
    try:
        return httpx.get("https://api.ipify.org", params={"format": "json"}, timeout=5).json()["ip"]
    except Exception:
        return None


def _raise_for(r: httpx.Response):
    try:
        body = r.json()
    except ValueError:
        body = {}
    err = body.get("error")
    if isinstance(err, dict):
        code, msg = err.get("code", "toss-error"), err.get("message", r.text[:200])
    else:
        code, msg = (err or "toss-error"), body.get("error_description") or r.text[:200]
    hint = ""
    if r.status_code == 403 or "ip" in str(code).lower():
        ip = public_ip()
        hint = (f"토스증권 WTS > 설정 > Open API > 허용 IP에 이 서버의 공인 IP"
                f"{f' {ip}' if ip else ''}를 등록하세요.")
    elif r.status_code == 401 or code in ("invalid_client", "invalid_request"):
        hint = "TOSS_CLIENT_ID / TOSS_CLIENT_SECRET 값을 다시 확인하세요."
    elif r.status_code == 429:
        hint = "호출 한도를 넘었습니다. 잠시 후 다시 시도하세요."
    raise TossError(f"토스증권 API 오류 ({r.status_code} {code}): {msg}", str(code), r.status_code, hint)


def _token(force: bool = False) -> str:
    with _lock:
        cached = db.cache_get("toss:token")
        if cached and not force and cached["exp"] - 300 > time.time():
            return cached["token"]
        r = httpx.post(f"{BASE}/oauth2/token", timeout=15, data={
            "grant_type": "client_credentials",
            "client_id": settings.toss_client_id,
            "client_secret": settings.toss_client_secret,
        })
        if r.status_code != 200:
            _raise_for(r)
        j = r.json()
        db.cache_set("toss:token", {"token": j["access_token"], "exp": time.time() + int(j.get("expires_in", 86400))})
        return j["access_token"]


def _get(path: str, params: dict | None = None, account: int | str | None = None) -> dict:
    if not configured():
        raise TossError("토스증권 API 키가 설정되지 않았습니다.", "not-configured", 400,
                        "서버 환경변수 TOSS_CLIENT_ID, TOSS_CLIENT_SECRET을 설정하세요.")
    for attempt in (0, 1):
        headers = {"Authorization": f"Bearer {_token(force=attempt == 1)}"}
        if account is not None:
            headers["X-Tossinvest-Account"] = str(account)
        try:
            r = httpx.get(f"{BASE}{path}", params=params, headers=headers, timeout=20)
        except httpx.HTTPError as e:
            raise TossError(f"토스증권 서버에 연결하지 못했습니다: {e}", "network", 503) from e
        if r.status_code == 401 and attempt == 0:
            continue  # token was invalidated (e.g. re-issued elsewhere) -> retry once with a new one
        if r.status_code != 200:
            _raise_for(r)
        return r.json()
    raise TossError("토큰을 갱신하지 못했습니다.", "auth", 401)


def accounts() -> list[dict]:
    hit = db.cache_get("toss:accounts", max_age_hours=1)
    if hit is not None:
        return hit
    res = _get("/api/v1/accounts").get("result", [])
    out = [{"accountSeq": a.get("accountSeq"), "accountNo": _mask(a.get("accountNo", "")),
            "accountType": a.get("accountType")} for a in res]
    db.cache_set("toss:accounts", out)
    return out


def _mask(no: str) -> str:
    return no[:3] + "•" * max(0, len(no) - 6) + no[-3:] if len(no) > 6 else "•••"


def holdings_raw(account_seq: int | str) -> dict:
    return _get("/api/v1/holdings", account=account_seq).get("result", {})


def usd_krw() -> float | None:
    try:
        j = _get("/api/v1/exchange-rate", {"baseCurrency": "USD", "quoteCurrency": "KRW"})
        return _num((j.get("result") or j).get("rate"))
    except TossError:
        return None


def _krw(v, currency: str, fx: float | None) -> float | None:
    """Amounts are either {'krw': '..', 'usd': '..'} objects or plain strings in the item currency."""
    if isinstance(v, dict):
        if _num(v.get("krw")) is not None:
            return _num(v.get("krw"))
        usd = _num(v.get("usd"))
        return usd * fx if usd is not None and fx else None
    x = _num(v)
    if x is None:
        return None
    return x * fx if currency == "USD" and fx else x


def normalize(raw: dict, fx: float | None = None) -> dict:
    """Toss holdings -> CallWatch portfolio rows (weights by KRW market value)."""
    items = raw.get("items") or []
    rows = []
    for it in items:
        cur = it.get("currency") or ("USD" if it.get("marketCountry") == "US" else "KRW")
        mv = it.get("marketValue") or {}
        pl = it.get("profitLoss") or {}
        value = _krw(mv.get("amount"), cur, fx)
        if value is None:
            q, p = _num(it.get("quantity")), _num(it.get("lastPrice"))
            value = q * p * (fx if cur == "USD" and fx else 1) if q and p else 0.0
        daily = it.get("dailyProfitLoss") or {}
        rows.append({
            "ticker": str(it.get("symbol", "")).upper(), "name": it.get("name") or "",
            "market": it.get("marketCountry") or ("US" if cur == "USD" else "KR"), "currency": cur,
            "shares": _num(it.get("quantity")), "last_price": _num(it.get("lastPrice")),
            "avg_price": _num(it.get("averagePurchasePrice")), "value_krw": round(value or 0.0),
            "pl_krw": _krw(pl.get("amount"), cur, fx), "pl_rate": _num(pl.get("rate")),
            "daily_rate": _num(daily.get("rate")),
        })
    total = sum(r["value_krw"] for r in rows) or 1
    for r in rows:
        r["weight"] = round(r["value_krw"] / total, 4)
    mv = raw.get("marketValue") or {}
    pl = raw.get("profitLoss") or {}
    summary = {
        "market_value_krw": _krw(mv.get("amount"), "KRW", fx) or float(total),
        "purchase_krw": _krw(raw.get("totalPurchaseAmount"), "KRW", fx),
        "pl_krw": _krw(pl.get("amount"), "KRW", fx), "pl_rate": _num(pl.get("rate")),
        "daily_rate": _num((raw.get("dailyProfitLoss") or {}).get("rate")),
    }
    return {"rows": sorted(rows, key=lambda r: -r["value_krw"]), "summary": summary}

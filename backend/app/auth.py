"""Request context: who is calling (Supabase Auth JWT) and which data mode (demo/live) they view.

Sign-in is optional for the deployment: without SUPABASE_URL / SUPABASE_JWT_SECRET the API runs as a
single-user app (uid "local"). With it, every write is scoped to the signed-in user's id.
"""
from __future__ import annotations

import contextvars
import hashlib
import hmac
import re
import time
from functools import lru_cache

import httpx
import jwt

from .config import settings

_user: contextvars.ContextVar[dict | None] = contextvars.ContextVar("user", default=None)
_mode: contextvars.ContextVar[str] = contextvars.ContextVar("mode", default="demo" if settings.demo_mode else "live")
_client: contextvars.ContextVar[str] = contextvars.ContextVar("client", default="")
_owner_key: contextvars.ContextVar[str] = contextvars.ContextVar("owner_key", default="")
_ip: contextvars.ContextVar[str] = contextvars.ContextVar("ip", default="")


class AuthError(Exception):
    pass


@lru_cache(maxsize=1)
def _jwks():
    return jwt.PyJWKClient(f"{settings.supabase_url}/auth/v1/.well-known/jwks.json", cache_keys=True)


_remote_cache: dict[str, tuple[float, dict]] = {}


def _verify_remote(token: str) -> dict:
    """Ask Supabase Auth itself (works for any signing algorithm). Cached until the token expires."""
    h = hashlib.sha256(token.encode()).hexdigest()
    hit = _remote_cache.get(h)
    if hit and hit[0] > time.time():
        return hit[1]
    r = httpx.get(f"{settings.supabase_url}/auth/v1/user", timeout=8,
                  headers={"apikey": settings.supabase_anon_key, "Authorization": f"Bearer {token}"})
    r.raise_for_status()
    u = r.json()
    claims = {"sub": u["id"], "email": u.get("email") or ""}
    exp = jwt.decode(token, options={"verify_signature": False}).get("exp", time.time() + 300)
    if len(_remote_cache) > 5000:
        _remote_cache.clear()
    _remote_cache[h] = (min(exp, time.time() + 3600), claims)
    return claims


def verify(token: str) -> dict:
    """Validate a Supabase access token.
    HS256 (legacy shared secret) -> SUPABASE_JWT_SECRET; ES256/RS256 (signing keys) -> JWKS;
    otherwise fall back to Supabase's /auth/v1/user endpoint."""
    try:
        alg = jwt.get_unverified_header(token).get("alg", "")
        if alg == "HS256" and settings.supabase_jwt_secret:
            claims = jwt.decode(token, settings.supabase_jwt_secret, algorithms=["HS256"], audience="authenticated")
        elif alg != "HS256" and settings.supabase_url:
            key = _jwks().get_signing_key_from_jwt(token).key
            claims = jwt.decode(token, key, algorithms=["ES256", "RS256", "EdDSA"], audience="authenticated")
        elif settings.supabase_url and settings.supabase_anon_key:
            claims = _verify_remote(token)
        else:
            raise AuthError("server cannot verify HS256 tokens: set SUPABASE_JWT_SECRET or SUPABASE_ANON_KEY")
    except Exception as e:  # expired, bad signature, unreachable JWKS ...
        raise AuthError("로그인이 만료되었거나 올바르지 않습니다. 다시 로그인해 주세요.") from e
    return {"uid": claims["sub"], "email": (claims.get("email") or "").lower()}


def bind(authorization: str | None, data_mode: str | None, client_id: str | None, owner_key: str | None,
         ip: str | None = None):
    user = None
    if authorization and authorization.lower().startswith("bearer ") and settings.auth_enabled:
        user = verify(authorization.split(" ", 1)[1].strip())
    _user.set(user)
    if data_mode in ("demo", "live"):
        _mode.set(data_mode)
    cid = (client_id or "")[:64]
    _client.set(cid if re.fullmatch(r"[A-Za-z0-9-]{8,64}", cid or "") else "")
    _owner_key.set(owner_key or "")
    _ip.set((ip or "")[:64])


def ip() -> str:
    return _ip.get()


def user() -> dict | None:
    """Signed-in user (Supabase), or None. Without sign-in configured there are no accounts."""
    if not settings.auth_enabled:
        return None
    return _user.get()


def mode() -> str:
    return _mode.get()


def uid() -> str | None:
    """Storage owner id. Signed-in users by account; everyone else by a per-browser id (no sign-up needed).
    Calls without a browser id (Swagger, scripts) share "local" when sign-in is off."""
    u = user()
    if u:
        return u["uid"].lower()
    if _client.get():
        return f"anon-{_client.get().lower()}"
    return None if settings.auth_enabled else "local"


def is_verified_owner() -> bool:
    """Explicitly identified operator (owner email or OWNER_KEY). Only these skip usage limits."""
    if settings.auth_enabled and settings.owner_emails:
        u = _user.get()
        if u and u["email"] and u["email"] in settings.owner_emails:
            return True
    k = _owner_key.get()
    return bool(settings.owner_key and k) and hmac.compare_digest(k, settings.owner_key)


def is_owner() -> bool:
    """May this caller use the server-side Toss connection?"""
    if settings.auth_enabled and settings.owner_emails:
        u = _user.get()
        if u and u["email"] and u["email"] in settings.owner_emails:
            return True
    if settings.owner_key:
        k = _owner_key.get()
        return bool(k) and hmac.compare_digest(k, settings.owner_key)
    # no owner key: fine for local use, but never on a server that holds Toss credentials
    return not settings.auth_enabled and not (settings.toss_client_id and settings.toss_client_secret)

"""Request context: who is calling (Supabase Auth JWT) and which data mode (demo/live) they view.

Sign-in is optional for the deployment: without SUPABASE_URL / SUPABASE_JWT_SECRET the API runs as a
single-user app (uid "local"). With it, every write is scoped to the signed-in user's id.
"""
from __future__ import annotations

import contextvars
import hmac
import re
from functools import lru_cache

import jwt

from .config import settings

_user: contextvars.ContextVar[dict | None] = contextvars.ContextVar("user", default=None)
_mode: contextvars.ContextVar[str] = contextvars.ContextVar("mode", default="demo" if settings.demo_mode else "live")
_client: contextvars.ContextVar[str] = contextvars.ContextVar("client", default="")
_owner_key: contextvars.ContextVar[str] = contextvars.ContextVar("owner_key", default="")


class AuthError(Exception):
    pass


@lru_cache(maxsize=1)
def _jwks():
    return jwt.PyJWKClient(f"{settings.supabase_url}/auth/v1/.well-known/jwks.json", cache_keys=True)


def verify(token: str) -> dict:
    try:
        if settings.supabase_jwt_secret:
            claims = jwt.decode(token, settings.supabase_jwt_secret, algorithms=["HS256"], audience="authenticated")
        else:
            key = _jwks().get_signing_key_from_jwt(token).key
            claims = jwt.decode(token, key, algorithms=["ES256", "RS256", "EdDSA"], audience="authenticated")
    except Exception as e:  # expired, bad signature, unreachable JWKS ...
        raise AuthError("로그인이 만료되었거나 올바르지 않습니다. 다시 로그인해 주세요.") from e
    return {"uid": claims["sub"], "email": (claims.get("email") or "").lower()}


def bind(authorization: str | None, data_mode: str | None, client_id: str | None, owner_key: str | None):
    user = None
    if authorization and authorization.lower().startswith("bearer ") and settings.auth_enabled:
        user = verify(authorization.split(" ", 1)[1].strip())
    _user.set(user)
    if data_mode in ("demo", "live"):
        _mode.set(data_mode)
    cid = (client_id or "")[:64]
    _client.set(cid if re.fullmatch(r"[A-Za-z0-9-]{8,64}", cid or "") else "")
    _owner_key.set(owner_key or "")


def user() -> dict | None:
    """Signed-in user, or a fixed local user when sign-in is not configured."""
    if not settings.auth_enabled:
        return {"uid": "local", "email": ""}
    return _user.get()


def mode() -> str:
    return _mode.get()


def uid() -> str | None:
    """Storage owner id. Anonymous visitors get a per-browser id, but only for demo data."""
    u = user()
    if u:
        return u["uid"].lower()
    if mode() == "demo" and _client.get():
        return f"anon-{_client.get().lower()}"
    return None


def is_owner() -> bool:
    """May this caller use the server-side Toss connection and see account amounts?"""
    if settings.auth_enabled:
        u = _user.get()
        return bool(u and u["email"] and u["email"] in settings.owner_emails)
    if not settings.owner_key:
        return True
    k = _owner_key.get()
    return bool(k) and hmac.compare_digest(k, settings.owner_key)

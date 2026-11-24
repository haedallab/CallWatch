"""Optional sign-in: per-user data, owner-only Toss, anonymous visitors."""
import time

import jwt
import pytest
from fastapi.testclient import TestClient

from app import main

SECRET = "test-secret-at-least-32-bytes-long-xx"


def token(uid: str, email: str, exp: int = 3600) -> str:
    return jwt.encode({"sub": uid, "email": email, "aud": "authenticated", "exp": int(time.time()) + exp},
                      SECRET, algorithm="HS256")


def H(uid=None, email="", client=None):
    h = {}
    if uid:
        h["Authorization"] = f"Bearer {token(uid, email)}"
    if client:
        h["X-Client-Id"] = client
    return h


@pytest.fixture()
def c():
    s = main.settings
    object.__setattr__(s, "supabase_jwt_secret", SECRET)
    object.__setattr__(s, "owner_emails", ["owner@kaist.ac.kr"])
    object.__setattr__(s, "daily_analysis_limit", 1)
    yield TestClient(main.app)
    object.__setattr__(s, "supabase_jwt_secret", "")
    object.__setattr__(s, "owner_emails", [])
    object.__setattr__(s, "daily_analysis_limit", 30)


def test_holdings_are_private_per_user(c):
    a, b = H("user-a", "a@x.com"), H("user-b", "b@x.com")
    assert c.put("/api/portfolio", json=[{"ticker": "NVDA"}], headers=a).status_code == 200
    assert [r["ticker"] for r in c.get("/api/portfolio", headers=a).json()] == ["NVDA"]
    assert c.get("/api/portfolio", headers=b).json() == []  # never a's list


def test_bad_token_is_401_and_live_write_needs_login(c):
    assert c.get("/api/portfolio", headers={"Authorization": "Bearer nope"}).status_code == 401
    r = c.put("/api/portfolio", json=[{"ticker": "AAPL"}])
    assert r.status_code == 401 and "로그인" in r.json()["detail"]


def test_anonymous_visitor_gets_own_space_even_with_signin_on(c):
    v1, v2 = H(client="browser-one-1234"), H(client="browser-two-5678")
    assert c.put("/api/portfolio", json=[{"ticker": "LLY"}], headers=v1).status_code == 200
    assert [r["ticker"] for r in c.get("/api/portfolio", headers=v1).json()] == ["LLY"]
    assert c.get("/api/portfolio", headers=v2).json() == []


def test_toss_only_for_owner_account(c, monkeypatch):
    from .test_toss import fake_toss
    fake_toss(monkeypatch)
    other = H("user-c", "c@x.com")
    st = c.get("/api/broker/status", headers=other).json()
    assert st["available"] is False and st["owner_only"] is True
    assert c.post("/api/broker/toss/sync", json={}, headers=other).status_code == 403
    me = c.get("/api/me", headers=other).json()
    assert me["signed_in"] and not me["owner"] and not me["toss_available"]

    own = H("user-o", "Owner@kaist.ac.kr")
    assert c.get("/api/me", headers=own).json()["owner"] is True
    r = c.post("/api/broker/toss/sync", json={}, headers=own)
    assert r.status_code == 200 and r.json()["n"] == 2
    # synced holdings land only in the owner's portfolio
    assert any(h.get("source") == "toss" for h in c.get("/api/portfolio", headers=own).json())
    assert not any(h.get("source") == "toss" for h in c.get("/api/portfolio", headers=other).json())


def test_transcripts_private_and_personal_report(c):
    a, b = H("user-t", "t@x.com"), H("user-u", "u@x.com")
    # sentences from NVIDIA's fiscal Q4 2026 call (outlook given by the CFO)
    text = ("Revenue is expected to be $78.0 billion, plus or minus 2%. "
            "GAAP and non-GAAP gross margins are expected to be 74.9% and 75.0%, respectively, plus or minus 50 basis points. "
            "We are not assuming any Data Center compute revenue from China in our outlook. ") * 2
    r = c.post("/api/transcripts", json={"ticker": "NVDA", "call_date": "2026-02-25", "text": text}, headers=a)
    assert r.status_code == 200
    tid = r.json()["id"]
    ids_a = {x["id"] for x in c.get("/api/transcripts/NVDA", headers=a).json()}
    ids_b = {x["id"] for x in c.get("/api/transcripts/NVDA", headers=b).json()}
    assert tid in ids_a and tid not in ids_b
    # b cannot delete a's transcript
    c.delete(f"/api/transcripts/{tid}", headers=b)
    assert tid in {x["id"] for x in c.get("/api/transcripts/NVDA", headers=a).json()}
    # a's analysis of NVDA is stored privately; b's comes from the shared cache
    ra = c.post("/api/analyze/NVDA?events=4&use_llm=false&evidence=false", headers=a).json()
    rb = c.post("/api/analyze/NVDA?events=4&use_llm=false&evidence=false", headers=b).json()
    assert ra["personal"] is True and rb["personal"] is False


def test_delete_my_data(c):
    a = H("user-d", "d@x.com")
    c.put("/api/portfolio", json=[{"ticker": "MSFT"}], headers=a)
    assert c.delete("/api/me", headers=a).json()["deleted"] is True
    assert c.get("/api/portfolio", headers=a).json() == []


def test_live_analysis_requires_login_when_signin_is_on_and_has_daily_limit(c):
    r = c.post("/api/analyze/AAPL")
    assert r.status_code == 401
    h = H("user-l", "l@x.com")
    main.db.bump_usage("user-l", time.strftime("%Y-%m-%d"))  # use up the 1-per-day test limit
    assert c.post("/api/analyze/AMZN", headers=h).status_code == 429


def test_preview_parses_paste_and_flags_korean_codes(c):
    text = "종목\t수량\nNVDA\t10주\nlly, 5\n삼성전자 005930 3\nnot a ticker line 123\nZZZZ 1\n"
    r = c.post("/api/portfolio/preview", json={"text": text}, headers=H(client="browser-prev-0001")).json()
    by = {x["ticker"]: x for x in r["rows"]}
    assert by["NVDA"]["shares"] == 10 and by["NVDA"]["analyzable"]
    assert by["LLY"]["shares"] == 5
    assert by["005930"]["market"] == "KR" and by["005930"]["ok"] and not by["005930"]["analyzable"]
    assert by["ZZZZ"]["ok"] is False
    assert r["n_ok"] == 3 and abs(sum(x["weight"] for x in r["rows"] if x["ok"]) - 1) < 0.01


def test_save_keeps_korean_holding_as_excluded(c):
    h = H("user-k", "k@x.com")
    rows = c.put("/api/portfolio", json=[{"ticker": "NVDA", "shares": 1}, {"ticker": "005930", "shares": 2}], headers=h).json()
    assert {r["ticker"]: r["analyzable"] for r in rows} == {"NVDA": True, "005930": False}
    ex = c.get("/api/portfolio/summary", headers=h).json()["excluded"]
    assert [e["ticker"] for e in ex] == ["005930"]


def test_hs256_without_secret_falls_back_to_supabase_user_endpoint(monkeypatch):
    from app import auth
    s = main.settings
    object.__setattr__(s, "supabase_url", "https://x.supabase.co")
    object.__setattr__(s, "supabase_anon_key", "anon")
    calls = []

    class R:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"id": "remote-uid", "email": "R@x.com"}

    monkeypatch.setattr(auth.httpx, "get", lambda url, **kw: calls.append(url) or R())
    try:
        t = token("ignored", "r@x.com")
        assert auth.verify(t) == {"uid": "remote-uid", "email": "r@x.com"}
        auth.verify(t)
        assert len(calls) == 1  # cached
    finally:
        object.__setattr__(s, "supabase_url", "")
        object.__setattr__(s, "supabase_anon_key", "")

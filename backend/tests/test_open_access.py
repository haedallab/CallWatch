"""Open access (no sign-in configured): browse featured stocks, per-browser holdings, limits for anonymous visitors."""
import os
import tempfile
import time

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp())
os.environ.setdefault("WARM_FEATURED", "0")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import main  # noqa: E402


def B(cid, mode="demo"):
    return {"X-Client-Id": cid, "X-Data-Mode": mode}


@pytest.fixture()
def c():
    return TestClient(main.app)


def test_featured_board_is_public_and_uses_shared_reports(c):
    f = c.get("/api/featured", headers=B("visitor-0001")).json()
    assert set(f["tickers"]) == {"KAIA", "NBLU", "HNRT", "ORBT"}  # demo set
    c.post("/api/analyze/KAIA?events=4&use_llm=false&evidence=false", headers=B("visitor-0001"))
    f = c.get("/api/featured", headers=B("visitor-0002")).json()
    assert f["status"]["KAIA"] == "ready" and any(x["ticker"] == "KAIA" for x in f["companies"])


def test_holdings_are_per_browser_without_signup(c):
    a, b = B("browser-aaaa-1111", "live"), B("browser-bbbb-2222", "live")
    main.db.cache_set("holdings:live:anon-browser-aaaa-1111", [{"ticker": "AAPL", "weight": 1, "analyzable": True}])
    assert [h["ticker"] for h in c.get("/api/portfolio", headers=a).json()] == ["AAPL"]
    assert c.get("/api/portfolio", headers=b).json() == []
    me = c.get("/api/me", headers=b).json()
    assert me["signed_in"] is False and me["uid"] == "anon-browser-bbbb-2222" and me["usage"]["limit"] == 1


def test_anonymous_new_ticker_limit_counts_browser_and_ip(c):
    day = time.strftime("%Y-%m-%d")
    main.db.cache_set(f"usage:ip:testclient:{day}", 1)  # same IP already used the quota from another browser
    r = c.post("/api/analyze/AMZN", headers=B("fresh-browser-3333", "live"))
    assert r.status_code == 429 and "한도" in r.json()["detail"]
    main.db.cache_set(f"usage:ip:testclient:{day}", 0)


def test_toss_needs_owner_key_when_server_holds_toss_credentials(c):
    s = main.settings
    object.__setattr__(s, "toss_client_id", "id")
    object.__setattr__(s, "toss_client_secret", "secret")
    try:
        r = c.post("/api/broker/toss/sync", json={}, headers=B("visitor-4444", "live"))
        assert r.status_code == 403
        st = c.get("/api/broker/status", headers=B("visitor-4444", "live")).json()
        assert st["available"] is False
        # demo account still open to everyone
        assert c.post("/api/broker/toss/sync", json={}, headers=B("visitor-4444")).status_code == 200
    finally:
        object.__setattr__(s, "toss_client_id", "")
        object.__setattr__(s, "toss_client_secret", "")


def test_operator_public_transcript_feeds_everyone_without_full_text(c):
    s = main.settings
    object.__setattr__(s, "owner_key", "op-key")
    text = ("For the full fiscal year 2026 we expect revenue of $4.20 billion to $4.30 billion. " * 5).strip()
    body = {"ticker": "NBLU", "call_date": "2026-02-01", "text": text, "public": True,
            "source_url": "https://ir.example.com/q4"}
    try:
        assert c.post("/api/transcripts", json=body, headers=B("visitor-5555")).status_code == 403
        r = c.post("/api/transcripts", json=body, headers=B("operator-0001") | {"X-Owner-Key": "op-key"})
        assert r.status_code == 200 and r.json()["public"] is True
        rows = c.get("/api/transcripts/NBLU?include_text=true", headers=B("visitor-6666")).json()
        pub = [x for x in rows if x["public"]]
        assert pub and "text" not in pub[0] and pub[0]["source_url"] == "https://ir.example.com/q4"
        # visitors' analyses stay on the shared key and include the public transcript
        for _ in range(100):  # the operator upload refreshes the shared report in the background
            if not main.RUNNING:
                break
            time.sleep(0.05)
        rep = c.post("/api/analyze/NBLU?events=4&use_llm=false&evidence=false&refresh=true",
                     headers=B("visitor-6666")).json()
        assert rep["personal"] is False
        assert any(g.get("transcript_url") == "https://ir.example.com/q4" for g in rep["guidance"])
        assert c.delete(f"/api/transcripts/{pub[0]['id']}", headers=B("visitor-6666")).status_code == 403
    finally:
        object.__setattr__(s, "owner_key", "")


def test_call_links_registry(c):
    s = main.settings
    object.__setattr__(s, "owner_key", "op-key")
    try:
        c.post("/api/analyze/KAIA?events=4&use_llm=false&evidence=false", headers=B("visitor-7777"))
        got = c.get("/api/calls/KAIA", headers=B("visitor-7777")).json()
        assert got["events"]
        d = got["events"][0]["date"]
        assert c.put("/api/calls/KAIA", json={"audio": {d: "https://ir.example.com/a.mp3"}},
                     headers=B("visitor-7777")).status_code == 403
        r = c.put("/api/calls/KAIA", json={"audio": {d: "https://ir.example.com/a.mp3"}, "ir_url": "https://ir.example.com"},
                  headers=B("op-0001") | {"X-Owner-Key": "op-key"})
        assert r.status_code == 200
        got = c.get("/api/calls/KAIA", headers=B("visitor-7777")).json()
        assert got["ir_url"] == "https://ir.example.com" and got["events"][0]["audio_url"].endswith("a.mp3")
        assert c.put("/api/calls/KAIA", json={"ir_url": "javascript:alert(1)"},
                     headers=B("op-0001") | {"X-Owner-Key": "op-key"}).status_code == 400
    finally:
        object.__setattr__(s, "owner_key", "")

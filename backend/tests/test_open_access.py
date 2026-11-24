"""Open access (no sign-in configured): browse featured stocks, per-browser holdings, limits for anonymous visitors."""
import time

import pytest
from fastapi.testclient import TestClient

from app import main


def B(cid):
    return {"X-Client-Id": cid}


@pytest.fixture()
def c():
    return TestClient(main.app)


def test_featured_board_is_public_and_uses_shared_reports(c):
    f = c.get("/api/featured", headers=B("visitor-0001")).json()
    assert f["tickers"] == ["NVDA", "LLY"] and f["names"]["NVDA"] == "NVIDIA CORP"
    # featured stocks are free to analyse for anyone; the result is shared
    c.post("/api/analyze/NVDA?events=5&use_llm=false&evidence=false", headers=B("visitor-0001"))
    f = c.get("/api/featured", headers=B("visitor-0002")).json()
    assert f["status"]["NVDA"] == "ready" and any(x["ticker"] == "NVDA" for x in f["companies"])
    assert f["status"]["LLY"] in ("queued", "failed")


def test_holdings_are_per_browser_without_signup(c):
    a, b = B("browser-aaaa-1111"), B("browser-bbbb-2222")
    main.db.cache_set("holdings:live:anon-browser-aaaa-1111", [{"ticker": "AAPL", "weight": 1, "analyzable": True}])
    assert [h["ticker"] for h in c.get("/api/portfolio", headers=a).json()] == ["AAPL"]
    assert c.get("/api/portfolio", headers=b).json() == []
    me = c.get("/api/me", headers=b).json()
    assert me["signed_in"] is False and me["uid"] == "anon-browser-bbbb-2222" and me["usage"]["limit"] == 1


def test_anonymous_new_ticker_limit_counts_browser_and_ip(c):
    day = time.strftime("%Y-%m-%d")
    main.db.cache_set(f"usage:ip:testclient:{day}", 1)  # same IP already used the quota from another browser
    r = c.post("/api/analyze/MSFT", headers=B("fresh-browser-3333"))
    assert r.status_code == 429 and "한도" in r.json()["detail"]
    main.db.cache_set(f"usage:ip:testclient:{day}", 0)


def test_toss_needs_owner_key_when_server_holds_toss_credentials(c, monkeypatch):
    from .test_toss import fake_toss
    fake_toss(monkeypatch)
    s = main.settings
    object.__setattr__(s, "toss_client_id", "id")
    object.__setattr__(s, "toss_client_secret", "secret")
    try:
        assert c.post("/api/broker/toss/sync", json={}, headers=B("visitor-4444")).status_code == 403
        st = c.get("/api/broker/status", headers=B("visitor-4444")).json()
        assert st["available"] is False
    finally:
        object.__setattr__(s, "toss_client_id", "")
        object.__setattr__(s, "toss_client_secret", "")


def test_operator_public_transcript_feeds_everyone_without_full_text(c):
    s = main.settings
    object.__setattr__(s, "owner_key", "op-key")
    # NVIDIA's Q1 FY2027 outlook as read on the call (not part of the fixture's press releases)
    text = ("NVIDIA's outlook for the second quarter of fiscal 2027 is as follows: Revenue is expected to be "
            "$91.0 billion, plus or minus 2%. GAAP and non-GAAP gross margins are expected to be 74.9% and 75.0%, "
            "respectively, plus or minus 50 basis points. ") * 2
    body = {"ticker": "NVDA", "call_date": "2026-05-20", "text": text, "public": True,
            "source_url": "https://ir.example.com/q4"}
    try:
        assert c.post("/api/transcripts", json=body, headers=B("visitor-5555")).status_code == 403
        r = c.post("/api/transcripts", json=body, headers=B("operator-0001") | {"X-Owner-Key": "op-key"})
        assert r.status_code == 200 and r.json()["public"] is True
        rows = c.get("/api/transcripts/NVDA?include_text=true", headers=B("visitor-6666")).json()
        pub = [x for x in rows if x["public"]]
        assert pub and "text" not in pub[0] and pub[0]["source_url"] == "https://ir.example.com/q4"
        # visitors' analyses stay on the shared key and include the public transcript
        for _ in range(100):  # the operator upload refreshes the shared report in the background
            if not main.RUNNING:
                break
            time.sleep(0.05)
        rep = c.post("/api/analyze/NVDA?events=5&use_llm=false&evidence=false&refresh=true",
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
        c.post("/api/analyze/NVDA?events=5&use_llm=false&evidence=false", headers=B("visitor-7777"))
        got = c.get("/api/calls/NVDA", headers=B("visitor-7777")).json()
        assert got["ir_url"] == "https://investor.nvidia.com"
        assert got["events"][0]["webcast_url"] == "https://investor.nvidia.com"  # found in the release text
        assert got["events"]
        d = got["events"][0]["date"]
        assert c.put("/api/calls/NVDA", json={"audio": {d: "https://ir.example.com/a.mp3"}},
                     headers=B("visitor-7777")).status_code == 403
        r = c.put("/api/calls/NVDA", json={"audio": {d: "https://ir.example.com/a.mp3"}, "ir_url": "https://ir.example.com"},
                  headers=B("op-0001") | {"X-Owner-Key": "op-key"})
        assert r.status_code == 200
        got = c.get("/api/calls/NVDA", headers=B("visitor-7777")).json()
        assert got["ir_url"] == "https://ir.example.com" and got["events"][0]["audio_url"].endswith("a.mp3")
        assert c.put("/api/calls/NVDA", json={"ir_url": "javascript:alert(1)"},
                     headers=B("op-0001") | {"X-Owner-Key": "op-key"}).status_code == 400
    finally:
        object.__setattr__(s, "owner_key", "")


def test_transcript_from_url_operator_only(c, monkeypatch):
    from app.services import transcripts as tr
    s = main.settings
    object.__setattr__(s, "owner_key", "op-key")

    class R:
        headers = {"content-type": "text/html"}
        text = "<html><body><p>" + ("For the full fiscal year 2026 we expect revenue of $4.2 billion. " * 60) + "</p></body></html>"
        content = text.encode()
        def raise_for_status(self): pass

    monkeypatch.setattr(tr.httpx, "get", lambda *a, **k: R())
    body = {"ticker": "NVDA", "call_date": "2026-02-25", "url": "https://ir.example.com/t.html"}
    op = B("op-0002") | {"X-Owner-Key": "op-key"}
    try:
        assert c.post("/api/transcripts/from-url", json=body, headers=B("visitor-8888")).status_code == 403
        assert c.post("/api/transcripts/from-url?refresh=false", json=body | {"url": "https://127.0.0.1/x"}, headers=op).status_code == 400
        r = c.post("/api/transcripts/from-url?refresh=false", json=body, headers=op)
        assert r.status_code == 200 and r.json()["chars"] > 2000
    finally:
        object.__setattr__(s, "owner_key", "")

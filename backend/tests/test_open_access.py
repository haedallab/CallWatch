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
    assert me["signed_in"] is False and me["uid"] == "anon-browser-bbbb-2222" and me["usage"]["limit"] == 3


def test_anonymous_new_ticker_limit_counts_browser_and_ip(c):
    day = time.strftime("%Y-%m-%d")
    main.db.cache_set(f"usage:ip:testclient:{day}", 3)  # same IP already used the quota from other browsers
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

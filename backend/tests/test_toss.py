"""Toss Securities connector: response normalisation, token reuse, error hints, owner-key gating."""
import os
import tempfile

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp())
os.environ.setdefault("WARM_FEATURED", "0")

import httpx  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import db, main  # noqa: E402
from app.services import toss  # noqa: E402

# shape copied from the official spec example (openapi.tossinvest.com, /api/v1/holdings "withHoldings")
SPEC_EXAMPLE = {
    "totalPurchaseAmount": {"krw": "6500000", "usd": "1553"},
    "marketValue": {"amount": {"krw": "7200000", "usd": "1785"}, "amountAfterCost": {"krw": "7050000", "usd": "1771.43"}},
    "profitLoss": {"amount": {"krw": "700000", "usd": "232"}, "rate": "0.1179", "rateAfterCost": "0.0983"},
    "dailyProfitLoss": {"amount": {"krw": "100000", "usd": "25"}, "rate": "0.0141"},
    "items": [
        {"symbol": "005930", "name": "삼성전자", "marketCountry": "KR", "currency": "KRW", "quantity": "100",
         "lastPrice": "72000", "averagePurchasePrice": "65000",
         "marketValue": {"purchaseAmount": "6500000", "amount": "7200000"}, "profitLoss": {"amount": "700000", "rate": "0.1077"}},
        {"symbol": "AAPL", "name": "애플", "marketCountry": "US", "currency": "USD", "quantity": "3",
         "lastPrice": "230.5", "averagePurchasePrice": "200",
         "marketValue": {"purchaseAmount": "600", "amount": "691.5"}, "profitLoss": {"amount": "91.5", "rate": "0.1525"}},
    ],
}


def test_normalize_mixed_currencies_and_weights():
    out = toss.normalize(SPEC_EXAMPLE, fx=1400.0)
    rows = {r["ticker"]: r for r in out["rows"]}
    assert rows["AAPL"]["value_krw"] == pytest.approx(691.5 * 1400, rel=1e-6)
    assert rows["005930"]["market"] == "KR" and rows["AAPL"]["pl_rate"] == pytest.approx(0.1525)
    assert sum(r["weight"] for r in out["rows"]) == pytest.approx(1.0, abs=1e-3)
    assert out["summary"]["market_value_krw"] == 7200000 and out["summary"]["pl_rate"] == pytest.approx(0.1179)


def test_empty_holdings():
    assert toss.normalize({"items": []})["rows"] == []


def test_token_is_cached_and_403_gives_ip_hint(monkeypatch):
    object.__setattr__(toss.settings, "toss_client_id", "id")
    object.__setattr__(toss.settings, "toss_client_secret", "secret")
    db.execute("DELETE FROM kv_cache WHERE key LIKE 'toss:%'")
    calls = {"token": 0}

    def fake_post(url, **kw):
        calls["token"] += 1
        return httpx.Response(200, json={"access_token": "T", "token_type": "Bearer", "expires_in": 86400})

    def fake_get(url, **kw):
        if "ipify" in url:
            return httpx.Response(200, json={"ip": "203.0.113.7"})
        if url.endswith("/api/v1/accounts"):
            return httpx.Response(200, json={"result": [{"accountNo": "12345678901", "accountSeq": 1, "accountType": "BROKERAGE"}]})
        return httpx.Response(403, json={"error": {"requestId": "r", "code": "ip-not-allowed", "message": "허용되지 않은 IP 주소입니다."}})

    monkeypatch.setattr(toss.httpx, "post", fake_post)
    monkeypatch.setattr(toss.httpx, "get", fake_get)
    acc = toss.accounts()
    assert acc[0]["accountNo"] == "123•••••901"  # account number masked
    with pytest.raises(toss.TossError) as e:
        toss.holdings_raw(1)
    assert "203.0.113.7" in e.value.hint and e.value.status == 403
    assert calls["token"] == 1  # one token reused across calls (re-issuing would invalidate the old one)
    object.__setattr__(toss.settings, "toss_client_id", "")
    object.__setattr__(toss.settings, "toss_client_secret", "")


def test_owner_key_gates_sync_and_hides_money():
    object.__setattr__(main.settings, "owner_key", "s3cret")
    c = TestClient(main.app)
    live = {"X-Data-Mode": "live"}
    assert c.post("/api/broker/toss/sync", json={}, headers=live).status_code == 403
    demo_h = {"X-Data-Mode": "demo"}
    ok = c.post("/api/broker/toss/sync", json={}, headers=demo_h | {"X-Owner-Key": "s3cret"})
    assert ok.status_code == 200 and ok.json()["n_analyzable"] == 4
    # callers without a browser id share the "local" portfolio: amounts hidden unless owner
    public = c.get("/api/portfolio", headers=demo_h).json()
    assert "value_krw" not in public[0] and "weight" in public[0]
    owner = c.get("/api/portfolio", headers=demo_h | {"X-Owner-Key": "s3cret"}).json()
    assert owner[0]["value_krw"] > 0
    object.__setattr__(main.settings, "owner_key", "")

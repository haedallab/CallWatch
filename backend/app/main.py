"""CallWatch API - earnings-call guidance aligned with SEC filings and prices.

Run:  uvicorn app.main:app --reload --port 8000     (Swagger UI at /docs)
"""
from __future__ import annotations

import json
import logging
import queue
import threading
import time
from contextlib import asynccontextmanager
from datetime import date

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator

from . import auth, db
from .config import settings
from .services import edgar, importer, guidance, llm, rag, scoring, toss, transcripts
from .services.align import STATUS_KO
from .services.metrics import fmt, fmt_range, public_metrics
from .services.pipeline import LiveSource, analyze

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("callwatch")
logging.getLogger("httpx").setLevel(logging.WARNING)  # per-request lines are noise (and may carry query strings)

TAGS = [
    {"name": "system", "description": "상태·메타 정보"},
    {"name": "account", "description": "로그인 사용자 정보·내 데이터 삭제 (Supabase Auth)"},
    {"name": "portfolio", "description": "보유 종목과 포트폴리오 요약"},
    {"name": "broker", "description": "토스증권 Open API 연동 (조회 전용)"},
    {"name": "analysis", "description": "가이던스 추출 → 공시(XBRL)·주가 정렬"},
    {"name": "transcripts", "description": "어닝콜 원문 업로드·관리"},
    {"name": "ai", "description": "LLM 질의응답 (RAG, 출처 포함)"},
]

async def request_context(
    request: Request,
    authorization: str | None = Header(None, include_in_schema=False),
    x_data_mode: str | None = Header(None, include_in_schema=False),
    x_client_id: str | None = Header(None, include_in_schema=False),
    x_owner_key: str | None = Header(None, include_in_schema=False),
):
    """Bind the caller (Supabase JWT), data mode and anonymous browser id for this request."""
    try:
        fwd = request.headers.get("x-forwarded-for", "")
        ip = fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "")
        auth.bind(authorization, x_data_mode, x_client_id, x_owner_key, ip)
    except auth.AuthError as e:
        raise HTTPException(401, str(e)) from e


@asynccontextmanager
async def lifespan(_app):
    start_warm()
    yield


app = FastAPI(
    lifespan=lifespan,
    title="CallWatch API",
    version="1.1.0",
    description="어닝콜·실적 보도자료의 **가이던스 발언**을 SEC EDGAR 10-Q/10-K(XBRL) 실적과 주가 반응에 "
                "정렬(Align)해 경영진 가이던스 신뢰도를 보여주는 API. 투자 권유가 아닙니다.\n\n"
                "**가입 없이 사용** — 주요 종목(`/api/featured`)은 서버가 미리 분석해 누구나 봅니다. 브라우저마다 "
                "`X-Client-Id`로 보유 종목을 따로 저장하고, 새 종목 분석은 하루 횟수를 제한합니다. "
                "로그인(`Authorization: Bearer`, Supabase)은 선택입니다. "
                "공시 기반 분석 결과는 모두가 공유하는 캐시이고, 토스증권 연동은 운영자에게만 열려 있습니다.",
    openapi_tags=TAGS,
    dependencies=[Depends(request_context)],
)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"])

STATE = {"sec_ok": None, "sec_checked": 0.0}


def source():
    """Real data only: SEC EDGAR + price providers + stored transcripts."""
    return LiveSource


def mode() -> str:
    return auth.mode()


def owner() -> bool:
    return auth.is_owner()


def require_owner() -> bool:
    if not auth.is_owner():
        if settings.auth_enabled:
            raise HTTPException(403, "토스증권 연동은 서비스 운영자 계정에서만 켜져 있습니다. 보유 종목은 직접 입력해 주세요.")
        raise HTTPException(403, "토스증권 연동은 운영자 전용입니다. 보유 종목은 붙여넣기로 입력해 주세요.")
    return True


def require_user() -> str:
    """Storage id of the caller (signed-in account or this browser)."""
    u = auth.uid()
    if not u:
        raise HTTPException(401, "로그인이 필요합니다. 로그인하지 않아도 주요 종목과 데모 데이터는 볼 수 있습니다.")
    return u


def hide_money() -> bool:
    """Callers without a browser id share the "local" portfolio; hide amounts from them unless owner.
    Everyone else only ever sees their own holdings."""
    return auth.uid() == "local" and not auth.is_owner()


def report_key(ticker: str, uid: str | None = None) -> str:
    """Analysis results are a shared cache, except when the user added their own transcripts."""
    t = ticker.upper()
    u = auth.uid() if uid is None else uid
    if u and u != "local" and db.list_transcripts(t, u):
        return f"{mode()}:{u}:{t}"
    return f"{mode()}:{t}"


def find_report(ticker: str) -> tuple[str, dict | None]:
    k = report_key(ticker)
    r = db.get_report(k)
    if r is None and k.count(":") == 2:
        k = f"{mode()}:{ticker.upper()}"
        r = db.get_report(k)
    return k, r


MONEY = ("value_krw", "pl_krw", "shares", "avg_price", "last_price")


def _err(e: Exception, status: int = 400):
    raise HTTPException(status_code=status, detail=str(e)) from e


# ---------------------------------------------------------------------------------------
# schemas
# ---------------------------------------------------------------------------------------
class Holding(BaseModel):
    ticker: str = Field(..., examples=["NVDA"], max_length=10)
    weight: float | None = Field(None, ge=0, le=1, description="포트폴리오 비중 (0~1)")
    shares: float | None = Field(None, ge=0)
    note: str | None = Field(None, max_length=120)
    name: str | None = None
    market: str | None = Field(None, description="US | KR")

    @field_validator("ticker")
    @classmethod
    def up(cls, v: str) -> str:
        return v.strip().upper()


class PreviewIn(BaseModel):
    text: str | None = Field(None, max_length=20_000, description="붙여넣은 표/CSV/자유 텍스트 (줄마다 한 종목)")
    items: list[Holding] | None = Field(None, description="직접 입력한 종목 목록")


class SyncIn(BaseModel):
    account_seq: int | None = Field(None, description="토스증권 accountSeq (비우면 첫 종합매매 계좌)")


class ExtractIn(BaseModel):
    text: str = Field(..., min_length=20, max_length=300_000)
    ticker: str = Field("TEMP", max_length=10)
    event_date: date = Field(default_factory=date.today)
    use_llm: bool = True


class TranscriptIn(BaseModel):
    ticker: str = Field(..., max_length=10)
    call_date: date
    text: str = Field(..., min_length=200, max_length=500_000)
    public: bool = Field(False, description="운영자 전용: 모든 방문자의 공용 분석에 반영 (회사 IR에 공개된 원문)")
    source_url: str | None = Field(None, max_length=500, description="원문 출처 (예: 회사 IR 페이지)")


class TranscriptUrlIn(BaseModel):
    ticker: str = Field(..., max_length=10)
    call_date: date
    url: str = Field(..., max_length=500, description="회사 IR의 콜 원문 PDF/HTML 주소")


class CallsIn(BaseModel):
    ir_url: str | None = Field(None, max_length=500, description="회사 IR 이벤트(웹캐스트) 페이지")
    audio: dict[str, str] | None = Field(None, description="실적발표일(YYYY-MM-DD) → 녹음 파일 주소 (빈 문자열이면 삭제)")
    webcast: dict[str, str] | None = Field(None, description="실적발표일 → 웹캐스트 페이지 주소 (자동 추출값 덮어쓰기)")


class QAIn(BaseModel):
    ticker: str = Field(..., max_length=10)
    question: str = Field(..., min_length=3, max_length=1000)
    k: int = Field(4, ge=1, le=8)


# ---------------------------------------------------------------------------------------
# system
# ---------------------------------------------------------------------------------------
@app.get("/health", tags=["system"], summary="서버 상태")
def health():
    if time.time() - STATE["sec_checked"] > 300:
        try:
            edgar.ticker_map()
            STATE["sec_ok"] = True
        except Exception:
            STATE["sec_ok"] = False
        STATE["sec_checked"] = time.time()
    return {"status": "ok", "mode": mode(), "sec_reachable": STATE["sec_ok"], "llm": settings.llm_label,
            "llm_enabled": llm.enabled(), "llm_stats": llm.STATS, "auth_enabled": settings.auth_enabled,
            "default_mode": "live"}


# ---------------------------------------------------------------------------------------
# account
# ---------------------------------------------------------------------------------------
@app.get("/api/me", tags=["account"], summary="현재 사용자 · 권한 · 오늘 사용량")
def me():
    u = auth.user()
    uid = auth.uid()
    today = date.today().isoformat()
    return {"auth_enabled": settings.auth_enabled, "signed_in": bool(u),
            "user": u, "uid": uid, "mode": mode(), "owner": auth.is_owner(), "operator": auth.is_verified_owner(),
            "toss_available": auth.is_owner() and toss.configured(),
            "featured": _featured(),
            "usage": {"today": db.count_usage(uid, today) if uid else 0, "limit": _limit(),
                      "qa_today": db.count_usage(f"qa:{uid}", today) if uid else 0, "qa_limit": settings.qa_daily_limit}}


@app.delete("/api/me", tags=["account"], summary="내 데이터 삭제 (보유 종목·트랜스크립트·개인 분석 결과)")
def delete_me(uid: str = Depends(require_user)):
    db.delete_user(uid)
    if uid.startswith("anon-") or uid == "local":
        return {"deleted": True, "account_deleted": False}
    account_deleted = False
    u = auth.user()
    if settings.auth_enabled and u and settings.supabase_service_key and settings.supabase_url:
        try:
            r = httpx.delete(f"{settings.supabase_url}/auth/v1/admin/users/{u['uid']}", timeout=10,
                             headers={"apikey": settings.supabase_service_key,
                                      "Authorization": f"Bearer {settings.supabase_service_key}"})
            account_deleted = r.status_code in (200, 204)
        except httpx.HTTPError:
            log.warning("supabase account delete failed for %s", u["uid"])
    return {"deleted": True, "account_deleted": account_deleted}


@app.get("/api/meta", tags=["system"], summary="데이터 출처·판정 규칙·지표 목록")
def meta():
    return {
        "mode": mode(),
        "llm": settings.llm_label,
        "metrics": public_metrics(),
        "status_labels": STATUS_KO,
        "sources": [
            {"name": "SEC EDGAR Submissions API", "use": "8-K Item 2.02(실적발표) 일자, 10-Q/10-K 목록",
             "url": "https://data.sec.gov/submissions/"},
            {"name": "SEC EDGAR XBRL companyfacts", "use": "분기/연간 실적(매출, 마진, EPS, OpEx, CapEx)",
             "url": "https://data.sec.gov/api/xbrl/companyfacts/"},
            {"name": "8-K Exhibit 99.1 보도자료", "use": "'Outlook/Guidance' 섹션의 공식 가이던스",
             "url": "https://www.sec.gov/Archives/edgar/data/"},
            {"name": "10-Q/10-K MD&A", "use": "실적 근거 문단 (TF-IDF 검색)", "url": "https://www.sec.gov/"},
            {"name": "어닝콜 트랜스크립트", "use": "사용자 업로드 · 로컬 파일 · API Ninjas(선택)", "url": ""},
            {"name": "Yahoo Finance (yfinance) / Stooq", "use": "일별 종가, 벤치마크 SPY", "url": ""},
        ],
        "disclaimer": "본 서비스는 공시 정보의 정리·대조 도구이며 투자 권유가 아닙니다. 판단 전 공시 원문을 확인하세요.",
    }


@app.get("/api/search", tags=["portfolio"], summary="티커/회사명 검색")
def search(q: str = Query(..., min_length=1, max_length=40)):
    try:
        return edgar.search(q)
    except edgar.EdgarError as e:
        _err(e, 503)


# ---------------------------------------------------------------------------------------
# portfolio
# ---------------------------------------------------------------------------------------
def _hkey(uid: str) -> str:
    return f"holdings:{mode()}:{uid}"


def _holdings() -> list[dict]:
    uid = auth.uid()
    h = db.cache_get(_hkey(uid)) if uid else None
    return h or []


@app.get("/api/portfolio", tags=["portfolio"], summary="내 보유 종목 조회")
def get_portfolio():
    rows = _holdings()
    if not hide_money():
        return rows
    return [{k: v for k, v in r.items() if k not in MONEY} for r in rows]


def _check(rows: list[dict]) -> list[dict]:
    """Resolve each row against SEC. Korean codes are kept but marked non-analyzable."""
    out = []
    for r in rows:
        t = r["ticker"].upper()
        kr = (r.get("market") == "KR") or bool(importer.KR_CODE.match(t))
        row = {**r, "ticker": t, "market": "KR" if kr else "US", "ok": True, "analyzable": not kr, "error": None}
        if kr:
            row["error"] = "국내 종목 — 미국 SEC 공시 대상이 아니라 분석에서 제외됩니다."
        else:
            try:
                info = source().resolve(t)
                row["name"] = row.get("name") or info.get("title")
            except edgar.EdgarError as e:
                msg = str(e)
                unreachable = "찾지 못했" not in msg and "데모 모드" not in msg
                row |= {"ok": unreachable, "analyzable": unreachable, "error": msg}
        out.append(row)
    return out


def _weights(rows: list[dict]) -> None:
    given = [r for r in rows if r.get("weight")]
    if given and len(given) == len(rows):
        tw = sum(r["weight"] for r in rows)
        for r in rows:
            r["weight"] = round(r["weight"] / tw, 4)
    elif rows:  # equal weights unless every row says otherwise
        for r in rows:
            r["weight"] = round(1 / len(rows), 4)


@app.post("/api/portfolio/preview", tags=["portfolio"], summary="붙여넣기·직접 입력한 보유 종목 확인 (저장 안 함)")
def preview_portfolio(body: PreviewIn):
    rows, skipped = importer.parse(body.text or "") if body.text else ([], [])
    for it in body.items or []:
        rows.append(it.model_dump())
    if not rows:
        raise HTTPException(422, {"message": "종목을 찾지 못했습니다. 한 줄에 'AAPL 10' 처럼 티커와 수량을 적어 주세요.",
                                  "skipped": skipped})
    rows = _check(rows[:30])
    good = [r for r in rows if r["ok"]]
    _weights(good)
    return {"rows": rows, "skipped": skipped, "n_ok": len(good), "n_analyzable": sum(r["analyzable"] for r in good)}


@app.put("/api/portfolio", tags=["portfolio"], summary="내 보유 종목 저장 (전체 교체)")
def put_portfolio(items: list[Holding], uid: str = Depends(require_user)):
    if len(items) > 30:
        _err(ValueError("최대 30종목까지 등록할 수 있습니다."))
    rows = _check([it.model_dump() for it in items])
    bad = [{"ticker": r["ticker"], "error": r["error"]} for r in rows if not r["ok"]]
    if bad:
        raise HTTPException(status_code=422, detail={"message": "확인되지 않는 티커가 있습니다.", "invalid": bad})
    rows = [{k: v for k, v in r.items() if k not in ("ok", "error")} | {"source": "manual"} for r in rows]
    _weights(rows)
    db.cache_set(_hkey(uid), rows)
    return rows


@app.get("/api/portfolio/summary", tags=["portfolio"], summary="포트폴리오 신뢰도 요약 (분석된 종목 기준)")
def portfolio_summary():
    out = _summary(_holdings())
    out["broker"] = db.cache_get(f"broker:last:{mode()}:{auth.uid()}") if auth.uid() else None
    return out


def _summary(hold: list[dict], shared_only: bool = False) -> dict:
    reports, missing = [], []
    for h in hold:
        if not h.get("analyzable", True):
            continue
        r = db.get_report(f"{mode()}:{h['ticker']}") if shared_only else find_report(h["ticker"])[1]
        (reports.append(r) if r else missing.append(h["ticker"]))
    summary = scoring.portfolio(reports, {h["ticker"]: h.get("weight") or 0 for h in hold})
    feed = []
    for r in reports:
        for g in r["guidance"]:
            feed.append({k: g.get(k) for k in ("id", "ticker", "event_date", "metric", "metric_label", "basis", "kind",
                                               "low", "high", "mid", "unit", "status", "status_ko", "surprise",
                                               "surprise_unit", "favorable", "kept", "basis_mismatch", "progress")}
                        | {"period": (g.get("period") or {}).get("label"), "source": g.get("source")})
    upcoming = []
    for r in reports:
        evs = r.get("events") or []
        if evs:
            last = date.fromisoformat(evs[-1]["date"])
            upcoming.append({"ticker": r["ticker"], "last_release": evs[-1]["date"],
                             "next_release_est": date.fromordinal(last.toordinal() + 91).isoformat()})
    excluded = [{"ticker": h["ticker"], "name": h.get("name"), "weight": h.get("weight"),
                 "reason": "미국 SEC 공시 대상이 아님 (국내 종목은 DART 연동 확장 예정)"}
                for h in hold if not h.get("analyzable", True)]
    return {**summary, "mode": mode(), "missing": missing, "guidance_feed": feed, "excluded": excluded,
            "broker": None, "upcoming": sorted(upcoming, key=lambda x: x["next_release_est"])}


# ---------------------------------------------------------------------------------------
# featured: analysed by the server, open to everyone
# ---------------------------------------------------------------------------------------
RUNNING: dict[str, float] = {}        # report key -> start time (one analysis per key at a time)
WARM: dict[str, str] = {}             # featured ticker -> last warm-up error


def _featured() -> list[str]:
    return settings.featured


@app.get("/api/featured", tags=["portfolio"], summary="주요 종목 요약 (가입 없이 공개, 서버가 미리 분석)")
def featured():
    ts = _featured()
    out = _summary([{"ticker": t, "weight": round(1 / len(ts), 4)} for t in ts], shared_only=True)
    status = {}
    for t in ts:
        k = f"{mode()}:{t}"
        status[t] = ("running" if k.upper() in RUNNING else "ready" if db.report_updated(k) else
                     "failed" if WARM.get(t) else "queued")
    names = {}
    for t in ts:
        r = db.get_report(f"{mode()}:{t}")
        names[t] = r["name"] if r else None
        if not names[t]:
            try:
                names[t] = edgar.resolve(t).get("title")
            except Exception:
                pass
    return out | {"tickers": ts, "status": status, "names": names,
                  "errors": {t: e for t, e in WARM.items() if t in ts}}


# ---------------------------------------------------------------------------------------
# broker: Toss Securities (read-only)
# ---------------------------------------------------------------------------------------
@app.get("/api/broker/status", tags=["broker"], summary="토스증권 연동 상태")
def broker_status():
    is_owner, uid = auth.is_owner(), auth.uid()
    base = {"provider": "toss", "mode": mode(), "configured": toss.configured(), "owner": is_owner,
            "owner_only": True, "owner_key_required": bool(settings.owner_key),
            "last_sync": db.cache_get(f"broker:last:{mode()}:{uid}") if uid else None}
    if not is_owner:
        return base | {"connected": None, "available": False,
                       "error": "토스증권 연동은 서비스 운영자에게만 켜져 있습니다.",
                       "hint": "토스증권 Open API는 본인 계좌의 본인 이용만 허용합니다. 보유 종목은 직접 입력하거나 붙여넣어 주세요."}
    if not toss.configured():
        return base | {"connected": False, "error": "서버에 토스증권 API 키가 없습니다.",
                       "hint": "Render 환경변수에 TOSS_CLIENT_ID, TOSS_CLIENT_SECRET을 넣고 서버 공인 IP를 토스증권에 등록하세요."}
    if not is_owner:
        return base | {"connected": None}
    try:
        return base | {"connected": True, "accounts": toss.accounts()}
    except toss.TossError as e:
        return base | {"connected": False, "error": str(e), "code": e.code, "hint": e.hint}


@app.post("/api/broker/toss/sync", tags=["broker"], summary="토스증권 보유종목을 포트폴리오로 가져오기")
def broker_sync(body: SyncIn, _: bool = Depends(require_owner), uid: str = Depends(require_user)):
    try:
        accts = toss.accounts()
        if not accts:
            raise HTTPException(404, "조회 가능한 종합매매 계좌가 없습니다.")
        seq = body.account_seq or (int(settings.toss_account_seq) if settings.toss_account_seq else accts[0]["accountSeq"])
        raw, fx = toss.holdings_raw(seq), toss.usd_krw()
    except toss.TossError as e:
        raise HTTPException(e.status if e.status < 500 else 502, {"message": str(e), "code": e.code, "hint": e.hint}) from e
    norm = toss.normalize(raw, fx)
    rows = []
    for r in norm["rows"]:
        ok = r["market"] == "US"
        if ok:
            try:
                source().resolve(r["ticker"])
            except edgar.EdgarError as e:
                ok = "찾지 못했" not in str(e)  # keep if SEC merely unreachable
        rows.append(r | {"analyzable": ok, "source": "toss", "note": r["name"][:40]})
    db.cache_set(_hkey(uid), rows)
    last = {"at": time.strftime("%Y-%m-%d %H:%M"), "account_seq": seq, "n": len(rows),
            "n_analyzable": sum(r["analyzable"] for r in rows), "summary": norm["summary"], "usd_krw": fx}
    db.cache_set(f"broker:last:{mode()}:{uid}", last)
    return {"holdings": rows, **last}


# ---------------------------------------------------------------------------------------
# analysis
# ---------------------------------------------------------------------------------------
def _warm_loop():
    """Keep featured stocks analysed so first-time visitors never wait."""
    time.sleep(5)
    while True:
        for t in settings.featured:
            key = f"live:{t}"
            if _fresh(key) or key.upper() in RUNNING:
                continue
            RUNNING[key.upper()] = time.time()
            try:
                rep = analyze(t, n_events=8, use_llm=llm.enabled(), src=LiveSource, store_key=key)
                rep["n_events_requested"] = 8
                db.save_report(key, rep)
                WARM.pop(t, None)
                log.info("warm-up %s: %d guidance items", t, len(rep["guidance"]))
            except Exception as e:  # keep going with the others
                WARM[t] = str(e)[:300]
                log.warning("warm-up %s failed: %s", t, e)
            finally:
                RUNNING.pop(key.upper(), None)
            time.sleep(3)
        time.sleep(600 if WARM else 3600)  # retry failures sooner


def start_warm():
    if settings.warm_featured and settings.featured:
        threading.Thread(target=_warm_loop, daemon=True, name="warm-featured").start()
def _limit() -> int:
    if auth.is_verified_owner():
        return 0  # unlimited
    return settings.daily_analysis_limit if auth.user() else settings.anon_daily_analysis_limit


def _charge(ticker: str) -> str | None:
    """Live analyses hit SEC and the LLM. Featured stocks are free; anything else counts against a daily
    limit per browser/account and per IP (owners unlimited)."""
    uid = auth.uid()
    if auth.is_verified_owner():
        return uid
    if settings.auth_enabled and not uid:
        raise HTTPException(401, "실데이터 분석은 로그인 후 이용할 수 있습니다.")
    if ticker.upper() in settings.featured:
        return uid
    day, limit = date.today().isoformat(), _limit()
    ip_key = f"ip:{auth.ip()}" if auth.ip() else None
    used = max(db.count_usage(uid, day) if uid else 0, db.count_usage(ip_key, day) if ip_key and not auth.user() else 0)
    if used >= limit:
        raise HTTPException(429, f"오늘 새 종목 분석 한도({limit}회)를 모두 썼습니다. 주요 종목과 이미 분석된 종목은 계속 볼 수 있고, "
                                 "한도는 내일 초기화됩니다.")
    if uid:
        db.bump_usage(uid, day)
    if ip_key:
        db.bump_usage(ip_key, day)
    return uid


def _fresh(key: str) -> bool:
    t = db.report_updated(key)
    return bool(t) and time.time() - t < settings.featured_refresh_hours * 3600


@app.post("/api/analyze/{ticker}", tags=["analysis"], summary="종목 분석 실행 (가이던스 추출·정렬·이벤트스터디)")
def run_analysis(ticker: str, events: int = Query(8, ge=2, le=16), use_llm: bool = True,
                 refresh: bool = False, evidence: bool = True):
    key = report_key(ticker)
    if not refresh:
        cached = db.get_report(key)
        if cached and cached.get("n_events_requested") == events:
            return cached
    if refresh and not auth.is_verified_owner() and _fresh(key):
        cached = db.get_report(key)
        if cached:
            return cached  # recently refreshed; avoid hammering SEC
    if key.upper() in RUNNING:
        raise HTTPException(409, "지금 이 종목을 분석하고 있습니다. 잠시 후 결과가 나타납니다.")
    uid = _charge(ticker)
    try:
        RUNNING[key.upper()] = time.time()
        rep = analyze(ticker, n_events=events, use_llm=use_llm, with_evidence=evidence, src=source(),
                      user_id=uid, store_key=key)
    except edgar.EdgarError as e:
        msg = str(e)
        _err(e, 404 if "찾지 못했" in msg else 503)
    finally:
        RUNNING.pop(key.upper(), None)
    rep["n_events_requested"] = events
    db.save_report(key, rep)
    return rep


@app.get("/api/analyze/{ticker}/stream", tags=["analysis"],
         summary="분석 실행 + 단계별 진행 상황 스트리밍 (Server-Sent Events)")
def analyze_stream(ticker: str, events: int = Query(8, ge=2, le=16), use_llm: bool = True,
                   refresh: bool = Query(False, description="이미 분석된 결과가 있어도 다시 계산")):
    q: queue.Queue = queue.Queue()
    key = report_key(ticker)
    src = source()
    cached = db.get_report(key)
    reuse = cached and (not refresh or (not auth.is_verified_owner() and _fresh(key)))
    if not reuse and key.upper() in RUNNING:
        raise HTTPException(409, "지금 이 종목을 분석하고 있습니다. 잠시 후 결과가 나타납니다.")
    uid = None if reuse else _charge(ticker)  # resolve before the worker thread: context vars do not cross threads

    def work():
        if reuse:
            q.put(("done", {"ticker": cached["ticker"], "score": cached["score"], "n_guidance": len(cached["guidance"]),
                            "elapsed_sec": 0, "warnings": cached.get("warnings", []), "cached": True}))
            return
        RUNNING[key.upper()] = time.time()
        try:
            rep = analyze(ticker, n_events=events, use_llm=use_llm, src=src, progress=lambda e: q.put(("progress", e)),
                          user_id=uid, store_key=key)
            rep["n_events_requested"] = events
            db.save_report(key, rep)
            q.put(("done", {"ticker": rep["ticker"], "score": rep["score"], "n_guidance": len(rep["guidance"]),
                            "elapsed_sec": rep["elapsed_sec"], "warnings": rep["warnings"]}))
        except Exception as e:  # surface every failure to the client
            q.put(("error", {"message": str(e)}))
        finally:
            RUNNING.pop(key.upper(), None)

    threading.Thread(target=work, daemon=True).start()

    def gen():
        while True:
            try:
                kind, data = q.get(timeout=15)
            except queue.Empty:
                yield ": keep-alive\n\n"
                continue
            yield f"event: {kind}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"
            if kind in ("done", "error"):
                break

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/report/{ticker}", tags=["analysis"], summary="저장된 분석 결과 조회")
def get_report(ticker: str):
    r = find_report(ticker)[1]
    if not r:
        raise HTTPException(404, "아직 분석되지 않은 종목입니다. POST /api/analyze/{ticker} 를 먼저 호출하세요.")
    return r


@app.get("/api/report/{ticker}/guidance", tags=["analysis"], summary="가이던스 목록 필터링")
def report_guidance(ticker: str, status: str | None = None, metric: str | None = None):
    r = get_report(ticker)
    return [g for g in r["guidance"] if (not status or g.get("status") == status)
            and (not metric or g["metric"] == metric)]


@app.post("/api/extract", tags=["analysis"], summary="텍스트에서 가이던스 추출 (저장 안 함)")
def extract(body: ExtractIn):
    items = guidance.extract(body.text, ticker=body.ticker, event_date=body.event_date.isoformat(),
                             source="사용자 입력", use_llm=body.use_llm)
    return {"items": items, "llm_used": body.use_llm and llm.enabled(), "n": len(items)}


@app.get("/api/document", tags=["analysis"], summary="공시/보도자료 원문 텍스트 (sec.gov 한정)")
def document(url: str):
    try:
        if not url.startswith(("https://www.sec.gov/", "https://data.sec.gov/")):
            raise HTTPException(400, "sec.gov 문서만 조회할 수 있습니다.")
        return {"url": url, "text": edgar.document_text(url)}
    except edgar.EdgarError as e:
        _err(e, 503)
    except (StopIteration, ValueError) as e:
        _err(e, 404)


# ---------------------------------------------------------------------------------------
# transcripts
# ---------------------------------------------------------------------------------------
@app.post("/api/transcripts", tags=["transcripts"], summary="어닝콜 트랜스크립트 저장 + 가이던스 미리보기")
def add_transcript(body: TranscriptIn, uid: str = Depends(require_user)):
    try:
        source().resolve(body.ticker)
    except edgar.EdgarError as e:
        _err(e, 404)
    if body.public and not auth.is_verified_owner():
        raise HTTPException(403, "공개 원문은 운영자만 올릴 수 있습니다.")
    if body.source_url and not body.source_url.startswith("https://"):
        raise HTTPException(400, "출처는 https:// 주소여야 합니다.")
    owner_id = transcripts.PUBLIC if body.public else uid
    tid = db.save_transcript(body.ticker, body.call_date.isoformat(), "upload", body.text, owner_id, body.source_url or "")
    items = guidance.extract(body.text, ticker=body.ticker, event_date=body.call_date.isoformat(),
                             source="어닝콜 트랜스크립트", use_llm=True)
    if body.public:
        _refresh_shared(body.ticker.upper())
    return {"id": tid, "n_guidance": len(items), "items": items, "public": body.public,
            "hint": ("공개 원문으로 저장했습니다. 이 종목의 공용 분석을 백그라운드에서 다시 계산합니다." if body.public else
                     "재분석(refresh=true)하면 트랜스크립트 가이던스가 실적과 정렬됩니다. "
                     "올린 원문은 나에게만 보이며, 이 종목의 분석 결과도 내 전용으로 저장됩니다.")}


@app.post("/api/transcripts/from-url", tags=["transcripts"], summary="IR 페이지의 콜 원문(PDF·HTML)을 공개 원문으로 가져오기 (운영자)")
def transcript_from_url(body: TranscriptUrlIn, refresh: bool = True):
    if not auth.is_verified_owner():
        raise HTTPException(403, "운영자만 쓸 수 있습니다.")
    try:
        text = transcripts.fetch_text(body.url)
    except ValueError as e:
        _err(e, 400)
    except httpx.HTTPError as e:
        _err(e, 502)
    if len(text) < 2000:
        raise HTTPException(422, f"원문이 너무 짧습니다({len(text)}자). 주소가 원문 파일인지 확인하세요.")
    t = body.ticker.upper()
    tid = db.save_transcript(t, body.call_date.isoformat(), "upload", text[:500_000], transcripts.PUBLIC, body.url)
    if refresh:
        _refresh_shared(t)
    return {"id": tid, "chars": len(text), "preview": text[:300]}


def _refresh_shared(ticker: str):
    """Recompute the shared report after the operator adds a public transcript."""
    key, use_llm = f"{mode()}:{ticker}", llm.enabled()

    def work():
        if key.upper() in RUNNING:
            return
        RUNNING[key.upper()] = time.time()
        try:
            rep = analyze(ticker, n_events=8, use_llm=use_llm, src=source(), store_key=key)
            rep["n_events_requested"] = 8
            db.save_report(key, rep)
        except Exception as e:
            log.warning("shared refresh %s failed: %s", ticker, e)
        finally:
            RUNNING.pop(key.upper(), None)

    threading.Thread(target=work, daemon=True).start()


@app.get("/api/transcripts/{ticker}", tags=["transcripts"], summary="트랜스크립트 목록 (공용 샘플 + 내가 올린 원문)")
def list_transcripts(ticker: str, include_text: bool = False):
    uid = auth.uid()
    rows = transcripts.all_transcripts(ticker, uid)
    out = []
    for r in rows:
        public = r.get("user_id") == transcripts.PUBLIC
        row = {**{k: r[k] for k in ("id", "ticker", "call_date", "source")}, "chars": len(r["text"]),
               "preview": r["text"][:300], "public": public, "source_url": r.get("source_url") or ""}
        # operator-published transcripts belong to the company: visitors get quotes and the link, not the full text
        if include_text and (not public or auth.is_verified_owner()):
            row["text"] = r["text"]
        out.append(row)
    return out


@app.delete("/api/transcripts/{tid}", tags=["transcripts"], summary="내가 올린 트랜스크립트 삭제")
def delete_transcript(tid: str, uid: str = Depends(require_user)):
    if tid.startswith(transcripts.PUBLIC + ":"):
        if not auth.is_verified_owner():
            raise HTTPException(403, "공개 원문은 운영자만 지울 수 있습니다.")
        db.delete_transcript(tid, transcripts.PUBLIC)
        _refresh_shared(tid.split(":")[1])
        return {"deleted": tid}
    db.delete_transcript(tid, uid)
    return {"deleted": tid}


@app.get("/api/transcripts/{ticker}/fetch", tags=["transcripts"], summary="API Ninjas에서 트랜스크립트 가져오기 (선택)")
def fetch_transcript(ticker: str, year: int = Query(..., ge=2010, le=2100), quarter: int = Query(..., ge=1, le=4),
                     uid: str = Depends(require_user)):
    if not settings.api_ninjas_key:
        raise HTTPException(400, "API_NINJAS_KEY 가 설정되지 않았습니다. 원문을 직접 붙여넣어 주세요.")
    r = transcripts.fetch_api_ninjas(ticker, year, quarter, uid)
    if not r:
        raise HTTPException(404, "해당 분기 트랜스크립트를 찾지 못했습니다.")
    return {k: r[k] for k in ("ticker", "call_date", "source")} | {"chars": len(r["text"])}


# ---------------------------------------------------------------------------------------
# earnings calls: where to listen
# ---------------------------------------------------------------------------------------
IR_PAGES = {  # fallback when a release does not name its webcast page
    "AAPL": "https://investor.apple.com/investor-relations/default.aspx",
    "MSFT": "https://www.microsoft.com/en-us/investor",
    "NVDA": "https://investor.nvidia.com",
    "GOOGL": "https://abc.xyz/investor/",
    "TSLA": "https://ir.tesla.com",
    "C": "https://www.citigroup.com/global/investors",
    "LLY": "https://investor.lilly.com",
}
AUDIO_EXT = (".mp3", ".m4a", ".aac", ".wav", ".ogg", ".mp4")


def _https(u: str | None) -> bool:
    return bool(u) and u.startswith("https://") and len(u) < 500


@app.get("/api/calls/{ticker}", tags=["analysis"], summary="실적발표 콜 듣기 링크 (웹캐스트·녹음·IR 페이지)")
def calls(ticker: str):
    t = ticker.upper()
    reg = db.cache_get(f"calls:{t}") or {}
    rep = find_report(t)[1] or {}
    events = []
    for e in rep.get("events") or []:
        d = e["date"]
        audio = (reg.get("audio") or {}).get(d)
        events.append({"date": d, "audio_url": audio,
                       "webcast_url": (reg.get("webcast") or {}).get(d) or e.get("webcast_url"),
                       "press_release_url": e.get("press_release_url")})
    return {"ticker": t, "ir_url": reg.get("ir_url") or IR_PAGES.get(t), "events": events[::-1],
            "note": "웹캐스트 다시듣기는 회사가 보통 몇 주~몇 달 동안만 제공합니다."}


@app.put("/api/calls/{ticker}", tags=["analysis"], summary="콜 링크 등록 (운영자)")
def set_calls(ticker: str, body: CallsIn):
    if not auth.is_verified_owner():
        raise HTTPException(403, "콜 링크는 운영자만 등록할 수 있습니다.")
    t = ticker.upper()
    reg = db.cache_get(f"calls:{t}") or {}
    if body.ir_url is not None:
        if body.ir_url and not _https(body.ir_url):
            raise HTTPException(400, "https:// 주소만 등록할 수 있습니다.")
        reg["ir_url"] = body.ir_url or None
    for field_name in ("audio", "webcast"):
        updates = getattr(body, field_name)
        if updates is None:
            continue
        cur = dict(reg.get(field_name) or {})
        for d, u in updates.items():
            try:
                date.fromisoformat(d)
            except ValueError:
                raise HTTPException(400, f"날짜 형식이 아닙니다: {d}") from None
            if not u:
                cur.pop(d, None)
            elif not _https(u):
                raise HTTPException(400, "https:// 주소만 등록할 수 있습니다.")
            else:
                cur[d] = u
        reg[field_name] = cur
    db.cache_set(f"calls:{t}", reg)
    return calls(t)


# ---------------------------------------------------------------------------------------
# AI Q&A
# ---------------------------------------------------------------------------------------
@app.post("/api/qa", tags=["ai"], summary="종목 질의응답 (해당 종목 문서만 검색, 출처 표시)")
def qa(body: QAIn):
    t = body.ticker.upper()
    key, rep = find_report(t)
    corpus = db.cache_get(f"corpus:{key.lower()}") or []
    if not corpus:
        raise HTTPException(404, "먼저 이 종목을 분석해 주세요 (문서 색인이 없습니다).")
    if llm.enabled() and not auth.is_verified_owner():
        day, who = date.today().isoformat(), f"qa:{auth.uid() or 'ip:' + auth.ip()}"
        if db.count_usage(who, day) >= settings.qa_daily_limit:
            raise HTTPException(429, f"오늘 AI 질문 한도({settings.qa_daily_limit}회)를 모두 썼습니다. 내일 다시 이용해 주세요.")
        db.bump_usage(who, day)
    rep = rep or {}
    # structured facts as an extra, always-relevant context
    facts = []
    gs = [g for g in rep.get("guidance", []) if g.get("status") in ("above", "within", "below", "pending")]
    misses = sorted([g for g in gs if g.get("status") != "pending" and not g.get("kept")],
                    key=lambda g: -abs(g.get("surprise") or 0))
    pend = [g for g in gs if g.get("status") == "pending"]
    recent = sorted([g for g in gs if g.get("kept")], key=lambda g: g["event_date"], reverse=True)
    for g in (misses[:5] + pend[:4] + recent[:6])[:14]:
        facts.append(f"{g['event_date']} 발표 · {g['metric_label']} ({g['basis']}) 가이던스 "
                     f"{fmt_range(g['low'], g['high'], g['unit'])} → {(g.get('period') or {}).get('label', '')} "
                     f"판정: {g.get('status_ko')}"
                     + (f"{' (유리)' if g.get('favorable') else ' (불리)' if g.get('favorable') is False else ''}, "
                        f"실제 {fmt(g['actual'], g['unit'])}, 차이 {g['surprise']:+.1f}{'%p' if g['surprise_unit'] == 'pp' else '%'}"
                        if g.get("actual") is not None else ""))
    hits = rag.rank(body.question, corpus, k=body.k)
    ctx = ([{"text": "\n".join(facts), "source": "CallWatch 정렬 결과표", "date": rep.get("generated_at", ""),
             "url": ""}] if facts else []) + hits
    t0 = time.time()
    out = rag.answer(body.question, ctx)
    out["latency_ms"] = int((time.time() - t0) * 1000)
    return out

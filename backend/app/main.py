"""CallWatch API - earnings-call guidance aligned with SEC filings and prices.

Run:  uvicorn app.main:app --reload --port 8000     (Swagger UI at /docs)
"""
from __future__ import annotations

import json
import logging
import queue
import threading
import time
from datetime import date

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator

from . import auth, db
from .config import settings
from .services import demo, edgar, importer, guidance, llm, rag, scoring, toss, transcripts
from .services.align import STATUS_KO
from .services.metrics import fmt, fmt_range, public_metrics
from .services.pipeline import LiveSource, analyze

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("callwatch")

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
    authorization: str | None = Header(None, include_in_schema=False),
    x_data_mode: str | None = Header(None, description="demo | live (브라우저마다 따로 선택)"),
    x_client_id: str | None = Header(None, include_in_schema=False),
    x_owner_key: str | None = Header(None, include_in_schema=False),
):
    """Bind the caller (Supabase JWT), data mode and anonymous browser id for this request."""
    try:
        auth.bind(authorization, x_data_mode, x_client_id, x_owner_key)
    except auth.AuthError as e:
        raise HTTPException(401, str(e)) from e


app = FastAPI(
    title="CallWatch API",
    version="1.1.0",
    description="어닝콜·실적 보도자료의 **가이던스 발언**을 SEC EDGAR 10-Q/10-K(XBRL) 실적과 주가 반응에 "
                "정렬(Align)해 경영진 가이던스 신뢰도를 보여주는 API. 투자 권유가 아닙니다.\n\n"
                "**사용자 구분** — `Authorization: Bearer <Supabase access token>`로 로그인 사용자를, "
                "`X-Data-Mode: demo|live`로 데이터 모드를 구분합니다. 보유 종목·트랜스크립트는 사용자별로 저장되고, "
                "공시 기반 분석 결과는 모든 사용자가 공유하는 캐시입니다. 토스증권 연동은 서버 소유자 계정에서만 켜집니다.",
    openapi_tags=TAGS,
    dependencies=[Depends(request_context)],
)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"])

STATE = {"sec_ok": None, "sec_checked": 0.0}


def is_demo() -> bool:
    return auth.mode() == "demo"


def source(demo_mode: bool | None = None):
    return demo.DemoSource if (is_demo() if demo_mode is None else demo_mode) else LiveSource


def mode() -> str:
    return auth.mode()


def owner() -> bool:
    return auth.is_owner()


def require_owner() -> bool:
    if not auth.is_owner():
        if settings.auth_enabled:
            raise HTTPException(403, "토스증권 연동은 서비스 운영자 계정에서만 켜져 있습니다. 보유 종목은 직접 입력해 주세요.")
        raise HTTPException(401, "계좌 연동은 소유자 키(X-Owner-Key)가 필요합니다.")
    return True


def require_user() -> str:
    """Storage id of the caller; live data needs a signed-in user."""
    u = auth.uid()
    if not u:
        raise HTTPException(401, "로그인이 필요합니다. 로그인하지 않아도 데모 데이터는 둘러볼 수 있습니다.")
    return u


def hide_money() -> bool:
    """Single-user deployments share one portfolio; hide amounts from visitors there.
    With sign-in, everyone only ever sees their own holdings."""
    return not settings.auth_enabled and not auth.is_owner()


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


class ModeIn(BaseModel):
    demo: bool


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


class QAIn(BaseModel):
    ticker: str = Field(..., max_length=10)
    question: str = Field(..., min_length=3, max_length=1000)
    k: int = Field(4, ge=1, le=8)


# ---------------------------------------------------------------------------------------
# system
# ---------------------------------------------------------------------------------------
@app.get("/health", tags=["system"], summary="서버 상태")
def health():
    if not is_demo() and time.time() - STATE["sec_checked"] > 300:
        try:
            edgar.ticker_map()
            STATE["sec_ok"] = True
        except Exception:
            STATE["sec_ok"] = False
        STATE["sec_checked"] = time.time()
    return {"status": "ok", "mode": mode(), "sec_reachable": STATE["sec_ok"], "llm": settings.llm_label,
            "llm_enabled": llm.enabled(), "llm_stats": llm.STATS, "auth_enabled": settings.auth_enabled,
            "default_mode": "demo" if settings.demo_mode else "live"}


@app.post("/api/mode", tags=["system"], summary="(호환용) 모드 확인 — 모드는 요청마다 X-Data-Mode 헤더로 보냅니다")
def set_mode(body: ModeIn):
    return {"mode": "demo" if body.demo else "live",
            "hint": "모드는 서버 전역이 아니라 요청별입니다. 이후 요청에 X-Data-Mode 헤더를 넣어 주세요."}


# ---------------------------------------------------------------------------------------
# account
# ---------------------------------------------------------------------------------------
@app.get("/api/me", tags=["account"], summary="현재 사용자 · 권한 · 오늘 사용량")
def me():
    u = auth.user()
    uid = auth.uid()
    today = date.today().isoformat()
    return {"auth_enabled": settings.auth_enabled, "signed_in": bool(u) and settings.auth_enabled,
            "user": u if settings.auth_enabled else None, "uid": uid, "mode": mode(), "owner": auth.is_owner(),
            "toss_available": auth.is_owner() and (is_demo() or toss.configured()),
            "usage": {"today": (db.cache_get(f"usage:{uid}:{today}") or 0) if uid else 0,
                      "limit": settings.daily_analysis_limit}}


@app.delete("/api/me", tags=["account"], summary="내 데이터 삭제 (보유 종목·트랜스크립트·개인 분석 결과)")
def delete_me(uid: str = Depends(require_user)):
    db.delete_user(uid)
    if auth.mode() == "demo" and uid.startswith("anon-"):
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
        return demo.search(q) if is_demo() else edgar.search(q)
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
    if h is None and is_demo():
        h = demo.DEMO_PORTFOLIO
    return h or []


@app.get("/api/portfolio", tags=["portfolio"], summary="내 보유 종목 조회")
def get_portfolio():
    rows = _holdings()
    if not hide_money():
        return rows
    return [{k: v for k, v in r.items() if k not in MONEY} for r in rows]


def _check(rows: list[dict]) -> list[dict]:
    """Resolve each row against SEC (or demo data). Korean codes are kept but marked non-analyzable."""
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
    hold = _holdings()
    reports, missing = [], []
    for h in hold:
        if not h.get("analyzable", True):
            continue
        r = find_report(h["ticker"])[1]
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
            "broker": db.cache_get(f"broker:last:{mode()}:{auth.uid()}") if auth.uid() else None,
            "upcoming": sorted(upcoming, key=lambda x: x["next_release_est"])}


# ---------------------------------------------------------------------------------------
# broker: Toss Securities (read-only)
# ---------------------------------------------------------------------------------------
@app.get("/api/broker/status", tags=["broker"], summary="토스증권 연동 상태")
def broker_status():
    is_owner, uid = auth.is_owner(), auth.uid()
    base = {"provider": "toss", "mode": mode(), "configured": toss.configured(), "owner": is_owner,
            "owner_only": settings.auth_enabled, "owner_key_required": bool(settings.owner_key) and not settings.auth_enabled,
            "last_sync": db.cache_get(f"broker:last:{mode()}:{uid}") if uid else None}
    if settings.auth_enabled and not is_owner:
        return base | {"connected": None, "available": False,
                       "error": "토스증권 연동은 서비스 운영자 계정에서만 켜져 있습니다.",
                       "hint": "토스증권 Open API는 본인 계좌의 본인 이용만 허용합니다. 보유 종목은 직접 입력하거나 붙여넣어 주세요."}
    if is_demo():
        return base | {"connected": True, "demo": True,
                       "accounts": [{"accountSeq": 1, "accountNo": "123•••••901", "accountType": "BROKERAGE"}]}
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
        if is_demo():
            raw, fx, seq = toss.demo_holdings(), 1420.0, 1
        else:
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
                ok = "찾지 못했" not in str(e) and "데모 모드" not in str(e)  # keep if SEC merely unreachable
        rows.append(r | {"analyzable": ok, "source": "toss", "note": r["name"][:40]})
    db.cache_set(_hkey(uid), rows)
    last = {"at": time.strftime("%Y-%m-%d %H:%M"), "account_seq": seq, "n": len(rows),
            "n_analyzable": sum(r["analyzable"] for r in rows), "summary": norm["summary"], "usd_krw": fx}
    db.cache_set(f"broker:last:{mode()}:{uid}", last)
    return {"holdings": rows, **last}


# ---------------------------------------------------------------------------------------
# analysis
# ---------------------------------------------------------------------------------------
def _charge() -> str | None:
    """Live analyses hit SEC and the LLM; require sign-in and count them per user per day."""
    uid = auth.uid()
    if is_demo():
        return uid
    if settings.auth_enabled:
        if not uid:
            raise HTTPException(401, "실데이터 분석은 로그인 후 이용할 수 있습니다. 데모 모드는 로그인 없이 쓸 수 있습니다.")
        n = db.bump_usage(uid, date.today().isoformat())
        if n > settings.daily_analysis_limit and not auth.is_owner():
            raise HTTPException(429, f"오늘 실데이터 분석 한도({settings.daily_analysis_limit}회)를 모두 썼습니다. "
                                     "이미 분석된 종목은 계속 볼 수 있습니다.")
    return uid


@app.post("/api/analyze/{ticker}", tags=["analysis"], summary="종목 분석 실행 (가이던스 추출·정렬·이벤트스터디)")
def run_analysis(ticker: str, events: int = Query(8, ge=2, le=16), use_llm: bool = True,
                 refresh: bool = False, evidence: bool = True):
    key = report_key(ticker)
    if not refresh:
        cached = db.get_report(key)
        if cached and cached.get("n_events_requested") == events:
            return cached
    uid = _charge()
    try:
        rep = analyze(ticker, n_events=events, use_llm=use_llm, with_evidence=evidence, src=source(),
                      user_id=uid, store_key=key)
    except edgar.EdgarError as e:
        msg = str(e)
        _err(e, 404 if "찾지 못했" in msg or "데모 모드" in msg else 503)
    rep["n_events_requested"] = events
    db.save_report(key, rep)
    return rep


@app.get("/api/analyze/{ticker}/stream", tags=["analysis"],
         summary="분석 실행 + 단계별 진행 상황 스트리밍 (Server-Sent Events)")
def analyze_stream(ticker: str, events: int = Query(8, ge=2, le=16), use_llm: bool = True):
    q: queue.Queue = queue.Queue()
    key = report_key(ticker)
    src = source()
    uid = _charge()  # resolve before the worker thread: context vars do not cross threads

    def work():
        try:
            rep = analyze(ticker, n_events=events, use_llm=use_llm, src=src, progress=lambda e: q.put(("progress", e)),
                          user_id=uid, store_key=key)
            rep["n_events_requested"] = events
            db.save_report(key, rep)
            q.put(("done", {"ticker": rep["ticker"], "score": rep["score"], "n_guidance": len(rep["guidance"]),
                            "elapsed_sec": rep["elapsed_sec"], "warnings": rep["warnings"]}))
        except Exception as e:  # surface every failure to the client
            q.put(("error", {"message": str(e)}))

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
        if url.startswith("demo://"):
            return {"url": url, "text": demo.document(url)}
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
    tid = db.save_transcript(body.ticker, body.call_date.isoformat(), "upload", body.text, uid)
    items = guidance.extract(body.text, ticker=body.ticker, event_date=body.call_date.isoformat(),
                             source="어닝콜 트랜스크립트", use_llm=True)
    return {"id": tid, "n_guidance": len(items), "items": items,
            "hint": "재분석(refresh=true)하면 트랜스크립트 가이던스가 실적과 정렬됩니다. "
                    "올린 원문은 나에게만 보이며, 이 종목의 분석 결과도 내 전용으로 저장됩니다."}


@app.get("/api/transcripts/{ticker}", tags=["transcripts"], summary="트랜스크립트 목록 (공용 샘플 + 내가 올린 원문)")
def list_transcripts(ticker: str, include_text: bool = False):
    uid = auth.uid()
    rows = demo.DemoSource.transcripts(ticker, uid) if is_demo() else transcripts.all_transcripts(ticker, uid)
    return [{**{k: r[k] for k in ("id", "ticker", "call_date", "source")}, "chars": len(r["text"]),
             "preview": r["text"][:300]} | ({"text": r["text"]} if include_text else {}) for r in rows]


@app.delete("/api/transcripts/{tid}", tags=["transcripts"], summary="내가 올린 트랜스크립트 삭제")
def delete_transcript(tid: str, uid: str = Depends(require_user)):
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
# AI Q&A
# ---------------------------------------------------------------------------------------
@app.post("/api/qa", tags=["ai"], summary="종목 질의응답 (해당 종목 문서만 검색, 출처 표시)")
def qa(body: QAIn):
    t = body.ticker.upper()
    key, rep = find_report(t)
    corpus = db.cache_get(f"corpus:{key.lower()}") or []
    if not corpus:
        raise HTTPException(404, "먼저 이 종목을 분석해 주세요 (문서 색인이 없습니다).")
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

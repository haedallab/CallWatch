import { useEffect, useMemo, useRef, useState } from "react";
import { Link, Navigate, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ChevronRight, Download, FileText, Keyboard, Loader2, Play, RefreshCw, X } from "lucide-react";
import clsx from "clsx";
import { api, ApiError, type Guidance, type Report } from "../lib/api";
import { useApp } from "../lib/store";
import { useTickers } from "../lib/tickers";
import { basisKo, C, fmt, fmtRange, fmtSurprise, shortMetric, statusView, type Tone } from "../lib/format";
import { Empty, ErrorState, findQuote, Highlighted, Kpi, Legend, PageSkeleton, RangeBar, Seg, Skeleton, StatusPill, type Span } from "../components/ui";
import { CarBars, PriceChart, TrendChart } from "../components/Charts";
import SourceDrawer from "../components/SourceDrawer";
import { CallListen, CallsAdmin, useCalls } from "../components/CallLinks";

type Tab = "ledger" | "trend" | "price" | "align";
const TONES: { key: Tone; label: string }[] = [
  { key: "within", label: "부합" }, { key: "good", label: "유리한 이탈" }, { key: "bad", label: "불리한 이탈" },
  { key: "drift", label: "중립 이탈" }, { key: "pending", label: "결과 대기" }, { key: "na", label: "검증 불가" },
];

export default function Company() {
  const { ticker } = useParams();
  const tk = useTickers();
  if (!ticker) {
    const first = tk.list[0]?.ticker;
    if (tk.isLoading) return <PageSkeleton />;
    if (first) return <Navigate to={`/company/${first}`} replace />;
    return <Empty title="분석할 종목이 없습니다" body="포트폴리오에서 종목을 추가하거나, ⌘K를 눌러 티커를 입력하면 바로 이동합니다." />;
  }
  return <CompanyView key={ticker} ticker={ticker.toUpperCase()} />;
}

function CompanyView({ ticker }: { ticker: string }) {
  const app = useApp();
  const nav = useNavigate();
  const [sp, setSp] = useSearchParams();
  const tk = useTickers();
  const rep = useQuery({ queryKey: ["report", ticker], queryFn: () => api.report(ticker), retry: (n, e) => !(e instanceof ApiError && e.status === 404) && n < 1 });
  const tab = (sp.get("tab") as Tab) || "ledger";
  const setParam = (k: string, v: string | null) => { const n = new URLSearchParams(sp); v === null ? n.delete(k) : n.set(k, v); setSp(n, { replace: true }); };
  const job = app.jobs[ticker];
  const running = job && (job.state === "running" || job.state === "queued");
  const notFound = rep.error instanceof ApiError && rep.error.status === 404;

  const tabs: { key: Tab; label: string }[] = [
    { key: "ledger", label: "약속 장부" }, { key: "trend", label: "가이던스 vs 실적" },
    { key: "price", label: "주가 반응" }, { key: "align", label: "발표문 정렬" },
  ];
  const ctx = (
    <div className="ctxbar" role="navigation" aria-label="종목 탐색">
      <div className="crumb">
        <Link to={tk.mine.some((m) => m.ticker === ticker) ? "/portfolio" : "/"}>{tk.mine.some((m) => m.ticker === ticker) ? "내 포트폴리오" : "주요 종목"}</Link><ChevronRight size={14} />
        <select value={ticker} aria-label="종목 전환" onChange={(e) => nav(`/company/${e.target.value}?tab=${tab}`)}>
          {(["내 보유 종목", "주요 종목"] as const).map((g) => {
            const items = tk.list.filter((x) => x.group === g);
            return items.length ? <optgroup key={g} label={g}>{items.map((x) => <option key={x.ticker} value={x.ticker}>{x.ticker} · {x.name.slice(0, 16)}</option>)}</optgroup> : null;
          })}
          {!tk.list.some((x) => x.ticker === ticker) && <option value={ticker}>{ticker}</option>}
        </select>
      </div>
      {rep.data && (
        <div className="subtabs" role="tablist">
          {tabs.map((t) => <button key={t.key} role="tab" aria-selected={tab === t.key} onClick={() => setParam("tab", t.key)}>{t.label}{t.key === "ledger" && <span className="muted small"> {rep.data!.guidance.length}</span>}</button>)}
        </div>
      )}
      <div className="ctx-sum">
        {rep.data && <span>신뢰도 <b style={{ color: rep.data.score.score == null ? C.muted : rep.data.score.score >= 80 ? C.within : rep.data.score.score >= 60 ? C.drift : C.bad }}>{rep.data.score.score ?? "–"}</b> · {rep.data.score.style.split(" (")[0]}</span>}
        {rep.data?.mode === "demo" && <span className="tag">데모</span>}
        <button className="btn sm" disabled={running} onClick={() => app.analyze([ticker], { refresh: true })}>
          {running ? <Loader2 size={14} className="spin" /> : rep.data ? <RefreshCw size={14} /> : <Play size={14} />}{rep.data ? "다시 분석" : "분석하기"}
        </button>
      </div>
    </div>
  );

  if (rep.isLoading) return <>{ctx}<PageSkeleton /></>;
  if (rep.isError && !notFound) return <>{ctx}<ErrorState error={rep.error} retry={() => rep.refetch()} /></>;
  if (!rep.data) {
    return (
      <>
        {ctx}
        <div className="page-head"><div><h1>{ticker}</h1><p>아직 분석하지 않은 종목입니다.</p></div></div>
        {running || job ? <LiveProgress ticker={ticker} /> : (
          <Empty icon={<Play size={36} color={C.dark} />} title={`${ticker} 분석을 시작할까요?`}
            body="최근 실적발표 보도자료(8-K)에서 가이던스를 찾아 SEC XBRL 실적과 맞추고 주가 반응을 계산합니다. 단계별 진행 상황이 실시간으로 보입니다.">
            <button className="btn primary lg" onClick={() => app.analyze([ticker])}><Play size={18} />지금 분석하기</button>
          </Empty>
        )}
      </>
    );
  }
  const r = rep.data;
  const s = r.score;
  const mr = r.market_response;
  return (
    <>
      {ctx}
      <div className="page-head">
        <div>
          <h1>{r.name} <span className="muted" style={{ fontWeight: 600 }}>{r.ticker}</span></h1>
          <p className="small">CIK {r.cik} · {r.generated_at} 분석 · 실적발표 {r.events.length}회 · 추출 엔진 {r.llm} · {r.mode === "demo" ? "데모(가상) 데이터" : "SEC EDGAR 실데이터"}</p>
        </div>
      </div>
      {running && <LiveProgress ticker={ticker} compact />}
      {r.warnings.map((w) => <div key={w} className="banner warn"><AlertTriangle size={16} />{w}</div>)}
      <div className="grid-kpi">
        <Kpi accent label="경영진 가이던스 신뢰도" value={s.score ?? "–"} sub={s.grade} />
        <Kpi label="가이던스 성향" value={s.style.split(" (")[0]} sub={s.style.includes("(") ? s.style.split("(")[1].replace(")", "") : ""} />
        <Kpi label="약속 이행률" value={s.hit_rate !== null ? `${Math.round(s.hit_rate * 100)}%` : "–"} sub={`검증 ${s.n_verified} · 대기 ${s.n_pending} · 참고 ${s.n_reference_only}`} />
        <Kpi label="결과 공개일 초과수익 (이행 시)" value={mr.kept.avg_car_m1p1 !== null ? `${mr.kept.avg_car_m1p1 > 0 ? "+" : ""}${mr.kept.avg_car_m1p1.toFixed(1)}%` : "–"}
          sub={mr.missed.avg_car_m1p1 !== null ? `미이행 시 ${mr.missed.avg_car_m1p1 > 0 ? "+" : ""}${mr.missed.avg_car_m1p1.toFixed(1)}%` : "미이행 사례 없음"} />
      </div>
      <p className="small muted" style={{ margin: "-8px 0 0" }}>{s.explain}</p>
      {tab === "ledger" && <Ledger r={r} />}
      {tab === "trend" && <Trend r={r} />}
      {tab === "price" && <Price r={r} />}
      {tab === "align" && <Align r={r} />}
    </>
  );
}

function LiveProgress({ ticker, compact }: { ticker: string; compact?: boolean }) {
  const job = useApp().jobs[ticker];
  if (!job) return null;
  return (
    <section className="card" aria-live="polite" aria-label="분석 진행">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <b className="row" style={{ gap: 8 }}>{job.state === "error" ? <X size={16} color={C.bad} /> : <Loader2 size={16} className={clsx(job.state !== "done" && "spin")} />}
          {job.state === "error" ? "분석 실패" : job.state === "done" ? "분석 완료" : `${ticker} 분석 중`}</b>
        <span className="small muted">{Math.round(job.pct * 100)}%</span>
      </div>
      <div className={clsx("job", job.state)}><div className="bar" style={{ height: 8 }}><i style={{ width: `${Math.max(job.pct, 0.03) * 100}%` }} /></div></div>
      {job.state === "error" ? <ErrorState error={new ApiError(0, job.error || "실패")} /> : !compact && (
        <ol className="small muted" style={{ margin: "10px 0 0", paddingLeft: 18, lineHeight: 1.8 }}>
          {job.log.slice(-6).map((l, i) => <li key={i} style={{ color: i === Math.min(job.log.length, 6) - 1 ? C.ink : undefined }}>{l}</li>)}
        </ol>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------------------
function Ledger({ r }: { r: Report }) {
  const [sp, setSp] = useSearchParams();
  const [tones, setTones] = useState<Tone[]>([]);
  const [metric, setMetric] = useState("");
  const [source, setSource] = useState("");
  const [doc, setDoc] = useState<Guidance | null>(null);
  const period = sp.get("period");
  const listRef = useRef<HTMLDivElement>(null);
  const counts = useMemo(() => { const c: Record<string, number> = {}; r.guidance.forEach((g) => { const t = statusView(g).tone; c[t] = (c[t] || 0) + 1; }); return c; }, [r]);
  const rows = useMemo(() => r.guidance.filter((g) => (!tones.length || tones.includes(statusView(g).tone)) && (!metric || g.metric === metric)
    && (!source || g.source === source) && (!period || g.period?.label === period))
    .sort((a, b) => b.event_date.localeCompare(a.event_date) || a.metric.localeCompare(b.metric)), [r, tones, metric, source, period]);
  const selId = sp.get("g");
  const firstVerified = rows.find((g) => ["above", "within", "below"].includes(g.status)) || rows[0];
  const sel = rows.find((g) => g.id === selId) || firstVerified;
  const select = (id: string) => { const n = new URLSearchParams(sp); n.set("g", id); setSp(n, { replace: true }); };

  useEffect(() => {  // keyboard: j/k or arrows move through the ledger
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).closest("input, textarea, select") || !sel) return;
      const i = rows.findIndex((g) => g.id === sel.id);
      if ((e.key === "j" || e.key === "ArrowDown") && i < rows.length - 1) { e.preventDefault(); select(rows[i + 1].id); }
      if ((e.key === "k" || e.key === "ArrowUp") && i > 0) { e.preventDefault(); select(rows[i - 1].id); }
      if (e.key === "o" && sel.source_url) setDoc(sel);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });
  useEffect(() => {  // keep the selected row visible inside the list without scrolling the page
    const box = listRef.current, el = box?.querySelector<HTMLElement>('[aria-selected="true"]');
    if (!box || !el) return;
    const top = el.offsetTop;  // .glist is the offsetParent (position: relative)
    if (top < box.scrollTop || top + el.offsetHeight > box.scrollTop + box.clientHeight) box.scrollTop = top - 8;
  }, [sel?.id]);

  if (!r.guidance.length) return <Empty title="추출된 가이던스가 없습니다" body="이 회사는 보도자료에 수치 전망을 싣지 않을 수 있습니다. ‘어닝콜 원문 넣기’에서 콜 트랜스크립트를 추가해 보세요." />;
  const metrics = [...new Map(r.guidance.map((g) => [g.metric, g.metric_label])).entries()];
  const sources = [...new Set(r.guidance.map((g) => g.source))];
  const csv = () => {
    const head = ["발표일", "대상기간", "지표", "기준", "하단", "상단", "실제", "차이", "판정", "출처", "원문"];
    const lines = rows.map((g) => [g.event_date, g.period?.label || "", g.metric_label, g.basis, g.low, g.high, g.actual ?? "", fmtSurprise(g), statusView(g).label, g.source, g.quote]
      .map((v) => `"${String(v).replace(/"/g, '""')}"`).join(","));
    const url = URL.createObjectURL(new Blob(["﻿" + [head.join(","), ...lines].join("\n")], { type: "text/csv" }));
    Object.assign(document.createElement("a"), { href: url, download: `${r.ticker}_guidance.csv` }).click();
    URL.revokeObjectURL(url);
  };

  return (
    <>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <div className="row" role="group" aria-label="판정 필터" style={{ gap: 6 }}>
          {TONES.filter((t) => counts[t.key]).map((t) => (
            <button key={t.key} className="chip" aria-pressed={tones.includes(t.key)}
              onClick={() => setTones(tones.includes(t.key) ? tones.filter((x) => x !== t.key) : [...tones, t.key])}>
              <i className="dot" style={{ background: (C as Record<string, string>)[t.key], marginRight: 0 }} />{t.label}<span className="n">{counts[t.key]}</span>
            </button>
          ))}
          {period && <button className="chip" aria-pressed onClick={() => { const n = new URLSearchParams(sp); n.delete("period"); setSp(n); }}>{period}<X size={13} /></button>}
        </div>
        <div className="row">
          <select className="select" style={{ width: 190 }} value={metric} onChange={(e) => setMetric(e.target.value)} aria-label="지표 필터">
            <option value="">전체 지표</option>{metrics.map(([k, l]) => <option key={k} value={k}>{shortMetric(l)}</option>)}
          </select>
          {sources.length > 1 && <select className="select" style={{ width: 170 }} value={source} onChange={(e) => setSource(e.target.value)} aria-label="출처 필터">
            <option value="">전체 출처</option>{sources.map((s) => <option key={s} value={s}>{s.split(" (")[0]}</option>)}</select>}
          <button className="btn sm" onClick={csv}><Download size={14} />CSV</button>
        </div>
      </div>
      <div className="xs muted row" style={{ gap: 6 }}><Keyboard size={13} />{rows.length}건 · <kbd>J</kbd>/<kbd>K</kbd> 또는 방향키로 이동, <kbd>O</kbd> 원문 열기</div>
      {!rows.length ? <Empty title="조건에 맞는 가이던스가 없습니다" body="필터를 하나씩 풀어 보세요." /> : (
        <div className="ledger">
          <div className="glist" ref={listRef} role="listbox" aria-label="가이던스 목록">
            {rows.map((g) => {
              const sv = statusView(g);
              return (
                <button key={g.id} role="option" aria-selected={sel?.id === g.id} className="gitem" style={{ borderLeftColor: sv.color }} onClick={() => select(g.id)}>
                  <span className="t">{shortMetric(g.metric_label)} · {g.period?.label || "기간 불명"}{g.basis !== "unspecified" && <span className="muted small"> · {basisKo(g.basis)}</span>}</span>
                  <span className="pill" style={{ background: sv.color }}>{sv.label}</span>
                  <span className="m"><span>{g.event_date} 발표</span><span>{fmtRange(g.low, g.high, g.unit)}</span>{g.actual !== undefined && <span>실제 {fmt(g.actual, g.unit)} ({fmtSurprise(g)})</span>}</span>
                </button>
              );
            })}
          </div>
          {sel && <Detail g={sel} r={r} onDoc={() => setDoc(sel)} onSelect={select} />}
        </div>
      )}
      {doc && <SourceDrawer url={doc.source_url} quote={doc.quote} title={`${doc.source} · ${doc.event_date}`} onClose={() => setDoc(null)} />}
    </>
  );
}

function Detail({ g, r, onDoc, onSelect }: { g: Guidance; r: Report; onDoc: () => void; onSelect: (id: string) => void }) {
  const sv = statusView(g);
  const calls = useCalls(r.ticker);
  const pt = g.period?.type || "Q";
  return (
    <aside className="detail card" aria-live="polite" aria-label="선택한 가이던스 근거">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h3 style={{ fontSize: 19 }}>{shortMetric(g.metric_label)} · {g.period?.label || "기간 불명"}</h3><StatusPill g={g} />
      </div>
      <RangeBar g={g} />
      <div className="metric-row">
        <div><span>가이던스 중간값</span><b>{fmt(g.mid, g.unit)}</b></div>
        <div><span>실제 (SEC)</span><b style={{ color: g.actual !== undefined ? sv.color : C.muted }}>{g.actual !== undefined ? fmt(g.actual, g.unit) : "대기"}</b></div>
        <div><span>차이</span><b>{fmtSurprise(g)}</b></div>
      </div>
      <div>
        <div className="quote">“{g.quote}”</div>
        <div className="src" style={{ marginTop: 6 }}>{g.source} · {g.event_date} 발표 · {basisKo(g.basis)} · 추출 {g.extractor}{g.timeframe_text && ` · 기간 표현 “${g.timeframe_text}”`}</div>
      </div>
      {(g.source_url || g.transcript_id) && <button className="btn sm" style={{ alignSelf: "flex-start" }} onClick={onDoc} disabled={!g.source_url}><FileText size={14} />발표문에서 이 문장 보기</button>}
      <CallListen calls={calls.data} date={g.event_date} />
      {g.notes.map((n) => <div key={n} className="note"><AlertTriangle size={14} style={{ flex: "none", marginTop: 2 }} />{n}</div>)}
      {g.progress && (
        <div>
          <div className="small"><b>연간 목표 진행</b> · {g.progress.through}까지 누적 {fmt(g.progress.ytd, g.unit)}</div>
          <div className="job"><div className="bar" style={{ height: 8 }}><i style={{ width: `${Math.min(g.progress.progress_pct, 100)}%`, background: g.progress.on_track ? C.within : C.drift }} /></div></div>
          <div className="xs muted">목표 대비 {g.progress.progress_pct}% · 기간 경과 {g.progress.elapsed_pct}% · {g.progress.on_track ? "순항" : "뒤처짐"}</div>
        </div>
      )}
      <div>
        <div className="small" style={{ fontWeight: 650, marginBottom: 2 }}>같은 지표의 흐름 <span className="muted xs">· 점을 누르면 그 가이던스로 이동</span></div>
        <TrendChart rep={r} metric={g.metric} ptype={pt} selectedId={g.id} onSelect={onSelect} height={210} />
      </div>
      {g.actual_source && <div className="small"><b>실적 출처</b> · XBRL <code>{g.actual_source.concept}</code> · {g.actual_source.form} ({g.actual_source.filed} 제출){g.actual_source.derived && " · 누적값 차감"}</div>}
      {g.evidence?.length ? (
        <div className="col" style={{ gap: 8 }}>
          <b className="small">공시 근거 문단 · {g.filing?.form} MD&A</b>
          {g.evidence.map((e, i) => <div key={i}><div className="quote ev small">{e.text.slice(0, 520)}{e.text.length > 520 && "…"}</div><div className="src">관련도 {e.score.toFixed(2)} · {e.form} {e.filing_date}{e.url.startsWith("http") && <> · <a href={e.url} target="_blank" rel="noreferrer">SEC 원문</a></>}</div></div>)}
        </div>
      ) : null}
      {(g.announcement?.car_m1p1 != null || g.realization?.car_m1p1 != null) && (
        <div className="metric-row" style={{ gridTemplateColumns: "1fr 1fr" }}>
          <div><span>가이던스 발표 때 CAR[-1,+1]</span><b>{g.announcement?.car_m1p1 != null ? `${g.announcement.car_m1p1 > 0 ? "+" : ""}${g.announcement.car_m1p1.toFixed(2)}%` : "–"}</b></div>
          <div><span>결과 공개 때 ({g.realization_event || "–"})</span><b>{g.realization?.car_m1p1 != null ? `${g.realization.car_m1p1 > 0 ? "+" : ""}${g.realization.car_m1p1.toFixed(2)}%` : "–"}</b></div>
        </div>
      )}
    </aside>
  );
}

// ---------------------------------------------------------------------------------------
function Trend({ r }: { r: Report }) {
  const [sp, setSp] = useSearchParams();
  const present = Object.keys(r.actuals).filter((m) => r.actuals[m].Q.length || r.actuals[m].FY.length);
  const guided = present.filter((m) => r.guidance.some((g) => g.metric === m));
  const order = [...guided, ...present.filter((m) => !guided.includes(m))];
  const [m, setM] = useState(order[0]);
  const [pt, setPt] = useState<"Q" | "FY">("Q");
  const sel = r.guidance.find((g) => g.id === sp.get("g"));
  if (!order.length) return <Empty title="차트로 그릴 실적이 없습니다" body="XBRL 실적이 아직 없거나 태그가 다를 수 있습니다." />;
  return (
    <section className="card col">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <Seg label="지표" value={m} onChange={setM} items={order.map((k) => ({ key: k, label: shortMetric(r.actuals[k].label) }))} />
        <Seg label="주기" value={pt} onChange={setPt} items={[{ key: "Q", label: "분기" }, { key: "FY", label: "연간" }]} />
      </div>
      <TrendChart rep={r} metric={m} ptype={pt} selectedId={sel?.id} onSelect={(id) => { const n = new URLSearchParams(sp); n.set("g", id); setSp(n, { replace: true }); }} />
      <Legend />
      <span className="xs muted">선 = SEC에 보고된 실제 값, 세로 막대 = 가이던스 범위, 다이아몬드 = 중간값. Q4 값은 연간(10-K)에서 1~3분기를 뺀 값입니다.</span>
      {sel && sel.metric === m && (
        <div className="card row" style={{ background: "#F8FAFD", justifyContent: "space-between" }}>
          <div style={{ flex: 1, minWidth: 260 }}><b>{sel.period?.label} · {basisKo(sel.basis)}</b> <StatusPill g={sel} /><div className="small muted" style={{ marginTop: 4 }}>“{sel.quote}”</div></div>
          <div style={{ width: 280 }}><RangeBar g={sel} compact /></div>
          <button className="btn sm" onClick={() => { const n = new URLSearchParams(sp); n.set("tab", "ledger"); setSp(n); }}>약속 장부에서 근거 보기</button>
        </div>
      )}
    </section>
  );
}

function Price({ r }: { r: Report }) {
  const calls = useCalls(r.ticker);
  if (!r.prices.length) return <Empty title="주가 데이터가 없습니다" body="가격 소스(yfinance/Stooq)에 연결하지 못했습니다. 잠시 뒤 다시 분석해 보세요." />;
  const model = r.events.find((e) => e.reaction?.model)?.reaction?.model || "–";
  const f = (v?: number | null) => (v === undefined || v === null ? "–" : `${v > 0 ? "+" : ""}${v.toFixed(2)}%`);
  return (
    <>
      <section className="card">
        <div className="card-h"><h2>주가와 실적발표</h2><span className="sub">점 색 = 그 발표에서 공개된 직전 가이던스 이행 비율</span></div>
        <PriceChart rep={r} />
      </section>
      <div className="grid-2">
        <section className="card"><div className="card-h"><h2>발표별 초과수익률</h2><span className="sub">CAR[-1,+1], SPY 대비</span></div><CarBars rep={r} /></section>
        <section className="card">
          <div className="card-h"><h2>이벤트 스터디</h2><span className="sub">{model}</span></div>
          <div className="tbl-wrap" style={{ border: 0 }}>
            <table className="tbl"><thead><tr><th>발표일</th><th>반응일</th><th className="num">당일</th><th className="num">[-1,+1]</th><th className="num">[0,+5]</th><th className="num">[0,+20]</th><th>콜</th></tr></thead>
              <tbody>{[...r.events].reverse().map((e) => (
                <tr key={e.date}><td>{e.date}</td><td className="muted">{e.reaction?.reaction_date || "–"}</td>
                  {[e.reaction?.car_0, e.reaction?.car_m1p1, e.reaction?.car_0p5, e.reaction?.car_0p20].map((v, i) => <td key={i} className="num" style={{ color: v == null ? undefined : v >= 0 ? C.good : C.bad }}>{f(v)}</td>)}
                  <td><CallListen calls={calls.data} date={e.date} compact /></td></tr>
              ))}</tbody></table>
          </div>
          {calls.data && <p className="xs muted">콜 = 보도자료에 적힌 웹캐스트, IR = 회사 IR 페이지. {calls.data.note}</p>}
          <p className="xs muted">추정창 [-130,-11] 거래일 시장모형, 장 마감 후 발표는 다음 거래일을 반응일로 봅니다. 같은 날 다른 뉴스의 영향도 함께 담겨 있어 인과로 해석하지 않습니다.</p>
        </section>
      </div>
      <CallsAdmin key={calls.dataUpdatedAt} ticker={r.ticker} calls={calls.data} />
    </>
  );
}

function Align({ r }: { r: Report }) {
  const groups = useMemo(() => {
    const m = new Map<string, Guidance[]>();
    r.guidance.forEach((g) => { const k = `${g.event_date}|${g.source}|${g.source_url || g.transcript_id || ""}`; m.set(k, [...(m.get(k) || []), g]); });
    return [...m.entries()].sort((a, b) => b[0].localeCompare(a[0]));
  }, [r]);
  const [key, setKey] = useState(groups[0]?.[0]);
  const [active, setActive] = useState<string | null>(null);
  const items = groups.find(([k]) => k === key)?.[1] || [];
  const first = items[0];
  const docQ = useQuery({ queryKey: ["doc", first?.source_url], queryFn: () => api.document(first!.source_url), enabled: !!first?.source_url, staleTime: Infinity });
  const trQ = useQuery({ queryKey: ["tr", r.ticker], queryFn: () => api.transcripts(r.ticker, true), enabled: !!first?.transcript_id && !first?.source_url });
  const text = docQ.data?.text || trQ.data?.find((t) => t.id === first?.transcript_id)?.text || "";
  const docRef = useRef<HTMLDivElement>(null);
  const spans: Span[] = items.flatMap((g) => { const s = findQuote(text, g.quote); return s ? [{ start: s[0], end: s[1], tag: shortMetric(g.metric_label), id: g.id }] : []; });
  const win = spans.length ? Math.max(0, Math.min(...spans.map((s) => s.start)) - 800) : 0;
  const shown = text.slice(win, win + 12000);
  const pick = (id: string) => {
    setActive(id);
    docRef.current?.querySelector(`mark[data-id="${id}"]`)?.scrollIntoView({ block: "center", behavior: "smooth" });
    document.getElementById(`card-${id}`)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  };
  if (!groups.length) return <Empty title="정렬할 발표문이 없습니다" body="가이던스가 추출된 발표문이 있어야 합니다." />;
  return (
    <>
      <div className="row" style={{ gap: 6 }} role="group" aria-label="발표문 선택">
        {groups.slice(0, 10).map(([k, gs]) => (
          <button key={k} className="chip" aria-pressed={k === key} onClick={() => { setKey(k); setActive(null); }}>
            {k.split("|")[0]}<span className="n">{gs[0].source.startsWith("어닝콜") ? "콜" : "8-K"} · {gs.length}건</span>
          </button>
        ))}
      </div>
      <div className="grid-2" style={{ gridTemplateColumns: "minmax(0,1.15fr) minmax(0,1fr)" }}>
        <section className="card col">
          <div className="card-h" style={{ margin: 0 }}><h2>발표 원문</h2><span className="sub">강조 문장을 누르면 오른쪽 판정으로 이동</span></div>
          {(docQ.isLoading || trQ.isLoading) && <div className="col">{[0, 1, 2, 3].map((i) => <Skeleton key={i} h={18} />)}</div>}
          {docQ.isError && <ErrorState error={docQ.error} retry={() => docQ.refetch()} />}
          {!text && !docQ.isLoading && !trQ.isLoading && first?.transcript_id && (
            <div className="col" style={{ gap: 10 }}>
              <p className="small muted" style={{ margin: 0 }}>회사가 공개한 어닝콜 원문에서 찾은 문장입니다. 전문은 출처에서 확인하세요.</p>
              {items.map((g) => <blockquote key={g.id} className="quote">“{g.quote}”</blockquote>)}
              {first.transcript_url && <a className="small" href={first.transcript_url} target="_blank" rel="noreferrer">어닝콜 원문 출처 열기</a>}
            </div>
          )}
          {text && <div className="doc" ref={docRef}><Highlighted text={shown} spans={spans.filter((s) => s.start >= win).map((s) => ({ ...s, start: s.start - win, end: s.end - win }))} active={active} onPick={pick} /></div>}
        </section>
        <section className="col">
          {items.sort((a, b) => a.metric.localeCompare(b.metric)).map((g) => {
            const sv = statusView(g);
            return (
              <button key={g.id} id={`card-${g.id}`} className={clsx("card", active === g.id && "flash")} onClick={() => pick(g.id)}
                style={{ textAlign: "left", borderLeft: `4px solid ${sv.color}`, cursor: "pointer", boxShadow: active === g.id ? `0 0 0 2px ${C.blue}` : undefined }}>
                <div className="row" style={{ justifyContent: "space-between" }}><b>{shortMetric(g.metric_label)} · {g.period?.label || "–"} <span className="muted small">{basisKo(g.basis)}</span></b><StatusPill g={g} /></div>
                <RangeBar g={g} />
              </button>
            );
          })}
        </section>
      </div>
    </>
  );
}

import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { useQueries, useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, LayoutList, Printer, X } from "lucide-react";
import clsx from "clsx";
import { api, type Report } from "../lib/api";
import { useApp } from "../lib/store";
import { C, basisKo, fmt, fmtSurprise, krw, pct, shortMetric, statusView } from "../lib/format";
import { Empty, Kpi, Legend, PageSkeleton, RangeBar, StatusPill } from "../components/ui";
import { TrendChart } from "../components/Charts";
import { Alerts, Heatmap } from "./Portfolio";

interface Slide { key: string; label: string; body: ReactNode }

/** Presentation mode: slides assembled from the same components as the app, so they never drift apart. */
export default function Present() {
  const nav = useNavigate();
  const app = useApp();
  const mine = useQuery({ queryKey: ["summary"], queryFn: api.summary });
  const feat = useQuery({ queryKey: ["featured"], queryFn: api.featured });
  // present my portfolio when it has results, otherwise the public featured stocks
  const useMine = !!mine.data?.companies.length;
  const sum = useMine ? mine : feat;
  const scope = useMine ? "내 포트폴리오" : "주요 종목";
  const health = useQuery({ queryKey: ["health"], queryFn: api.health });
  const scored = (sum.data?.companies || []).filter((c) => c.score !== null).sort((a, b) => b.weight - a.weight).slice(0, 5);
  const reps = useQueries({ queries: scored.map((c) => ({ queryKey: ["report", c.ticker], queryFn: () => api.report(c.ticker) })) });
  const [cur, setCur] = useState(0);
  const [all, setAll] = useState(false);

  const slides: Slide[] = useMemo(() => {
    const s = sum.data;
    if (!s || !s.companies.length) return [];
    const feed = s.guidance_feed;
    const ver = feed.filter((f) => ["above", "within", "below"].includes(f.status) && !f.basis_mismatch);
    const kept = ver.filter((f) => f.kept).length;
    const pend = feed.filter((f) => f.status === "pending");
    const off = pend.filter((f) => f.progress && !f.progress.on_track);
    const today = new Date().toISOString().slice(0, 10);
    const out: Slide[] = [
      { key: "cover", label: "표지", body: (
        <div className="pcover">
          <div className="pcover-eye">CallWatch · 금융빅데이터분석실습 팀 프로젝트</div>
          <h1>{scope}의 가이던스,<br />지켜지고 있나요?</h1>
          <p>어닝콜·실적발표 가이던스 × SEC 10-Q/10-K 실적 × 주가 반응</p>
          <div className="pcover-grid">
            <div><span>기준일</span><b>{today}</b></div>
            <div><span>분석 종목</span><b>{s.n_scored}개 · 가이던스 {feed.length}건</b></div>
            <div><span>{useMine ? "비중 가중 신뢰도" : "평균 신뢰도"}</span><b>{s.weighted_score?.toFixed(0) ?? "–"}점</b></div>
            <div><span>데이터</span><b>{health.data?.mode === "demo" ? "데모 (가상 기업)" : "SEC EDGAR 공시 · 주가"}</b></div>
          </div>
        </div>) },
      { key: "overview", label: "한눈에 보기", body: (
        <>
          <h2 className="ptitle">한눈에 보기</h2>
          <div className="grid-kpi">
            <Kpi accent label={useMine ? "비중 가중 경영진 신뢰도" : "평균 경영진 신뢰도"} value={s.weighted_score?.toFixed(0) ?? "–"} sub="100점 만점 · 80 이상 높음" />
            <Kpi label="약속 이행률" value={ver.length ? `${Math.round((kept / ver.length) * 100)}%` : "–"} sub={`검증된 ${ver.length}건 중 ${kept}건`} />
            <Kpi label="불리한 방향 이탈" value={`${ver.length - kept}건`} sub="가이던스를 나쁜 쪽으로 벗어남" />
            <Kpi label="결과 대기" value={`${pend.length}건`} sub={off.length ? `연간 진행률 부진 ${off.length}건` : "아직 실적 미발표"} />
          </div>
          <div className="card">
            <div className="card-h"><h2>종목별 경영진 신뢰도</h2><span className="sub">막대 길이 = 점수{useMine ? ", 오른쪽 = 비중" : ""}</span></div>
            <div className="col" style={{ gap: 10 }}>
              {[...s.companies].sort((a, b) => (b.score ?? -1) - (a.score ?? -1)).map((c) => {
                const color = c.score == null ? C.na : c.score >= 80 ? C.within : c.score >= 60 ? C.drift : C.bad;
                return (
                  <div key={c.ticker} className="row" style={{ flexWrap: "nowrap", gap: 14 }}>
                    <b style={{ width: 64 }}>{c.ticker}</b>
                    <div className="scorebar" style={{ flex: 1 }}><div className="t" style={{ height: 14 }}><i style={{ width: `${c.score ?? 0}%`, background: color }} /></div><b style={{ color, width: 34, textAlign: "right" }}>{c.score ?? "–"}</b></div>
                    <span className="small muted" style={{ width: 150 }}>{c.style.split(" (")[0]}{useMine ? ` · 비중 ${pct(c.weight, 0)}` : ""}</span>
                  </div>
                );
              })}
            </div>
          </div>
          {s.broker && <p className="small muted" style={{ margin: 0 }}>토스증권 {s.broker.at} 동기화 · 평가금액 <span className={clsx(app.masked && "mask")}>{krw(s.broker.summary.market_value_krw)}</span> · 총 손익률 {pct(s.broker.summary.pl_rate, 2, true)}</p>}
        </>) },
      { key: "alerts", label: "지금 확인할 것", body: (
        <>
          <h2 className="ptitle">지금 확인할 것</h2>
          <Alerts items={[...ver.filter((f) => !f.kept).sort((a, b) => b.event_date.localeCompare(a.event_date)), ...off]} />
        </>) },
      { key: "heat", label: "분기별 이행 지도", body: (<><h2 className="ptitle">분기별 가이던스 이행 지도</h2><Heatmap feed={feed} /></>) },
    ];
    reps.forEach((q, i) => {
      const r = q.data;
      if (!r) return;
      out.push({ key: `co-${r.ticker}`, label: r.ticker, body: <CompanySlide r={r} weight={scored[i]?.weight} /> });
    });
    out.push({ key: "method", label: "판정 방법·출처", body: <MethodSlide /> });
    return out;
  }, [sum.data, reps.map((q) => q.dataUpdatedAt).join(), health.data, app.masked]); // eslint-disable-line react-hooks/exhaustive-deps

  const go = useCallback((i: number) => { setCur(Math.max(0, Math.min(slides.length - 1, i))); window.scrollTo({ top: 0 }); }, [slides.length]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (/INPUT|TEXTAREA|SELECT/.test((document.activeElement as HTMLElement)?.tagName)) return;
      if (e.key === "Escape") nav(-1);
      if (all) return;
      if (e.key === "ArrowRight" || e.key === "PageDown" || e.key === " ") { e.preventDefault(); go(cur + 1); }
      if (e.key === "ArrowLeft" || e.key === "PageUp") { e.preventDefault(); go(cur - 1); }
      if (e.key === "Home") go(0);
      if (e.key === "End") go(slides.length - 1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [cur, all, go, nav, slides.length]);

  if (sum.isLoading) return <div className="present"><div className="deck"><PageSkeleton /></div></div>;
  if (!slides.length) {
    return (
      <div className="present"><div className="deck">
        <Empty title="발표할 분석 결과가 없습니다" body="주요 종목 분석이 끝나거나 내 종목을 분석하면 그 결과로 발표 슬라이드가 자동으로 만들어집니다.">
          <button className="btn primary" onClick={() => nav("/")}>주요 종목으로 가기</button>
        </Empty>
      </div></div>
    );
  }
  const n = slides.length;
  return (
    <div className={clsx("present", all && "allmode")}>
      <header className="pbar">
        <b>CallWatch · 발표 모드</b>
        <span className="small" style={{ opacity: .8 }}>{slides[cur]?.label}</span>
        <div style={{ marginLeft: "auto" }} className="row">
          <button className="tb-icon" aria-pressed={all} onClick={() => setAll(!all)} title={all ? "슬라이드로 보기" : "전체 보기"} aria-label="전체 보기"><LayoutList size={17} /></button>
          <button className="tb-icon" onClick={() => window.print()} title="인쇄 / PDF" aria-label="인쇄 또는 PDF 저장"><Printer size={17} /></button>
          <button className="tb-icon" onClick={() => nav(-1)} title="발표 모드 나가기 (Esc)" aria-label="발표 모드 나가기"><X size={18} /></button>
        </div>
      </header>
      <div className="deck">
        {slides.map((s, i) => (
          <section key={s.key} className={clsx("pslide", (all || i === cur) && "on")} aria-hidden={!all && i !== cur} aria-label={`${i + 1}번 슬라이드 ${s.label}`}>
            <div className="plabel"><span>{i + 1} / {n}</span><em>{s.label}</em></div>
            {s.body}
          </section>
        ))}
      </div>
      {!all && (
        <nav className="pnav" aria-label="슬라이드 이동">
          <div className="pnav-prog"><i style={{ width: `${((cur + 1) / n) * 100}%` }} /></div>
          <div className="pnav-in">
            <button className="btn sm" onClick={() => go(cur - 1)} disabled={cur === 0}><ChevronLeft size={15} />이전</button>
            <div className="pdots">{slides.map((s, i) => <button key={s.key} className={clsx("pdot", i === cur && "on")} onClick={() => go(i)} aria-label={`${i + 1}. ${s.label}`} aria-current={i === cur} />)}</div>
            <button className="btn sm primary" onClick={() => go(cur + 1)} disabled={cur === n - 1}>다음<ChevronRight size={15} /></button>
            <span className="small muted" style={{ minWidth: 58, textAlign: "right" }}><b style={{ color: C.ink }}>{cur + 1}</b> / {n}</span>
          </div>
        </nav>
      )}
    </div>
  );
}

function CompanySlide({ r, weight }: { r: Report; weight?: number }) {
  const s = r.score;
  const guided = Object.keys(r.actuals).find((m) => r.guidance.some((g) => g.metric === m && g.period?.type === "Q")) || "revenue";
  const recent = r.guidance.filter((g) => ["above", "within", "below"].includes(g.status) && !g.basis_mismatch)
    .sort((a, b) => b.event_date.localeCompare(a.event_date)).slice(0, 3);
  const pending = r.guidance.find((g) => g.status === "pending" && g.metric === "revenue");
  const mr = r.market_response;
  return (
    <>
      <h2 className="ptitle">{r.name} <span className="muted" style={{ fontWeight: 600 }}>{r.ticker}</span></h2>
      <div className="grid-kpi">
        <Kpi accent label="경영진 신뢰도" value={s.score ?? "–"} sub={`${s.grade} · 비중 ${pct(weight, 0)}`} />
        <Kpi label="가이던스 성향" value={s.style.split(" (")[0]} sub={s.explain.split(",")[0]} />
        <Kpi label="약속 이행률" value={s.hit_rate !== null ? `${Math.round(s.hit_rate * 100)}%` : "–"} sub={`검증 ${s.n_verified} · 대기 ${s.n_pending}`} />
        <Kpi label="결과 공개일 초과수익" value={mr.kept.avg_car_m1p1 !== null ? `${mr.kept.avg_car_m1p1 > 0 ? "+" : ""}${mr.kept.avg_car_m1p1.toFixed(1)}%` : "–"}
          sub={mr.missed.avg_car_m1p1 !== null ? `이행 시 · 미이행 시 ${mr.missed.avg_car_m1p1 > 0 ? "+" : ""}${mr.missed.avg_car_m1p1.toFixed(1)}%` : "이행 시"} />
      </div>
      <div className="grid-2">
        <div className="card">
          <div className="card-h"><h2>{shortMetric(r.actuals[guided]?.label || "")} · 가이던스 vs 실적</h2></div>
          <TrendChart rep={r} metric={guided} ptype="Q" height={260} />
          <Legend />
        </div>
        <div className="card col">
          <div className="card-h" style={{ margin: 0 }}><h2>최근 판정</h2></div>
          {recent.map((g) => (
            <div key={g.id} style={{ borderLeft: `4px solid ${statusView(g).color}`, paddingLeft: 12 }}>
              <div className="row" style={{ justifyContent: "space-between" }}><b>{shortMetric(g.metric_label)} · {g.period?.label} <span className="muted small">{basisKo(g.basis)}</span></b><StatusPill g={g} /></div>
              <RangeBar g={g} compact />
              <div className="xs muted">실제 {fmt(g.actual, g.unit)} · 차이 {fmtSurprise(g)} · “{g.quote.slice(0, 90)}{g.quote.length > 90 ? "…" : ""}”</div>
            </div>
          ))}
          {pending && <div className="small muted">다음 확인: {pending.period?.label} 매출 가이던스 {fmt(pending.low, pending.unit)} – {fmt(pending.high, pending.unit)} (결과 대기)</div>}
        </div>
      </div>
    </>
  );
}

function MethodSlide() {
  const steps = [
    ["종목", "주요 종목은 서버가 매일 분석 · 내 종목은 가입 없이 붙여넣기 (운영자는 토스증권 오픈API)"],
    ["발표 찾기", "SEC 8-K Item 2.02 = 실적발표일"],
    ["가이던스 추출", "보도자료 Outlook + 콜 원문, 규칙+AI 교차검증"],
    ["기간 정렬", "회사별 회계 달력으로 대상 분기·연도 확정"],
    ["실적 대조", "XBRL 최초 보고값, Q4·현금흐름은 차감 계산"],
    ["시장 반응", "발표일·결과 공개일 CAR (시장모형, SPY)"],
  ];
  return (
    <>
      <h2 className="ptitle">판정 방법과 출처</h2>
      <div className="psteps">{steps.map(([t, d], i) => <div key={t} className="card"><span className="tag">{i + 1}</span><b style={{ display: "block", margin: "8px 0 4px" }}>{t}</b><span className="small muted">{d}</span></div>)}</div>
      <div className="grid-2">
        <div className="card col"><b>경영진 신뢰도 점수</b><div className="quote" style={{ fontWeight: 650 }}>100 × (0.7 × 이행률 + 0.3 × (1 − 이탈 심도))</div>
          <span className="small muted">이행 = 범위 부합 또는 유리한 방향 이탈. Non-GAAP 가이던스는 GAAP 실적과 1:1 비교가 안 되어 점수에서 제외.</span><Legend /></div>
        <div className="card col"><b>데이터 출처</b>
          <ul className="small" style={{ margin: 0, paddingLeft: 18, lineHeight: 1.9 }}>
            <li>보유 종목 — 사용자 입력(붙여넣기·CSV, 브라우저별 저장) · 운영자는 토스증권 Open API</li><li>SEC EDGAR — Submissions, XBRL companyfacts, 8-K Ex-99.1, 10-Q/10-K</li>
            <li>Yahoo Finance / Stooq — 일별 종가, SPY</li><li>어닝콜 트랜스크립트 — 사용자 업로드</li><li>Gemini — 가이던스 추출 보조, 출처 기반 질의응답</li>
          </ul>
          <span className="xs muted">투자 권유가 아니며, 판단 전 공시 원문을 확인해야 합니다.</span></div>
      </div>
    </>
  );
}


import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ChevronRight, Link2, Play, Plus, RefreshCw, Trash2, Wallet } from "lucide-react";
import clsx from "clsx";
import { toast } from "sonner";
import { api, ApiError, type FeedItem, type Holding } from "../lib/api";
import { useApp } from "../lib/store";
import { C, fmtRange, fmtSurprise, krw, pct, shortMetric, statusView } from "../lib/format";
import { Empty, ErrorState, Kpi, Modal, PageSkeleton } from "../components/ui";

export default function Portfolio() {
  const app = useApp();
  const nav = useNavigate();
  const port = useQuery({ queryKey: ["portfolio"], queryFn: api.portfolio });
  const sum = useQuery({ queryKey: ["summary"], queryFn: api.summary });
  const [addOpen, setAddOpen] = useState(false);

  if (port.isLoading || sum.isLoading) return <PageSkeleton />;
  if (port.isError) return <ErrorState error={port.error} retry={() => port.refetch()} />;
  const hold = port.data || [];
  const s = sum.data;
  const analyzable = hold.filter((h) => h.analyzable !== false).map((h) => h.ticker);

  const header = (
    <div className="page-head">
      <div>
        <h1>내 포트폴리오의 가이던스, 지켜지고 있나요?</h1>
        <p>보유 종목 경영진이 실적발표에서 내놓은 전망을 SEC 공시 실적과 한 줄씩 맞춰 보고, 약속을 얼마나 지키는지 비교합니다.</p>
      </div>
      <div className="head-actions">
        <button className="btn primary" data-tour="connect" onClick={() => app.setConnectOpen(true)}><Link2 size={16} />토스증권에서 가져오기</button>
        <button className="btn" onClick={() => setAddOpen(true)}><Plus size={16} />직접 추가</button>
        {s && s.missing.length > 0 ? (
          <button className="btn" disabled={app.busy} onClick={() => app.analyze(s.missing)}><Play size={16} />{s.missing.length}개 종목 분석</button>
        ) : hold.length > 0 && (
          <button className="btn" disabled={app.busy} onClick={() => app.analyze(analyzable)}><RefreshCw size={16} />다시 분석</button>
        )}
      </div>
    </div>
  );

  if (!hold.length) {
    return (
      <>
        {header}
        <Empty icon={<Wallet size={40} color={C.dark} />} title="보유 종목을 불러오세요"
          body="토스증권 계좌를 연결하면 보유종목과 비중을 그대로 가져옵니다. 계좌 없이 티커를 직접 넣거나, 오른쪽 위 ‘데모 데이터’로 먼저 둘러볼 수도 있습니다.">
          <button className="btn primary lg" onClick={() => app.setConnectOpen(true)}><Link2 size={18} />토스증권 연결</button>
          <button className="btn lg" onClick={() => setAddOpen(true)}>티커 직접 입력</button>
        </Empty>
        {addOpen && <AddHoldings current={hold} onClose={() => setAddOpen(false)} />}
      </>
    );
  }

  const feed = s?.guidance_feed || [];
  const ver = feed.filter((f) => ["above", "within", "below"].includes(f.status) && !f.basis_mismatch);
  const kept = ver.filter((f) => f.kept).length;
  const pend = feed.filter((f) => f.status === "pending");
  const off = pend.filter((f) => f.progress && !f.progress.on_track);
  const byT = Object.fromEntries((s?.companies || []).map((c) => [c.ticker, c]));
  const job = (t: string) => app.jobs[t];
  const broker = s?.broker;

  return (
    <>
      {header}
      {broker && (
        <div className="card row" style={{ justifyContent: "space-between", padding: "14px 18px" }}>
          <div className="row" style={{ gap: 28 }}>
            <div><div className="xs muted">토스증권 평가금액</div><b style={{ fontSize: 20 }} className={clsx(app.masked && "mask")}>{krw(broker.summary.market_value_krw)}</b></div>
            <div><div className="xs muted">총 손익률</div><b style={{ fontSize: 20, color: (broker.summary.pl_rate || 0) >= 0 ? C.bad : C.blue }}>{pct(broker.summary.pl_rate, 2, true)}</b></div>
            <div><div className="xs muted">오늘</div><b style={{ fontSize: 20, color: (broker.summary.daily_rate || 0) >= 0 ? C.bad : C.blue }}>{pct(broker.summary.daily_rate, 2, true)}</b></div>
            <div><div className="xs muted">분석 대상</div><b style={{ fontSize: 20 }}>{broker.n_analyzable}/{broker.n}종목</b></div>
          </div>
          <div className="row small muted">{broker.at} 동기화<button className="btn sm" onClick={() => app.setConnectOpen(true)}><RefreshCw size={14} />다시 가져오기</button></div>
        </div>
      )}

      {sum.isError && <ErrorState error={sum.error} retry={() => sum.refetch()} />}
      {s && !s.companies.length && (
        <Empty icon={<Play size={36} color={C.dark} />} title="아직 분석 결과가 없습니다"
          body={`보유 종목 ${analyzable.length}개의 실적발표 보도자료에서 가이던스를 찾아 SEC 실적과 맞춰 봅니다. 진행 상황은 오른쪽 아래에 실시간으로 표시됩니다.`}>
          <button className="btn primary lg" disabled={app.busy} onClick={() => app.analyze(analyzable)}><Play size={18} />{analyzable.length}개 종목 분석 시작</button>
        </Empty>
      )}

      {s && s.companies.length > 0 && (
        <>
          <div className="grid-kpi">
            <Kpi accent tour="score" label="비중 가중 경영진 신뢰도" value={s.weighted_score?.toFixed(0) ?? "–"} sub="100점 만점 · 80 이상 높음" />
            <Kpi label="약속 이행률" value={ver.length ? `${Math.round((kept / ver.length) * 100)}%` : "–"} sub={`검증된 ${ver.length}건 중 ${kept}건`} />
            <Kpi label="불리한 방향 이탈" value={`${ver.length - kept}건`} sub="가이던스를 나쁜 쪽으로 벗어남" />
            <Kpi label="결과 대기" value={`${pend.length}건`} sub={off.length ? `연간 진행률 부진 ${off.length}건` : "아직 실적 미발표"} />
          </div>

          <div className="grid-2">
            <section className="card" aria-labelledby="h-hold">
              <div className="card-h"><h2 id="h-hold">보유 종목</h2><span className="sub">행을 누르면 상세 분석으로 이동</span></div>
              <div className="tbl-wrap" style={{ border: 0 }}>
                <table className="tbl">
                  <thead><tr><th>종목</th><th>비중</th><th className="num">평가금액</th><th>신뢰도</th><th>성향</th><th className="num">검증·대기</th><th aria-label="이동" /></tr></thead>
                  <tbody>
                    {hold.map((h) => {
                      const c = byT[h.ticker];
                      const j = job(h.ticker);
                      const color = c?.score == null ? C.na : c.score >= 80 ? C.within : c.score >= 60 ? C.drift : C.bad;
                      return (
                        <tr key={h.ticker} className={clsx(h.analyzable !== false && "click")} tabIndex={h.analyzable !== false ? 0 : -1}
                          onClick={() => h.analyzable !== false && nav(`/company/${h.ticker}`)}
                          onKeyDown={(e) => e.key === "Enter" && h.analyzable !== false && nav(`/company/${h.ticker}`)}>
                          <td style={{ maxWidth: 190 }}><b>{h.ticker}</b><div className="xs muted" style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }} title={h.name || h.note || ""}>{h.name || h.note}</div></td>
                          <td><div className="row" style={{ gap: 6, flexWrap: "nowrap" }}><div className="wbar" style={{ width: 60 }}><i style={{ width: `${(h.weight || 0) * 100}%` }} /></div><span className="xs">{pct(h.weight, 1)}</span></div></td>
                          <td className={clsx("num small", app.masked && "mask")}>{h.value_krw !== undefined ? krw(h.value_krw) : "–"}</td>
                          <td style={{ minWidth: 120 }}>
                            {h.analyzable === false ? <span className="tag warn">국내 · 제외</span>
                              : j && j.state !== "done" && j.state !== "error" ? <span className="xs muted">{Math.round(j.pct * 100)}% 분석 중</span>
                                : c?.score != null ? <div className="scorebar"><div className="t"><i style={{ width: `${c.score}%`, background: color }} /></div><b style={{ color }}>{c.score}</b></div>
                                  : c ? <span className="xs muted">검증 대상 없음</span> : <button className="btn sm" onClick={(e) => { e.stopPropagation(); app.analyze([h.ticker]); }}>분석</button>}
                          </td>
                          <td className="small" style={{ whiteSpace: "nowrap" }}>{c?.style?.split(" (")[0] ?? ""}</td>
                          <td className="num small">{c ? `${c.n_verified} · ${c.n_pending}` : ""}</td>
                          <td>{h.analyzable !== false && <ChevronRight size={16} color={C.muted} />}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              {s.excluded.length > 0 && <p className="xs muted" style={{ margin: "10px 0 0" }}>국내 종목 {s.excluded.length}개({s.excluded.map((e) => e.name || e.ticker).join(", ")})는 SEC 공시가 없어 신뢰도 분석에서 빠졌습니다.</p>}
            </section>
            <Alerts items={[...ver.filter((f) => !f.kept).sort((a, b) => b.event_date.localeCompare(a.event_date)), ...off]} />
          </div>

          <Heatmap feed={feed} />
        </>
      )}
      {addOpen && <AddHoldings current={hold} onClose={() => setAddOpen(false)} />}
    </>
  );
}

export function Alerts({ items }: { items: FeedItem[] }) {
  const per: Record<string, number> = {};
  const list = items.filter((f) => { per[f.ticker] = (per[f.ticker] || 0) + 1; return per[f.ticker] <= 2; }).slice(0, 5);
  return (
    <section className="card" aria-labelledby="h-alert">
      <div className="card-h"><h2 id="h-alert">지금 확인할 것</h2><span className="sub">불리한 이탈 · 진행률 부진</span></div>
      {!list.length && <p className="muted">최근 불리한 이탈이나 진행률이 뒤처진 가이던스가 없습니다.</p>}
      <div className="col" style={{ gap: 8 }}>
        {list.map((f) => {
          const sv = f.status === "pending" ? { label: "진행률 부진", color: C.drift } : statusView(f);
          return (
            <Link key={f.id} to={`/company/${f.ticker}?g=${f.id}`} className="gitem" style={{ borderLeftColor: sv.color, textDecoration: "none", color: "inherit" }}>
              <span className="t">{f.ticker} · {shortMetric(f.metric_label)} · {f.period}</span>
              <span className="pill" style={{ background: sv.color }}>{sv.label}</span>
              <span className="m"><span>가이던스 {fmtRange(f.low, f.high, f.unit)}</span>
                {f.status === "pending" && f.progress ? <span>목표 진행률 {f.progress.progress_pct}% · 기간 경과 {f.progress.elapsed_pct}%</span> : <span>실제와 차이 {fmtSurprise(f)}</span>}</span>
            </Link>
          );
        })}
      </div>
    </section>
  );
}

export function Heatmap({ feed }: { feed: FeedItem[] }) {
  const nav = useNavigate();
  const grid = useMemo(() => {
    const rows = feed.filter((f) => ["above", "within", "below"].includes(f.status) && !f.basis_mismatch && f.period?.includes(" Q"));
    const by: Record<string, Record<string, { kept: number; n: number; first: string }>> = {};
    rows.forEach((f) => {
      const t = (by[f.ticker] ||= {});
      const c = (t[f.period!] ||= { kept: 0, n: 0, first: f.event_date });
      c.n += 1; c.kept += f.kept ? 1 : 0;
    });
    return Object.entries(by).map(([ticker, periods]) => ({
      ticker, cells: Object.entries(periods).sort((a, b) => a[1].first.localeCompare(b[1].first)).slice(-8),
    }));
  }, [feed]);
  if (!grid.length) return null;
  const cols = Math.max(...grid.map((r) => r.cells.length));
  const color = (r: number) => (r >= 0.99 ? C.within : r >= 0.5 ? "#C98A0A" : C.bad);
  return (
    <section className="card" data-tour="heat" aria-labelledby="h-heat">
      <div className="card-h"><h2 id="h-heat">분기별 가이던스 이행 지도</h2><span className="sub">칸 = 그 분기 가이던스 중 지켜진 비율 · 누르면 해당 분기로 이동</span></div>
      <div className="heat" style={{ gridTemplateColumns: `70px repeat(${cols}, minmax(0, 1fr))` }}>
        <div />
        {Array.from({ length: cols }, (_, i) => <div key={i} className="h">{i === cols - 1 ? "최근" : `${cols - 1 - i}분기 전`}</div>)}
        {grid.map((r) => (
          <div key={r.ticker} style={{ display: "contents" }}>
            <div className="rowl">{r.ticker}</div>
            {Array.from({ length: cols - r.cells.length }, (_, i) => <div key={`e${i}`} className="cell none">–</div>)}
            {r.cells.map(([label, c]) => (
              <button key={label} className="cell" style={{ background: color(c.kept / c.n) }}
                aria-label={`${r.ticker} ${label} 이행 ${c.kept}/${c.n}`}
                onClick={() => nav(`/company/${r.ticker}?period=${encodeURIComponent(label)}`)}>
                {label.split(" ")[1]}<small>{c.kept}/{c.n}</small>
              </button>
            ))}
          </div>
        ))}
      </div>
    </section>
  );
}

function AddHoldings({ current, onClose }: { current: Holding[]; onClose: () => void }) {
  const qc = useQueryClient();
  const [q, setQ] = useState("");
  const [rows, setRows] = useState<Holding[]>(current.filter((h) => h.analyzable !== false));
  const [err, setErr] = useState<unknown>(null);
  const found = useQuery({ queryKey: ["search", q], queryFn: () => api.search(q), enabled: q.trim().length >= 1, staleTime: 60_000 });
  const total = rows.reduce((a, r) => a + (r.weight || 0), 0);
  const save = async () => {
    try {
      await api.savePortfolio(rows.map((r) => ({ ticker: r.ticker, weight: total ? (r.weight || 0) / total : null, note: r.note || r.name })));
      qc.invalidateQueries(); toast.success("보유 종목을 저장했습니다."); onClose();
    } catch (e) { setErr(e); }
  };
  return (
    <Modal title="종목 직접 추가" onClose={onClose} width={640} footer={<><button className="btn" onClick={onClose}>취소</button><button className="btn primary" onClick={save} disabled={!rows.length}>저장</button></>}>
      <div className="field"><label htmlFor="q">티커 또는 회사명</label>
        <input id="q" className="input" value={q} onChange={(e) => setQ(e.target.value)} placeholder="예: NVDA, Microsoft" autoFocus /></div>
      {q && (
        <div className="col" style={{ gap: 4, maxHeight: 200, overflow: "auto" }}>
          {found.isLoading && <span className="small muted">찾는 중…</span>}
          {found.isError && <ErrorState error={found.error} />}
          {found.data?.length === 0 && <span className="small muted">결과가 없습니다. 미국 SEC에 보고하는 상장사만 지원합니다.</span>}
          {found.data?.map((f) => (
            <button key={f.ticker} className="gitem" style={{ borderLeftWidth: 1 }} disabled={rows.some((r) => r.ticker === f.ticker)}
              onClick={() => { setRows([...rows, { ticker: f.ticker, name: f.title, weight: null }]); setQ(""); }}>
              <span className="t">{f.ticker} <span className="muted small">{f.title}</span></span><Plus size={16} />
            </button>
          ))}
        </div>
      )}
      <div className="col" style={{ gap: 6 }}>
        {rows.map((r, i) => (
          <div key={r.ticker} className="row" style={{ flexWrap: "nowrap" }}>
            <b style={{ width: 70 }}>{r.ticker}</b><span className="small muted" style={{ flex: 1 }}>{r.name || r.note}</span>
            <input className="input" style={{ width: 110 }} type="number" min={0} max={100} step={0.5} placeholder="비중 %" aria-label={`${r.ticker} 비중`}
              value={r.weight ? +(r.weight * (r.weight <= 1 ? 100 : 1)).toFixed(1) : ""} onChange={(e) => { const n = [...rows]; n[i] = { ...r, weight: e.target.value ? Number(e.target.value) / 100 : null }; setRows(n); }} />
            <button className="icon-btn" aria-label={`${r.ticker} 삭제`} onClick={() => setRows(rows.filter((x) => x.ticker !== r.ticker))}><Trash2 size={16} /></button>
          </div>
        ))}
        {!rows.length && <span className="small muted">아직 추가한 종목이 없습니다.</span>}
      </div>
      <span className="xs muted">비중을 비워 두면 동일 비중으로 계산합니다. 합계가 100%가 아니면 비율대로 환산합니다.</span>
      {err ? <ErrorState error={err} /> : null}
      {err instanceof ApiError && Array.isArray((err.detail as { invalid?: unknown[] })?.invalid) && (
        <div className="note"><AlertTriangle size={14} />{((err.detail as { invalid: { ticker: string; error: string }[] }).invalid).map((b) => `${b.ticker}: ${b.error}`).join(" / ")}</div>
      )}
    </Modal>
  );
}


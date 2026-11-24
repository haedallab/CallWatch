import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ChevronRight, ClipboardPaste, Loader2 } from "lucide-react";
import { api } from "../lib/api";
import { useApp } from "../lib/store";
import { C, pct } from "../lib/format";
import { ErrorState, Kpi, PageSkeleton } from "../components/ui";
import { Alerts, Heatmap } from "./Portfolio";

const scoreColor = (s: number | null | undefined) => (s == null ? C.na : s >= 80 ? C.within : s >= 60 ? C.drift : C.bad);

/** Public front page: stocks the server keeps analysed, open to everyone without signing up. */
export default function Home() {
  const app = useApp();
  const nav = useNavigate();
  const f = useQuery({
    queryKey: ["featured"], queryFn: api.featured,
    // keep polling while the server is still warming up some of them
    refetchInterval: (q) => (q.state.data && Object.values(q.state.data.status).some((s) => s !== "ready" && s !== "failed") ? 15_000 : false),
  });
  if (f.isLoading) return <PageSkeleton />;
  if (f.isError) return <ErrorState error={f.error} retry={() => f.refetch()} />;
  const d = f.data!;
  const byT = Object.fromEntries(d.companies.map((c) => [c.ticker, c]));
  const feed = d.guidance_feed;
  const ver = feed.filter((x) => ["above", "within", "below"].includes(x.status) && !x.basis_mismatch);
  const kept = ver.filter((x) => x.kept).length;
  const pend = feed.filter((x) => x.status === "pending");
  const off = pend.filter((x) => x.progress && !x.progress.on_track);
  const lastRelease = Object.fromEntries(d.upcoming.map((u) => [u.ticker, u]));
  const ready = d.tickers.filter((t) => d.status[t] === "ready").length;
  const waiting = d.tickers.filter((t) => d.status[t] === "queued" || d.status[t] === "running").length;
  const failed = d.tickers.filter((t) => d.status[t] === "failed");
  const rows = [...d.tickers].sort((a, b) => (byT[b]?.score ?? -1) - (byT[a]?.score ?? -1));
  const avg = d.companies.filter((c) => c.score != null);
  const avgScore = avg.length ? avg.reduce((a, c) => a + (c.score || 0), 0) / avg.length : null;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>경영진은 지난 분기에 한 약속을 지켰을까요?</h1>
          <p>주요 미국 종목 {d.tickers.length}개의 실적발표 가이던스를 SEC 10-Q·10-K 실적과 한 줄씩 맞춰 봤습니다. 가입 없이 누구나 볼 수 있고, 매일 갱신됩니다.</p>
        </div>
        <div className="head-actions">
          <button className="btn primary" onClick={() => { nav("/portfolio"); app.setImportOpen(true); }}><ClipboardPaste size={16} />내 보유 종목으로 보기</button>
        </div>
      </div>

      {waiting > 0 ? (
        <div className="banner" role="status">
          <Loader2 size={18} className="spin" style={{ flex: "none", marginTop: 2 }} color="var(--dark)" />
          <div>서버가 SEC 공시를 읽어 {d.tickers.length}개 종목을 분석하고 있습니다 ({ready}/{d.tickers.length} 완료). 끝나는 대로 이 화면에 차례로 나타납니다.</div>
        </div>
      ) : failed.length > 0 && (
        <div className="banner warn" role="status">
          <AlertTriangle size={18} style={{ flex: "none", marginTop: 2 }} color={C.drift} />
          <div>{failed.join(", ")} 분석을 불러오지 못했습니다. SEC 서버 응답 문제일 수 있어 10분 뒤 자동으로 다시 시도합니다.</div>
        </div>
      )}

      <div className="grid-kpi">
        <Kpi accent tour="score" label="평균 경영진 신뢰도" value={avgScore?.toFixed(0) ?? "–"} sub={`${avg.length}개 종목 · 100점 만점`} />
        <Kpi label="약속 이행률" value={ver.length ? `${Math.round((kept / ver.length) * 100)}%` : "–"} sub={`검증된 ${ver.length}건 중 ${kept}건`} />
        <Kpi label="불리한 방향 이탈" value={`${ver.length - kept}건`} sub="가이던스를 나쁜 쪽으로 벗어남" />
        <Kpi label="결과 대기" value={`${pend.length}건`} sub={off.length ? `연간 진행률 부진 ${off.length}건` : "아직 실적 미발표"} />
      </div>

      <div className="grid-2">
        <section className="card" aria-labelledby="h-rank">
          <div className="card-h"><h2 id="h-rank">신뢰도 순위</h2><span className="sub">행을 누르면 가이던스별 근거로 이동</span></div>
          <div className="tbl-wrap" style={{ border: 0 }}>
            <table className="tbl">
              <thead><tr><th>종목</th><th>신뢰도</th><th>성향</th><th className="num">이행률</th><th className="num">검증·대기</th><th>최근 발표</th><th aria-label="이동" /></tr></thead>
              <tbody>
                {rows.map((t) => {
                  const c = byT[t];
                  const st = d.status[t];
                  const color = scoreColor(c?.score);
                  return (
                    <tr key={t} className="click" tabIndex={0} onClick={() => nav(`/company/${t}`)} onKeyDown={(e) => e.key === "Enter" && nav(`/company/${t}`)}>
                      <td style={{ maxWidth: 200 }}><b>{t}</b><div className="xs muted ellip" title={d.names[t] || ""}>{d.names[t] || ""}</div></td>
                      <td style={{ minWidth: 130 }}>
                        {c?.score != null ? <div className="scorebar"><div className="t"><i style={{ width: `${c.score}%`, background: color }} /></div><b style={{ color }}>{c.score}</b></div>
                          : c ? <span className="xs muted" title="실적 보도자료(8-K)에 수치 전망을 싣지 않고 어닝콜에서만 말하는 회사입니다. ‘원문 넣기’로 콜 원문을 넣으면 분석됩니다.">{c.n_verified + c.n_pending === 0 ? "공시에 수치 전망 없음" : "검증할 가이던스 부족"}</span>
                            : st === "failed" ? <span className="xs" style={{ color: C.bad }} title={d.errors[t]}><AlertTriangle size={12} /> 분석 실패</span>
                              : <span className="xs muted"><Loader2 size={12} className="spin" /> {st === "running" ? "분석 중" : "대기 중"}</span>}
                      </td>
                      <td className="small nowrap">{c?.style?.split(" (")[0] ?? ""}</td>
                      <td className="num small">{c?.hit_rate != null ? pct(c.hit_rate, 0) : ""}</td>
                      <td className="num small">{c ? `${c.n_verified} · ${c.n_pending}` : ""}</td>
                      <td className="small muted nowrap">{lastRelease[t]?.last_release ?? ""}</td>
                      <td><ChevronRight size={16} color={C.muted} /></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="xs muted" style={{ margin: "10px 0 0" }}>신뢰도 = 가이던스 범위 적중(70%) + 벗어난 정도(30%).{d.tickers.includes("SPCX") && " 2026년 6월 상장한 SPCX처럼 발표 이력이 짧은 종목은 검증 건수가 적어 점수가 비어 있을 수 있습니다."}</p>
        </section>
        <Alerts items={[...ver.filter((x) => !x.kept).sort((a, b) => b.event_date.localeCompare(a.event_date)), ...off]} />
      </div>

      <Heatmap feed={feed} />

      <section className="card cta-mine">
        <div>
          <h2 style={{ margin: 0 }}>내가 가진 종목도 이렇게 볼 수 있습니다</h2>
          <p className="muted" style={{ margin: "6px 0 0" }}>증권사 앱의 보유 종목 표를 붙여넣으면 미국 종목을 찾아 같은 방식으로 분석합니다. 가입은 필요 없고, 목록은 이 브라우저에만 저장됩니다.</p>
        </div>
        <button className="btn primary lg" onClick={() => { nav("/portfolio"); app.setImportOpen(true); }}><ClipboardPaste size={18} />보유 종목 붙여넣기</button>
      </section>
    </>
  );
}

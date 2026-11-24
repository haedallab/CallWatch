import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { CheckCircle2, ChevronDown, ChevronUp, Loader2, XCircle, X } from "lucide-react";
import clsx from "clsx";
import { useApp } from "../lib/store";

/** Floating panel that shows live analysis progress streamed from the server (SSE). */
export default function JobsDock() {
  const { jobs, busy, clearJobs } = useApp();
  const [open, setOpen] = useState(true);
  const nav = useNavigate();
  const list = Object.values(jobs);
  useEffect(() => { setOpen(busy); }, [busy]);  // expand while running, fold to a slim bar when finished
  if (!list.length) return null;
  const done = list.filter((j) => j.state === "done").length;
  return (
    <section className="dock" aria-live="polite" aria-label="분석 진행 상황">
      <div className="dock-h">
        {busy ? <Loader2 size={16} className="spin" /> : <CheckCircle2 size={16} />}
        <span style={{ flex: 1 }}>{busy ? `분석 중 · ${done}/${list.length}` : `분석 완료 · ${done}/${list.length}`}</span>
        <button className="icon-btn" style={{ color: "#fff", width: 28, height: 28 }} onClick={() => setOpen(!open)} aria-label={open ? "접기" : "펼치기"}>
          {open ? <ChevronDown size={16} /> : <ChevronUp size={16} />}
        </button>
        {!busy && <button className="icon-btn" style={{ color: "#fff", width: 28, height: 28 }} onClick={clearJobs} aria-label="닫기"><X size={16} /></button>}
      </div>
      {open && (
        <div className="dock-b">
          {list.map((j) => (
            <div key={j.ticker} className={clsx("job", j.state)}>
              <div className="row" style={{ gap: 8, justifyContent: "space-between" }}>
                <b>{j.ticker}</b>
                {j.state === "done" ? <button className="btn sm ghost" onClick={() => nav(`/company/${j.ticker}`)}>결과 보기</button>
                  : j.state === "error" ? <XCircle size={16} color="var(--bad)" /> : <span className="xs muted">{Math.round(j.pct * 100)}%</span>}
              </div>
              <div className="xs muted" style={{ color: j.state === "error" ? "var(--bad)" : undefined }}>{j.message}</div>
              <div className="bar"><i style={{ width: `${Math.max(j.pct, 0.03) * 100}%` }} /></div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

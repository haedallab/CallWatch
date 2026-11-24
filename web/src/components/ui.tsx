import { useEffect, useRef, type ReactNode } from "react";
import { AlertTriangle, RotateCw, X } from "lucide-react";
import clsx from "clsx";
import { ApiError, type Guidance } from "../lib/api";
import { C, fmt, fmtRange, statusView } from "../lib/format";

export function StatusPill({ g }: { g: Pick<Guidance, "status" | "favorable"> }) {
  const s = statusView(g);
  return <span className="pill" style={{ background: s.color }}>{s.label}</span>;
}

export function Kpi({ label, value, sub, accent, masked, tour }: { label: string; value: ReactNode; sub?: ReactNode; accent?: boolean; masked?: boolean; tour?: string }) {
  return (
    <div className={clsx("kpi", accent && "accent")} data-tour={tour}>
      <div className={clsx("v", masked && "mask")}>{value}</div>
      <div className="l">{label}</div>
      {sub && <div className="s">{sub}</div>}
    </div>
  );
}

export const Skeleton = ({ h = 16, w = "100%", r }: { h?: number; w?: number | string; r?: number }) =>
  <div className="skel" style={{ height: h, width: w, borderRadius: r }} aria-hidden />;

export function PageSkeleton() {
  return (
    <div className="col" aria-busy="true" aria-label="불러오는 중">
      <Skeleton h={34} w={360} />
      <div className="grid-kpi">{[0, 1, 2, 3].map((i) => <Skeleton key={i} h={108} r={10} />)}</div>
      <div className="grid-2"><Skeleton h={300} r={10} /><Skeleton h={300} r={10} /></div>
    </div>
  );
}

export function Empty({ title, body, icon, children }: { title: string; body: string; icon?: ReactNode; children?: ReactNode }) {
  return (
    <div className="empty">
      {icon}
      <div style={{ flex: 1, minWidth: 260 }}>
        <h3>{title}</h3>
        <p>{body}</p>
      </div>
      {children && <div className="row">{children}</div>}
    </div>
  );
}

export function ErrorState({ error, retry }: { error: unknown; retry?: () => void }) {
  const e = error instanceof ApiError ? error : null;
  return (
    <div className="banner err" role="alert">
      <AlertTriangle size={18} color={C.bad} style={{ flex: "none", marginTop: 2 }} />
      <div style={{ flex: 1 }}>
        <b>{e?.message || (error as Error)?.message || "문제가 발생했습니다."}</b>
        {e?.hint && <div className="small" style={{ marginTop: 4 }}>{e.hint}</div>}
      </div>
      {retry && <button className="btn sm" onClick={retry}><RotateCw size={14} />다시 시도</button>}
    </div>
  );
}

export function Overlay({ onClose, children, label }: { onClose: () => void; children: ReactNode; label: string }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    ref.current?.querySelector<HTMLElement>("button, input, textarea, select, [tabindex]")?.focus();
    return () => { window.removeEventListener("keydown", onKey); prev?.focus(); };
  }, [onClose]);
  return (
    <div className="overlay" role="dialog" aria-modal="true" aria-label={label} ref={ref}
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      {children}
    </div>
  );
}

export function Modal({ title, onClose, children, footer, width }: { title: ReactNode; onClose: () => void; children: ReactNode; footer?: ReactNode; width?: number }) {
  return (
    <Overlay onClose={onClose} label={typeof title === "string" ? title : "대화상자"}>
      <div className="modal" style={width ? { width: `min(${width}px, 94vw)` } : undefined}>
        <div className="modal-h"><h2>{title}</h2><button className="icon-btn" onClick={onClose} aria-label="닫기"><X size={18} /></button></div>
        <div className="modal-b">{children}</div>
        {footer && <div className="modal-f">{footer}</div>}
      </div>
    </Overlay>
  );
}

export function Drawer({ title, onClose, children, actions }: { title: ReactNode; onClose: () => void; children: ReactNode; actions?: ReactNode }) {
  return (
    <Overlay onClose={onClose} label={typeof title === "string" ? title : "원문 보기"}>
      <aside className="drawer">
        <div className="modal-h"><h2 style={{ fontSize: 17 }}>{title}</h2><div className="row">{actions}<button className="icon-btn" onClick={onClose} aria-label="닫기"><X size={18} /></button></div></div>
        <div className="body">{children}</div>
      </aside>
    </Overlay>
  );
}

export function Tabs<T extends string>({ value, onChange, items }: { value: T; onChange: (v: T) => void; items: { key: T; label: string; n?: number }[] }) {
  return (
    <div className="tabs" role="tablist">
      {items.map((it) => (
        <button key={it.key} role="tab" aria-selected={value === it.key} onClick={() => onChange(it.key)}>
          {it.label}{it.n !== undefined && <span className="muted small"> {it.n}</span>}
        </button>
      ))}
    </div>
  );
}

export function Seg<T extends string>({ value, onChange, items, label }: { value: T; onChange: (v: T) => void; items: { key: T; label: string }[]; label: string }) {
  return (
    <div className="seg" role="group" aria-label={label}>
      {items.map((it) => <button key={it.key} aria-pressed={value === it.key} onClick={() => onChange(it.key)}>{it.label}</button>)}
    </div>
  );
}

export const Switch = ({ checked, onChange, label, title }: { checked: boolean; onChange: (v: boolean) => void; label: string; title?: string }) => (
  <label className="switch" title={title}><input type="checkbox" role="switch" checked={checked} onChange={(e) => onChange(e.target.checked)} />{label}</label>
);

/** Guided range (band) vs reported actual (dot) on one axis - the app's core visual. */
export function RangeBar({ g, compact }: { g: Guidance; compact?: boolean }) {
  const { low: lo, high: hi, mid, unit } = g;
  const act = g.actual;
  const vals = [lo, hi, ...(act !== undefined && act !== null ? [act] : [])];
  const span = Math.max(...vals) - Math.min(...vals) || Math.abs(mid) * 0.04 || 1;
  const a = Math.min(...vals) - span * 0.35, b = Math.max(...vals) + span * 0.35;
  const x = (v: number) => ((v - a) / (b - a)) * 100;
  const s = statusView(g);
  return (
    <div className={clsx("rb", compact && "compact")} role="img"
      aria-label={`가이던스 ${fmtRange(lo, hi, unit)}, ${act !== undefined ? `실제 ${fmt(act, unit)}, ${s.label}` : "실제 값 대기"}`}>
      <div className="track">
        <div className="base" />
        <div className="band" style={{ left: `${x(lo)}%`, width: `${Math.max(x(hi) - x(lo), 0.8)}%` }} />
        <div className="mid" style={{ left: `${x(mid)}%` }} />
        {act !== undefined && act !== null && <div className="act" style={{ left: `${x(act)}%`, background: s.color }} />}
      </div>
      {!compact && (
        <div className="lbl">
          <span>가이던스 <b style={{ color: C.ink }}>{fmtRange(lo, hi, unit)}</b></span>
          <span>{act !== undefined ? <>실제 <b style={{ color: s.color }}>{fmt(act, unit)}</b></> : "실제 값 대기 중"}</span>
        </div>
      )}
    </div>
  );
}

export function Legend() {
  const items: [string, string][] = [["부합", C.within], ["유리한 방향 이탈", C.good], ["불리한 방향 이탈", C.bad], ["방향 중립 이탈", C.drift], ["결과 대기", C.pending], ["검증 불가", C.na]];
  return <div className="legend">{items.map(([t, c]) => <span key={t}><i className="dot" style={{ background: c }} />{t}</span>)}</div>;
}

export interface Span { start: number; end: number; tag: string; id: string }

/** Text with highlighted spans; clicking a span reports its id. */
export function Highlighted({ text, spans, active, onPick }: { text: string; spans: Span[]; active?: string | null; onPick?: (id: string) => void }) {
  const parts: ReactNode[] = [];
  let pos = 0;
  [...spans].sort((x, y) => x.start - y.start).forEach((s) => {
    if (s.start < pos || s.end <= s.start) return;
    parts.push(text.slice(pos, s.start));
    parts.push(
      <mark key={s.id + s.start} className="hl" data-id={s.id} data-active={active === s.id} tabIndex={0}
        onClick={() => onPick?.(s.id)} onKeyDown={(e) => e.key === "Enter" && onPick?.(s.id)}>
        {text.slice(s.start, s.end)}<sup>{s.tag}</sup>
      </mark>,
    );
    pos = s.end;
  });
  parts.push(text.slice(pos));
  return <>{parts}</>;
}

export function findQuote(text: string, quote: string): [number, number] | null {
  if (!quote) return null;
  let i = text.indexOf(quote);
  if (i < 0) i = text.toLowerCase().indexOf(quote.slice(0, 60).toLowerCase());
  return i >= 0 ? [i, i + quote.length] : null;
}

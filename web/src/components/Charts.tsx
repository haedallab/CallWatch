import {
  Bar, BarChart, CartesianGrid, Cell, ComposedChart, ErrorBar, Legend, Line, LineChart, ReferenceLine,
  ResponsiveContainer, Scatter, Tooltip, XAxis, YAxis,
} from "recharts";
import type { Guidance, Report } from "../lib/api";
import { C, fmt, fmtRange, fmtSurprise, statusView, type Tone } from "../lib/format";

const ts = (d: string) => new Date(d + "T00:00:00").getTime();
const ym = (t: number) => { const d = new Date(t); return `${String(d.getFullYear()).slice(2)}.${String(d.getMonth() + 1).padStart(2, "0")}`; };
const AX = { fontSize: 12, fill: C.muted };

function unitOf(metric: string, items: Guidance[]) {
  return items[0]?.unit || (metric.includes("margin") ? "%" : metric === "eps" ? "USD/share" : "USD");
}
const scaleOf = (unit: string) => (unit === "USD" ? 1e9 : 1);

const Diamond = (color: string, size = 7, ring = false) => (p: { cx?: number; cy?: number }) => {
  const { cx = 0, cy = 0 } = p;
  return (
    <g>
      {ring && <circle cx={cx} cy={cy} r={size + 6} fill="none" stroke={C.blue} strokeWidth={2} />}
      <path d={`M${cx} ${cy - size} L${cx + size} ${cy} L${cx} ${cy + size} L${cx - size} ${cy} Z`} fill="#fff" stroke={color} strokeWidth={2.5} />
    </g>
  );
};

interface GPoint { x: number; y: number; err: [number, number]; g: Guidance }

/** Actual (line) vs guidance ranges (error bars, coloured by verdict); the selected item is ringed. */
export function TrendChart({ rep, metric, ptype, selectedId, onSelect, height = 340 }:
  { rep: Report; metric: string; ptype: "Q" | "FY"; selectedId?: string | null; onSelect?: (id: string) => void; height?: number }) {
  const act = rep.actuals[metric]?.[ptype] || [];
  const items = rep.guidance.filter((g) => g.metric === metric && g.period?.type === ptype && g.kind !== "growth_yoy");
  const unit = unitOf(metric, items);
  const k = scaleOf(unit);
  const line = act.map((r) => ({ x: ts(r.end), y: r.value / k, label: r.label }));
  const pts: GPoint[] = items.map((g, i) => ({
    x: ts(g.period!.end) + ((i % 3) - 1) * 4 * 86400000, y: g.mid / k, err: [(g.mid - g.low) / k, (g.high - g.mid) / k], g,
  }));
  const tones: Tone[] = ["within", "good", "bad", "drift", "pending", "na"];
  const sel = pts.find((p) => p.g.id === selectedId);
  if (!line.length && !pts.length) return <p className="muted small">표시할 데이터가 없습니다.</p>;
  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart margin={{ top: 10, right: 16, bottom: 0, left: 0 }}>
        <CartesianGrid stroke={C.line} vertical={false} />
        <XAxis dataKey="x" type="number" scale="time" domain={["dataMin - 2000000000", "dataMax + 2000000000"]} tickFormatter={ym} tick={AX} stroke={C.line} />
        <YAxis tick={AX} stroke={C.line} width={54} domain={["auto", "auto"]} tickFormatter={(v) => (unit === "%" ? `${v}%` : unit === "USD" ? `${v}B` : `$${v}`)} />
        <Tooltip content={<GTip unit={unit} />} />
        <Line data={line} dataKey="y" name="실제 (SEC XBRL)" stroke={C.dark} strokeWidth={2.5} dot={{ r: 3.5, fill: C.dark }} isAnimationActive={false} />
        {tones.map((t) => {
          const d = pts.filter((p) => statusView(p.g).tone === t);
          if (!d.length) return null;
          const color = statusView(d[0].g).color;
          return (
            <Scatter key={t} data={d} dataKey="y" fill={color} name={statusView(d[0].g).label} shape={Diamond(color)} isAnimationActive={false}
              onClick={(p: unknown) => onSelect?.((p as { payload: GPoint }).payload.g.id)} style={{ cursor: onSelect ? "pointer" : undefined }}>
              <ErrorBar dataKey="err" direction="y" stroke={color} strokeWidth={5} width={0} strokeOpacity={0.45} />
            </Scatter>
          );
        })}
        {sel && <Scatter data={[sel]} dataKey="y" legendType="none" shape={Diamond(statusView(sel.g).color, 9, true)} isAnimationActive={false} />}
        <Legend iconSize={10} wrapperStyle={{ fontSize: 12.5 }} />
      </ComposedChart>
    </ResponsiveContainer>
  );
}

function GTip({ active, payload, unit }: { active?: boolean; payload?: { payload: GPoint & { label?: string } }[]; unit: string }) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload;
  const box = { background: "#fff", border: `1px solid ${C.line}`, borderRadius: 8, padding: "8px 10px", fontSize: 12.5, boxShadow: "0 4px 14px rgba(0,0,0,.08)", maxWidth: 300 };
  if (!p.g) return <div style={box}><b>{p.label}</b><br />실제 {fmt(p.y * scaleOf(unit), unit)}</div>;
  const s = statusView(p.g);
  return (
    <div style={box}>
      <b>{p.g.period?.label} 가이던스</b> · {p.g.basis}<br />
      {fmtRange(p.g.low, p.g.high, p.g.unit)} → 실제 {fmt(p.g.actual, p.g.unit)}<br />
      <span style={{ color: s.color, fontWeight: 700 }}>{s.label}</span> {fmtSurprise(p.g)}<br />
      <span style={{ color: C.muted }}>{p.g.event_date} 발표 · 클릭하면 상세</span>
    </div>
  );
}

export function PriceChart({ rep, height = 360 }: { rep: Report; height?: number }) {
  if (!rep.prices.length) return null;
  const c0 = rep.prices[0].close, b0 = rep.prices[0].bench;
  const step = Math.max(1, Math.floor(rep.prices.length / 400));
  const data = rep.prices.filter((_, i) => i % step === 0).map((p) => ({ x: ts(p.date), s: (p.close / c0) * 100, b: (p.bench / b0) * 100 }));
  const byEvent: Record<string, boolean[]> = {};
  rep.guidance.forEach((g) => {
    if (g.realization_event && ["above", "within", "below"].includes(g.status) && !g.basis_mismatch) (byEvent[g.realization_event] ||= []).push(!!g.kept);
  });
  const dots = rep.events.map((e) => {
    const d = ts(e.reaction?.reaction_date || e.date);
    const near = data.find((p) => p.x >= d) || data[data.length - 1];
    const kept = byEvent[e.date] || [];
    const share = kept.length ? kept.filter(Boolean).length / kept.length : null;
    const color = share === null ? C.pending : share >= 0.67 ? C.within : share >= 0.34 ? C.drift : C.bad;
    return { x: near.x, s: near.s, color, date: e.date, kept: kept.length ? `${kept.filter(Boolean).length}/${kept.length}` : "해당 없음", car: e.reaction?.car_m1p1 };
  });
  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={data} margin={{ top: 10, right: 16, bottom: 0, left: 0 }}>
        <CartesianGrid stroke={C.line} vertical={false} />
        <XAxis dataKey="x" type="number" scale="time" domain={["dataMin", "dataMax"]} tickFormatter={ym} tick={AX} stroke={C.line} />
        <YAxis tick={AX} stroke={C.line} width={44} domain={["auto", "auto"]} />
        <ReferenceLine y={100} stroke={C.line} />
        <Tooltip content={<PTip />} />
        <Line dataKey="b" name="SPY (벤치마크)" stroke="#9AA6B8" strokeWidth={1.5} dot={false} isAnimationActive={false} />
        <Line dataKey="s" name={rep.ticker} stroke={C.dark} strokeWidth={2.2} dot={false} isAnimationActive={false} />
        <Scatter data={dots} dataKey="s" name="실적발표 (색 = 직전 가이던스 이행)" fill={C.pending} isAnimationActive={false}
          shape={(p: { cx?: number; cy?: number; payload?: { color: string } }) => <circle cx={p.cx} cy={p.cy} r={7} fill={p.payload?.color} stroke="#fff" strokeWidth={2} />} />
        <Legend iconSize={10} wrapperStyle={{ fontSize: 12.5 }} />
      </ComposedChart>
    </ResponsiveContainer>
  );
}

function PTip({ active, payload }: { active?: boolean; payload?: { payload: { x: number; s: number; b?: number; date?: string; kept?: string; car?: number | null } }[] }) {
  if (!active || !payload?.length) return null;
  const p = payload[payload.length - 1].payload;
  const box = { background: "#fff", border: `1px solid ${C.line}`, borderRadius: 8, padding: "8px 10px", fontSize: 12.5 };
  if (p.date) return <div style={box}><b>실적발표 {p.date}</b><br />직전 가이던스 이행 {p.kept}{p.car !== undefined && p.car !== null && <><br />CAR[-1,+1] {p.car > 0 ? "+" : ""}{p.car.toFixed(2)}%</>}</div>;
  return <div style={box}>{new Date(p.x).toISOString().slice(0, 10)}<br />종목 {p.s.toFixed(1)}{p.b !== undefined && <> · SPY {p.b.toFixed(1)}</>}</div>;
}

export function CarBars({ rep, height = 260 }: { rep: Report; height?: number }) {
  const data = rep.events.filter((e) => e.reaction?.car_m1p1 !== undefined && e.reaction?.car_m1p1 !== null)
    .map((e) => ({ d: e.date.slice(2), v: e.reaction!.car_m1p1 as number }));
  if (!data.length) return <p className="muted small">계산된 초과수익률이 없습니다.</p>;
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 18, right: 8, bottom: 0, left: 0 }}>
        <CartesianGrid stroke={C.line} vertical={false} />
        <XAxis dataKey="d" tick={AX} stroke={C.line} />
        <YAxis tick={AX} stroke={C.line} width={40} tickFormatter={(v) => `${v}%`} />
        <ReferenceLine y={0} stroke={C.muted} />
        <Tooltip formatter={(v) => [`${Number(v) > 0 ? "+" : ""}${Number(v).toFixed(2)}%`, "CAR[-1,+1]"]} />
        <Bar dataKey="v" radius={[4, 4, 0, 0]} isAnimationActive={false} label={{ position: "top", fontSize: 11, fill: C.muted, formatter: (v: unknown) => `${Number(v) > 0 ? "+" : ""}${Number(v).toFixed(1)}` }}>
          {data.map((d) => <Cell key={d.d} fill={d.v >= 0 ? C.good : C.bad} />)}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

export function Sparkline({ values, color = C.dark }: { values: number[]; color?: string }) {
  if (values.length < 2) return null;
  return (
    <ResponsiveContainer width={90} height={28}>
      <LineChart data={values.map((v, i) => ({ i, v }))}><Line dataKey="v" stroke={color} strokeWidth={1.6} dot={false} isAnimationActive={false} /></LineChart>
    </ResponsiveContainer>
  );
}

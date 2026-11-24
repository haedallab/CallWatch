import type { Guidance, FeedItem } from "./api";

export const C = {
  dark: "#004191", medium: "#004187", blue: "#1487C8", light: "#5FBEEB",
  ink: "#13233F", muted: "#5B6B82", line: "#D9E2EE", paper: "#F4F7FB",
  within: "#1B7F5A", good: "#0F766E", bad: "#B42318", drift: "#B26A00", pending: "#64748B", na: "#9AA6B8",
};

export type Tone = "within" | "good" | "bad" | "drift" | "pending" | "na";

export function statusView(g: Pick<Guidance, "status" | "favorable">): { label: string; tone: Tone; color: string } {
  if (g.status === "within") return { label: "부합", tone: "within", color: C.within };
  if (g.status === "above" || g.status === "below") {
    const w = g.status === "above" ? "상회" : "하회";
    if (g.favorable === true) return { label: `${w} · 유리`, tone: "good", color: C.good };
    if (g.favorable === false) return { label: `${w} · 불리`, tone: "bad", color: C.bad };
    return { label: `${w} · 이탈`, tone: "drift", color: C.drift };
  }
  if (g.status === "pending") return { label: "결과 대기", tone: "pending", color: C.pending };
  return { label: "검증 불가", tone: "na", color: C.na };
}

export const bucket = (g: Pick<Guidance, "status" | "favorable">): Tone => statusView(g).tone;

export function fmt(v: number | null | undefined, unit: string): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "–";
  if (unit === "%") return `${v.toFixed(1)}%`;
  if (unit === "USD/share") return `$${v.toFixed(2)}`;
  const a = Math.abs(v);
  if (a >= 1e9) return `$${(v / 1e9).toFixed(2)}B`;
  if (a >= 1e6) return `$${Math.round(v / 1e6).toLocaleString()}M`;
  return `$${Math.round(v).toLocaleString()}`;
}

export function fmtRange(lo: number, hi: number, unit: string): string {
  return Math.abs(hi - lo) < 1e-9 * Math.max(Math.abs(lo), 1) ? fmt(lo, unit) : `${fmt(lo, unit)} – ${fmt(hi, unit)}`;
}

export function fmtSurprise(g: Pick<Guidance, "surprise" | "surprise_unit"> | FeedItem): string {
  if (g.surprise === undefined || g.surprise === null) return "–";
  const s = g.surprise >= 0 ? "+" : "";
  return `${s}${g.surprise.toFixed(1)}${g.surprise_unit === "pp" ? "%p" : "%"}`;
}

export function krw(v: number | null | undefined, masked = false): string {
  if (v === null || v === undefined) return "–";
  if (masked) return "••••••";
  const a = Math.abs(v);
  if (a >= 1e8) return `${(v / 1e8).toFixed(2)}억원`;
  if (a >= 1e4) return `${Math.round(v / 1e4).toLocaleString()}만원`;
  return `${Math.round(v).toLocaleString()}원`;
}

export const pct = (v: number | null | undefined, digits = 1, sign = false) =>
  v === null || v === undefined ? "–" : `${sign && v >= 0 ? "+" : ""}${(v * 100).toFixed(digits)}%`;

export const basisKo = (b: string) => ({ GAAP: "GAAP", "non-GAAP": "Non-GAAP", unspecified: "기준 명시 없음" } as Record<string, string>)[b] || b;

export const shortMetric = (label: string) => label.split(" (")[0];

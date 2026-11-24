export const API_URL = (import.meta.env.VITE_API_URL || "http://localhost:8000").replace(/\/$/, "");

export type Status = "above" | "within" | "below" | "pending" | "unverifiable";

export interface Period { type: "Q" | "FY"; start: string; end: string; label: string }
export interface Reaction { reaction_date?: string; car_0?: number | null; car_m1p1?: number | null; car_0p5?: number | null; car_0p20?: number | null; raw_1d?: number; model?: string; beta?: number }
export interface Evidence { text: string; score: number; form: string; url: string; filing_date: string }
export interface Guidance {
  id: string; ticker: string; event_date: string; source: string; source_url: string; transcript_id?: string;
  metric: string; metric_label: string; basis: "GAAP" | "non-GAAP" | "unspecified";
  kind: "level" | "ratio" | "growth_yoy"; low: number; high: number; mid: number; unit: "USD" | "%" | "USD/share";
  period_type: string; quarter?: number | null; fiscal_year?: number | null; timeframe_text: string; timeframe_assumed: boolean;
  quote: string; span: [number, number]; extractor: string;
  period?: Period | null; status: Status; status_ko: string; actual?: number; surprise?: number; surprise_unit?: "%" | "pp";
  range_position?: number | null; favorable?: boolean | null; kept?: boolean; basis_mismatch?: boolean; notes: string[];
  actual_source?: { concept: string; form: string; accn: string; filed: string; period_end: string; derived: boolean };
  filing?: { form: string; filing_date: string; period: string; url: string } | null; evidence?: Evidence[];
  realization_event?: string | null; announcement?: Reaction; realization?: Reaction;
  progress?: { ytd: number; through: string; progress_pct: number; elapsed_pct: number; on_track: boolean };
}
export interface Score {
  n_total: number; n_verified: number; n_pending: number; n_unverifiable: number; n_reference_only: number;
  score: number | null; grade: string; style: string; hit_rate: number | null; beat_share: number | null;
  miss_share: number | null; mean_surprise_pct: number | null; explain: string;
}
export interface EventRow { date: string; accession: string; after_close: boolean; url: string; press_release_url?: string; has_outlook?: boolean; n_guidance?: number; reaction?: Reaction }
export interface Report {
  ticker: string; name: string; cik: string; mode: "live" | "demo"; generated_at: string; elapsed_sec: number; llm: string;
  events: EventRow[]; guidance: Guidance[]; score: Score;
  market_response: { kept: { n: number; avg_car_m1p1: number | null }; missed: { n: number; avg_car_m1p1: number | null } };
  actuals: Record<string, { label: string; Q: { end: string; value: number; derived?: boolean; label: string }[]; FY: { end: string; value: number; label: string }[] }>;
  prices: { date: string; close: number; bench: number }[]; warnings: string[];
}
export interface Holding {
  ticker: string; name?: string; market?: string; weight?: number | null; shares?: number | null; note?: string | null;
  value_krw?: number; pl_krw?: number | null; pl_rate?: number | null; daily_rate?: number | null; analyzable?: boolean; source?: string;
}
export interface CompanyRow { ticker: string; name: string; weight: number; score: number | null; grade: string; style: string; n_verified: number; n_pending: number; hit_rate: number | null }
export interface FeedItem extends Pick<Guidance, "id" | "ticker" | "event_date" | "metric" | "metric_label" | "basis" | "kind" | "low" | "high" | "mid" | "unit" | "status" | "status_ko" | "surprise" | "surprise_unit" | "favorable" | "kept" | "basis_mismatch" | "progress"> { period: string | null; source: string }
export interface Summary {
  companies: CompanyRow[]; weighted_score: number | null; n_companies: number; n_scored: number; mode: string; missing: string[];
  guidance_feed: FeedItem[]; excluded: { ticker: string; name?: string; weight?: number; reason: string }[];
  upcoming: { ticker: string; last_release: string; next_release_est: string }[];
  broker: BrokerSync | null;
}
export interface BrokerSync { at: string; account_seq: number; n: number; n_analyzable: number; usd_krw: number | null; summary: { market_value_krw: number; purchase_krw: number | null; pl_krw: number | null; pl_rate: number | null; daily_rate: number | null } }
export interface BrokerStatus {
  provider: "toss"; mode: string; configured: boolean; owner: boolean; owner_key_required: boolean; connected: boolean | null;
  demo?: boolean; accounts?: { accountSeq: number; accountNo: string; accountType: string }[]; error?: string; hint?: string; code?: string; last_sync: BrokerSync | null;
}
export interface Health { status: string; mode: "live" | "demo"; sec_reachable: boolean | null; llm: string; llm_enabled: boolean }
export interface Citation { text: string; source: string; date?: string; url?: string; score?: number }
export interface QAResponse { answer: string; citations: Citation[]; mode: "llm" | "extractive" | "empty"; latency_ms: number }

export class ApiError extends Error {
  status: number; hint?: string; detail: unknown;
  constructor(status: number, message: string, hint?: string, detail?: unknown) {
    super(message); this.status = status; this.hint = hint; this.detail = detail;
  }
}

const OWNER_KEY = "gl.ownerKey";
export const ownerKey = {
  get: () => sessionStorage.getItem(OWNER_KEY) || "",
  set: (v: string) => (v ? sessionStorage.setItem(OWNER_KEY, v) : sessionStorage.removeItem(OWNER_KEY)),
};

export async function request<T>(method: string, path: string, opts: { body?: unknown; params?: Record<string, unknown> } = {}): Promise<T> {
  const url = new URL(API_URL + path);
  Object.entries(opts.params || {}).forEach(([k, v]) => v !== undefined && v !== null && url.searchParams.set(k, String(v)));
  const headers: Record<string, string> = { Accept: "application/json" };
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  if (ownerKey.get()) headers["X-Owner-Key"] = ownerKey.get();
  let r: Response;
  try {
    r = await fetch(url, { method, headers, body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined });
  } catch {
    throw new ApiError(0, "서버에 연결하지 못했습니다.", "백엔드(Render)가 잠들어 있으면 30초 정도 뒤 다시 시도하세요.");
  }
  if (!r.ok) {
    let detail: unknown = null;
    try { detail = (await r.json()).detail; } catch { /* not json */ }
    const d = detail as { message?: string; hint?: string } | string | null;
    const msg = typeof d === "string" ? d : d?.message || `요청이 실패했습니다 (${r.status})`;
    throw new ApiError(r.status, msg, typeof d === "object" && d ? d.hint : undefined, detail);
  }
  return r.json() as Promise<T>;
}

export const api = {
  health: () => request<Health>("GET", "/health"),
  setMode: (demo: boolean) => request("POST", "/api/mode", { body: { demo } }),
  meta: () => request<{ llm: string; mode: string; sources: { name: string; use: string; url: string }[]; disclaimer: string }>("GET", "/api/meta"),
  search: (q: string) => request<{ ticker: string; title: string; cik: string }[]>("GET", "/api/search", { params: { q } }),
  portfolio: () => request<Holding[]>("GET", "/api/portfolio"),
  savePortfolio: (rows: Holding[]) => request<Holding[]>("PUT", "/api/portfolio", { body: rows }),
  summary: () => request<Summary>("GET", "/api/portfolio/summary"),
  report: (t: string) => request<Report>("GET", `/api/report/${t}`),
  brokerStatus: () => request<BrokerStatus>("GET", "/api/broker/status"),
  brokerSync: (account_seq?: number) => request<{ holdings: Holding[] } & BrokerSync>("POST", "/api/broker/toss/sync", { body: { account_seq } }),
  document: (url: string) => request<{ url: string; text: string }>("GET", "/api/document", { params: { url } }),
  extract: (text: string, ticker: string, event_date: string, use_llm: boolean) =>
    request<{ items: Guidance[]; llm_used: boolean; n: number }>("POST", "/api/extract", { body: { text, ticker, event_date, use_llm } }),
  saveTranscript: (ticker: string, call_date: string, text: string) =>
    request<{ id: string; n_guidance: number }>("POST", "/api/transcripts", { body: { ticker, call_date, text } }),
  transcripts: (t: string, include_text = false) =>
    request<{ id: string; call_date: string; source: string; chars: number; preview: string; text?: string }[]>("GET", `/api/transcripts/${t}`, { params: { include_text } }),
  deleteTranscript: (id: string) => request("DELETE", `/api/transcripts/${encodeURIComponent(id)}`),
  qa: (ticker: string, question: string) => request<QAResponse>("POST", "/api/qa", { body: { ticker, question } }),
};

export interface ProgressEvent { step: string; message: string; pct: number }
export interface DoneEvent { ticker: string; score: Score; n_guidance: number; elapsed_sec: number; warnings: string[] }

/** Run an analysis and receive step-by-step progress over Server-Sent Events. */
export function analyzeStream(ticker: string, opts: { events?: number; useLlm?: boolean },
  on: { progress: (e: ProgressEvent) => void; done: (e: DoneEvent) => void; error: (msg: string) => void }) {
  const url = new URL(`${API_URL}/api/analyze/${ticker}/stream`);
  url.searchParams.set("events", String(opts.events ?? 8));
  url.searchParams.set("use_llm", String(opts.useLlm ?? true));
  const es = new EventSource(url);
  let finished = false;
  es.addEventListener("progress", (e) => on.progress(JSON.parse((e as MessageEvent).data)));
  es.addEventListener("done", (e) => { finished = true; es.close(); on.done(JSON.parse((e as MessageEvent).data)); });
  es.addEventListener("error", (e) => {
    const data = (e as MessageEvent).data;
    if (finished) return;
    finished = true; es.close();
    on.error(data ? JSON.parse(data).message : "분석 서버와의 연결이 끊어졌습니다. 다시 시도해 주세요.");
  });
  return () => { finished = true; es.close(); };
}

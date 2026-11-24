import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { analyzeStream, type DoneEvent } from "./api";

export interface Job { ticker: string; state: "queued" | "running" | "done" | "error"; pct: number; message: string; log: string[]; result?: DoneEvent; error?: string }

interface Ctx {
  masked: boolean; setMasked: (v: boolean) => void;
  useLlm: boolean; setUseLlm: (v: boolean) => void;
  events: number; setEvents: (v: number) => void;
  jobs: Record<string, Job>; busy: boolean;
  analyze: (tickers: string[]) => Promise<void>;
  clearJobs: () => void;
  tour: boolean; setTour: (v: boolean) => void;
  paletteOpen: boolean; setPaletteOpen: (v: boolean) => void;
  connectOpen: boolean; setConnectOpen: (v: boolean) => void;
}

const AppCtx = createContext<Ctx | null>(null);

function persisted<T>(key: string, initial: T): [T, (v: T) => void] {
  const [v, setV] = useState<T>(() => {
    try { const s = localStorage.getItem(key); return s === null ? initial : (JSON.parse(s) as T); } catch { return initial; }
  });
  const set = useCallback((x: T) => { setV(x); try { localStorage.setItem(key, JSON.stringify(x)); } catch { /* private mode */ } }, [key]);
  return [v, set];
}

export function AppProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const [masked, setMasked] = persisted("gl.masked", false);
  const [useLlm, setUseLlm] = persisted("gl.useLlm", true);
  const [events, setEvents] = persisted("gl.events", 8);
  const [jobs, setJobs] = useState<Record<string, Job>>({});
  const [tour, setTour] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [connectOpen, setConnectOpen] = useState(false);
  const running = useRef(false);

  const patch = (t: string, p: Partial<Job>) => setJobs((j) => ({ ...j, [t]: { ...j[t], ...p } }));

  const analyze = useCallback(async (tickers: string[]) => {
    if (!tickers.length) return;
    setJobs((j) => {
      const n = { ...j };
      tickers.forEach((t) => { n[t] = { ticker: t, state: "queued", pct: 0, message: "대기 중", log: [] }; });
      return n;
    });
    if (running.current) return;
    running.current = true;
    let ok = 0;
    for (const t of tickers) {
      patch(t, { state: "running", message: "시작", pct: 0.01 });
      await new Promise<void>((resolve) => {
        analyzeStream(t, { events, useLlm }, {
          progress: (e) => setJobs((j) => ({ ...j, [t]: { ...j[t], pct: e.pct, message: e.message, log: [...(j[t]?.log || []), e.message].slice(-30) } })),
          done: (d) => { ok += 1; patch(t, { state: "done", pct: 1, message: `가이던스 ${d.n_guidance}건 · ${d.elapsed_sec}초`, result: d }); qc.invalidateQueries({ queryKey: ["report", t] }); resolve(); },
          error: (msg) => { patch(t, { state: "error", message: msg, error: msg }); resolve(); },
        });
      });
    }
    running.current = false;
    qc.invalidateQueries({ queryKey: ["summary"] });
    if (ok === tickers.length) toast.success(`${ok}개 종목 분석을 마쳤습니다.`);
    else toast.error(`${tickers.length - ok}개 종목 분석에 실패했습니다.`, { description: "진행 패널에서 원인을 확인하세요." });
  }, [events, useLlm, qc]);

  const busy = Object.values(jobs).some((j) => j.state === "running" || j.state === "queued");
  const value = useMemo(() => ({
    masked, setMasked, useLlm, setUseLlm, events, setEvents, jobs, busy, analyze,
    clearJobs: () => setJobs({}), tour, setTour, paletteOpen, setPaletteOpen, connectOpen, setConnectOpen,
  }), [masked, setMasked, useLlm, setUseLlm, events, setEvents, jobs, busy, analyze, tour, paletteOpen, connectOpen]);
  return <AppCtx.Provider value={value}>{children}</AppCtx.Provider>;
}

export function useApp() {
  const c = useContext(AppCtx);
  if (!c) throw new Error("AppProvider missing");
  return c;
}

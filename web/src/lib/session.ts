import { createClient, type SupabaseClient } from "@supabase/supabase-js";

const SB_URL = (import.meta.env.VITE_SUPABASE_URL as string | undefined) || "";
const SB_KEY = (import.meta.env.VITE_SUPABASE_ANON_KEY as string | undefined) || "";

/** Supabase Auth client; null when the deployment runs without sign-in (single-user / local). */
export const supabase: SupabaseClient | null = SB_URL && SB_KEY
  ? createClient(SB_URL, SB_KEY, { auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true, flowType: "pkce" } })
  : null;
export const authEnabled = !!supabase;

export async function accessToken(): Promise<string | null> {
  if (!supabase) return null;
  const { data } = await supabase.auth.getSession();
  return data.session?.access_token ?? null;
}

function store(key: string) {
  return {
    get: () => { try { return localStorage.getItem(key); } catch { return null; } },
    set: (v: string | null) => { try { v === null ? localStorage.removeItem(key) : localStorage.setItem(key, v); } catch { /* private mode */ } },
  };
}

/** Anonymous per-browser id: gives visitors their own scratch space in demo mode. */
export const clientId = (() => {
  const s = store("cw.cid");
  let v = s.get();
  if (!v) {
    v = (crypto.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`).replace(/[^A-Za-z0-9-]/g, "");
    s.set(v);
  }
  return v;
})();

/** Data mode is chosen per browser (not server-wide): "demo" | "live" | null (= server default). */
export const dataMode = store("cw.mode") as { get: () => "demo" | "live" | null; set: (v: "demo" | "live" | null) => void };
/** Remember what to do after a magic-link round trip (e.g. switch to live data). */
export const afterLogin = store("cw.afterLogin");

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { Session } from "@supabase/supabase-js";
import { toast } from "sonner";
import { api, type Me } from "./api";
import { afterLogin, authEnabled, dataMode, supabase } from "./session";
import { useApp } from "./store";

interface AuthCtx {
  enabled: boolean;
  session: Session | null;
  email: string | null;
  me: Me | undefined;
  loginOpen: string | null;               // reason shown in the sign-in dialog, null = closed
  openLogin: (reason?: string, then?: "live") => void;
  closeLogin: () => void;
  signInEmail: (email: string) => Promise<void>;
  signInGoogle: () => Promise<void>;
  signOut: () => Promise<void>;
  /** Switch this browser between demo and live data; live needs sign-in when auth is on. */
  switchMode: (demo: boolean) => Promise<void>;
}

const Ctx = createContext<AuthCtx | null>(null);
const redirect = () => `${window.location.origin}${window.location.pathname}`;

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const app = useApp();
  const [session, setSession] = useState<Session | null>(null);
  const [loginOpen, setLoginOpen] = useState<string | null>(null);
  const me = useQuery({ queryKey: ["me", session?.user.id ?? "anon"], queryFn: api.me, staleTime: 60_000, retry: 0 });

  const applyMode = useCallback(async (m: "demo" | "live", quiet = false) => {
    dataMode.set(m);
    app.clearJobs();
    await qc.invalidateQueries();
    if (!quiet && m === "live") toast.success("실데이터(SEC 공시)로 전환했습니다.");
  }, [qc, app]);

  useEffect(() => {
    if (!supabase) return;
    supabase.auth.getSession().then(({ data }) => setSession(data.session));
    const { data } = supabase.auth.onAuthStateChange((event, s) => {
      setSession(s);
      if (event === "SIGNED_IN") {
        setLoginOpen(null);
        const next = afterLogin.get();
        afterLogin.set(null);
        if (next === "live") applyMode("live", true);
        else qc.invalidateQueries();
        toast.success(`${s?.user.email ?? "계정"}으로 로그인했습니다.`);
      } else if (event === "SIGNED_OUT") {
        app.clearJobs();
        qc.invalidateQueries();
      }
    });
    return () => data.subscription.unsubscribe();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const openLogin = useCallback((reason?: string, then?: "live") => {
    afterLogin.set(then ?? null);
    setLoginOpen(reason || "보유 종목을 저장하고 실데이터로 분석하려면 로그인하세요.");
  }, []);

  const value = useMemo<AuthCtx>(() => ({
    enabled: authEnabled,
    session,
    email: session?.user.email ?? null,
    me: me.data,
    loginOpen,
    openLogin,
    closeLogin: () => { afterLogin.set(null); setLoginOpen(null); },
    signInEmail: async (email: string) => {
      if (!supabase) return;
      const { error } = await supabase.auth.signInWithOtp({ email, options: { emailRedirectTo: redirect(), shouldCreateUser: true } });
      if (error) throw error;
    },
    signInGoogle: async () => {
      if (!supabase) return;
      const { error } = await supabase.auth.signInWithOAuth({ provider: "google", options: { redirectTo: redirect() } });
      if (error) throw error;
    },
    signOut: async () => {
      await supabase?.auth.signOut();
      toast.success("로그아웃했습니다.");
    },
    switchMode: async (demo: boolean) => {
      if (!demo && authEnabled && !session) {
        openLogin("로그인하면 다른 기기에서도 같은 보유 종목을 볼 수 있습니다.", "live");
        return;
      }
      await applyMode(demo ? "demo" : "live");
    },
  }), [session, me.data, loginOpen, openLogin, applyMode]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth() {
  const c = useContext(Ctx);
  if (!c) throw new Error("AuthProvider missing");
  return c;
}

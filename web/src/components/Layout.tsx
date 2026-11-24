import { useEffect, useRef, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Eye, EyeOff, LogOut, MonitorPlay, Search, Sparkles, UserRound } from "lucide-react";
import { toast } from "sonner";
import { API_URL, api, ownerKey } from "../lib/api";
import { useApp } from "../lib/store";
import { useAuth } from "../lib/auth";
import { C } from "../lib/format";
import { Modal, Switch } from "./ui";
import CommandPalette from "./CommandPalette";
import JobsDock from "./JobsDock";
import Tour from "./Tour";
import ConnectToss from "./ConnectToss";
import ErrorBoundary from "./ErrorBoundary";
import LoginDialog from "./LoginDialog";
import ImportHoldings from "./ImportHoldings";

/** Signed-in: avatar + menu. Signed-out (with sign-in configured): a login button. */
function AccountMenu() {
  const a = useAuth();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const close = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);
  if (!a.enabled) return null;
  if (!a.session) return <button className="tb-login" onClick={() => a.openLogin()}>로그인</button>;
  const email = a.email || "";
  return (
    <div className="pop-wrap" ref={ref}>
      <button className="tb-icon" aria-expanded={open} aria-label="내 계정" title={email} onClick={() => setOpen(!open)}>
        <span className="avatar">{(email[0] || "?").toUpperCase()}</span>
      </button>
      {open && (
        <div className="popover menu" role="menu">
          <div className="who"><b className="small" style={{ wordBreak: "break-all" }}>{email}</b>
            <div className="xs muted">{a.me?.owner ? "운영자 · 토스증권 연동 가능" : "개인 계정 · 보유 종목 직접 입력"}</div></div>
          <NavLink to="/account" role="menuitem" onClick={() => setOpen(false)}><UserRound size={16} />내 계정 · 데이터 관리</NavLink>
          <button role="menuitem" onClick={() => { setOpen(false); a.signOut(); }}><LogOut size={16} />로그아웃</button>
        </div>
      )}
    </div>
  );
}

const NAV = [
  { to: "/", label: "주요 종목", end: true },
  { to: "/portfolio", label: "내 포트폴리오" },
  { to: "/company", label: "종목" },
  { to: "/transcript", label: "원문 넣기" },
  { to: "/ask", label: "AI에게 묻기" },
  { to: "/method", label: "판정 방법" },
];

function Logo() {
  return (
    <svg width="26" height="26" viewBox="0 0 32 32" aria-hidden>
      <circle cx="16" cy="16" r="12" fill="none" stroke={C.light} strokeWidth="2.5" />
      <rect x="9" y="12.5" width="14" height="7" rx="1.5" fill={C.light} opacity=".5" />
      <circle cx="19.5" cy="16" r="3" fill="#fff" />
    </svg>
  );
}

/** One dot summarising backend / data / broker / AI health; details in a popover. */
function StatusDot() {
  const health = useQuery({ queryKey: ["health"], queryFn: api.health, refetchInterval: 60_000, retry: 1 });
  const broker = useQuery({ queryKey: ["broker"], queryFn: api.brokerStatus, retry: 0 });
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const close = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);
  const h = health.data;
  const demo = h?.mode === "demo";
  const rows: [string, boolean | null | undefined][] = [
    [health.isError ? "백엔드 연결 실패" : h ? "백엔드 연결됨" : "백엔드 확인 중", health.isError ? false : h ? true : null],
    [demo ? "데이터: 데모(가상 기업)" : `SEC EDGAR ${h?.sec_reachable ? "응답" : h?.sec_reachable === false ? "연결 실패" : "확인 중"}`, demo ? true : h?.sec_reachable],
    broker.data?.available === false
      ? ["토스증권: 운영자 계정 전용 · 직접 입력 사용", true]
      : [`토스증권 ${broker.data?.demo ? "데모 계좌" : broker.data?.connected ? "연결됨" : broker.data?.configured ? "확인 필요" : "미연결"}`, broker.data?.demo || broker.data?.connected ? true : broker.data?.configured ? null : false],
    [`AI: ${h?.llm ?? "–"}`, h?.llm_enabled ? true : null],
  ];
  const worst = rows.some(([, ok]) => ok === false) ? false : rows.some(([, ok]) => ok === null) ? null : true;
  const color = (ok: boolean | null | undefined) => (ok ? "#4ADE80" : ok === false ? "#F87171" : "#FBBF24");
  return (
    <div className="pop-wrap" ref={ref}>
      <button className="tb-icon" aria-expanded={open} aria-label="연결 상태" onClick={() => setOpen(!open)} title="연결 상태">
        <i className="dot" style={{ background: color(worst), margin: 0, width: 10, height: 10 }} />
      </button>
      {open && (
        <div className="popover" role="dialog" aria-label="연결 상태">
          {rows.map(([label, ok]) => <div key={label} className="row" style={{ gap: 0 }}><i className="dot" style={{ background: color(ok) }} />{label}</div>)}
          <a className="xs" href={`${API_URL}/docs`} target="_blank" rel="noreferrer">API 문서 (Swagger UI)</a>
        </div>
      )}
    </div>
  );
}

export default function Layout() {
  const qc = useQueryClient();
  const app = useApp();
  const auth = useAuth();
  const loc = useLocation();
  const nav = useNavigate();
  const health = useQuery({ queryKey: ["health"], queryFn: api.health, refetchInterval: 60_000, retry: 1 });
  const port = useQuery({ queryKey: ["portfolio"], queryFn: api.portfolio });
  const [keyOpen, setKeyOpen] = useState(false);
  const [keyVal, setKeyVal] = useState(ownerKey.get());
  const mode = health.data?.mode;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); app.setPaletteOpen(true); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [app]);

  useEffect(() => {  // first visit: offer the guided tour once
    if (health.data && !localStorage.getItem("gl.toured")) { localStorage.setItem("gl.toured", "1"); setTimeout(() => app.setTour(true), 900); }
  }, [health.data]); // eslint-disable-line react-hooks/exhaustive-deps

  const switchMode = auth.switchMode;

  return (
    <div className="app">
      <header className="topbar">
        <div className="topbar-in">
          <NavLink to="/" className="brand" aria-label="CallWatch 홈"><Logo /><b>CallWatch</b></NavLink>
          <nav className="tabs-top" aria-label="주 메뉴" data-tour="nav">
            {NAV.map((n) => <NavLink key={n.to} to={n.to} end={n.end}>{n.label}</NavLink>)}
          </nav>
          <div className="tb-right">
            <button className="tb-search" onClick={() => app.setPaletteOpen(true)} data-tour="palette" aria-label="종목·메뉴 검색 (Ctrl+K)">
              <Search size={15} /><span className="hide-m">검색</span><kbd>⌘K</kbd>
            </button>
            <Switch checked={mode === "demo"} onChange={switchMode} label="데모" title="가상 기업 4곳의 합성 데이터로 전 기능을 체험합니다" />
            <button className="tb-icon" aria-pressed={app.masked} onClick={() => app.setMasked(!app.masked)}
              title={app.masked ? "금액 보이기" : "금액 가리기 (발표·화면 공유용)"} aria-label="금액 가리기" data-tour="privacy">
              {app.masked ? <EyeOff size={17} /> : <Eye size={17} />}
            </button>
            <StatusDot />
            <button className="tb-icon hide-m" onClick={() => app.setTour(true)} title="화면 둘러보기" aria-label="화면 둘러보기"><Sparkles size={17} /></button>
            <button className="tb-present" onClick={() => nav("/present")} data-tour="present"><MonitorPlay size={15} /><span className="hide-m">발표 모드</span></button>
            <AccountMenu />
          </div>
        </div>
      </header>

      <main className="content" id="main">
        {mode === "demo" && !loc.pathname.startsWith("/company") && !loc.pathname.startsWith("/present") && (
          <div className="banner" role="note">
            <Sparkles size={18} color={C.dark} style={{ flex: "none", marginTop: 2 }} />
            <div>지금은 <b>가상 기업 4곳의 합성 데이터</b>로 보고 있습니다. 실제 SEC 공시로 보려면{" "}
              <button className="linklike" onClick={() => auth.switchMode(false)}>실데이터로 돌아가기</button>.</div>
          </div>
        )}
        <ErrorBoundary resetKey={loc.pathname}><Outlet /></ErrorBoundary>
        <div className="foot">CallWatch는 공시 정보를 정리·대조하는 리서치 보조 도구이며 투자 권유가 아닙니다. 판정은 SEC XBRL(GAAP) 수치 기준이며,
          중요한 판단 전에는 공시 원문을 확인하세요. 토스증권 연동은 조회 전용이며 주문 기능을 쓰지 않습니다.</div>
      </main>

      {app.paletteOpen && <CommandPalette onClose={() => app.setPaletteOpen(false)} switchMode={switchMode} mode={mode} />}
      {app.connectOpen && <ConnectToss onClose={() => app.setConnectOpen(false)} />}
      {app.tour && <Tour onClose={() => app.setTour(false)} />}
      {app.importOpen && <ImportHoldings current={port.data || []} onClose={() => app.setImportOpen(false)} />}
      <LoginDialog />
      <JobsDock />
      {keyOpen && (
        <Modal title="소유자 키" onClose={() => setKeyOpen(false)} width={460} footer={<>
          <button className="btn" onClick={() => { ownerKey.set(""); setKeyVal(""); qc.invalidateQueries(); setKeyOpen(false); }}>지우기</button>
          <button className="btn primary" onClick={() => { ownerKey.set(keyVal.trim()); qc.invalidateQueries(); setKeyOpen(false); toast.success("소유자 키를 적용했습니다."); }}>적용</button></>}>
          <p className="muted" style={{ margin: 0 }}>배포된 서버에서 내 계좌 금액과 토스증권 동기화는 소유자만 볼 수 있습니다. 서버의 OWNER_KEY 값을 입력하세요. 이 브라우저 탭을 닫으면 지워집니다.</p>
          <input className="input" type="password" value={keyVal} onChange={(e) => setKeyVal(e.target.value)} placeholder="OWNER_KEY" autoComplete="off" />
        </Modal>
      )}
    </div>
  );
}

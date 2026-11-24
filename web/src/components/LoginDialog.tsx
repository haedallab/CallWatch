import { useState } from "react";
import { Loader2, MailCheck, ShieldCheck } from "lucide-react";
import { useAuth } from "../lib/auth";
import { Modal } from "./ui";

function GoogleMark() {
  return (
    <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden>
      <path fill="#FFC107" d="M43.6 20.5H42V20H24v8h11.3C33.7 32.7 29.2 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34.1 6.1 29.3 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.4-.4-3.5z" />
      <path fill="#FF3D00" d="m6.3 14.7 6.6 4.8C14.7 15.1 19 12 24 12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34.1 6.1 29.3 4 24 4 16.3 4 9.7 8.3 6.3 14.7z" />
      <path fill="#4CAF50" d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2C29.2 35.1 26.7 36 24 36c-5.2 0-9.6-3.3-11.3-8l-6.5 5C9.5 39.6 16.2 44 24 44z" />
      <path fill="#1976D2" d="M43.6 20.5H42V20H24v8h11.3c-.8 2.2-2.2 4.2-4.1 5.6l6.2 5.2C37 39.2 44 34 44 24c0-1.3-.1-2.4-.4-3.5z" />
    </svg>
  );
}

export default function LoginDialog() {
  const a = useAuth();
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  if (!a.loginOpen) return null;

  const send = async () => {
    setBusy(true); setErr(null);
    try { await a.signInEmail(email.trim()); setSent(true); }
    catch (e) { setErr((e as Error).message || "로그인 링크를 보내지 못했습니다."); }
    finally { setBusy(false); }
  };

  return (
    <Modal title="CallWatch 로그인" onClose={a.closeLogin} width={440}>
      <p className="muted" style={{ margin: 0 }}>{a.loginOpen}</p>
      {sent ? (
        <div className="card row" style={{ alignItems: "flex-start" }}>
          <MailCheck size={22} color="var(--within)" style={{ flex: "none" }} />
          <div><b>{email}</b>로 로그인 링크를 보냈습니다.
            <div className="small muted">메일의 링크를 이 브라우저에서 열면 바로 로그인됩니다. 메일이 없으면 스팸함을 확인하세요.</div>
            <button className="btn ghost sm" style={{ marginTop: 6, paddingLeft: 0 }} onClick={() => setSent(false)}>다른 이메일로 받기</button></div>
        </div>
      ) : (
        <>
          <button className="btn lg" onClick={() => a.signInGoogle().catch((e) => setErr(e.message))}><GoogleMark />Google 계정으로 계속하기</button>
          <div className="or"><span>또는 이메일로 로그인 링크 받기</span></div>
          <form className="col" style={{ gap: 8 }} onSubmit={(e) => { e.preventDefault(); if (email.includes("@")) send(); }}>
            <label className="sr-only" htmlFor="login-email">이메일</label>
            <input id="login-email" className="input" type="email" inputMode="email" autoComplete="email" required value={email}
              onChange={(e) => setEmail(e.target.value)} placeholder="name@example.com" autoFocus />
            <button className="btn primary" type="submit" disabled={busy || !email.includes("@")}>
              {busy && <Loader2 size={16} className="spin" />}로그인 링크 받기</button>
          </form>
        </>
      )}
      {err && <div className="note" role="alert">{err}</div>}
      <div className="row xs muted" style={{ alignItems: "flex-start", flexWrap: "nowrap" }}>
        <ShieldCheck size={14} style={{ flex: "none", marginTop: 1 }} />
        <span>저장하는 정보는 이메일, 직접 입력한 보유 종목, 올린 어닝콜 원문뿐입니다. 계좌 비밀번호나 증권사 키는 받지 않으며, 계정 화면에서 언제든 모두 지울 수 있습니다.</span>
      </div>
      <button className="btn ghost" onClick={a.closeLogin}>로그인 없이 데모 계속 보기</button>
    </Modal>
  );
}

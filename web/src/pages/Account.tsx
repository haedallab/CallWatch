import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ClipboardPaste, Link2, Loader2, LogIn, LogOut, ShieldCheck, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { api, ownerKey } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useApp } from "../lib/store";
import { Modal, PageSkeleton } from "../components/ui";

export default function Account() {
  const a = useAuth();
  const app = useApp();
  const qc = useQueryClient();
  const nav = useNavigate();
  const me = useQuery({ queryKey: ["me", a.session?.user.id ?? "anon"], queryFn: api.me });
  const port = useQuery({ queryKey: ["portfolio"], queryFn: api.portfolio });
  const [confirm, setConfirm] = useState(false);
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [key, setKey] = useState("");

  if (me.isLoading) return <PageSkeleton />;
  const m = me.data;
  const signedIn = !!a.session;
  const mine = (port.data || []).filter((h) => h.source !== undefined);
  const used = m?.usage.today ?? 0;
  const limit = m?.usage.limit ?? 0;

  const wipe = async () => {
    setBusy(true);
    try {
      const r = await api.deleteMe();
      app.clearJobs();
      await qc.invalidateQueries();
      setConfirm(false); setTyped("");
      if (signedIn && r.account_deleted) { await a.signOut(); nav("/"); toast.success("계정과 저장된 데이터를 모두 지웠습니다."); }
      else toast.success("저장된 보유 종목·원문·개인 분석 결과를 지웠습니다.");
    } catch (e) { toast.error((e as Error).message); }
    finally { setBusy(false); }
  };

  return (
    <>
      <div className="page-head">
        <div>
          <h1>내 계정</h1>
          <p>로그인 정보, 내가 저장한 데이터, 오늘 쓸 수 있는 분석 횟수를 확인하고 정리합니다.</p>
        </div>
      </div>

      <div className="acct-grid">
        <section className="card col" aria-labelledby="h-who">
          <div className="card-h"><h2 id="h-who">{a.enabled ? "로그인" : "이 브라우저"}</h2></div>
          {!a.enabled ? (
            <>
              <p className="small muted" style={{ margin: 0 }}>가입 없이 쓰는 모드입니다. 내 보유 종목과 올린 원문은 이 브라우저에만 저장됩니다.</p>
              {m?.operator ? (
                <div className="row"><span className="tag">운영자</span><button className="btn sm" onClick={() => { ownerKey.set(""); qc.invalidateQueries(); }}>운영자 모드 끄기</button></div>
              ) : (
                <details className="xs owner-key">
                  <summary>운영자 키 입력</summary>
                  <form className="row" style={{ marginTop: 6 }} onSubmit={(e) => { e.preventDefault(); ownerKey.set(key.trim()); setKey(""); qc.invalidateQueries(); }}>
                    <input className="input" style={{ width: 220, height: 32 }} type="password" value={key} onChange={(e) => setKey(e.target.value)} placeholder="OWNER_KEY" autoComplete="off" aria-label="운영자 키" />
                    <button className="btn sm" type="submit">확인</button>
                  </form>
                </details>
              )}
            </>
          ) : signedIn ? (
            <>
              <dl className="kv">
                <dt>이메일</dt><dd><b>{a.email}</b></dd>
                <dt>로그인 방법</dt><dd>{a.session?.user.app_metadata?.provider === "google" ? "Google" : "이메일 링크"}</dd>
                <dt>권한</dt><dd>{m?.owner ? <span className="tag">운영자 · 토스증권 연동</span> : <span className="tag">개인 계정</span>}</dd>
              </dl>
              <button className="btn" style={{ alignSelf: "flex-start" }} onClick={() => a.signOut().then(() => nav("/"))}><LogOut size={16} />로그아웃</button>
            </>
          ) : (
            <>
              <p className="small muted" style={{ margin: 0 }}>지금은 로그인하지 않은 상태입니다. 넣은 종목은 이 브라우저에만 저장됩니다.</p>
              <button className="btn primary" style={{ alignSelf: "flex-start" }} onClick={() => a.openLogin(undefined, "live")}><LogIn size={16} />로그인하고 내 종목 분석하기</button>
            </>
          )}
        </section>

        <section className="card col" aria-labelledby="h-hold">
          <div className="card-h"><h2 id="h-hold">보유 종목 연결 방식</h2></div>
          {m?.toss_available ? (
            <>
              <p className="small" style={{ margin: 0 }}><b>토스증권 Open API로 가져옵니다.</b> 조회 전용이며 키는 서버 환경변수에만 있습니다.</p>
              <button className="btn" style={{ alignSelf: "flex-start" }} onClick={() => app.setConnectOpen(true)}><Link2 size={16} />토스증권에서 다시 가져오기</button>
            </>
          ) : (
            <>
              <p className="small" style={{ margin: 0 }}><b>직접 입력 · 붙여넣기</b>로 관리합니다. 토스증권 연동은 약관상 계좌 주인 본인만 쓸 수 있어 운영자 계정에만 켜져 있습니다.</p>
              <button className="btn" style={{ alignSelf: "flex-start" }} onClick={() => app.setImportOpen(true)}><ClipboardPaste size={16} />보유 종목 편집</button>
            </>
          )}
          <span className="xs muted">저장된 종목 {mine.length}개</span>
        </section>

        <section className="card col" aria-labelledby="h-use">
          <div className="card-h"><h2 id="h-use">오늘 분석 횟수</h2><span className="sub">실데이터 기준</span></div>
          {m?.owner ? <p className="small" style={{ margin: 0 }}>운영자 계정은 횟수 제한이 없습니다. 오늘 {used}회 실행.</p> : (
            <>
              <div className="row" style={{ justifyContent: "space-between" }}><b style={{ fontSize: 22 }}>{used} / {limit}회</b><span className="small muted">자정(서버 시간)에 초기화</span></div>
              <div className="usage" role="progressbar" aria-valuemin={0} aria-valuemax={limit} aria-valuenow={used}><i style={{ width: `${Math.min(100, (used / Math.max(limit, 1)) * 100)}%` }} /></div>
              <span className="xs muted">분석 실행(다시 분석 포함)만 차감됩니다. 주요 종목과 다른 사용자가 이미 분석한 종목 결과를 보는 것은 무료입니다.</span>
            </>
          )}
        </section>

        <section className="card col danger-zone" aria-labelledby="h-del">
          <div className="card-h"><h2 id="h-del">내 데이터 삭제</h2></div>
          <p className="small" style={{ margin: 0 }}>보유 종목, 내가 올린 어닝콜 원문, 그 원문으로 만든 개인 분석 결과, 사용 기록을 지웁니다.
            {signedIn && " 서버 설정에 따라 로그인 계정도 함께 삭제됩니다."} 공시만으로 만든 공용 분석 결과는 남습니다.</p>
          <button className="btn danger" style={{ alignSelf: "flex-start" }} onClick={() => setConfirm(true)} disabled={!m?.uid}><Trash2 size={16} />내 데이터 삭제</button>
        </section>
      </div>

      <div className="banner" style={{ marginTop: 16 }}>
        <ShieldCheck size={18} style={{ flex: "none", marginTop: 2 }} color="var(--dark)" />
        <div className="small">CallWatch는 계좌번호·비밀번호·증권사 API 키를 받지 않습니다. 보유 종목과 원문은 계정별로 분리해 저장하고, 다른 사용자에게 보이지 않습니다.</div>
      </div>

      {confirm && (
        <Modal title="내 데이터를 삭제할까요?" onClose={() => setConfirm(false)} width={460} footer={<>
          <button className="btn" onClick={() => setConfirm(false)}>취소</button>
          <button className="btn danger solid" disabled={typed !== "삭제" || busy} onClick={wipe}>{busy && <Loader2 size={16} className="spin" />}영구 삭제</button></>}>
          <p style={{ margin: 0 }}>보유 종목 {mine.length}개와 올린 원문, 개인 분석 결과가 지워지며 되돌릴 수 없습니다.</p>
          <div className="field"><label htmlFor="confirm-del">확인을 위해 <b>삭제</b>라고 입력하세요</label>
            <input id="confirm-del" className="input" value={typed} onChange={(e) => setTyped(e.target.value)} autoFocus autoComplete="off" /></div>
        </Modal>
      )}
    </>
  );
}

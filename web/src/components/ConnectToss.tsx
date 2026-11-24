import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, ClipboardPaste, ExternalLink, Link2, Loader2, Lock, ShieldCheck } from "lucide-react";
import clsx from "clsx";
import { api, ApiError, ownerKey, type Holding } from "../lib/api";
import { useApp } from "../lib/store";
import { krw, pct } from "../lib/format";
import { ErrorState, Modal, Skeleton } from "./ui";

const STEPS = ["연결 확인", "보유종목 가져오기", "분석 시작"];

export default function ConnectToss({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient();
  const app = useApp();
  const [step, setStep] = useState(0);
  const [seq, setSeq] = useState<number | undefined>();
  const [key, setKey] = useState("");
  const status = useQuery({ queryKey: ["broker"], queryFn: api.brokerStatus });
  const sync = useMutation({
    mutationFn: () => api.brokerSync(seq),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["portfolio"] }); qc.invalidateQueries({ queryKey: ["summary"] }); setStep(2); },
  });
  const s = status.data;
  const rows: Holding[] = sync.data?.holdings || [];
  const us = rows.filter((r) => r.analyzable);
  const ready = !!s && s.connected === true;
  const ownerOnly = s?.available === false;
  const toImport = () => { onClose(); app.setImportOpen(true); };

  if (ownerOnly) {
    return (
      <Modal title={<span className="row" style={{ gap: 8 }}><Lock size={19} color="var(--dark)" />토스증권 연동은 운영자 계정 전용입니다</span>} onClose={onClose} width={620}
        footer={<><button className="btn" onClick={onClose}>닫기</button><button className="btn primary" onClick={toImport}><ClipboardPaste size={16} />보유 종목 붙여넣기</button></>}>
        <p style={{ margin: 0 }}>CallWatch 서버의 토스증권 연결은 <b>서비스 운영자 본인 계좌</b>에만 켜 두었습니다. 다른 사용자의 계좌는 연결하지 않습니다.</p>
        <div className="card col" style={{ gap: 8 }}>
          <b className="small">왜 내 계좌는 연결할 수 없나요?</b>
          <ul className="small" style={{ margin: 0, paddingLeft: 18, lineHeight: 1.8 }}>
            <li>토스증권 Open API 키는 <b>계좌 주인 한 사람</b>에게 발급되고, 받은 정보는 본인의 투자 목적으로만 쓰도록 되어 있습니다.</li>
            <li>다른 서비스가 여러 사람의 키를 받아 대신 조회하면 이 조건을 벗어나고, 키가 유출되면 계좌가 위험해집니다.</li>
            <li>여러 사용자의 계좌를 모아 보여 주는 일은 마이데이터 등 별도 인가가 필요한 영역입니다.</li>
          </ul>
        </div>
        <div className="banner"><ClipboardPaste size={18} style={{ flex: "none", marginTop: 2 }} color="var(--dark)" />
          <div><b>대신 보유 종목 표를 붙여넣으세요.</b> 토스증권 앱의 ‘내 주식’ 화면이나 엑셀에서 복사해 붙여넣으면, 미국 종목을 찾아 분석 목록을 만들어 줍니다. 계좌번호나 비밀번호는 필요 없습니다.</div></div>
        <a className="xs" href="https://developers.tossinvest.com" target="_blank" rel="noreferrer">토스증권 Open API 안내 <ExternalLink size={11} /></a>
      </Modal>
    );
  }

  const footer = step === 0 ? (
    <><button className="btn" onClick={onClose}>닫기</button>
      <button className="btn primary" disabled={!ready || sync.isPending} onClick={() => { setStep(1); sync.mutate(); }}>보유종목 가져오기</button></>
  ) : step === 1 ? (
    <button className="btn" onClick={() => setStep(0)} disabled={sync.isPending}>이전</button>
  ) : (
    <><button className="btn" onClick={onClose}>나중에 분석</button>
      <button className="btn primary" disabled={!us.length} onClick={() => { app.analyze(us.map((r) => r.ticker)); onClose(); }}>
        미국 종목 {us.length}개 분석 시작</button></>
  );

  return (
    <Modal title={<span className="row" style={{ gap: 8 }}><Link2 size={20} color="var(--dark)" />토스증권 계좌 연결</span>} onClose={onClose} footer={footer} width={780}>
      <div className="steps" aria-label="진행 단계">
        {STEPS.map((t, i) => <div key={t} className={clsx("s", i === step && "on", i < step && "done")}><i />{i + 1}. {t}</div>)}
      </div>

      {step === 0 && (
        <>
          <div className="banner"><ShieldCheck size={18} style={{ flex: "none", marginTop: 2 }} color="var(--dark)" />
            <div><b>조회 전용 연결입니다.</b> 토스증권 오픈API의 계좌·보유종목·환율 조회만 쓰고 주문 API는 호출하지 않습니다.
              API 키는 서버(Render) 환경변수에만 있고 브라우저로 전달되지 않습니다.</div></div>
          {status.isLoading && <Skeleton h={90} />}
          {status.isError && <ErrorState error={status.error} retry={() => status.refetch()} />}
          {s?.demo && <div className="card row"><CheckCircle2 color="var(--within)" /><div><b>데모 계좌에 연결됨</b><div className="small muted">가상 계좌 123•••••901 · 미국 가상 기업 4종목과 국내 종목 1개</div></div></div>}
          {s && !s.demo && !s.configured && (
            <div className="card col">
              <b>서버에 토스증권 API 키가 아직 없습니다</b>
              <ol className="small" style={{ margin: 0, paddingLeft: 18, lineHeight: 1.9 }}>
                <li>토스증권 PC 웹(WTS) 로그인 → 설정 → Open API에서 <b>client_id · client_secret</b> 발급</li>
                <li>같은 화면의 <b>허용 IP</b>에 백엔드 서버의 공인 IP 등록 (Render는 대시보드의 Outbound IP)</li>
                <li>Render 환경변수에 <code>TOSS_CLIENT_ID</code>, <code>TOSS_CLIENT_SECRET</code>, 그리고 <code>OWNER_KEY</code> 설정</li>
              </ol>
              <a className="small" href="https://developers.tossinvest.com" target="_blank" rel="noreferrer">토스증권 Open API 문서 <ExternalLink size={12} /></a>
            </div>
          )}
          {s && s.configured && !s.owner && (
            <div className="card col">
              <b>소유자 확인이 필요합니다</b>
              <span className="small muted">배포된 서비스에서 내 계좌는 소유자만 동기화할 수 있습니다. 서버의 OWNER_KEY를 입력하세요.</span>
              <div className="row"><input className="input" style={{ flex: 1 }} type="password" value={key} onChange={(e) => setKey(e.target.value)} placeholder="OWNER_KEY" />
                <button className="btn primary" onClick={() => { ownerKey.set(key.trim()); status.refetch(); }}>확인</button></div>
            </div>
          )}
          {s && !s.demo && s.configured && s.owner && s.connected === false && (
            <ErrorState error={new ApiError(400, s.error || "연결하지 못했습니다.", s.hint)} retry={() => status.refetch()} />
          )}
          {s?.accounts && s.accounts.length > 0 && (
            <div className="field"><label>가져올 계좌</label>
              <div className="col" style={{ gap: 6 }}>
                {s.accounts.map((a, i) => (
                  <label key={a.accountSeq} className="card row" style={{ padding: 12, cursor: "pointer" }}>
                    <input type="radio" name="acct" defaultChecked={i === 0} onChange={() => setSeq(a.accountSeq)} />
                    <b>{a.accountType === "BROKERAGE" ? "종합매매" : a.accountType}</b><span className="muted">{a.accountNo}</span>
                  </label>
                ))}
              </div>
            </div>
          )}
        </>
      )}

      {step === 1 && (
        sync.isPending ? <div className="col" aria-busy="true"><div className="row muted"><Loader2 size={16} className="spin" />토스증권에서 보유종목과 환율을 불러오는 중…</div>{[0, 1, 2, 3].map((i) => <Skeleton key={i} h={36} />)}</div>
          : sync.isError ? <ErrorState error={sync.error} retry={() => sync.mutate()} /> : null
      )}

      {step === 2 && sync.data && (
        <>
          <div className="row" style={{ justifyContent: "space-between" }}>
            <div><div className="muted small">평가금액</div><b style={{ fontSize: 22 }} className={clsx(app.masked && "mask")}>{krw(sync.data.summary.market_value_krw)}</b>
              <span className="small" style={{ marginLeft: 8, color: (sync.data.summary.pl_rate || 0) >= 0 ? "var(--bad)" : "var(--blue)" }}>{pct(sync.data.summary.pl_rate, 2, true)}</span></div>
            <div className="small muted">{sync.data.at} 동기화 · USD/KRW {sync.data.usd_krw?.toLocaleString() ?? "–"}</div>
          </div>
          <div className="tbl-wrap" style={{ maxHeight: 320 }}>
            <table className="tbl">
              <thead><tr><th>종목</th><th>시장</th><th>비중</th><th className="num">평가금액</th><th className="num">손익률</th><th>분석</th></tr></thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.ticker}>
                    <td><b>{r.ticker}</b> <span className="muted small">{r.name}</span></td>
                    <td>{r.market}</td>
                    <td><div className="row" style={{ gap: 8 }}><div className="wbar"><i style={{ width: `${(r.weight || 0) * 100}%` }} /></div><span className="small">{pct(r.weight, 1)}</span></div></td>
                    <td className={clsx("num", app.masked && "mask")}>{krw(r.value_krw)}</td>
                    <td className="num" style={{ color: (r.pl_rate || 0) >= 0 ? "var(--bad)" : "var(--blue)" }}>{pct(r.pl_rate, 1, true)}</td>
                    <td>{r.analyzable ? <span className="tag">분석 대상</span> : <span className="tag warn" title="미국 SEC 공시 대상이 아닙니다">제외 · 국내</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="small muted" style={{ margin: 0 }}>국내 종목은 SEC 공시가 없어 이번 분석에서 빠지고 비중 표시에만 쓰입니다. 등락률 색은 국내 관례(상승 빨강, 하락 파랑)를 따릅니다.</p>
        </>
      )}
    </Modal>
  );
}


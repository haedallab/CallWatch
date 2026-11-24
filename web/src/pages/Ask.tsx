import { Fragment, useEffect, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Bot, Copy, Send, Trash2, User } from "lucide-react";
import { toast } from "sonner";
import { api, type Citation, type QAResponse } from "../lib/api";
import { Drawer, Empty, ErrorState } from "../components/ui";

const SUGGEST = ["다음 분기 매출 가이던스는 얼마이고 지난 분기엔 지켰나요?", "가이던스를 가장 크게 벗어난 항목은?", "매출총이익률 전망은 어떻게 바뀌어 왔나요?", "설비투자(CapEx) 계획은 순항 중인가요?"];
interface Msg { q: string; a?: QAResponse }

export default function Ask() {
  const port = useQuery({ queryKey: ["portfolio"], queryFn: api.portfolio });
  const opts = (port.data || []).filter((h) => h.analyzable !== false).map((h) => h.ticker);
  const [ticker, setTicker] = useState("");
  const t = ticker || opts[0] || "";
  const rep = useQuery({ queryKey: ["report", t], queryFn: () => api.report(t), enabled: !!t, retry: false });
  const [hist, setHist] = useState<Record<string, Msg[]>>({});
  const [q, setQ] = useState("");
  const [cite, setCite] = useState<Citation | null>(null);
  const end = useRef<HTMLDivElement>(null);
  const msgs = hist[t] || [];
  const ask = useMutation({
    mutationFn: (question: string) => api.qa(t, question),
    onMutate: (question) => setHist((h) => ({ ...h, [t]: [...(h[t] || []), { q: question }] })),
    onSuccess: (a) => setHist((h) => { const m = [...(h[t] || [])]; m[m.length - 1] = { ...m[m.length - 1], a }; return { ...h, [t]: m }; }),
    onError: () => setHist((h) => ({ ...h, [t]: (h[t] || []).slice(0, -1) })),
  });
  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [msgs.length, ask.isPending]);
  const send = (s: string) => { if (s.trim() && !ask.isPending) { ask.mutate(s.trim()); setQ(""); } };

  return (
    <>
      <div className="page-head"><div><h1>AI에게 묻기</h1><p>선택한 종목의 보도자료·트랜스크립트·10-Q MD&A와 정렬 결과표만 근거로 답합니다. 번호를 누르면 근거 원문이 열립니다.</p></div>
        <select className="select" style={{ width: 200 }} value={t} onChange={(e) => setTicker(e.target.value)} aria-label="종목">{opts.map((o) => <option key={o}>{o}</option>)}</select></div>
      {!opts.length ? <Empty title="먼저 보유 종목을 등록하세요" body="분석이 끝난 종목의 문서만 검색 대상이 됩니다." />
        : rep.isError ? <Empty title={`${t}은(는) 아직 분석 전입니다`} body="종목 상세에서 분석을 실행하면 질문할 수 있습니다." /> : (
          <section className="card col" style={{ minHeight: 420 }}>
            <div className="chat" aria-live="polite">
              {!msgs.length && <p className="muted">예시 질문을 누르거나 아래에 직접 입력하세요.</p>}
              {msgs.map((m, i) => (
                <Fragment key={i}>
                  <div className="msg user"><div className="av"><User size={16} /></div><div className="bubble">{m.q}</div></div>
                  <div className="msg ai"><div className="av"><Bot size={16} /></div>
                    <div className="bubble">
                      {m.a ? <Answer a={m.a} onCite={setCite} /> : <span className="muted">근거 문서를 찾고 답을 쓰는 중…</span>}
                    </div>
                  </div>
                </Fragment>
              ))}
              <div ref={end} />
            </div>
            {ask.isError && <ErrorState error={ask.error} retry={() => send(msgs[msgs.length - 1]?.q || "")} />}
            <div className="row" style={{ gap: 6 }}>{SUGGEST.map((s) => <button key={s} className="chip" onClick={() => send(s)} disabled={ask.isPending}>{s}</button>)}</div>
            <form className="row" style={{ flexWrap: "nowrap" }} onSubmit={(e) => { e.preventDefault(); send(q); }}>
              <input className="input" value={q} onChange={(e) => setQ(e.target.value)} placeholder={`${t}에 대해 질문하기`} aria-label="질문" />
              <button className="btn primary" disabled={!q.trim() || ask.isPending}><Send size={15} />보내기</button>
              {msgs.length > 0 && <button type="button" className="icon-btn" aria-label="대화 지우기" onClick={() => setHist((h) => ({ ...h, [t]: [] }))}><Trash2 size={16} /></button>}
            </form>
          </section>
        )}
      {cite && (
        <Drawer title={`${cite.source} · ${cite.date || ""}`} onClose={() => setCite(null)}
          actions={cite.url?.startsWith("http") ? <a className="btn sm" href={cite.url} target="_blank" rel="noreferrer">SEC 원문</a> : undefined}>
          <div className="doc">{cite.text}</div>
        </Drawer>
      )}
    </>
  );
}

function Answer({ a, onCite }: { a: QAResponse; onCite: (c: Citation) => void }) {
  const parts = a.answer.split(/(\[\d+\])/g);
  const mode = { llm: "AI 생성 답변", extractive: "원문 발췌 (LLM 키 없음)", empty: "근거 없음" }[a.mode];
  return (
    <>
      <div>{parts.map((p, i) => {
        const m = p.match(/^\[(\d+)\]$/);
        const c = m ? a.citations[Number(m[1]) - 1] : undefined;
        return c ? <button key={i} className="cite" onClick={() => onCite(c)} title={c.source}>{m![1]}</button> : <Fragment key={i}>{p}</Fragment>;
      })}</div>
      <div className="row xs muted" style={{ marginTop: 10, gap: 8 }}>
        <span>{mode} · {a.latency_ms}ms</span>
        {a.citations.map((c, i) => <button key={i} className="chip" style={{ height: 26 }} onClick={() => onCite(c)}>[{i + 1}] {c.source}</button>)}
        <button className="icon-btn" style={{ width: 26, height: 26 }} aria-label="답변 복사" onClick={() => { navigator.clipboard?.writeText(a.answer); toast.success("답변을 복사했습니다."); }}><Copy size={13} /></button>
      </div>
    </>
  );
}

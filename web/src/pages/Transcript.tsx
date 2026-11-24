import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileUp, Save, Search, Trash2, Wand2 } from "lucide-react";
import { toast } from "sonner";
import { api } from "../lib/api";
import { useApp } from "../lib/store";
import { basisKo, fmtRange, shortMetric } from "../lib/format";
import { Empty, ErrorState, Highlighted, Switch } from "../components/ui";

const SAMPLE = `Operator: Welcome to the third quarter earnings call.

Chief Financial Officer: Revenue for the quarter was $4.8 billion, up 12% year over year.
Turning to the outlook, for the fourth quarter we expect revenue to be between $5.0 billion and $5.2 billion.
We expect non-GAAP gross margin of 61% to 62%, and GAAP operating expenses of approximately $1.1 billion.
For the full year 2026, we now expect revenue growth of 14% to 15%, and we plan capital expenditures of approximately $900 million.
In the second half of next year we see margins expanding further.

Question-and-Answer Session

Analyst: Could you talk about pricing?
Chief Executive Officer: Pricing remains stable. We expect adjusted EPS of $1.45 to $1.50 for the fourth quarter.`;

export default function Transcript() {
  const app = useApp();
  const qc = useQueryClient();
  const port = useQuery({ queryKey: ["portfolio"], queryFn: api.portfolio });
  const opts = (port.data || []).filter((h) => h.analyzable !== false).map((h) => h.ticker);
  const [ticker, setTicker] = useState("");
  const t = ticker || opts[0] || "";
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10));
  const [text, setText] = useState("");
  const [drag, setDrag] = useState(false);
  const ex = useMutation({ mutationFn: () => api.extract(text, t || "TEMP", date, app.useLlm) });
  const saved = useQuery({ queryKey: ["tr", t, "list"], queryFn: () => api.transcripts(t), enabled: !!t });
  const save = useMutation({
    mutationFn: () => api.saveTranscript(t, date, text),
    onSuccess: (r) => { toast.success(`원문을 저장했습니다 · 가이던스 ${r.n_guidance}건`, { description: "이 종목을 다시 분석해 실적과 정렬합니다." }); qc.invalidateQueries({ queryKey: ["tr"] }); app.analyze([t]); },
  });
  const readFile = (f?: File) => f && f.text().then((s) => { setText(s); toast.message(`${f.name}을(를) 불러왔습니다.`); });
  const items = ex.data?.items || [];

  return (
    <>
      <div className="page-head"><div><h1>어닝콜 원문 넣기</h1>
        <p>보도자료에 없는 ‘말로 한 가이던스’를 잡아냅니다. 콜 트랜스크립트를 넣으면 전망 문장을 찾아 표시하고, 저장하면 SEC 실적과 함께 정렬됩니다.</p></div></div>
      <section className="card col">
        <div className="row">
          <div className="field" style={{ width: 200 }}><label htmlFor="t">종목</label>
            <select id="t" className="select" value={t} onChange={(e) => setTicker(e.target.value)}>{opts.map((o) => <option key={o}>{o}</option>)}{!opts.length && <option value="">종목 없음</option>}</select></div>
          <div className="field" style={{ width: 180 }}><label htmlFor="d">콜 날짜</label><input id="d" type="date" className="input" value={date} max={new Date().toISOString().slice(0, 10)} onChange={(e) => setDate(e.target.value)} /></div>
          <div style={{ flex: 1 }} />
          <button className="btn" onClick={() => setText(SAMPLE)}><Wand2 size={15} />예시 원문 채우기</button>
          <label className="btn"><FileUp size={15} />.txt 열기<input type="file" accept=".txt,text/plain" hidden onChange={(e) => readFile(e.target.files?.[0])} /></label>
        </div>
        <div onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)}
          onDrop={(e) => { e.preventDefault(); setDrag(false); readFile(e.dataTransfer.files?.[0]); }}
          style={{ outline: drag ? `2px dashed var(--blue)` : undefined, borderRadius: 8 }}>
          <textarea className="input" rows={11} value={text} onChange={(e) => setText(e.target.value)} aria-label="트랜스크립트 원문"
            placeholder="영문 트랜스크립트를 붙여넣거나 .txt 파일을 여기로 끌어다 놓으세요." />
        </div>
        <div className="row" style={{ justifyContent: "space-between" }}>
          <Switch checked={app.useLlm} onChange={app.setUseLlm} label="AI 추출 함께 사용" title="원문에 같은 문장이 없거나 수치가 다르면 AI 결과를 버립니다" />
          <div className="row">
            <span className="xs muted">{text.length.toLocaleString()}자</span>
            <button className="btn" disabled={text.length < 50 || ex.isPending} onClick={() => ex.mutate()}><Search size={15} />{ex.isPending ? "찾는 중…" : "가이던스 찾기"}</button>
            <button className="btn primary" disabled={text.length < 200 || !t || save.isPending} onClick={() => save.mutate()}><Save size={15} />저장하고 실적과 정렬</button>
          </div>
        </div>
        {ex.isError && <ErrorState error={ex.error} />}{save.isError && <ErrorState error={save.error} />}
      </section>

      {ex.data && (items.length ? (
        <div className="grid-2">
          <section className="card col"><div className="card-h" style={{ margin: 0 }}><h2>원문에서 찾은 문장</h2><span className="sub">{ex.data.llm_used ? "규칙 + AI" : "규칙 기반"}</span></div>
            <div className="doc"><Highlighted text={text} spans={items.map((i) => ({ start: i.span[0], end: i.span[1], tag: shortMetric(i.metric_label), id: i.id }))} /></div></section>
          <section className="card col"><div className="card-h" style={{ margin: 0 }}><h2>구조화된 가이던스 {items.length}건</h2></div>
            <div className="tbl-wrap" style={{ border: 0 }}><table className="tbl"><thead><tr><th>지표</th><th>기준</th><th>가이던스</th><th>기간</th></tr></thead>
              <tbody>{items.map((i) => (
                <tr key={i.id}><td><b>{shortMetric(i.metric_label)}</b></td><td className="small">{basisKo(i.basis)}</td>
                  <td>{fmtRange(i.low, i.high, i.unit)}{i.kind === "growth_yoy" && <span className="tag" style={{ marginLeft: 6 }}>YoY</span>}</td>
                  <td className="small">{i.timeframe_text || (i.timeframe_assumed ? "진행 중 분기로 가정" : i.period_type)}</td></tr>
              ))}</tbody></table></div>
            <span className="xs muted">‘second half’ 같은 반기 표현과 수치 없는 전망은 판정할 수 없어 제외합니다.</span></section>
        </div>
      ) : <Empty title="수치가 있는 전망 문장을 찾지 못했습니다" body="‘expect’, ‘outlook’, ‘guidance’ 같은 표현과 금액·비율이 함께 있는 문장을 찾습니다." />)}

      {t && (
        <section className="card">
          <div className="card-h"><h2>{t}에 저장된 원문</h2></div>
          {saved.isError && <ErrorState error={saved.error} />}
          {saved.data?.length === 0 && <p className="muted small">저장된 원문이 없습니다.</p>}
          <div className="col" style={{ gap: 8 }}>
            {saved.data?.map((r) => (
              <div key={r.id} className="row" style={{ flexWrap: "nowrap", borderBottom: "1px solid var(--line)", paddingBottom: 8 }}>
                <div style={{ flex: 1 }}><b>{r.call_date}</b> <span className="xs muted">{r.source} · {r.chars.toLocaleString()}자</span><div className="xs muted">{r.preview.slice(0, 160)}…</div></div>
                {r.source === "upload" && <button className="icon-btn" aria-label="삭제" onClick={async () => { await api.deleteTranscript(r.id); saved.refetch(); toast.success("삭제했습니다."); }}><Trash2 size={16} /></button>}
              </div>
            ))}
          </div>
        </section>
      )}
    </>
  );
}

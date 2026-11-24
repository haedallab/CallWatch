import { useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ClipboardPaste, FileUp, Loader2, Plus, Search, Trash2 } from "lucide-react";
import clsx from "clsx";
import { toast } from "sonner";
import { api, ApiError, type Holding, type Preview } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useApp } from "../lib/store";
import { ErrorState, Modal, Seg } from "./ui";

type Row = Holding & { market?: string };
const SAMPLE = "AAPL 10\nNVDA\t5주\nMSFT, 3\n005930 12   (국내 종목은 표시만 하고 분석에서 제외)";

/** Enter holdings by hand: search & add, or paste a table / upload a CSV. Nothing reaches a broker. */
export default function ImportHoldings({ current, onClose }: { current: Holding[]; onClose: () => void }) {
  const qc = useQueryClient();
  const app = useApp();
  const auth = useAuth();
  const [tab, setTab] = useState<"search" | "paste">("paste");
  const [rows, setRows] = useState<Row[]>(current.filter((h) => h.source).map((h) => ({ ...h })));
  const [q, setQ] = useState("");
  const [text, setText] = useState("");
  const [over, setOver] = useState(false);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [checking, setChecking] = useState(false);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const found = useQuery({ queryKey: ["search", q], queryFn: () => api.search(q), enabled: q.trim().length >= 1, staleTime: 60_000 });
  const needLogin = auth.enabled && !auth.session && auth.me?.mode === "live";

  const upsert = (add: Row[]) => setRows((cur) => {
    const m = new Map(cur.map((r) => [r.ticker, r]));
    add.forEach((r) => m.set(r.ticker, { ...m.get(r.ticker), ...r }));
    return [...m.values()];
  });

  const check = async (t = text) => {
    if (!t.trim()) return;
    setChecking(true); setErr(null);
    try {
      const p = await api.previewPortfolio({ text: t });
      setPreview(p);
      const ok = p.rows.filter((r) => r.ok);
      upsert(ok.map((r) => ({ ticker: r.ticker, name: r.name || undefined, market: r.market, shares: r.shares ?? null, weight: null, analyzable: r.analyzable })));
      if (ok.length) toast.success(`${ok.length}개 종목을 목록에 넣었습니다.`, { description: "아래에서 확인한 뒤 저장하세요." });
    } catch (e) { setErr(e); setPreview((e instanceof ApiError && (e.detail as Preview)?.skipped) ? { rows: [], skipped: (e.detail as Preview).skipped, n_ok: 0, n_analyzable: 0 } : null); }
    finally { setChecking(false); }
  };

  const readFile = async (f: File) => {
    if (f.size > 200_000) { toast.error("파일이 너무 큽니다 (200KB 이하 CSV/TXT)."); return; }
    const t = await f.text();
    setText(t); setTab("paste"); check(t);
  };

  const anyWeight = rows.some((r) => r.weight);
  const allWeight = rows.length > 0 && rows.every((r) => r.weight);
  const save = async () => {
    if (needLogin) { auth.openLogin("보유 종목을 저장하려면 로그인하세요. 저장한 목록은 나에게만 보입니다."); return; }
    setSaving(true); setErr(null);
    try {
      const tw = rows.reduce((a, r) => a + (r.weight || 0), 0);
      await api.savePortfolio(rows.map((r) => ({
        ticker: r.ticker, shares: r.shares ?? null, name: r.name, market: r.market,
        weight: allWeight && tw ? +((r.weight || 0) / tw).toFixed(4) : null, note: r.note || r.name || null,
      })));
      qc.invalidateQueries({ queryKey: ["portfolio"] }); qc.invalidateQueries({ queryKey: ["summary"] });
      const us = rows.filter((r) => r.analyzable !== false && r.market !== "KR").map((r) => r.ticker);
      toast.success(`보유 종목 ${rows.length}개를 저장했습니다.`, us.length ? { action: { label: `미국 ${us.length}종목 분석`, onClick: () => app.analyze(us) } } : undefined);
      onClose();
    } catch (e) { setErr(e); }
    finally { setSaving(false); }
  };

  const invalid = err instanceof ApiError ? (err.detail as { invalid?: { ticker: string; error: string }[] })?.invalid : undefined;

  return (
    <Modal title="보유 종목 입력" onClose={onClose} width={720} footer={<>
      <span className="xs muted" style={{ marginRight: "auto" }}>{rows.length}종목 · {rows.filter((r) => r.market === "KR").length ? "국내 종목은 분석 제외" : "미국 SEC 공시 기업만 분석"}</span>
      <button className="btn" onClick={onClose}>취소</button>
      <button className="btn primary" onClick={save} disabled={!rows.length || saving}>{saving && <Loader2 size={16} className="spin" />}{needLogin ? "로그인하고 저장" : "저장"}</button></>}>

      <div><Seg label="입력 방법" value={tab} onChange={setTab}
        items={[{ key: "paste", label: "붙여넣기 · CSV" }, { key: "search", label: "검색해서 추가" }]} /></div>

      {tab === "search" ? (
        <>
          <div className="field"><label htmlFor="q">티커 또는 회사명</label>
            <div style={{ position: "relative" }}>
              <Search size={15} style={{ position: "absolute", left: 11, top: 12 }} color="var(--muted)" />
              <input id="q" className="input" style={{ paddingLeft: 32 }} value={q} onChange={(e) => setQ(e.target.value)} placeholder="예: NVDA, Microsoft" autoFocus />
            </div></div>
          {q && (
            <div className="col" style={{ gap: 4, maxHeight: 190, overflow: "auto" }}>
              {found.isLoading && <span className="small muted">찾는 중…</span>}
              {found.isError && <ErrorState error={found.error} />}
              {found.data?.length === 0 && <span className="small muted">결과가 없습니다. 미국 SEC에 보고하는 상장사만 검색됩니다. 국내 종목은 ‘붙여넣기’에 6자리 코드로 넣으세요.</span>}
              {found.data?.map((f) => (
                <button key={f.ticker} className="gitem" style={{ borderLeftWidth: 1 }} disabled={rows.some((r) => r.ticker === f.ticker)}
                  onClick={() => { upsert([{ ticker: f.ticker, name: f.title, market: "US", weight: null, shares: null, analyzable: true }]); setQ(""); }}>
                  <span className="t">{f.ticker} <span className="muted small">{f.title}</span></span><Plus size={16} />
                </button>
              ))}
            </div>
          )}
        </>
      ) : (
        <>
          <div className="field">
            <label htmlFor="paste">증권사 앱·엑셀에서 복사한 표를 붙여넣으세요 <span className="muted">(한 줄에 한 종목: 티커 + 수량)</span></label>
            <textarea id="paste" className="paste" value={text} onChange={(e) => setText(e.target.value)} placeholder={SAMPLE}
              onPaste={(e) => { const t = e.clipboardData.getData("text"); if (t) { e.preventDefault(); setText(t); check(t); } }} />
          </div>
          <div className="row" style={{ flexWrap: "nowrap" }}>
            <div className={clsx("drop", over && "over")} style={{ flex: 1 }}
              onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
              onDrop={(e) => { e.preventDefault(); setOver(false); const f = e.dataTransfer.files[0]; if (f) readFile(f); }}>
              <FileUp size={16} />CSV·TXT 파일을 끌어다 놓거나
              <button className="btn sm" onClick={() => fileRef.current?.click()}>파일 고르기</button>
              <input ref={fileRef} type="file" accept=".csv,.txt,.tsv,text/csv,text/plain" hidden onChange={(e) => { const f = e.target.files?.[0]; if (f) readFile(f); e.target.value = ""; }} />
            </div>
            <button className="btn primary" disabled={!text.trim() || checking} onClick={() => check()}>
              {checking ? <Loader2 size={16} className="spin" /> : <ClipboardPaste size={16} />}확인</button>
          </div>
          {preview && (preview.skipped.length > 0 || preview.rows.some((r) => !r.ok)) && (
            <div className="note" role="status" style={{ flexDirection: "column", gap: 2 }}>
              {preview.rows.filter((r) => !r.ok).map((r) => <span key={r.ticker}><AlertTriangle size={13} /> {r.ticker}: {r.error}</span>)}
              {preview.skipped.map((s, i) => <span key={i}>{s.line ? `${s.line}번째 줄 ` : ""}“{s.text}” — {s.reason}</span>)}
            </div>
          )}
        </>
      )}

      <div className="tbl-wrap" style={{ maxHeight: 280 }}>
        <table className="tbl">
          <thead><tr><th>종목</th><th>시장</th><th className="num">수량</th><th className="num">비중 %</th><th aria-label="삭제" /></tr></thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={r.ticker} className={clsx("prev-row", r.market === "KR" && "kr")}>
                <td><b>{r.ticker}</b> <span className="muted small">{r.name || r.note}</span></td>
                <td>{r.market === "KR" ? <span className="tag warn" title="미국 SEC 공시 대상이 아니어서 분석에서 빠집니다">국내 · 제외</span> : <span className="tag">미국</span>}</td>
                <td className="num"><input className="input" style={{ width: 90, textAlign: "right" }} type="number" min={0} step="any" aria-label={`${r.ticker} 수량`}
                  value={r.shares ?? ""} onChange={(e) => { const n = [...rows]; n[i] = { ...r, shares: e.target.value === "" ? null : Number(e.target.value) }; setRows(n); }} /></td>
                <td className="num"><input className="input" style={{ width: 84, textAlign: "right" }} type="number" min={0} max={100} step={0.5} placeholder="자동" aria-label={`${r.ticker} 비중`}
                  value={r.weight ? +(r.weight * 100).toFixed(1) : ""} onChange={(e) => { const n = [...rows]; n[i] = { ...r, weight: e.target.value ? Number(e.target.value) / 100 : null }; setRows(n); }} /></td>
                <td><button className="icon-btn" aria-label={`${r.ticker} 빼기`} onClick={() => setRows(rows.filter((x) => x.ticker !== r.ticker))}><Trash2 size={16} /></button></td>
              </tr>
            ))}
            {!rows.length && <tr><td colSpan={5} className="small muted" style={{ textAlign: "center", padding: 22 }}>아직 넣은 종목이 없습니다.</td></tr>}
          </tbody>
        </table>
      </div>
      <span className="xs muted">{anyWeight && !allWeight ? "비중은 모든 종목에 넣었을 때만 쓰입니다. 일부만 넣으면 동일 비중으로 계산합니다." :
        "비중을 비워 두면 동일 비중으로 계산합니다. 모두 넣으면 합계를 100%로 환산합니다."}</span>
      {err && !invalid ? <ErrorState error={err} /> : null}
      {invalid && <div className="note"><AlertTriangle size={14} />{invalid.map((b) => `${b.ticker}: ${b.error}`).join(" / ")}</div>}
    </Modal>
  );
}

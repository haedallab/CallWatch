import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, Headphones, Save } from "lucide-react";
import { toast } from "sonner";
import { api, type CallEvent, type Calls } from "../lib/api";
import { useAuth } from "../lib/auth";

export function useCalls(ticker: string) {
  return useQuery({ queryKey: ["calls", ticker], queryFn: () => api.calls(ticker), staleTime: 5 * 60_000 });
}

const host = (u: string) => { try { return new URL(u).host.replace(/^www\./, ""); } catch { return u; } };

/** Where to hear the call behind one release: recording (plays here), webcast page, or the IR page. */
export function CallListen({ calls, date, compact }: { calls?: Calls; date: string; compact?: boolean }) {
  if (!calls) return null;
  const e: CallEvent | undefined = calls.events.find((x) => x.date === date);
  if (e?.audio_url) {
    return (
      <div className="call-listen">
        {!compact && <div className="small"><Headphones size={14} /> <b>{date} 실적발표 콜 녹음</b></div>}
        <audio controls preload="none" src={e.audio_url} style={{ width: "100%" }}>브라우저가 오디오 재생을 지원하지 않습니다.</audio>
      </div>
    );
  }
  const url = e?.webcast_url || calls.ir_url;
  if (!url) return compact ? <span className="xs muted">–</span> : null;
  const exact = !!e?.webcast_url;
  if (compact) {
    return <a className="icon-link" href={url} target="_blank" rel="noreferrer" title={exact ? "이 발표의 웹캐스트" : "회사 IR 페이지"}><Headphones size={15} />{exact ? "콜" : "IR"}</a>;
  }
  return (
    <a className="btn sm" style={{ alignSelf: "flex-start" }} href={url} target="_blank" rel="noreferrer"
      title={exact ? "보도자료에 적힌 웹캐스트 주소입니다. 다시듣기는 회사가 일정 기간만 제공합니다." : "이 발표의 웹캐스트 주소를 찾지 못해 회사 IR 페이지를 엽니다."}>
      <Headphones size={14} />{exact ? "이 발언이 나온 콜 듣기" : "IR 페이지에서 콜 찾기"} <span className="xs muted">{host(url)}</span><ExternalLink size={12} />
    </a>
  );
}

/** Operator form: IR page and per-release recording / webcast links. */
export function CallsAdmin({ ticker, calls }: { ticker: string; calls?: Calls }) {
  const auth = useAuth();
  const qc = useQueryClient();
  const [ir, setIr] = useState(calls?.ir_url || "");
  const [audio, setAudio] = useState<Record<string, string>>({});
  const [web, setWeb] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  if (!auth.me?.operator || !calls) return null;
  const save = async () => {
    setBusy(true);
    try {
      // untouched or cleared cells are skipped; a single space means "remove this link"
      const clean = (m: Record<string, string>) => Object.fromEntries(Object.entries(m).filter(([, v]) => v !== "").map(([k, v]) => [k, v.trim()]));
      await api.setCalls(ticker, { ir_url: ir.trim(), audio: clean(audio), webcast: clean(web) });
      setAudio({}); setWeb({});
      qc.invalidateQueries({ queryKey: ["calls", ticker] });
      toast.success("콜 링크를 저장했습니다.");
    } catch (e) { toast.error((e as Error).message); }
    finally { setBusy(false); }
  };
  return (
    <details className="card owner-key">
      <summary><b>운영자 · 콜 링크 등록</b> <span className="xs muted">녹음 파일 주소를 넣으면 이 화면에서 바로 재생됩니다</span></summary>
      <div className="col" style={{ gap: 8, marginTop: 10 }}>
        <div className="field"><label htmlFor="ir">IR 이벤트 페이지</label>
          <input id="ir" className="input" type="url" value={ir} onChange={(e) => setIr(e.target.value)} placeholder="https://investor.example.com/events" /></div>
        <div className="tbl-wrap" style={{ maxHeight: 300 }}>
          <table className="tbl">
            <thead><tr><th>발표일</th><th>녹음 파일 (mp3 등)</th><th>웹캐스트 페이지</th></tr></thead>
            <tbody>{calls.events.map((e) => (
              <tr key={e.date}><td className="nowrap">{e.date}</td>
                <td><input className="input" type="url" placeholder={e.audio_url || "https://…/call.mp3"} value={audio[e.date] ?? ""}
                  onChange={(x) => setAudio({ ...audio, [e.date]: x.target.value })} aria-label={`${e.date} 녹음 주소`} /></td>
                <td><input className="input" type="url" placeholder={e.webcast_url || "자동 추출 없음"} value={web[e.date] ?? ""}
                  onChange={(x) => setWeb({ ...web, [e.date]: x.target.value })} aria-label={`${e.date} 웹캐스트 주소`} /></td></tr>
            ))}</tbody>
          </table>
        </div>
        <span className="xs muted">비워 둔 칸은 바꾸지 않습니다. 등록한 링크를 지우려면 공백 하나를 넣고 저장하세요.</span>
        <button className="btn primary" style={{ alignSelf: "flex-start" }} disabled={busy} onClick={save}><Save size={15} />저장</button>
      </div>
    </details>
  );
}

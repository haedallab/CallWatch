import { useState } from "react";
import { Command } from "cmdk";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, ClipboardPaste, Eye, LineChart, Link2, Play, Sparkles } from "lucide-react";
import { api } from "../lib/api";
import { useApp } from "../lib/store";
import { Overlay } from "./ui";

export default function CommandPalette({ onClose }: { onClose: () => void }) {
  const nav = useNavigate();
  const app = useApp();
  const [q, setQ] = useState("");
  const port = useQuery({ queryKey: ["portfolio"], queryFn: api.portfolio });
  const feat = useQuery({ queryKey: ["featured"], queryFn: api.featured });
  const go = (fn: () => void) => { onClose(); fn(); };
  const tickers = (port.data || []).filter((h) => h.analyzable !== false);
  const typed = q.trim().toUpperCase();

  return (
    <Overlay onClose={onClose} label="명령 팔레트">
      <Command label="종목·메뉴 검색" loop>
        <Command.Input value={q} onValueChange={setQ} placeholder="종목 티커, 메뉴, 할 일을 입력하세요…" autoFocus />
        <Command.List>
          <Command.Empty>결과가 없습니다. 티커를 입력하고 Enter를 누르면 그 종목으로 이동합니다.</Command.Empty>
          {typed && /^[A-Z.\-]{1,6}$/.test(typed) && !tickers.some((t) => t.ticker === typed) && (
            <Command.Group heading="바로 가기">
              <Command.Item value={`go ${typed}`} onSelect={() => go(() => nav(`/company/${typed}`))}><ArrowRight size={16} />{typed} 종목 상세로 이동</Command.Item>
            </Command.Group>
          )}
          {tickers.length > 0 && (
            <Command.Group heading="내 보유 종목">
              {tickers.map((h) => (
                <Command.Item key={h.ticker} value={`${h.ticker} ${h.name || h.note || ""}`} onSelect={() => go(() => nav(`/company/${h.ticker}`))}>
                  <LineChart size={16} /><b>{h.ticker}</b><span className="muted small">{h.name || h.note}</span>
                </Command.Item>
              ))}
            </Command.Group>
          )}
          {feat.data && (
            <Command.Group heading="주요 종목">
              {feat.data.tickers.filter((t) => !tickers.some((h) => h.ticker === t)).map((t) => (
                <Command.Item key={t} value={`featured ${t} ${feat.data.names[t] || ""}`} onSelect={() => go(() => nav(`/company/${t}`))}>
                  <LineChart size={16} /><b>{t}</b><span className="muted small">{feat.data.names[t] || ""}</span>
                </Command.Item>
              ))}
            </Command.Group>
          )}
          <Command.Group heading="할 일">
            <Command.Item onSelect={() => go(() => app.setImportOpen(true))}><ClipboardPaste size={16} />보유 종목 붙여넣기 · 편집</Command.Item>
            <Command.Item onSelect={() => go(() => app.setConnectOpen(true))}><Link2 size={16} />토스증권 보유종목 가져오기</Command.Item>
            <Command.Item onSelect={() => go(() => app.analyze(tickers.map((t) => t.ticker)))} disabled={!tickers.length}><Play size={16} />보유 종목 전체 분석</Command.Item>
            <Command.Item onSelect={() => go(() => app.setMasked(!app.masked))}><Eye size={16} />{app.masked ? "금액 보이기" : "금액 가리기"}</Command.Item>
            <Command.Item onSelect={() => go(() => app.setTour(true))}><Sparkles size={16} />화면 둘러보기 시작</Command.Item>
          </Command.Group>
          <Command.Group heading="메뉴">
            {[["/", "주요 종목"], ["/portfolio", "내 포트폴리오"], ["/company", "종목 상세 분석"], ["/transcript", "어닝콜 원문 넣기"], ["/ask", "AI에게 묻기"], ["/method", "데이터·판정 방법"], ["/account", "내 계정 · 데이터 관리"]].map(([to, label]) => (
              <Command.Item key={to} onSelect={() => go(() => nav(to))}><ArrowRight size={16} />{label}</Command.Item>
            ))}
          </Command.Group>
        </Command.List>
      </Command>
    </Overlay>
  );
}

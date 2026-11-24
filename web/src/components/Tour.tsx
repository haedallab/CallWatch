import { useEffect, useLayoutEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";

const STEPS = [
  { sel: '[data-tour="score"]', path: "/", title: "1. 경영진 신뢰도", body: "주요 종목 경영진이 실적발표에서 한 약속을 SEC 실적과 맞춰 본 점수입니다. 가입 없이 바로 볼 수 있습니다." },
  { sel: '[data-tour="heat"]', path: "/", title: "2. 분기별 이행 지도", body: "칸을 누르면 그 분기의 가이던스와 실제 실적 비교로 바로 이동합니다." },
  { sel: '[data-tour="connect"]', path: "/portfolio", title: "3. 내 보유 종목 넣기", body: "증권사 앱이나 엑셀의 보유 종목 표를 붙여넣으면 미국 종목을 찾아 같은 방식으로 분석합니다. 목록은 이 브라우저에만 저장됩니다." },
  { sel: '[data-tour="privacy"]', path: "/portfolio", title: "4. 금액 가리기", body: "발표나 화면 공유 때 금액만 흐리게 가리고 비중·점수는 그대로 보여줍니다." },
  { sel: '[data-tour="palette"]', path: "/", title: "5. 어디서든 ⌘K", body: "티커를 입력해 종목으로 바로 가거나, 동기화·분석 같은 할 일을 키보드로 실행합니다." },
  { sel: '[data-tour="present"]', path: "/", title: "6. 발표 모드", body: "지금 분석 결과로 발표 슬라이드를 자동으로 만듭니다. 방향키로 넘기고, 전체 보기와 PDF 저장도 됩니다." },
];

export default function Tour({ onClose }: { onClose: () => void }) {
  const [i, setI] = useState(0);
  const [rect, setRect] = useState<DOMRect | null>(null);
  const loc = useLocation();
  const nav = useNavigate();
  const step = STEPS[i];

  useEffect(() => { if (loc.pathname !== step.path) nav(step.path); }, [i]); // eslint-disable-line react-hooks/exhaustive-deps
  useLayoutEffect(() => {
    let tries = 0;
    const find = () => {
      const el = document.querySelector(step.sel) as HTMLElement | null;
      if (el) { el.scrollIntoView({ block: "center", behavior: "smooth" }); setTimeout(() => setRect(el.getBoundingClientRect()), 250); }
      else if (tries++ < 20) setTimeout(find, 150); else setRect(null);
    };
    find();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (e.key === "ArrowRight") setI((x) => Math.min(x + 1, STEPS.length - 1));
      if (e.key === "ArrowLeft") setI((x) => Math.max(x - 1, 0));
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [i, step.sel, onClose]);

  const pad = 6;
  const top = rect ? Math.min(rect.bottom + 14, window.innerHeight - 200) : window.innerHeight / 2 - 90;
  const left = rect ? Math.min(Math.max(rect.left, 12), window.innerWidth - 352) : window.innerWidth / 2 - 170;
  return (
    <>
      {rect ? <div className="tour-hole" style={{ top: rect.top - pad, left: rect.left - pad, width: rect.width + pad * 2, height: rect.height + pad * 2 }} />
        : <div className="overlay" style={{ zIndex: 59 }} />}
      <div className="tour-card" role="dialog" aria-live="polite" aria-label="화면 둘러보기" style={{ top, left }}>
        <span className="xs muted">{i + 1} / {STEPS.length}</span>
        <h4>{step.title}</h4>
        <p>{step.body}</p>
        <div className="row" style={{ justifyContent: "flex-end", marginTop: 6 }}>
          <button className="btn sm ghost" onClick={onClose}>건너뛰기</button>
          {i > 0 && <button className="btn sm" onClick={() => setI(i - 1)}>이전</button>}
          {i < STEPS.length - 1 ? <button className="btn sm primary" onClick={() => setI(i + 1)} autoFocus>다음</button>
            : <button className="btn sm primary" onClick={onClose} autoFocus>시작하기</button>}
        </div>
      </div>
    </>
  );
}

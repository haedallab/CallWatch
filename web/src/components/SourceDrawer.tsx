import { useEffect, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { Copy, ExternalLink } from "lucide-react";
import { toast } from "sonner";
import { api } from "../lib/api";
import { Drawer, ErrorState, findQuote, Highlighted, Skeleton } from "./ui";

/** Side drawer showing the source document with the quoted sentence highlighted and scrolled into view. */
export default function SourceDrawer({ url, quote, title, text: givenText, onClose }:
  { url?: string; quote: string; title: string; text?: string; onClose: () => void }) {
  const q = useQuery({ queryKey: ["doc", url], queryFn: () => api.document(url!), enabled: !!url && !givenText, staleTime: Infinity });
  const text = givenText ?? q.data?.text ?? "";
  const box = useRef<HTMLDivElement>(null);
  const span = text ? findQuote(text, quote) : null;
  useEffect(() => {
    const m = box.current?.querySelector("mark");
    if (m) { m.scrollIntoView({ block: "center" }); m.classList.add("flash"); }
  }, [text]);
  return (
    <Drawer title={title} onClose={onClose} actions={<>
      <button className="btn sm" onClick={() => { navigator.clipboard?.writeText(quote); toast.success("문장을 복사했습니다."); }}><Copy size={14} />문장 복사</button>
      {url?.startsWith("http") && <a className="btn sm" href={url} target="_blank" rel="noreferrer"><ExternalLink size={14} />SEC 원문</a>}
    </>}>
      <div className="quote">“{quote}”</div>
      {q.isLoading && <div className="col">{[0, 1, 2, 3, 4].map((i) => <Skeleton key={i} h={18} />)}</div>}
      {q.isError && <ErrorState error={q.error} retry={() => q.refetch()} />}
      {text && (
        <>
          <span className="small muted">{span ? "강조 표시가 추출된 가이던스 문장입니다." : "문장 위치를 찾지 못해 문서 처음부터 보여줍니다."}</span>
          <div className="doc" ref={box}>
            <Highlighted text={text} spans={span ? [{ start: span[0], end: span[1], tag: "가이던스", id: "q" }] : []} active="q" />
          </div>
        </>
      )}
    </Drawer>
  );
}

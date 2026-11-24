import { useQuery } from "@tanstack/react-query";
import { api } from "./api";

/** Tickers the user can pick anywhere: their own analyzable holdings first, then the public featured list. */
export function useTickers() {
  const port = useQuery({ queryKey: ["portfolio"], queryFn: api.portfolio });
  const feat = useQuery({ queryKey: ["featured"], queryFn: api.featured });
  const mine = (port.data || []).filter((h) => h.analyzable !== false).map((h) => ({ ticker: h.ticker, name: h.name || h.note || "", group: "내 보유 종목" }));
  const featured = (feat.data?.tickers || []).filter((t) => !mine.some((m) => m.ticker === t))
    .map((t) => ({ ticker: t, name: feat.data?.names[t] || "", group: "주요 종목" }));
  return { list: [...mine, ...featured], mine, featured, isLoading: port.isLoading || feat.isLoading };
}

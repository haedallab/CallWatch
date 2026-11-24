import { useQuery } from "@tanstack/react-query";
import { API_URL, api } from "../lib/api";
import { ErrorState, Legend, Skeleton } from "../components/ui";

const FLOW = [
  ["계좌 불러오기", "토스증권 오픈API(조회 전용)로 계좌·보유종목·환율을 가져와 원화 평가금액 기준 비중을 계산합니다. 미국 SEC 제출 기업만 분석 대상입니다."],
  ["실적발표 찾기", "SEC EDGAR에서 Item 2.02가 붙은 8-K를 최근 N건 찾습니다. 이 날짜가 실적발표·어닝콜 일자입니다."],
  ["가이던스 추출", "보도자료(Ex-99.1) Outlook 섹션과 업로드한 콜 원문에서 전망 문장을 찾아 지표·범위·단위·기간·GAAP 여부로 구조화합니다. AI 결과는 원문에 같은 문장이 있고 수치가 맞을 때만 남깁니다."],
  ["기간 정렬", "10-K 회계연도로 회사별 회계 달력(52/53주, 1·6·12월 결산)을 만들어 ‘fourth quarter’, ‘Q2 FY26’, ‘full year’를 실제 기간으로 바꿉니다."],
  ["실적 대조", "XBRL companyfacts에서 그 기간의 최초 보고값을 찾습니다. Q4는 연간−3개 분기, 현금흐름 항목은 누적값 차감으로 분기화합니다."],
  ["근거·시장 반응", "해당 10-Q/10-K MD&A에서 관련 문단을 찾고, 가이던스 발표일과 결과 공개일의 초과수익률(시장모형, SPY)을 계산합니다."],
];

export default function Method() {
  const meta = useQuery({ queryKey: ["meta"], queryFn: api.meta });
  return (
    <>
      <div className="page-head"><div><h1>데이터·판정 방법</h1><p>어디서 데이터를 가져오고, 가이던스를 어떻게 실적과 맞추고, 점수를 어떻게 매기는지 모두 공개합니다.</p></div>
        <a className="btn" href={`${API_URL}/docs`} target="_blank" rel="noreferrer">API 문서 (Swagger UI)</a></div>
      <section className="card"><div className="card-h"><h2>처리 흐름</h2></div>
        <ol style={{ margin: 0, paddingLeft: 20, display: "flex", flexDirection: "column", gap: 10 }}>
          {FLOW.map(([t, d]) => <li key={t}><b>{t}</b><div className="muted small">{d}</div></li>)}
        </ol></section>
      <div className="grid-2">
        <section className="card col"><div className="card-h" style={{ margin: 0 }}><h2>판정 규칙</h2></div><Legend />
          <table className="tbl"><thead><tr><th>가이던스 형태</th><th>부합 기준</th></tr></thead><tbody>
            <tr><td>범위 ($5.0–5.2B)</td><td>하단 ≤ 실제 ≤ 상단</td></tr><tr><td>단일 금액 (approximately)</td><td>±2%</td></tr>
            <tr><td>단일 EPS</td><td>±1% 또는 ±$0.01</td></tr><tr><td>마진 (±50bp 포함)</td><td>제시 범위 또는 ±0.5%p</td></tr><tr><td>성장률 YoY</td><td>제시 범위 또는 ±1%p</td></tr></tbody></table>
          <p className="small muted" style={{ margin: 0 }}>매출·마진·이익·EPS는 높을수록, 영업비용은 낮을수록 유리, 설비투자는 중립입니다. Non-GAAP 가이던스는 GAAP XBRL과 1:1 비교가 안 되므로 참고로만 보여주고 점수에서 뺍니다.</p></section>
        <section className="card col"><div className="card-h" style={{ margin: 0 }}><h2>경영진 신뢰도 점수</h2></div>
          <div className="quote" style={{ fontWeight: 650 }}>점수 = 100 × (0.7 × 이행률 + 0.3 × (1 − 이탈 심도))</div>
          <p className="small muted" style={{ margin: 0 }}>이행률 = (부합 + 유리한 이탈) ÷ 검증 건수. 이탈 심도 = 불리한 이탈의 평균 |차이| (금액 10%, 비율 3%p에서 상한). 80 이상 높음, 60–79 보통, 60 미만 주의.
            유리한 상회가 60%를 넘으면 ‘보수적’, 불리한 이탈이 30%를 넘으면 ‘공격적’으로 분류합니다.</p></section>
      </div>
      <section className="card"><div className="card-h"><h2>데이터 출처</h2><span className="sub">현재 추출 엔진 {meta.data?.llm}</span></div>
        {meta.isLoading && <Skeleton h={140} />}{meta.isError && <ErrorState error={meta.error} retry={() => meta.refetch()} />}
        {meta.data && <table className="tbl"><thead><tr><th>출처</th><th>용도</th></tr></thead><tbody>
          <tr><td><a href="https://developers.tossinvest.com" target="_blank" rel="noreferrer">토스증권 Open API</a></td><td>계좌·보유종목·환율 (조회 전용, 허용 IP·OAuth2)</td></tr>
          {meta.data.sources.map((s) => <tr key={s.name}><td>{s.url ? <a href={s.url} target="_blank" rel="noreferrer">{s.name}</a> : s.name}</td><td>{s.use}</td></tr>)}</tbody></table>}</section>
      <section className="card"><div className="card-h"><h2>보안·개인정보</h2></div>
        <ul className="small" style={{ margin: 0, paddingLeft: 18, lineHeight: 1.9 }}>
          <li>토스증권·LLM API 키는 백엔드 환경변수에만 있고 브라우저로 전달되지 않습니다. 토스증권 토큰은 서버에서 캐시해 재발급을 최소화합니다.</li>
          <li>OWNER_KEY를 설정하면 계좌 금액과 동기화는 소유자만 볼 수 있고, 방문자에게는 비중과 점수만 보입니다. 계좌번호는 가운데를 가려 표시합니다.</li>
          <li>‘금액 가리기’는 발표·화면 공유 때 금액만 흐리게 처리합니다. 주문 API는 코드에 없습니다.</li>
          <li>원문 조회는 sec.gov 주소만 허용해 서버를 통한 임의 요청(SSRF)을 막습니다.</li>
        </ul></section>
      <section className="card"><div className="card-h"><h2>한계</h2></div>
        <ul className="small muted" style={{ margin: 0, paddingLeft: 18, lineHeight: 1.9 }}>
          <li>보도자료에 수치 전망이 없는 회사는 트랜스크립트를 넣어야 잡힙니다. 국내 종목(DART)은 아직 분석하지 않습니다.</li>
          <li>표 형식 Outlook, 세그먼트별 가이던스, ‘mid-single digits’ 같은 모호한 표현은 판정하지 않습니다.</li>
          <li>초과수익률에는 같은 날 다른 뉴스의 영향도 섞여 있어 인과로 해석할 수 없습니다.</li>
        </ul></section>
    </>
  );
}

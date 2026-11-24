"""Metric taxonomy shared by the guidance extractor and the XBRL aligner.

kind:
  amount -> USD level (revenue, capex ...)
  per_share -> USD/share (EPS)
  ratio -> derived percentage = numerator / denominator * 100
"""
from __future__ import annotations

METRICS: dict[str, dict] = {
    "revenue": {
        "label": "매출 (Revenue)",
        "kind": "amount",
        "concepts": [
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "Revenues",
            "SalesRevenueNet",
            "RevenueFromContractWithCustomerIncludingAssessedTax",
            "SalesRevenueGoodsNet",
        ],
        "keywords": ["revenue", "revenues", "net sales", "total sales", "sales", "top line", "top-line"],
    },
    "gross_margin": {
        "label": "매출총이익률 (Gross margin)",
        "kind": "ratio",
        "numerator": "gross_profit",
        "denominator": "revenue",
        "keywords": ["gross margin", "gross margins", "gross profit margin"],
    },
    "operating_margin": {
        "label": "영업이익률 (Operating margin)",
        "kind": "ratio",
        "numerator": "operating_income",
        "denominator": "revenue",
        "keywords": ["operating margin", "operating margins", "ebit margin"],
    },
    "operating_expenses": {
        "label": "영업비용 (OpEx)",
        "kind": "amount",
        "concepts": ["OperatingExpenses", "CostsAndExpenses"],
        "keywords": ["operating expenses", "opex", "operating expense"],
    },
    "operating_income": {
        "label": "영업이익 (Operating income)",
        "kind": "amount",
        "concepts": ["OperatingIncomeLoss"],
        "keywords": ["operating income", "operating profit", "income from operations"],
    },
    "net_income": {
        "label": "순이익 (Net income)",
        "kind": "amount",
        "concepts": ["NetIncomeLoss", "ProfitLoss"],
        "keywords": ["net income", "net earnings"],
    },
    "eps": {
        "label": "주당순이익 (EPS, diluted)",
        "kind": "per_share",
        "concepts": ["EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted", "EarningsPerShareBasic"],
        "keywords": ["earnings per share", "eps", "per diluted share", "per share"],
    },
    "capex": {
        "label": "설비투자 (CapEx)",
        "kind": "amount",
        "concepts": ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"],
        "keywords": ["capital expenditures", "capital expenditure", "capex", "capital spending"],
    },
    "operating_cash_flow": {
        "label": "영업현금흐름",
        "kind": "amount",
        "concepts": ["NetCashProvidedByUsedInOperatingActivities"],
        "keywords": ["operating cash flow", "cash flow from operations"],
    },
    # helpers used only as ratio components
    "gross_profit": {
        "label": "매출총이익",
        "kind": "amount",
        "concepts": ["GrossProfit"],
        "keywords": ["gross profit"],
        "helper": True,
    },
    "cost_of_revenue": {
        "label": "매출원가",
        "kind": "amount",
        "concepts": ["CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold"],
        "keywords": ["cost of revenue", "cost of sales"],
        "helper": True,
    },
}

# +1 higher is favourable, -1 lower is favourable, 0 neutral (accuracy only)
DIRECTION = {
    "revenue": 1, "gross_margin": 1, "operating_margin": 1, "operating_income": 1, "net_income": 1,
    "eps": 1, "operating_cash_flow": 1, "operating_expenses": -1, "capex": 0,
}

# metrics whose non-GAAP guidance cannot be checked 1:1 against GAAP XBRL
GAAP_SENSITIVE = {"eps", "gross_margin", "operating_margin", "operating_expenses", "operating_income", "net_income"}

# Order matters: more specific phrases first.
KEYWORD_ORDER = [
    "gross_margin", "operating_margin", "operating_expenses", "operating_income",
    "operating_cash_flow", "capex", "eps", "net_income", "gross_profit", "revenue",
]


def label(metric: str) -> str:
    return METRICS.get(metric, {}).get("label", metric)


def public_metrics() -> list[dict]:
    return [
        {"key": k, "label": v["label"], "kind": v["kind"]}
        for k, v in METRICS.items()
        if not v.get("helper")
    ]


def fmt(v: float | None, unit: str) -> str:
    """Human-friendly value: $32.5B, $412M, 74.5%, $1.23/sh."""
    if v is None:
        return "-"
    if unit == "%":
        return f"{v:.1f}%"
    if unit == "USD/share":
        return f"${v:,.2f}"
    a = abs(v)
    if a >= 1e9:
        return f"${v / 1e9:,.2f}B"
    if a >= 1e6:
        return f"${v / 1e6:,.0f}M"
    return f"${v:,.0f}"


def fmt_range(low: float, high: float, unit: str) -> str:
    return fmt(low, unit) if abs(high - low) < 1e-9 * max(abs(low), 1) else f"{fmt(low, unit)} ~ {fmt(high, unit)}"

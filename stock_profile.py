"""Stock profile classification for A-share research reports.

The classifier is intentionally deterministic and data-light. It gives the
prompts and renderers a stable lens for tailoring analysis without requiring
new external data sources.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


PROFILE_LABELS = {
    "blue_chip": "蓝筹白马",
    "cyclical": "周期股",
    "growth": "成长股",
    "loss_making": "亏损/困境股",
    "turnaround": "困境反转",
    "theme_small_cap": "题材小票",
    "high_dividend": "高股息",
    "standard": "普通个股",
}

KEY_CHECKS = {
    "blue_chip": ["ROE稳定性", "分红持续性", "估值分位", "现金流质量"],
    "cyclical": ["产品价格周期", "库存/产能", "行业景气拐点", "商品价格敏感性"],
    "growth": ["收入增速", "研发投入", "订单/渗透率", "估值容忍度"],
    "loss_making": ["现金余额", "债务压力", "PB/PS估值", "退市/持续经营风险"],
    "turnaround": ["亏损收窄", "现金流修复", "资产负债表压力", "明确反转催化"],
    "theme_small_cap": ["换手率", "题材持续性", "龙虎榜/游资", "监管与退潮风险"],
    "high_dividend": ["股息率", "派息稳定性", "现金流覆盖", "利率敏感性"],
    "standard": ["盈利趋势", "估值位置", "资金面", "风险事件"],
}


@dataclass
class StockProfile:
    """Structured stock type used by prompts and report views."""

    primary: str = "standard"
    labels: List[str] = field(default_factory=lambda: ["standard"])
    label_cn: str = PROFILE_LABELS["standard"]
    reasons: List[str] = field(default_factory=list)
    key_checks: List[str] = field(default_factory=lambda: KEY_CHECKS["standard"].copy())
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _safe_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    raw = str(value).strip().replace(",", "").replace("%", "")
    if not raw or raw in {"—", "-", "None", "nan"}:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _text_has(text: str, keywords: List[str]) -> bool:
    return any(k.lower() in text.lower() for k in keywords)


def infer_stock_profile(
    *,
    ticker: str = "",
    ticker_name: str = "",
    sector: str = "",
    metrics: Optional[Dict[str, Any]] = None,
    industry_compare: Optional[Dict[str, Any]] = None,
    text: str = "",
) -> StockProfile:
    """Infer a conservative stock profile from local structured fields."""
    metrics = metrics or {}
    industry_compare = industry_compare or {}
    haystack = " ".join([
        ticker or "",
        ticker_name or "",
        sector or "",
        str(industry_compare.get("industry_name", "")),
        text or "",
    ])

    labels: List[str] = []
    reasons: List[str] = []
    warnings: List[str] = []

    pe = _safe_float(metrics.get("pe"))
    pb = _safe_float(metrics.get("pb"))
    roe = _safe_float(metrics.get("roe"))
    eps = _safe_float(metrics.get("eps"))
    net_profit = _safe_float(metrics.get("net_profit"))
    market_cap = _safe_float(metrics.get("market_cap"))
    gross_margin = _safe_float(metrics.get("gross_margin"))
    dividend_yield = _safe_float(metrics.get("dividend_yield"))
    revenue_growth = _safe_float(
        metrics.get("revenue_growth")
        or metrics.get("revenue_yoy")
        or metrics.get("营业收入同比")
    )

    is_loss = (
        (pe is not None and pe < 0)
        or (eps is not None and eps < 0)
        or (roe is not None and roe < 0)
        or (net_profit is not None and net_profit < 0)
        or _text_has(haystack, ["亏损", "净亏损", "扭亏", "持续经营"])
    )
    if is_loss:
        labels.append("loss_making")
        reasons.append("盈利指标为负或文本显示亏损，PE估值需降权")
        warnings.append("亏损股不得以PE作为主估值锚")
        if revenue_growth is not None and revenue_growth > 0:
            labels.append("turnaround")
            reasons.append("亏损状态下收入仍增长，需验证反转质量")

    cyclical_terms = ["煤", "钢", "有色", "化工", "石油", "航运", "造纸", "水泥", "房地产", "猪", "养殖"]
    if _text_has(haystack, cyclical_terms):
        labels.append("cyclical")
        reasons.append("所属行业具有明显价格/库存周期属性")

    growth_terms = ["半导体", "芯片", "软件", "人工智能", "机器人", "算力", "创新药", "生物", "新能源", "军工"]
    if _text_has(haystack, growth_terms) or (
        revenue_growth is not None and revenue_growth >= 20
    ):
        labels.append("growth")
        reasons.append("行业或收入增速具备成长股特征")

    if dividend_yield is not None and dividend_yield >= 3.5:
        labels.append("high_dividend")
        reasons.append("股息率较高，需检查派息可持续性")

    if market_cap is not None and market_cap >= 1000:
        labels.append("blue_chip")
        reasons.append("总市值较大，按蓝筹/权重股框架评估")

    small_cap = market_cap is not None and market_cap < 80
    if small_cap and _text_has(haystack, ["概念", "题材", "涨停", "龙虎榜", "游资", "北交所"]):
        labels.append("theme_small_cap")
        reasons.append("小市值且具备题材/游资相关特征")
    elif small_cap and (gross_margin is None or gross_margin < 35):
        labels.append("theme_small_cap")
        reasons.append("小市值标的需额外关注资金博弈和流动性")

    if not labels:
        labels = ["standard"]
        reasons.append("未触发特殊类型规则，按普通个股框架评估")

    # Priority order: the first profile drives the report lens.
    priority = [
        "loss_making",
        "turnaround",
        "theme_small_cap",
        "cyclical",
        "growth",
        "high_dividend",
        "blue_chip",
        "standard",
    ]
    unique = []
    for p in priority:
        if p in labels and p not in unique:
            unique.append(p)
    primary = unique[0] if unique else "standard"

    if is_loss and pb is None:
        warnings.append("亏损股缺少PB，估值安全边际不足以判断")

    return StockProfile(
        primary=primary,
        labels=unique,
        label_cn=PROFILE_LABELS.get(primary, primary),
        reasons=reasons[:5],
        key_checks=KEY_CHECKS.get(primary, KEY_CHECKS["standard"]).copy(),
        warnings=list(dict.fromkeys(warnings))[:5],
    )


def stock_profile_prompt_block(profile: Optional[Dict[str, Any]]) -> str:
    """Render a concise prompt block for downstream agents."""
    if not profile:
        return ""
    label = profile.get("label_cn") or PROFILE_LABELS.get(profile.get("primary", ""), "")
    checks = "、".join(profile.get("key_checks") or [])
    warnings = "；".join(profile.get("warnings") or [])
    reasons = "；".join(profile.get("reasons") or [])
    parts = [
        f"【个股类型】{label or profile.get('primary', 'standard')}",
    ]
    if checks:
        parts.append(f"【必检项】{checks}")
    if reasons:
        parts.append(f"【分类依据】{reasons}")
    if warnings:
        parts.append(f"【硬性提示】{warnings}")
    return "\n".join(parts)

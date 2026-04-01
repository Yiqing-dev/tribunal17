"""
Decision Semantics Layer — centralizes all product-level Chinese labels.

Reports import from here instead of hardcoding action labels, explanations,
risk categories, and evidence-strength descriptors.
"""

from typing import Dict, Tuple


# ── Signal Emoji ────────────────────────────────────────────────────────

SIGNAL_EMOJI: Dict[str, str] = {
    "BUY": "\U0001f7e2",
    "HOLD": "\U0001f7e1",
    "SELL": "\U0001f534",
    "VETO": "\u26d4",
}

PILLAR_EMOJI: Dict[int, str] = {
    4: "\U0001f7e2",
    3: "\U0001f535",
    2: "\U0001f7e1",
    1: "\U0001f7e0",
    0: "\U0001f534",
}


def get_signal_emoji(action: str) -> str:
    """Return emoji for a signal action (e.g. BUY -> green circle)."""
    return SIGNAL_EMOJI.get(action.upper(), "\u26aa")


# ── Action Labels ────────────────────────────────────────────────────────

# (label, css_class, explanation)
ACTION_MAP: Dict[str, Tuple[str, str, str]] = {
    "BUY":  ("建议关注", "buy",  "当前研究结论偏积极，建议纳入重点观察池"),
    "HOLD": ("维持观察", "hold", "当前信号不明确，建议持续跟踪关键变量变化"),
    "SELL": ("建议回避", "sell", "多维度分析偏谨慎，建议降低关注优先级"),
    "VETO": ("风控否决", "veto", "证据链不完整或触发风控硬规则，建议暂不操作"),
}


# Softer action labels for user-facing Research-tier contexts (lineage, etc.)
# These avoid internal terms like BUY/SELL and use neutral descriptive tone.
SOFT_ACTION_MAP: Dict[str, str] = {
    "BUY":  "偏积极",
    "HOLD": "中性",
    "SELL": "偏谨慎",
    "VETO": "风控否决",
}


def get_soft_action_label(action: str) -> str:
    """Return soft/neutral Chinese label for lineage display (e.g. BUY → 偏积极)."""
    return SOFT_ACTION_MAP.get(action.upper(), action)


def get_action_label(action: str) -> str:
    """Return Chinese label for an action (e.g. BUY → 建议关注)."""
    entry = ACTION_MAP.get(action.upper())
    return entry[0] if entry else action


def get_action_class(action: str) -> str:
    """Return CSS class for an action."""
    entry = ACTION_MAP.get(action.upper())
    return entry[1] if entry else "hold"


def get_action_explanation(action: str) -> str:
    """Return Chinese explanation for an action."""
    entry = ACTION_MAP.get(action.upper())
    return entry[2] if entry else ""


# ── VETO Reason Differentiation ──────────────────────────────────────────

VETO_REASONS = {
    "risk_hard_block":       "触发风控硬规则，不建议操作",
    "evidence_insufficient": "证据链不完整，无法形成有效结论",
    "source_quality":        "数据源质量不达标，结论可靠性不足",
}


# ── Evidence Strength ────────────────────────────────────────────────────

EVIDENCE_STRENGTH_LABELS = {
    "HIGH":   "强",
    "MEDIUM": "中",
    "LOW":    "弱",
}


# ── Risk Category Chinese Labels ─────────────────────────────────────────

RISK_CATEGORY_LABELS = {
    # Core risk categories
    "concentration":        "集中度风险",
    "liquidity":            "流动性风险",
    "valuation":            "估值风险",
    "regulatory":           "政策/监管风险",
    "event":                "事件风险",
    # Capital flow
    "capital_flow":         "资金流向风险",
    "capital_outflow":      "资金净流出",
    "sector_capital_flow":  "板块资金轮动",
    "short_term_flow":      "短期资金面",
    # Earnings & fundamentals
    "earnings_uncertainty": "盈利不确定性",
    "earnings_decline":     "盈利下滑",
    "earnings_loss":        "持续亏损",
    "earnings_quality":     "盈利质量",
    # Institutional
    "institutional_exit":   "机构撤离",
    "coverage_gap":         "研报覆盖空白",
    # Structural
    "pledge_cascade":       "质押连锁风险",
    "shareholder_pledge":   "股东质押",
    "leverage_pressure":    "杠杆压力",
    "technical_weak":       "技术面偏弱",
    "negative_expected_return": "负期望收益",
    # Market & sector
    "sector_systemic":      "板块系统性风险",
    "market_breadth":       "市场宽度不足",
    "rotation_risk":        "轮动风险",
    # Deal & policy
    "deal_execution":       "交易执行风险",
    "synergy_unproven":     "协同未验证",
    "policy_timing":        "政策时点不确定",
    "geopolitical":         "地缘政治风险",
    # Support
    "tail_risk":            "尾部风险",
    "support_proximity":    "逼近支撑位",
    # Chinese passthrough
    "基本面增长":           "基本面增长放缓",
    "技术趋势":             "技术面走势偏弱",
    "宏观与流动性":         "宏观环境不确定",
    "事件风险":             "待定事件风险",
}


def get_risk_label(category: str) -> str:
    """Return Chinese label for a risk category.

    Handles compound labels like 'valuation、capital_flow' by translating
    each part separately.
    """
    if not category:
        return category
    # Direct match
    if category in RISK_CATEGORY_LABELS:
        return RISK_CATEGORY_LABELS[category]
    # Compound: split on common delimiters
    for sep in ("、", ",", "/", " "):
        if sep in category:
            parts = [p.strip() for p in category.split(sep) if p.strip()]
            translated = [RISK_CATEGORY_LABELS.get(p, p) for p in parts]
            return "、".join(translated)
    return category


def get_severity_label(severity: str) -> str:
    """Return Chinese label for a severity level."""
    return SEVERITY_LABELS.get((severity or "").lower(), severity or "")


# ── Thesis Effect Labels ─────────────────────────────────────────────────

THESIS_EFFECT_LABELS = {
    "unchanged":     "维持",
    "strengthened":  "强化",
    "strengthen":    "强化",
    "weakened":      "弱化",
    "weaken":        "弱化",
    "invalidate":    "失效",
    "invalidated":   "失效",
}


def get_thesis_label(effect: str) -> str:
    """Return Chinese label for a thesis effect."""
    return THESIS_EFFECT_LABELS.get(effect, effect or "无")


# ── Severity Labels ──────────────────────────────────────────────────────

SEVERITY_LABELS = {
    "critical": "严重",
    "high":     "高",
    "medium":   "中",
    "low":      "低",
}

SEVERITY_CSS = {
    "critical": "veto",
    "high":     "sell",
    "medium":   "hold",
    "low":      "muted",
}

# ── CSS Class Whitelist ────────────────────────────────────────────────────

_BADGE_WHITELIST = frozenset({
    "buy", "hold", "sell", "veto",
    "high", "medium", "low", "muted",
    "ok", "good", "warn", "bad",
})


def safe_badge_class(value: str, default: str = "hold") -> str:
    """Whitelist-validate a value before interpolating into a CSS class attribute."""
    v = (value or "").strip().lower()
    return v if v in _BADGE_WHITELIST else default


# ── Node Name Chinese Labels ────────────────────────────────────────────

NODE_NAME_LABELS = {
    "Macro Analyst":          "宏观分析师",
    "Market Breadth":         "市场宽度分析",
    "Sector Rotation":        "板块轮动分析",
    "Data Verification":      "数据验证",
    "Market Analyst":         "市场分析师",
    "Social Analyst":         "舆情分析师",
    "News Analyst":           "新闻分析师",
    "Fundamentals Analyst":   "基本面分析师",
    "Catalyst Agent":         "催化剂分析师",
    "Scenario Agent":         "情景分析师",
    "Bull Researcher":        "看多研究员",
    "Bear Researcher":        "看空研究员",
    "Research Manager":       "研究经理",
    "Risk Judge":             "风控审查",
    "ResearchOutput":         "研究结论",
    "Publishing Compliance":  "合规审查",
}


def get_node_label(name: str) -> str:
    """Return Chinese label for a graph node name."""
    return NODE_NAME_LABELS.get(name, name)


# ── Dimension Chinese Labels ────────────────────────────────────────────

DIMENSION_LABELS = {
    "fundamentals":  "基本面",
    "growth":        "成长性",
    "sentiment":     "市场情绪",
    "competitive":   "竞争格局",
    "valuation":     "估值",
    "cost":          "成本",
    "technicals":    "技术面",
    "macro":         "宏观",
    "policy":        "政策",
    "liquidity":     "流动性",
}


def get_dimension_label(dim: str) -> str:
    """Return Chinese label for a claim dimension."""
    return DIMENSION_LABELS.get(dim, dim)


# ── Parse Status Chinese Labels ─────────────────────────────────────────

PARSE_STATUS_LABELS = {
    "strict_ok":     "严格通过",
    "partial_ok":    "部分通过",
    "fallback_used": "回退解析",
    "failed":        "解析失败",
}


# ── Compliance Status Chinese Labels ─────────────────────────────────────

COMPLIANCE_STATUS_LABELS = {
    "allow":     "通过",
    "downgrade": "降级",
    "review":    "待审查",
    "block":     "阻止",
}


# ── Node Status Chinese Labels ──────────────────────────────────────────

NODE_STATUS_LABELS = {
    "ok":      "正常",
    "warn":    "警告",
    "error":   "异常",
    "skipped": "跳过",
}


# ── Freshness Status Chinese Labels ─────────────────────────────────────

FRESHNESS_STATUS_LABELS = {
    "FRESH": "新鲜", "fresh": "新鲜",
    "LAGGING": "滞后", "lagging": "滞后",
    "STALE": "过期", "stale": "过期",
    "UNAVAILABLE": "不可用", "unavailable": "不可用",
    "RECOVERED": "已恢复", "recovered": "已恢复",
}


# ── Audit Conclusion Labels ────────────────────────────────────────────

AUDIT_CONCLUSIONS = {
    "high":   ("高可信", "可参考研究结论，无需额外人工复核。"),
    "medium": ("中等可信", "可参考研究结论，但建议人工复核标注环节。"),
    "low":    ("低可信", "不建议仅凭快照或研究报告作判断，应先完成人工复核。"),
}


def compute_audit_conclusion(trust_signals, weakest_node=""):
    """Compute audit conclusion from trust signals.

    Returns (level, label, text) where level is high/medium/low.
    """
    if not trust_signals:
        return "low", "低可信", "无信任信号数据，无法评估可信度。"

    bad_count = sum(1 for ts in trust_signals if ts.get("status") == "bad")
    warn_count = sum(1 for ts in trust_signals if ts.get("status") == "warn")

    if bad_count >= 2:
        level = "low"
    elif bad_count >= 1 or warn_count >= 2:
        level = "medium"
    else:
        level = "high"

    label, explanation = AUDIT_CONCLUSIONS[level]
    if weakest_node and level == "medium":
        explanation = f"可参考研究结论，但建议人工复核{weakest_node}。"
    elif weakest_node and level == "low":
        explanation = f"不建议仅凭快照或研究报告作判断，应先完成人工复核（关注{weakest_node}）。"

    return level, label, explanation


# ── Internal Token Patterns (for stripping from user-facing text) ─────

# Tokens that must NEVER appear in Tier 1 or Tier 2 output.
INTERNAL_TOKEN_PREFIXES = (
    "好的", "作为", "针对", "让我", "以下是", "我将", "我会",
    "根据您的", "感谢您", "非常好",
)


# ── Tone Moderation (soften extreme bull/bear superlatives for product output) ──

TONE_MODERATION_MAP = {
    "极其": "较为",
    "极强": "较强",
    "极高": "较高",
    "极低": "较低",
    "完好无损": "基本完整",
    "质变": "显著改善",
    "足以抵御任何": "有助于抵御",
    "断崖式": "较大幅度",
    "飞跃": "明显提升",
}


# ── No-Compliance Wording ──────────────────────────────────────────────

NO_COMPLIANCE_LABEL = "未捕获独立合规轨迹，建议结合总状态判断。"


# ── Market Regime & Breadth Labels ────────────────────────────────────

REGIME_LABELS = {
    "RISK_ON":  ("进攻", "buy"),
    "NEUTRAL":  ("中性", "hold"),
    "RISK_OFF": ("防御", "sell"),
}


BREADTH_LABELS = {
    "HEALTHY":        ("健康", "buy"),
    "NARROW":         ("分化", "hold"),
    "DETERIORATING":  ("恶化", "sell"),
}


def get_regime_label(regime: str) -> str:
    """Return Chinese label for a market regime."""
    entry = REGIME_LABELS.get(regime.upper())
    return entry[0] if entry else regime


def get_regime_class(regime: str) -> str:
    """Return CSS class for a market regime."""
    entry = REGIME_LABELS.get(regime.upper())
    return entry[1] if entry else "hold"


def get_breadth_label(state: str) -> str:
    """Return Chinese label for breadth state."""
    entry = BREADTH_LABELS.get(state.upper())
    return entry[0] if entry else state


def get_breadth_class(state: str) -> str:
    """Return CSS class for breadth state."""
    entry = BREADTH_LABELS.get(state.upper())
    return entry[1] if entry else "hold"

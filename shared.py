"""Shared prompt blocks and constants reused across all agents.

All functions return plain strings with {placeholders} already filled in.
"""

# ── Output tag constants ────────────────────────────────────────────────
# Used in prompts.py (definition) and bridge.py / web_collector.py (parsing).
# Changing a tag here updates both sides automatically.

TAG_CATALYST_OUTPUT = "CATALYST_OUTPUT"
TAG_RISK_OUTPUT = "RISK_OUTPUT"
TAG_RISK_DEBATER_OUTPUT = "RISK_DEBATER_OUTPUT"
TAG_MACRO_OUTPUT = "MACRO_OUTPUT"
TAG_BREADTH_OUTPUT = "BREADTH_OUTPUT"
TAG_SECTOR_OUTPUT = "SECTOR_OUTPUT"
TAG_GLOBAL_MACRO_OUTPUT = "GLOBAL_MACRO_OUTPUT"
TAG_SYNTHESIS_OUTPUT = "SYNTHESIS_OUTPUT"
TAG_SCENARIO_OUTPUT = "SCENARIO_OUTPUT"
TAG_TRADECARD_JSON = "TRADECARD_JSON"
TAG_TRADE_PLAN_JSON = "TRADE_PLAN_JSON"
TAG_ORDER_PROPOSAL_JSON = "ORDER_PROPOSAL_JSON"

# Round delimiters for bull/bear debate merging
ROUND_1_HEADER = "=== Round 1 ==="
ROUND_2_HEADER = "=== Round 2 ==="


# ── Confidence normalization (single source of truth) ───────────────────
# ONE implementation, shared by bridge.py (parsing) AND the renderers
# (display), so confidence can never diverge by scale across code paths.
# CLAUDE.md rule #7: values >=10 are on a 0-100 scale (/100); values >1 but
# <10 are on a 1-10 scale (/10). Returns the -1.0 "not set" sentinel for
# None / boolean / negative / unparseable input (RunTrace.finalize() and
# downstream aggregators skip confidence < 0). Result is clamped to [0, 1].
_CONFIDENCE_LABELS = {
    "high": 0.8, "med": 0.5, "medium": 0.5, "low": 0.2,
    "高": 0.8, "中": 0.5, "低": 0.2,
}


def normalize_confidence_value(val) -> float:
    """Canonical confidence normalizer → [0.0, 1.0], or -1.0 sentinel."""
    if val is None:
        return -1.0
    if isinstance(val, bool):
        return -1.0  # avoid treating True/False as 1.0/0.0
    if isinstance(val, (int, float)):
        conf = float(val)
    elif isinstance(val, str):
        mapped = _CONFIDENCE_LABELS.get(val.strip().lower())
        if mapped is not None:
            return mapped
        raw = val.strip().rstrip("%")
        try:
            conf = float(raw)
        except (ValueError, TypeError):
            return -1.0
        if val.strip().endswith("%"):
            conf = conf / 100.0
    else:
        return -1.0

    if conf < 0:
        return -1.0
    # values >=10 → 0-100 scale (/100); values >1 but <10 → 1-10 scale (/10).
    if conf >= 10:
        conf = conf / 100.0
    elif conf > 1.0:
        conf = conf / 10.0
    return max(0.0, min(1.0, conf))


def mean_confidence(values, sentinel: float = -1.0) -> float:
    """Mean of confidence values, EXCLUDING the -1.0 'unset' sentinel (and any
    <0 / non-numeric). Returns ``sentinel`` when nothing real remains, so the
    result routes straight through ``format_confidence_pct`` (→ '—'). Single
    source for the sentinel-excluding confidence mean used by both the renderers
    (pool / brief / workbench) and the backend (calibration / reflection / health).
    """
    vals = [float(v) for v in values
            if isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0]
    return sum(vals) / len(vals) if vals else sentinel


# ── A-share price-limit board rules (single source of truth) ────────────
# Used for limit-up/down counting AND exchange-suffix routing, so the two
# never disagree (previously akshare used ("8","4","9"), recap used ("8","4"),
# and bare "9" wrongly classified 900xxx 上交所B股 as 北交所).
def is_bse_code(code: str) -> bool:
    """北交所 (Beijing Stock Exchange) bare code? 8xxxxx (83/87/88), 920xxx, or
    43xxxx (legacy NEEQ). Bare '9' is NOT BSE — 900xxx is a 上交所 B-share (±10%)."""
    code = str(code).strip()
    return code.startswith(("8", "43", "920"))


def limit_threshold_pct(code: str, name: str = "", *, near: bool = True) -> float:
    """A-share daily price-limit % for tagging limit-up / limit-down.

    ST/*ST ±5 · 创业板(300/301)/科创板(688/689) ±20 · 北交所 ±30 · else ±10
    (主板 and B-shares 900xxx/200xxx). ``near=True`` returns the slightly
    inside-the-limit counting threshold (4.9/19.9/29.9/9.9) that tags a stock as
    'at limit' despite float rounding; ``near=False`` returns the exact limit.
    """
    code = str(code).strip()
    if "ST" in str(name or "").upper():
        return 4.9 if near else 5.0
    if is_bse_code(code):
        return 29.9 if near else 30.0
    if code.startswith(("3", "68")):
        return 19.9 if near else 20.0
    return 9.9 if near else 10.0


# ── Risk flag canonicalization ──────────────────────────────────────────
# Maps many synonyms (中/英变体) to a small set of canonical categories.
# Used by bridge._parse_risk_manager() to de-duplicate 200+ raw labels into
# ~10 categories so downstream consumers see a stable vocabulary.
# Rationale (2026-04-13 reflection): raw risk flags proliferated to 200+
# synonyms, causing signal inflation that silently biased action → HOLD
# without improving early-warning accuracy.

_SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}

CANONICAL_RISK_FLAGS = {
    # fund_flow family
    "fund_flow": ("fund_flow", "medium"),
    "capital_flow": ("fund_flow", "medium"),
    "capital_flow_risk": ("fund_flow", "medium"),
    "capital_outflow": ("fund_flow", "high"),
    "fund_outflow": ("fund_flow", "high"),
    "短期资金面偏空": ("fund_flow", "medium"),
    "资金面偏空": ("fund_flow", "medium"),
    "资金面持续偏空": ("fund_flow", "high"),
    "资金面": ("fund_flow", "medium"),
    "资金面风险": ("fund_flow", "medium"),
    "资金流向风险": ("fund_flow", "medium"),
    "资金流出风险": ("fund_flow", "high"),
    "资金流动风险": ("fund_flow", "medium"),
    "资金面恶化": ("fund_flow", "high"),
    "资金面信息真空": ("fund_flow", "low"),
    "资金面真空": ("fund_flow", "low"),
    "资金面虚假信号": ("fund_flow", "low"),
    "资金面出货": ("fund_flow", "high"),
    "资金面游资出货": ("fund_flow", "high"),
    "资金面系统性出逃": ("fund_flow", "high"),
    "资金面系统性撤退": ("fund_flow", "high"),
    "资金持续净流出": ("fund_flow", "high"),
    "资金流入递减": ("fund_flow", "medium"),
    "资金脉冲衰减": ("fund_flow", "medium"),
    "短期资金面": ("fund_flow", "medium"),
    "主力流出": ("fund_flow", "high"),
    "主力净流出": ("fund_flow", "high"),
    "主力资金出货": ("fund_flow", "high"),
    "主力出货": ("fund_flow", "high"),
    "资金出货": ("fund_flow", "high"),
    "sector_capital_flow": ("fund_flow", "medium"),
    # valuation family
    "valuation": ("valuation", "medium"),
    "估值": ("valuation", "medium"),
    "估值风险": ("valuation", "medium"),
    "高估值": ("valuation", "high"),
    "valuation_stretch": ("valuation", "high"),
    "valuation_dislocation": ("valuation", "high"),
    "valuation_erosion": ("valuation", "medium"),
    "valuation_concern": ("valuation", "medium"),
    "valuation_ceiling": ("valuation", "medium"),
    "估值高估": ("valuation", "high"),
    "估值偏高": ("valuation", "high"),
    "估值泡沫": ("valuation", "high"),
    "估值泡沫风险": ("valuation", "high"),
    "估值争议": ("valuation", "medium"),
    "估值动态风险": ("valuation", "medium"),
    "估值失锚": ("valuation", "high"),
    "估值安全边际": ("valuation", "medium"),
    "估值安全边际不足": ("valuation", "high"),
    "PE估值偏高": ("valuation", "high"),
    "AI溢价兑现风险": ("valuation", "high"),
    "DDM利率敏感性": ("valuation", "low"),
    # catalyst family
    "催化剂": ("event_risk", "low"),
    "催化剂缺失": ("event_risk", "low"),
    "催化剂风险": ("event_risk", "medium"),
    "催化剂执行风险": ("event_risk", "medium"),
    "催化剂真空": ("event_risk", "low"),
    "催化剂真空风险": ("event_risk", "low"),
    "催化剂定性存疑": ("event_risk", "medium"),
    "前瞻性催化剂偏空": ("event_risk", "medium"),
    "catalyst_vacuum": ("event_risk", "low"),
    # sector / regime family
    "板块轮动": ("macro", "low"),
    "板块轮动不确定": ("macro", "low"),
    "板块错配风险": ("macro", "medium"),
    "板块切换": ("macro", "low"),
    "板块系统性": ("macro", "medium"),
    "板块防御失效": ("macro", "medium"),
    "sector_decoupling": ("macro", "medium"),
    "sector_systemic": ("macro", "high"),
    "sector_risk": ("macro", "medium"),
    "regime_mismatch": ("macro", "medium"),
    "RISK_OFF市场环境": ("macro", "high"),
    "市场环境": ("macro", "low"),
    "市场环境风险": ("macro", "medium"),
    "市场环境约束": ("macro", "low"),
    "市场环境逆风": ("macro", "medium"),
    "市场环境加重": ("macro", "high"),
    "市场系统性": ("macro", "high"),
    "市场系统性风险": ("macro", "high"),
    "systemic_risk_off": ("macro", "high"),
    "市场对齐": ("macro", "low"),
    "风格切换风险": ("macro", "medium"),
    # event risk family
    "earnings_event": ("event_risk", "high"),
    "annual_report": ("event_risk", "high"),
    "年报风险": ("event_risk", "high"),
    "年报披露": ("event_risk", "high"),
    "event_risk": ("event_risk", "medium"),
    "event": ("event_risk", "medium"),
    "事件风险": ("event_risk", "medium"),
    # fundamental family
    "fundamental": ("fundamental", "medium"),
    "fundamental_weakness": ("fundamental", "high"),
    "基本面": ("fundamental", "medium"),
    "基本面风险": ("fundamental", "medium"),
    "loss": ("fundamental", "high"),
    "亏损": ("fundamental", "high"),
    "亏损风险": ("fundamental", "high"),
    # technical family
    "technical": ("technical", "medium"),
    "technical_weakness": ("technical", "medium"),
    "技术面": ("technical", "medium"),
    "技术面风险": ("technical", "medium"),
    "macd_death_cross": ("technical", "medium"),
    # technical_break* family — same fact triple-counted in raw flags (research improvement #4)
    "technical_break": ("technical", "high"),
    "technical_breakdown": ("technical", "high"),
    "technical_breakdown_risk": ("technical", "high"),
    "technical_bearish": ("technical", "high"),
    "technical_weak": ("technical", "medium"),
    "技术面破位": ("technical", "high"),
    "技术面破位风险": ("technical", "high"),
    "技术面下行通道": ("technical", "high"),
    "技术面空头格局": ("technical", "high"),
    "技术面压力": ("technical", "medium"),
    "技术面临界": ("technical", "medium"),
    "技术面待确认": ("technical", "low"),
    "技术面方向待定": ("technical", "low"),
    "技术面验证": ("technical", "low"),
    "技术面赔率不对称": ("technical", "medium"),
    "技术确认缺口": ("technical", "medium"),
    "技术分析": ("technical", "low"),
    # liquidity family
    "liquidity": ("liquidity", "medium"),
    "流动性": ("liquidity", "medium"),
    "流动性风险": ("liquidity", "medium"),
    "low_liquidity": ("liquidity", "high"),
    "低流动性": ("liquidity", "high"),
    # shareholder / pledge family
    "pledge": ("shareholder", "high"),
    "质押": ("shareholder", "high"),
    "质押风险": ("shareholder", "high"),
    "shareholder": ("shareholder", "medium"),
    "大股东减持": ("shareholder", "high"),
    "forced_liquidation": ("shareholder", "critical"),
    "强制平仓": ("shareholder", "critical"),
    "股东风险": ("shareholder", "medium"),
    # macro / regime family
    "macro": ("macro", "medium"),
    "宏观风险": ("macro", "medium"),
    "regime": ("macro", "medium"),
    "beta_override": ("macro", "low"),
    "β反噬": ("macro", "medium"),
    # sentiment family
    "sentiment": ("sentiment", "medium"),
    "情绪": ("sentiment", "medium"),
    "情绪风险": ("sentiment", "medium"),
    "crowded_trade": ("sentiment", "high"),
    "拥挤交易": ("sentiment", "high"),
    # policy / regulation family
    "policy": ("policy", "medium"),
    "政策": ("policy", "medium"),
    "regulation": ("policy", "medium"),
    "regulatory": ("policy", "medium"),
    "监管风险": ("policy", "high"),
    # geopolitical family
    "tariff": ("geopolitical", "medium"),
    "关税": ("geopolitical", "medium"),
    "geopolitical": ("geopolitical", "medium"),
    "地缘政治": ("geopolitical", "medium"),
}


def canonicalize_risk_flag(raw_category):
    """Map a raw risk_flag category string → (canonical_category, default_severity).

    Returns ("other", "medium") for unrecognized categories.
    Lookup is case-insensitive with substring match.
    """
    if not raw_category:
        return ("other", "medium")
    key = str(raw_category).strip().lower()
    if key in CANONICAL_RISK_FLAGS:
        return CANONICAL_RISK_FLAGS[key]
    for synonym, mapping in CANONICAL_RISK_FLAGS.items():
        syn_lower = synonym.lower()
        if syn_lower in key or (len(key) >= 4 and key in syn_lower):
            return mapping
    return ("other", "medium")


def dedupe_and_cap_flags(flags, cap=6):
    """De-duplicate by canonical category and cap at `cap` items.

    Input: list of dicts with at least {"category", "severity", "description"}.
    Output: list of dicts in canonical form, sorted by severity, truncated to cap.
    """
    if not flags:
        return []
    by_category = {}
    for f in flags:
        if isinstance(f, str):
            # BRG-02: LLMs often emit a flat list of category strings
            # (e.g. ["liquidity_risk", "valuation_risk"]) instead of dicts.
            # Wrap each so it is canonicalized rather than silently dropped,
            # which would zero out the risk flags and make a risky stock look clean.
            f = f.strip()
            if not f:
                continue
            f = {"category": f}
        elif not isinstance(f, dict):
            continue
        raw_cat = f.get("category", "")
        canonical, default_sev = canonicalize_risk_flag(raw_cat)
        sev = str(f.get("severity", default_sev) or default_sev).lower()
        if sev not in _SEVERITY_ORDER:
            sev = default_sev
        existing = by_category.get(canonical)
        # Keep the highest-severity instance per canonical category.
        if existing is None or _SEVERITY_ORDER[sev] < _SEVERITY_ORDER[existing["severity"]]:
            by_category[canonical] = {
                "category": canonical,
                "severity": sev,
                "description": f.get("description", ""),
                "evidence": f.get("evidence", ""),
                "mitigant": f.get("mitigant", ""),
                "_raw_category": raw_cat,
            }
    ordered = sorted(by_category.values(), key=lambda x: _SEVERITY_ORDER[x["severity"]])
    return ordered[:cap]


def common_input_block(
    ticker: str,
    market: str = "CN_A",
    horizon: str = "3-6 Months",
    mode: str = "STANDARD",
    capital: int = 200_000,
    currency: str = "CNY",
    language: str = "Chinese",
    stock_profile_block: str = "",
    calibration_block: str = "",
) -> str:
    # No input validation by design — callers (prompts.py functions) are trusted internal code.
    extra = ""
    if stock_profile_block:
        extra += f"\n{stock_profile_block.strip()}\n"
    if calibration_block:
        extra += f"\n{calibration_block.strip()}\n"
    return (
        f"**COMMON INPUT BLOCK**:\n"
        f"【Target】 {ticker}\n"
        f"【Market】 {market}\n"
        f"【Window】 Past 30 Days\n"
        f"【Horizon】 {horizon}\n"
        f"【Mode】 {mode}\n"
        f"【Capital】 {capital:,.0f} {currency}\n"
        f"【Language】 {language}\n"
        f"{extra}"
    )


ASTOCK_RULES = """
【A 股交易规则（必须纳入分析）】
1. **涨跌停制度**：主板 ±10%，创业板/科创板 ±20%，北交所 ±30%，ST/*ST ±5%。涨停/跌停时 RSI/MACD 信号需特殊解读。
2. **T+1 交易**：当日买入次日方可卖出，不适合给出日内交易建议。
3. **ST/*ST 风险警示**：ST 股涨跌幅 ±5%，*ST 有退市风险，必须特别标注。
4. **融资融券**：并非所有股票可做空，建议卖出时需说明是否为融券标的。
5. **北向资金**：沪深港通外资流向是 A 股最重要的"聪明钱"指标之一。
6. **龙虎榜**：异常波动时关注席位（机构 vs 游资），判断资金性质。
7. **解禁/减持**：限售股解禁和大股东减持计划对股价有重大压力。
8. **概念股/题材轮动**：A股板块轮动频繁，需关注个股所属概念板块（如新能源/AI/半导体/核电）的资金轮动方向，板块退潮时龙头也难幸免。
9. **限售解禁压力**：大规模限售股解禁（>5%流通盘）前后1个月属高风险窗口，需评估减持意愿和历史减持模式。
"""


LANGUAGE_ZH = """
【语言与格式要求】
1. 请用中文撰写所有报告和分析，使用专业金融术语。
2. 最终交易建议请用「最终交易建议：**买入/持有/卖出**」格式输出。
3. 关键数据必须用 Markdown 表格呈现。
4. 每个核心论点必须有具体数据支撑，避免空泛描述。
"""


GLOBAL_CONSTRAINTS = """
【Global Constraints / Evidence Rules】
1) All FACTs must have a source link + date (YYYY-MM-DD).
2) Source Tiering: S1=Exchange/Official; S2=Auth Data/Mainstream Media; S3=Social/Forum.
3) Must distinguish: FACT / INTERP / DISPROVE (Invalidation).
4) No vague words like "mixed" or "neutral". Give testable thresholds.
5) Strict 30-day window unless justifying context.
"""


GLOBAL_CONSTRAINTS_SHORT = """
【Global Constraints】
1) All FACTs must have source link + date.
2) S1 (Official) > S2 (Auth) > S3 (Social).
3) Distinguish FACT / INTERP / DISPROVE.
"""


EVIDENCE_PROTOCOL = """
**EVIDENCE PROTOCOL — CRITICAL:**
- If an Evidence Bundle with [E#] items is provided below, cite by [E#] reference.
- If NO Evidence Bundle is available, cite by report section, e.g. [基本面报告-ROE数据, 技术面报告-MACD].
- Every claim MUST be traceable to at least one source. If none exists, state "NO EVIDENCE AVAILABLE".
- **禁止编造数字 (NO FABRICATED NUMBERS)**：只能引用可溯源的数据（Evidence Bundle / 报告）。若某维度无可靠数据，必须写明"数据缺失"并保守（偏中性）打分；绝不可虚构具体数值（PE / ROE / 目标价 / 增速 / 资金流等）来支撑论点。提示与范例中的数字仅示意格式，不可照搬到结论。
- At the end list all cited sources: CITED_EVIDENCE: [E1, E3, E5] or CITED_EVIDENCE: [基本面报告, 技术面报告]

**STRUCTURED CLAIMS (append at end of response):**
For each major claim, output EXACTLY this format. The `[clm-xNNN]` ID is REQUIRED
so the Research Manager can later adjudicate each claim by ID.
  - Bull analysts: use `[clm-u001]`, `[clm-u002]`, …  (u = up/bull)
  - Bear analysts: use `[clm-r001]`, `[clm-r002]`, …  (r = risk/bear)
  - Numbering is sequential per analyst, 3 digits, starts at 001.

Format (parser-sensitive — follow exactly):

CLAIM [clm-u001]: <claim text>
EVIDENCE: [E#, E#] or [report-section, report-section]
CONFIDENCE: <0.0-1.0>
INVALIDATION: <what would disprove this>

CLAIM [clm-u002]: <next claim…>
…
"""


REBUTTAL_PROTOCOL = """
**REBUTTAL PROTOCOL — 针对对方具体 claim 的真交锋（第二轮必做）：**
- 在掌握对方论据后，针对对方【最强的 2-4 条 claim】逐条反驳，必须引用对方的 claim ID。
- 格式（parser 依赖，严格遵守每条两行）：
  REBUT [clm-xNNN]: <为何这条对方论据站不住脚 / 被高估，引用 [E#] 或报告段落>
  REBUT_CONFIDENCE: <0.0-1.0>
  （bull 反驳 bear 的 clm-rNNN；bear 反驳 bull 的 clm-uNNN）
- 只反驳对方【真实提出过】的 claim ID；若未提供对方 claim ID 或找不到，跳过 REBUT，**不要编造 ID 或数字**。
- 这些 REBUT 会被解析为 opposing_claims，用于衡量辩论是否真正交锋（而非各说各话）。
"""


# --- Market-level input block (no ticker) ---

def market_input_block(
    current_date: str,
    market: str = "CN_A",
    language: str = "Chinese",
    **_ignored,
) -> str:
    """Input header for market-level agents (no ticker parameter).

    Accepts and ignores extra kwargs (**_ignored): the 3 market agents forward
    their own **kw here, so any extra keyword (e.g. market_snapshot_md) must not
    raise a TypeError (PROMPT-01)."""
    return (
        f"**COMMON INPUT BLOCK**:\n"
        f"【Scope】 全市场 (Market-Level)\n"
        f"【Market】 {market}\n"
        f"【Date】 {current_date}\n"
        f"【Language】 {language}\n"
    )


# --- Subagent-specific additions (not in original) ---

SUBAGENT_DATA_INSTRUCTION = """
**DATA COLLECTION (Subagent Mode):**
You have access to WebSearch for real-time data. For each data point you need:
1. Use WebSearch to find the latest data (stock price, financials, news, fund flow, etc.)
2. Record every source URL and date
3. Assign source tier: S1 (exchange/official filing), S2 (authoritative media/data vendor), S3 (social/forum)
4. If a data point cannot be found via search, mark it as "DATA UNAVAILABLE" — do NOT fabricate data.
"""


SUBAGENT_DATA_INSTRUCTION_WITH_AKSHARE = """
**DATA USAGE (Subagent Mode — akshare 数据已注入):**
下方已注入 akshare 采集的结构化数据，这是你的 **PRIMARY 数据源**（标记为 S2 级别）。使用规则：
1. 优先使用已注入的 akshare 数据进行分析，不要重复搜索已有数据点（价格、PE/PB、资金流向等）。
2. WebSearch **仅用于补充**以下 akshare 未覆盖的信息：
   - 突发新闻/公告（akshare 新闻可能有延迟）
   - 社交媒体情绪（股吧/雪球讨论热度）
   - 分析师深度评论和解读
   - akshare 数据中标记为"—"（缺失）的关键指标
3. 如果 akshare 数据与 WebSearch 数据存在矛盾，以 akshare 数据为准（除非 WebSearch 来源为 S1 交易所官方数据）。
4. 对 akshare 提供的每个数据点，可直接引用为 FACT，来源标记为 "akshare/S2"。
"""

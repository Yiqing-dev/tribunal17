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
TAG_TRADECARD_JSON = "TRADECARD_JSON"
TAG_TRADE_PLAN_JSON = "TRADE_PLAN_JSON"
TAG_ORDER_PROPOSAL_JSON = "ORDER_PROPOSAL_JSON"

# Round delimiters for bull/bear debate merging
ROUND_1_HEADER = "=== Round 1 ==="
ROUND_2_HEADER = "=== Round 2 ==="


def common_input_block(
    ticker: str,
    market: str = "CN_A",
    horizon: str = "3-6 Months",
    mode: str = "STANDARD",
    capital: int = 200_000,
    currency: str = "CNY",
    language: str = "Chinese",
) -> str:
    # No input validation by design — callers (prompts.py functions) are trusted internal code.
    return (
        f"**COMMON INPUT BLOCK**:\n"
        f"【Target】 {ticker}\n"
        f"【Market】 {market}\n"
        f"【Window】 Past 30 Days\n"
        f"【Horizon】 {horizon}\n"
        f"【Mode】 {mode}\n"
        f"【Capital】 {capital:,.0f} {currency}\n"
        f"【Language】 {language}\n"
    )


ASTOCK_RULES = """
【A 股交易规则（必须纳入分析）】
1. **涨跌停制度**：主板 ±10%，创业板/科创板 ±20%。涨停/跌停时 RSI/MACD 信号需特殊解读。
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
- At the end list all cited sources: CITED_EVIDENCE: [E1, E3, E5] or CITED_EVIDENCE: [基本面报告, 技术面报告]

**STRUCTURED CLAIMS (append at end of response):**
For each major claim, output EXACTLY this format:
CLAIM: <claim text>
EVIDENCE: [E#, E#] or [report-section, report-section]
CONFIDENCE: <0.0-1.0>
INVALIDATION: <what would disprove this>
"""


# --- Market-level input block (no ticker) ---

def market_input_block(
    current_date: str,
    market: str = "CN_A",
    language: str = "Chinese",
) -> str:
    """Input header for market-level agents (no ticker parameter)."""
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

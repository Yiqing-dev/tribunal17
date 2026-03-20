"""Web search enhancement layer — supplements akshare with international macro context.

Provides prompt templates for Claude Code agents that use WebSearch/WebFetch
to gather data akshare cannot provide:
1. International macro narrative (geopolitics, oil, forex, US-China trade)
2. Cross-market catalysts (global deals impacting A-share sectors)
3. Sector-level news from English-language sources
4. Fallback market data when akshare APIs fail

The agents return structured text that gets merged into market_context.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional


# ── Prompt: Global Macro Web Agent ──────────────────────────────────

def global_macro_prompt(trade_date: str, market_snapshot_md: str = "") -> str:
    """Prompt for a web-searching agent that gathers international macro context.

    This agent runs in parallel with the 3 akshare-based L1 agents.
    It searches English and Chinese financial media for information
    akshare structurally cannot provide.
    """
    snapshot_hint = ""
    if market_snapshot_md:
        snapshot_hint = f"""
**已知 A 股数据（来自 akshare，不必重复搜索）：**
{market_snapshot_md}

基于以上数据，聚焦搜索 akshare 未覆盖的国际视角和跨市场信息。
"""

    return f"""**ROLE**: You are the Global Macro Intelligence Agent (全球宏观情报司).
**OBJECTIVE**: Search the web for international macro context that affects A-share markets.
**DATE**: {trade_date}

{snapshot_hint}

**SEARCH TASKS (use WebSearch for each):**

1. **Global market overview** — search:
   - "China stock market {trade_date}" OR "Shanghai composite {trade_date}"
   - "SSE composite CSI 300" on Trading Economics or Investing.com
   - Extract: how international media frames today's A-share moves, any foreign catalysts

2. **Geopolitical events** — search:
   - "geopolitics China markets {trade_date}" OR major headlines (war, sanctions, trade)
   - How geopolitical events impact specific A-share sectors (oil→petrochemical, war→defense)

3. **Cross-market catalysts** — search:
   - Major global deals involving Chinese companies (M&A, licensing, partnerships)
   - US/EU regulatory actions affecting Chinese sectors (chip sanctions, tariffs)
   - Commodity price moves (oil, copper, gold, lithium) → sector implications

4. **Foreign capital sentiment** — search:
   - "northbound flow" OR "foreign investors China A-shares"
   - MSCI/FTSE China index changes, ETF flow data
   - Analyst upgrades/downgrades on China from Goldman, Morgan Stanley, etc.

5. **Overnight global markets** — search:
   - US markets (S&P 500, Nasdaq) close, major movers
   - European markets summary
   - Asian peers (Nikkei, Hang Seng, KOSPI)
   - How overnight moves set the tone for A-shares

**OUTPUT FORMAT — You MUST end with this exact block:**

```
GLOBAL_MACRO_OUTPUT:
overnight_markets = <1-2 sentences: US/EU/Asia close and tone>
geopolitical_risk = <key geopolitical events affecting markets, or NONE>
cross_market_catalysts = <specific deals/events impacting A-share sectors>
sector_implications = <which A-share sectors benefit/suffer from global events>
foreign_sentiment = <international analyst/media tone on China equities>
macro_narrative = <3-4 sentence Chinese summary synthesizing all above into A-share context>
```

**RULES:**
- Every claim must cite the source URL or publication name
- Distinguish FACT (data/quotes) from INTERPRETATION
- Focus on information NOT available from Chinese domestic data feeds
- Output the narrative summary in Chinese, other fields can be English or Chinese
- If a search returns no relevant results, note "未找到相关信息" for that field
"""


# ── Prompt: Market Snapshot Web Fallback ────────────────────────────

def market_snapshot_web_fallback_prompt(trade_date: str,
                                        missing_fields: List[str] = None) -> str:
    """Prompt for filling gaps in market snapshot when akshare APIs fail.

    Only invoked when specific akshare APIs fail (breadth, sector flow, etc).
    """
    fields_hint = ""
    if missing_fields:
        fields_hint = f"**需要补充的数据**: {', '.join(missing_fields)}\n"

    return f"""**ROLE**: You are the Market Data Recovery Agent (数据修复司).
**OBJECTIVE**: Use web search to fill missing A-share market data for {trade_date}.
**PRIORITY**: Only search for data that akshare failed to provide.

{fields_hint}

**SEARCH TASKS:**

1. If breadth data is missing — search:
   - "A股 涨跌家数 {trade_date}" OR "{trade_date} A股 上涨 下跌"
   - Look for advance/decline counts on eastmoney, sina finance, or financial news

2. If sector flow data is missing — search:
   - "板块资金流向 {trade_date}" OR "行业涨跌幅排名 {trade_date}"
   - Extract top 5 inflow and top 5 outflow sectors

3. If index data is missing — search:
   - "上证指数 深证成指 创业板指 {trade_date} 收盘"
   - Extract OHLCV for the 3 major indices

4. If limit board data is missing — search:
   - "涨停 跌停 {trade_date}" OR "涨停板 {trade_date}"
   - Extract limit-up count, limit-down count, notable stocks

**OUTPUT FORMAT:**
```
SNAPSHOT_RECOVERY:
advance_count = <number or UNKNOWN>
decline_count = <number or UNKNOWN>
limit_up_count = <number or UNKNOWN>
limit_down_count = <number or UNKNOWN>
top_sectors_up = <sector1 +X%, sector2 +Y%, ...>
top_sectors_down = <sector1 -X%, sector2 -Y%, ...>
index_sse = <close price or UNKNOWN>
index_szse = <close price or UNKNOWN>
index_chinext = <close price or UNKNOWN>
source = <where this data came from>
```
"""


# ── Prompt: Per-Ticker Web Enhancement ──────────────────────────────

def ticker_web_enhancement_prompt(ticker: str, name: str,
                                   trade_date: str) -> str:
    """Prompt for gathering web-only data to supplement akshare per-ticker data.

    Focuses on information akshare structurally misses:
    - International analyst coverage
    - Global supply chain context
    - Cross-listed comparables
    """
    return f"""**ROLE**: You are the International Research Agent for {ticker} ({name}).
**OBJECTIVE**: Search for international/English-language context about this company.

**SEARCH TASKS:**

1. Search: "{name}" OR "{ticker}" in English financial media (Reuters, Bloomberg)
   - International analyst ratings and target prices
   - Global supply chain positioning

2. Search: "{name} 行业" sector peers and global comparables
   - How this company compares to international peers
   - Industry-level trends from global perspective

3. Search: recent corporate actions (M&A, licensing deals, partnerships)
   - Specifically deals with foreign entities

**OUTPUT FORMAT:**
```
TICKER_WEB_OUTPUT:
international_coverage = <analyst ratings/commentary from global banks, or NONE>
global_context = <supply chain, competitive positioning vs global peers>
recent_deals = <notable cross-border deals or partnerships>
sector_global_trend = <global trend for this sector>
```
"""


# ── Parsers ─────────────────────────────────────────────────────────

def parse_global_macro_output(text: str) -> Dict[str, str]:
    """Parse GLOBAL_MACRO_OUTPUT: block from web agent response."""
    result = {
        "overnight_markets": "",
        "geopolitical_risk": "",
        "cross_market_catalysts": "",
        "sector_implications": "",
        "foreign_sentiment": "",
        "macro_narrative": "",
    }

    # Find the block
    block_match = re.search(
        r"GLOBAL_MACRO_OUTPUT:\s*\n(.*?)(?:\n```|\Z)",
        text, re.DOTALL,
    )
    if not block_match:
        # Fallback: try to find key=value pairs anywhere
        block_text = text
    else:
        block_text = block_match.group(1)

    for key in result:
        pattern = rf"^{key}\s*=\s*(.+?)$"
        m = re.search(pattern, block_text, re.MULTILINE)
        if m:
            result[key] = m.group(1).strip()

    return result


def parse_snapshot_recovery(text: str) -> Dict[str, str]:
    """Parse SNAPSHOT_RECOVERY: block from recovery agent."""
    result = {}
    block_match = re.search(
        r"SNAPSHOT_RECOVERY:\s*\n(.*?)(?:\n```|\Z)",
        text, re.DOTALL,
    )
    block_text = block_match.group(1) if block_match else text

    keys = [
        "advance_count", "decline_count", "limit_up_count", "limit_down_count",
        "top_sectors_up", "top_sectors_down",
        "index_sse", "index_szse", "index_chinext", "source",
    ]
    for key in keys:
        m = re.search(rf"^{key}\s*=\s*(.+?)$", block_text, re.MULTILINE)
        if m:
            val = m.group(1).strip()
            if val.upper() != "UNKNOWN":
                result[key] = val

    return result


def parse_ticker_web_output(text: str) -> Dict[str, str]:
    """Parse TICKER_WEB_OUTPUT: block."""
    result = {
        "international_coverage": "",
        "global_context": "",
        "recent_deals": "",
        "sector_global_trend": "",
    }
    block_match = re.search(
        r"TICKER_WEB_OUTPUT:\s*\n(.*?)(?:\n```|\Z)",
        text, re.DOTALL,
    )
    block_text = block_match.group(1) if block_match else text

    for key in result:
        m = re.search(rf"^{key}\s*=\s*(.+?)$", block_text, re.MULTILINE)
        if m:
            result[key] = m.group(1).strip()

    return result


# ── Integration helpers ─────────────────────────────────────────────

def merge_global_macro_into_context(
    market_context: Dict,
    global_macro: Dict[str, str],
) -> Dict:
    """Merge parsed global macro output into market_context dict.

    Adds new keys without overwriting existing akshare-derived data.
    """
    if not global_macro:
        return market_context

    market_context["global_macro"] = {
        "overnight_markets": global_macro.get("overnight_markets", ""),
        "geopolitical_risk": global_macro.get("geopolitical_risk", ""),
        "cross_market_catalysts": global_macro.get("cross_market_catalysts", ""),
        "sector_implications": global_macro.get("sector_implications", ""),
        "foreign_sentiment": global_macro.get("foreign_sentiment", ""),
        "macro_narrative": global_macro.get("macro_narrative", ""),
    }

    # Append global risk factors to risk_alerts if present
    geo_risk = global_macro.get("geopolitical_risk", "")
    if geo_risk and geo_risk.upper() not in ("NONE", "未找到相关信息", ""):
        existing = market_context.get("risk_alerts", "")
        if existing and existing != "NONE":
            market_context["risk_alerts"] = f"{existing}, [全球]{geo_risk}"
        else:
            market_context["risk_alerts"] = f"[全球]{geo_risk}"

    return market_context


def format_global_macro_block(global_macro: Dict[str, str]) -> str:
    """Format global macro data as text block for prompt injection.

    Appended to market_context_block so per-ticker agents see it.
    """
    if not global_macro or not any(global_macro.values()):
        return ""

    parts = ["国际宏观情报:"]

    overnight = global_macro.get("overnight_markets", "")
    if overnight:
        parts.append(f"  隔夜外盘: {overnight}")

    geo = global_macro.get("geopolitical_risk", "")
    if geo and geo.upper() not in ("NONE", "未找到相关信息"):
        parts.append(f"  地缘风险: {geo}")

    catalysts = global_macro.get("cross_market_catalysts", "")
    if catalysts and catalysts.upper() not in ("NONE", "未找到相关信息"):
        parts.append(f"  跨市场催化剂: {catalysts}")

    implications = global_macro.get("sector_implications", "")
    if implications:
        parts.append(f"  板块影响: {implications}")

    sentiment = global_macro.get("foreign_sentiment", "")
    if sentiment and sentiment.upper() not in ("NONE", "未找到相关信息"):
        parts.append(f"  外资情绪: {sentiment}")

    narrative = global_macro.get("macro_narrative", "")
    if narrative:
        parts.append(f"  综合研判: {narrative}")

    if len(parts) <= 1:
        return ""

    return "\n".join(parts) + "\n"


def apply_snapshot_recovery(
    market_snapshot,
    recovery: Dict[str, str],
) -> None:
    """Apply recovered data fields to MarketSnapshot in-place.

    Only fills zero/empty fields — never overwrites existing data.
    """
    if not recovery:
        return

    def _safe_int(val):
        try:
            return int(float(val.replace(",", "")))
        except (ValueError, TypeError, AttributeError):
            return 0

    if getattr(market_snapshot, "advance_count", 0) == 0:
        v = _safe_int(recovery.get("advance_count", ""))
        if v:
            market_snapshot.advance_count = v

    if getattr(market_snapshot, "decline_count", 0) == 0:
        v = _safe_int(recovery.get("decline_count", ""))
        if v:
            market_snapshot.decline_count = v

    if getattr(market_snapshot, "limit_up_count", 0) == 0:
        v = _safe_int(recovery.get("limit_up_count", ""))
        if v:
            market_snapshot.limit_up_count = v

    if getattr(market_snapshot, "limit_down_count", 0) == 0:
        v = _safe_int(recovery.get("limit_down_count", ""))
        if v:
            market_snapshot.limit_down_count = v

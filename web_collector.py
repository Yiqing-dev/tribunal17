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

import logging
import re

logger = logging.getLogger(__name__)
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

**KEY DATA SOURCES (all blocked by 403, must use WebSearch with site: filter):**
- tradingeconomics.com — China stock market indices, forecasts, macro indicators
- investing.com — Daily OHLCV historical data, 52-week range, cross-market indices (Hang Seng, Nikkei, S&P 500)
- reuters.com, bloomberg.com, cnbc.com — global market news and analysis

**SEARCH TASKS (use WebSearch for each, NEVER use WebFetch on these sites):**

1. **Trading Economics China data** — search:
   - "site:tradingeconomics.com china stock market" OR "site:tradingeconomics.com shanghai composite"
   - "site:tradingeconomics.com china GDP interest rate inflation"
   - Extract: Shanghai Composite level, 52-week range, monthly/yearly change %, forecasts, macro indicators (GDP growth, CPI, PMI, interest rate)

2. **Investing.com market data** — search:
   - "site:investing.com shanghai composite SSEC {trade_date}"
   - "site:investing.com hang seng nikkei S&P 500 {trade_date}"
   - Extract: recent daily close prices and % changes for Shanghai Composite + global peers (Hang Seng, Nikkei, S&P 500, Nasdaq), 52-week range, recent trend direction

3. **Global market overview** — search:
   - "China stock market {trade_date}" OR "Shanghai composite {trade_date}"
   - Extract: how international media frames today's A-share moves, any foreign catalysts

4. **Geopolitical events** — search:
   - "geopolitics China markets {trade_date}" OR major headlines (war, sanctions, trade)
   - How geopolitical events impact specific A-share sectors (oil→petrochemical, war→defense)

5. **Cross-market catalysts** — search:
   - Major global deals involving Chinese companies (M&A, licensing, partnerships)
   - US/EU regulatory actions affecting Chinese sectors (chip sanctions, tariffs)
   - Commodity price moves (oil, copper, gold, lithium) → sector implications

6. **Foreign capital sentiment** — search:
   - "northbound flow" OR "foreign investors China A-shares"
   - MSCI/FTSE China index changes, ETF flow data
   - Analyst upgrades/dowgrades on China from Goldman, Morgan Stanley, etc.

7. **Overnight global markets** — search:
   - US markets (S&P 500, Nasdaq) close, major movers
   - European markets summary
   - Asian peers (Nikkei, Hang Seng, KOSPI)
   - How overnight moves set the tone for A-shares

**OUTPUT FORMAT — You MUST end with this exact block:**

```
GLOBAL_MACRO_OUTPUT:
te_china_index = <Shanghai Composite level and % change from Trading Economics, or UNKNOWN>
te_macro_indicators = <GDP growth, CPI, PMI, interest rate from Trading Economics, or UNKNOWN>
te_forecast = <Trading Economics forecast/outlook for Shanghai Composite, or UNKNOWN>
inv_recent_prices = <recent 3-5 day Shanghai Composite close prices from Investing.com, e.g. "3/26: 3917(-0.4%), 3/25: 3932(+1.3%)", or UNKNOWN>
inv_global_peers = <Hang Seng, Nikkei, S&P 500 latest close and % change from Investing.com, or UNKNOWN>
inv_52w_range = <52-week high and low from Investing.com, or UNKNOWN>
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
        "te_china_index": "",
        "te_macro_indicators": "",
        "te_forecast": "",
        "inv_recent_prices": "",
        "inv_global_peers": "",
        "inv_52w_range": "",
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
        # Fallback: only scan short text to avoid false matches from prose
        if len(text) > 2000:
            logger.warning("GLOBAL_MACRO_OUTPUT block not found; text too long for safe fallback scan")
            return result
        block_text = text
    else:
        block_text = block_match.group(1)

    for key in result:
        if key == "macro_narrative":
            # macro_narrative may span multiple lines — greedily capture to end of block
            m = re.search(
                rf"^macro_narrative\s*=\s*(.*?)(?=\n\w+\s*=|\Z)",
                block_text, re.MULTILINE | re.DOTALL,
            )
        else:
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
    if block_match:
        block_text = block_match.group(1)
    elif len(text) > 2000:
        logger.warning("SNAPSHOT_RECOVERY block not found; text too long for safe fallback scan")
        return result
    else:
        block_text = text

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
    if block_match:
        block_text = block_match.group(1)
    elif len(text) > 2000:
        logger.warning("TICKER_WEB_OUTPUT block not found; text too long for safe fallback scan")
        return result
    else:
        block_text = text

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

    market_context = dict(market_context)
    market_context["global_macro"] = {
        "te_china_index": global_macro.get("te_china_index", ""),
        "te_macro_indicators": global_macro.get("te_macro_indicators", ""),
        "te_forecast": global_macro.get("te_forecast", ""),
        "inv_recent_prices": global_macro.get("inv_recent_prices", ""),
        "inv_global_peers": global_macro.get("inv_global_peers", ""),
        "inv_52w_range": global_macro.get("inv_52w_range", ""),
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

    te_index = global_macro.get("te_china_index", "")
    if te_index and te_index.upper() not in ("UNKNOWN", "未找到相关信息"):
        parts.append(f"  Trading Economics 中国指数: {te_index}")

    te_macro = global_macro.get("te_macro_indicators", "")
    if te_macro and te_macro.upper() not in ("UNKNOWN", "未找到相关信息"):
        parts.append(f"  宏观指标(TE): {te_macro}")

    te_forecast = global_macro.get("te_forecast", "")
    if te_forecast and te_forecast.upper() not in ("UNKNOWN", "未找到相关信息"):
        parts.append(f"  TE预测: {te_forecast}")

    inv_prices = global_macro.get("inv_recent_prices", "")
    if inv_prices and inv_prices.upper() not in ("UNKNOWN", "未找到相关信息"):
        parts.append(f"  近期走势(Investing.com): {inv_prices}")

    inv_peers = global_macro.get("inv_global_peers", "")
    if inv_peers and inv_peers.upper() not in ("UNKNOWN", "未找到相关信息"):
        parts.append(f"  全球指数: {inv_peers}")

    inv_range = global_macro.get("inv_52w_range", "")
    if inv_range and inv_range.upper() not in ("UNKNOWN", "未找到相关信息"):
        parts.append(f"  52周区间: {inv_range}")

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

    # Index data recovery — fill empty index_data from web search results
    if not getattr(market_snapshot, "index_data", None):
        market_snapshot.index_data = {}
    _INDEX_MAP = {
        "index_sse": ("sh000001", "\u4e0a\u8bc1\u6307\u6570"),
        "index_szse": ("sz399001", "\u6df1\u8bc1\u6210\u6307"),
        "index_chinext": ("sz399006", "\u521b\u4e1a\u677f\u6307"),
    }
    for key, (code, name) in _INDEX_MAP.items():
        if code in market_snapshot.index_data:
            continue  # don't overwrite existing
        raw = recovery.get(key, "")
        if not raw or raw.upper() == "UNKNOWN":
            continue
        m = re.match(r'([\d,.]+)\s*\(([+-]?[\d.]+)%?\)', raw.replace(",", ""))
        if m:
            market_snapshot.index_data[code] = {
                "name": name,
                "close": float(m.group(1)),
                "change_pct": float(m.group(2)),
            }
            logger.info("Recovered index %s: %s (%.2f%%)", name, m.group(1), float(m.group(2)))


# ── Prompt: Concept Board Web Fallback ─────────────────────────────

def concept_board_web_prompt(trade_date: str) -> str:
    """Prompt for fetching concept board rankings when EM API is down.

    Targets structured data: top concepts with % change and market cap.
    """
    return f"""**ROLE**: You are the Concept Board Recovery Agent (概念板块修复司).
**OBJECTIVE**: Fetch today's A-share concept board (概念板块) ranking data for {trade_date}.

**SEARCH TASKS (try each until you get structured data):**

1. Search "A股概念板块涨跌幅排名 {trade_date}" — look for tables on:
   - 东方财富 (eastmoney.com)
   - 同花顺 (10jqka.com)
   - 新浪财经 (finance.sina.com.cn)

2. If search finds a page with rankings, use WebFetch to load it and extract:
   - Top 15 concept boards by % change (涨幅最大)
   - For each: name, % change, total market cap if available

3. Fallback: search "概念板块 今日 热门" and extract whatever ranking is available

**OUTPUT FORMAT — end with this exact block:**
```
CONCEPT_BOARD_OUTPUT:
concept_count = <number of concepts extracted>
concepts = <JSON array, each element: {{"name": "概念名", "change_pct": 3.5, "market_cap_yi": 12000}}>
source = <URL or site name where data came from>
```

**RULES:**
- Output `market_cap_yi` in 亿元. If market cap unavailable, use 0.
- Sort by change_pct descending.
- Include at least 10 concepts if possible, max 20.
- If no data found at all, set concept_count = 0 and concepts = [].
"""


# ── Prompt: Top 10 Shareholders Web Fallback ───────────────────────

def top10_shareholders_web_prompt(ticker: str, name: str) -> str:
    """Prompt for fetching top 10 circulating shareholders when EM API bugs out.

    This is quarterly data — not time-sensitive, very well published online.
    """
    return f"""**ROLE**: You are the Shareholder Data Agent (股东数据修复司).
**OBJECTIVE**: Fetch the latest top 10 circulating shareholders (十大流通股东) for {ticker} ({name}).

**SEARCH TASKS:**

1. Search "{name} 十大流通股东" or "{ticker} 十大流通股东 最新"
   - Look for data on: eastmoney.com, cninfo.com.cn, sina finance

2. Use WebFetch to load the page and extract the shareholder table:
   - Shareholder name (股东名称)
   - Shares held (持股数量, in 万股)
   - Holding ratio (持股比例, as %)
   - Change vs previous quarter (增减, in 万股; positive=increase, negative=decrease)

3. Also note the report date (报告期, e.g. 2025-12-31) — this indicates data freshness.

**OUTPUT FORMAT:**
```
TOP10_SHAREHOLDERS_OUTPUT:
report_date = <YYYY-MM-DD, the financial report period>
ticker = {ticker}
shareholder_count = <number of shareholders extracted>
shareholders = <JSON array: [{{"name": "股东名", "shares_wan": 5000, "pct": 3.5, "change_wan": 200}}, ...]>
source = <URL>
```

**RULES:**
- 持股数量 in 万股 (10,000 shares). Convert if displayed in 股.
- If change data is unavailable, use 0 for change_wan.
- Include all 10 shareholders if possible.
- If the page shows multiple quarters, extract only the LATEST quarter.
"""


# ── Parsers for new prompts ────────────────────────────────────────

def parse_concept_board_output(text: str) -> List[Dict]:
    """Parse CONCEPT_BOARD_OUTPUT: block → list of concept dicts."""
    import json as _json

    block_match = re.search(
        r"CONCEPT_BOARD_OUTPUT:\s*\n(.*?)(?:\n```|\Z)",
        text, re.DOTALL,
    )
    block_text = block_match.group(1) if block_match else text

    # Extract concepts JSON array
    m = re.search(r"concepts\s*=\s*(\[[\s\S]*\])", block_text, re.DOTALL)
    if not m:
        return []
    try:
        concepts = _json.loads(m.group(1))
        return [
            {
                "name": str(c.get("name", "")),
                "change_pct": float(c.get("change_pct", 0)),
                "total_market_cap": float(c.get("market_cap_yi", 0)) * 1e8,
            }
            for c in concepts
            if c.get("name")
        ]
    except (_json.JSONDecodeError, TypeError, ValueError):
        return []


def parse_top10_shareholders_output(text: str) -> Dict:
    """Parse TOP10_SHAREHOLDERS_OUTPUT: block → dict with shareholders list."""
    import json as _json

    block_match = re.search(
        r"TOP10_SHAREHOLDERS_OUTPUT:\s*\n(.*?)(?:\n```|\Z)",
        text, re.DOTALL,
    )
    block_text = block_match.group(1) if block_match else text

    result: Dict = {"report_date": "", "shareholders": []}

    # Report date
    m = re.search(r"report_date\s*=\s*(.+?)$", block_text, re.MULTILINE)
    if m:
        result["report_date"] = m.group(1).strip()

    # Shareholders JSON array
    m = re.search(r"shareholders\s*=\s*(\[[\s\S]*\])", block_text, re.DOTALL)
    if not m:
        return result
    try:
        shareholders = _json.loads(m.group(1))
        result["shareholders"] = [
            {
                "name": str(s.get("name", "")),
                "shares_wan": float(s.get("shares_wan", 0)),
                "pct": float(s.get("pct", 0)),
                "change_wan": float(s.get("change_wan", 0)),
            }
            for s in shareholders
            if s.get("name")
        ]
    except (_json.JSONDecodeError, TypeError, ValueError):
        pass

    return result


# ── Integration: apply concept board to market snapshot ────────────

def apply_concept_board_recovery(
    market_snapshot,
    concepts: List[Dict],
) -> None:
    """Apply web-recovered concept board data to MarketSnapshot.

    Only fills if concept_fund_flow is empty.
    """
    if not concepts:
        return
    if getattr(market_snapshot, "concept_fund_flow", None):
        return  # already has data, don't overwrite
    market_snapshot.concept_fund_flow = concepts[:15]


def format_top10_shareholders_md(data: Dict) -> str:
    """Format parsed top-10 shareholders as markdown for AkshareBundle injection."""
    if not data or not data.get("shareholders"):
        return ""

    lines = [f"### 十大流通股东 (报告期: {data.get('report_date', '未知')})"]
    lines.append("| 股东名称 | 持股(万股) | 占比(%) | 增减(万股) |")
    lines.append("|---------|----------|--------|----------|")
    for s in data["shareholders"]:
        change = s.get("change_wan", 0)
        if change > 0:
            change_str = f"+{change:.0f}"
        elif change < 0:
            change_str = f"{change:.0f}"
        else:
            change_str = "不变"
        lines.append(
            f"| {s['name']} | {s['shares_wan']:.0f} | {s['pct']:.2f} | {change_str} |"
        )
    return "\n".join(lines)

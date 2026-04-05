"""Comprehensive akshare data collector for A-share stocks.

Collects ALL available structured data for a single ticker via akshare APIs.
Output: AkshareBundle with structured data (for verification) + markdown (for agents).

Usage:
    from subagent_pipeline.akshare_collector import collect
    bundle = collect("601985")
"""

from __future__ import annotations

import logging
import math
import random
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Optional

from .proxy_pool import em_proxy_session

logger = logging.getLogger(__name__)

# Lazy import akshare (thread-safe)
import threading as _threading
_ak = None
_ak_lock = _threading.Lock()


def _get_ak():
    global _ak
    if _ak is None:
        with _ak_lock:
            if _ak is None:  # double-check after acquiring lock
                import akshare as ak
                _ak = ak
    return _ak


# ── Global API throttle ─────────────────────────────────────────────────
# Ensures minimum interval between consecutive akshare API calls to avoid
# 429 rate limits from upstream data providers (EM, Sina, THS).
# Configurable via TA_API_MIN_INTERVAL (seconds) and TA_API_JITTER (seconds).

_throttle_lock = _threading.Lock()
_last_api_call: float = 0.0

_THROTTLE_MIN_INTERVAL = 0.3   # default minimum seconds between calls
_THROTTLE_JITTER = 0.2         # default random jitter upper bound


def _throttle() -> None:
    """Wait if needed to maintain minimum interval between API calls."""
    global _last_api_call
    from .config import get_env_float
    min_interval = get_env_float("TA_API_MIN_INTERVAL", _THROTTLE_MIN_INTERVAL)
    jitter = get_env_float("TA_API_JITTER", _THROTTLE_JITTER)
    needed = min_interval + random.uniform(0, jitter)
    with _throttle_lock:
        elapsed = time.time() - _last_api_call
        if elapsed < needed:
            time.sleep(needed - elapsed)
        _last_api_call = time.time()


def _retry_call(fn, *args, max_retries=2, base_delay=1.0, **kwargs):
    """Call fn with retry on transient failures (network, rate limit).

    Retries up to max_retries times with exponential backoff.
    Applies global throttle before each attempt.
    Only retries on known transient exceptions; re-raises everything else.
    """
    for attempt in range(max_retries + 1):
        try:
            _throttle()
            return fn(*args, **kwargs)
        except Exception as e:
            err_str = str(e).lower()
            is_transient = any(kw in err_str for kw in (
                "timeout", "timed out", "connection", "rate limit",
                "too many requests", "503", "429", "retry",
                "reset by peer", "broken pipe",
            ))
            if not is_transient or attempt == max_retries:
                raise
            delay = base_delay * (2 ** attempt)
            logger.info(f"Retry {attempt+1}/{max_retries} for {fn.__name__} "
                        f"after {delay:.1f}s: {e}")
            time.sleep(delay)


# ──────────────────────────────────────────────────────────────────────
# Data bundle
# ──────────────────────────────────────────────────────────────────────

@dataclass
class AkshareBundle:
    ticker: str          # bare 6-digit code
    name: str = ""
    trade_date: str = ""

    # ── Key metrics (for verification) ──
    current_price: Optional[float] = None
    prev_close: Optional[float] = None
    pe_ttm: Optional[float] = None
    pb: Optional[float] = None
    ps_ttm: Optional[float] = None
    market_cap_yi: Optional[float] = None   # 总市值(亿元)
    float_cap_yi: Optional[float] = None    # 流通市值(亿元)
    turnover_rate: Optional[float] = None
    revenue_latest: Optional[float] = None  # 最新一期营收(万元)
    net_profit_latest: Optional[float] = None  # 净利润(万元)
    roe: Optional[float] = None
    gross_margin: Optional[float] = None
    eps: Optional[float] = None
    bps: Optional[float] = None             # 每股净资产
    sector: str = ""
    listing_date: str = ""

    # ── Time series ──
    price_history: list = field(default_factory=list)
    fund_flow_5d: list = field(default_factory=list)
    valuation_30d: list = field(default_factory=list)
    northbound_history: list = field(default_factory=list)
    northbound_stale_days: int = 0

    # ── Structured lists ──
    top10_shareholders: list = field(default_factory=list)
    news_articles: list = field(default_factory=list)
    research_reports: list = field(default_factory=list)
    lhb_records: list = field(default_factory=list)

    # ── Financial statement summaries ──
    financial_summary: dict = field(default_factory=dict)
    financial_ratios: dict = field(default_factory=dict)

    # ── Formatted markdown (for agents) ──
    markdown_report: str = ""

    # ── Collection metadata ──
    apis_succeeded: list = field(default_factory=list)
    apis_failed: list = field(default_factory=list)
    collection_seconds: float = 0.0

    @property
    def success_rate(self) -> float:
        total = len(self.apis_succeeded) + len(self.apis_failed)
        return len(self.apis_succeeded) / total if total > 0 else 0.0

    def verification_dict(self) -> dict:
        """Return key metrics as flat dict for verification comparison."""
        return {
            "current_price": self.current_price,
            "pe_ttm": self.pe_ttm,
            "pb": self.pb,
            "ps_ttm": self.ps_ttm,
            "market_cap_yi": self.market_cap_yi,
            "turnover_rate": self.turnover_rate,
            "revenue_latest": self.revenue_latest,
            "net_profit_latest": self.net_profit_latest,
            "roe": self.roe,
            "gross_margin": self.gross_margin,
            "eps": self.eps,
            "name": self.name,
            "sector": self.sector,
        }

    # ── Per-analyst markdown renderers ──────────────────────────────

    def _header(self, perspective: str) -> str:
        total = len(self.apis_succeeded) + len(self.apis_failed)
        hdr = (
            f"# {self.ticker} {self.name} — akshare 数据（{perspective}）\n"
            f"采集日期: {self.trade_date} | API 成功率: {len(self.apis_succeeded)}/{total}"
        )
        if self.apis_failed:
            hdr += f" | 失败: {', '.join(self.apis_failed)}"
        return hdr

    def render_market_analyst_md(self) -> str:
        """Render data relevant to the Technical Analyst: price, volume, fund flow, northbound, LHB."""
        parts = [self._header("技术分析视角")]

        # Core price metrics
        parts.append("\n## 核心行情指标")
        parts.append("| 指标 | 数值 |")
        parts.append("|------|------|")
        parts.append(f"| 最新价 | {_fmt_num(self.current_price)}元 |")
        parts.append(f"| 昨收 | {_fmt_num(self.prev_close)}元 |")
        parts.append(f"| 换手率 | {_fmt_num(self.turnover_rate)}% |")
        parts.append(f"| 总市值 | {_fmt_num(self.market_cap_yi)}亿 |")
        parts.append(f"| 流通市值 | {_fmt_num(self.float_cap_yi)}亿 |")

        # Price history (last 10 days)
        if self.price_history:
            parts.append("\n## 近期行情（最近10个交易日）")
            parts.append("| 日期 | 开盘 | 收盘 | 最高 | 最低 | 涨跌幅(%) | 成交额 | 换手率(%) |")
            parts.append("|------|------|------|------|------|----------|--------|----------|")
            for row in self.price_history[-10:]:
                parts.append(
                    f"| {row['date']} | {_fmt_num(row['open'])} | {_fmt_num(row['close'])} "
                    f"| {_fmt_num(row['high'])} | {_fmt_num(row['low'])} "
                    f"| {_fmt_num(row['change_pct'])} "
                    f"| {_fmt_num(row['amount'])} | {_fmt_num(row['turnover'])} |"
                )

        # Fund flow
        if self.fund_flow_5d:
            parts.append("\n## 资金流向（最近5个交易日）")
            parts.append("| 日期 | 收盘 | 涨跌幅(%) | 主力净流入 | 主力净占比(%) |")
            parts.append("|------|------|----------|----------|------------|")
            for row in self.fund_flow_5d:
                parts.append(
                    f"| {row['date']} | {_fmt_num(row['close'])} "
                    f"| {_fmt_num(row['change_pct'])} "
                    f"| {_fmt_num(row['main_net_inflow'])} "
                    f"| {_fmt_num(row['main_net_pct'])} |"
                )

        # Northbound
        if self.northbound_history:
            stale = getattr(self, 'northbound_stale_days', 0)
            if stale > 180:
                parts.append("\n## 北向资金持股（⚠️ 历史数据，已停止实时披露）")
                parts.append(f"> 注意：北向资金逐日持股数据自2024年8月起已停止实时披露（监管政策调整）。"
                             f"以下为停止披露前最后10个交易日数据（截至{self.northbound_history[-1]['date']}），"
                             f"仅供历史参考，不反映当前持仓。分析时请勿将数据缺失解读为外资撤退。")
            else:
                parts.append("\n## 北向资金持股（最近10个交易日）")
            parts.append("| 日期 | 持股数量 | 持股占比(%) | 持股市值 |")
            parts.append("|------|---------|-----------|---------|")
            for row in self.northbound_history[-10:]:
                parts.append(
                    f"| {row['date']} | {_fmt_num(row.get('hold_shares'))} "
                    f"| {_fmt_num(row.get('hold_pct'))} "
                    f"| {_fmt_num(row.get('hold_value'))} |"
                )

        # LHB
        if self.lhb_records:
            parts.append("\n## 龙虎榜记录（近30天）")
            for rec in self.lhb_records:
                parts.append(
                    f"- {rec['date']}: {rec['reason']} | 净买额 {_fmt_num(rec.get('net_buy'))}"
                )

        return "\n".join(parts)

    def render_fundamentals_analyst_md(self) -> str:
        """Render data relevant to the Fundamentals Analyst: valuation, financials, shareholders, research."""
        parts = [self._header("基本面视角")]

        # Full valuation + profitability metrics
        parts.append("\n## 核心指标")
        parts.append("| 指标 | 数值 |")
        parts.append("|------|------|")
        parts.append(f"| 最新价 | {_fmt_num(self.current_price)}元 |")
        parts.append(f"| PE(TTM) | {_fmt_num(self.pe_ttm)} |")
        parts.append(f"| PB | {_fmt_num(self.pb)} |")
        parts.append(f"| PS(TTM) | {_fmt_num(self.ps_ttm)} |")
        parts.append(f"| 总市值 | {_fmt_num(self.market_cap_yi)}亿 |")
        parts.append(f"| 流通市值 | {_fmt_num(self.float_cap_yi)}亿 |")
        parts.append(f"| ROE | {_fmt_num(self.roe)}% |")
        parts.append(f"| 毛利率 | {_fmt_num(self.gross_margin)}% |")
        parts.append(f"| EPS | {_fmt_num(self.eps)}元 |")
        parts.append(f"| 每股净资产 | {_fmt_num(self.bps)}元 |")
        parts.append(f"| 营收(最新期) | {_fmt_num(self.revenue_latest)} |")
        parts.append(f"| 归母净利润(最新期) | {_fmt_num(self.net_profit_latest)} |")
        parts.append(f"| 行业 | {self.sector} |")
        parts.append(f"| 上市日期 | {self.listing_date} |")

        # Financial summary (top metrics from abstract)
        if self.financial_summary.get("metrics"):
            period = self.financial_summary.get("period", "")
            parts.append(f"\n## 财务摘要（报告期: {period}）")
            parts.append("| 指标 | 数值 |")
            parts.append("|------|------|")
            for name, val in list(self.financial_summary["metrics"].items())[:20]:
                parts.append(f"| {name} | {_fmt_num(val)} |")

        # Valuation history
        if self.valuation_30d:
            parts.append("\n## 估值走势（最近10个交易日）")
            parts.append("| 日期 | PE(TTM) | PB |")
            parts.append("|------|---------|-----|")
            for row in self.valuation_30d[-10:]:
                parts.append(
                    f"| {row['date']} | {_fmt_num(row.get('pe_ttm'))} "
                    f"| {_fmt_num(row.get('pb'))} |"
                )

        # Top 10 shareholders
        if self.top10_shareholders:
            parts.append("\n## 十大流通股东")
            parts.append("| 排名 | 股东名称 | 性质 | 持股比例(%) | 增减 |")
            parts.append("|------|---------|------|-----------|------|")
            for sh in self.top10_shareholders[:10]:
                parts.append(
                    f"| {sh.get('rank', '')} | {sh['name']} "
                    f"| {sh['type']} | {_fmt_num(sh.get('pct'))} "
                    f"| {sh.get('change', '')} |"
                )

        # Research reports
        if self.research_reports:
            parts.append("\n## 机构研报")
            parts.append("| 日期 | 机构 | 评级 | 标题 |")
            parts.append("|------|------|------|------|")
            for rpt in self.research_reports[:8]:
                parts.append(
                    f"| {rpt['date']} | {rpt['institution']} "
                    f"| {rpt['rating']} | {rpt['title'][:40]} |"
                )

        return "\n".join(parts)

    def render_news_analyst_md(self) -> str:
        """Render data relevant to the News Analyst: news, research reports, LHB, basic identity."""
        parts = [self._header("新闻/催化剂视角")]

        # Basic identity
        parts.append(f"\n**标的**: {self.ticker} {self.name} | 行业: {self.sector} | 上市: {self.listing_date}")

        # News
        if self.news_articles:
            parts.append("\n## 近期新闻")
            for i, art in enumerate(self.news_articles, 1):
                parts.append(f"{i}. **{art['title']}** — {art['source']} ({art['time']})")
                if art.get("url"):
                    parts.append(f"   链接: {art['url']}")
                if art.get("content"):
                    parts.append(f"   > {art['content'][:150]}...")

        # Research reports
        if self.research_reports:
            parts.append("\n## 机构研报")
            parts.append("| 日期 | 机构 | 评级 | 标题 |")
            parts.append("|------|------|------|------|")
            for rpt in self.research_reports[:8]:
                parts.append(
                    f"| {rpt['date']} | {rpt['institution']} "
                    f"| {rpt['rating']} | {rpt['title'][:40]} |"
                )

        # LHB (dragon-tiger board — signals unusual institutional/retail activity)
        if self.lhb_records:
            parts.append("\n## 龙虎榜记录（近30天）")
            for rec in self.lhb_records:
                parts.append(
                    f"- {rec['date']}: {rec['reason']} | 净买额 {_fmt_num(rec.get('net_buy'))}"
                )

        return "\n".join(parts)

    def render_sentiment_analyst_md(self) -> str:
        """Render data relevant to the Sentiment Analyst: fund flow, northbound, shareholders, LHB, volume."""
        parts = [self._header("资金/情绪视角")]

        # Core metrics (price + volume context)
        parts.append("\n## 核心指标")
        parts.append("| 指标 | 数值 |")
        parts.append("|------|------|")
        parts.append(f"| 最新价 | {_fmt_num(self.current_price)}元 |")
        parts.append(f"| 换手率 | {_fmt_num(self.turnover_rate)}% |")
        parts.append(f"| 总市值 | {_fmt_num(self.market_cap_yi)}亿 |")
        parts.append(f"| 流通市值 | {_fmt_num(self.float_cap_yi)}亿 |")

        # Fund flow
        if self.fund_flow_5d:
            parts.append("\n## 资金流向（最近5个交易日）")
            parts.append("| 日期 | 收盘 | 涨跌幅(%) | 主力净流入 | 主力净占比(%) |")
            parts.append("|------|------|----------|----------|------------|")
            for row in self.fund_flow_5d:
                parts.append(
                    f"| {row['date']} | {_fmt_num(row['close'])} "
                    f"| {_fmt_num(row['change_pct'])} "
                    f"| {_fmt_num(row['main_net_inflow'])} "
                    f"| {_fmt_num(row['main_net_pct'])} |"
                )

        # Northbound (sentiment view — same staleness annotation as technical view)
        if self.northbound_history:
            stale = getattr(self, 'northbound_stale_days', 0)
            if stale > 180:
                parts.append("\n## 北向资金持股（⚠️ 历史数据，已停止实时披露）")
                parts.append(f"> 注意：北向资金逐日持股数据自2024年8月起已停止实时披露（监管政策调整）。"
                             f"以下为停止披露前最后10个交易日数据，仅供历史参考。")
            else:
                parts.append("\n## 北向资金持股（最近10个交易日）")
            parts.append("| 日期 | 持股数量 | 持股占比(%) | 持股市值 |")
            parts.append("|------|---------|-----------|---------|")
            for row in self.northbound_history[-10:]:
                parts.append(
                    f"| {row['date']} | {_fmt_num(row.get('hold_shares'))} "
                    f"| {_fmt_num(row.get('hold_pct'))} "
                    f"| {_fmt_num(row.get('hold_value'))} |"
                )

        # Top 10 shareholders (institutional change signal)
        if self.top10_shareholders:
            parts.append("\n## 十大流通股东")
            parts.append("| 排名 | 股东名称 | 性质 | 持股比例(%) | 增减 |")
            parts.append("|------|---------|------|-----------|------|")
            for sh in self.top10_shareholders[:10]:
                parts.append(
                    f"| {sh.get('rank', '')} | {sh['name']} "
                    f"| {sh['type']} | {_fmt_num(sh.get('pct'))} "
                    f"| {sh.get('change', '')} |"
                )

        # Recent price (last 5 days for volume trend context)
        if self.price_history:
            parts.append("\n## 近期行情（最近5个交易日）")
            parts.append("| 日期 | 收盘 | 涨跌幅(%) | 成交额 | 换手率(%) |")
            parts.append("|------|------|----------|--------|----------|")
            for row in self.price_history[-5:]:
                parts.append(
                    f"| {row['date']} | {_fmt_num(row['close'])} "
                    f"| {_fmt_num(row['change_pct'])} "
                    f"| {_fmt_num(row['amount'])} "
                    f"| {_fmt_num(row['turnover'])} |"
                )

        # LHB
        if self.lhb_records:
            parts.append("\n## 龙虎榜记录（近30天）")
            for rec in self.lhb_records:
                parts.append(
                    f"- {rec['date']}: {rec['reason']} | 净买额 {_fmt_num(rec.get('net_buy'))}"
                )

        return "\n".join(parts)

    def render_price_reference_md(self) -> str:
        """Compact price reference for ResearchOutput stage — anchors entry/stop/target prices."""
        if not self.price_history and self.current_price is None:
            return ""
        parts = [f"**{self.ticker} {self.name} 价格参考**"]
        parts.append(f"- 最新价: {_fmt_num(self.current_price)}元")
        parts.append(f"- 昨收: {_fmt_num(self.prev_close)}元")

        if self.price_history:
            prices_10d = self.price_history[-10:]
            highs = [r["high"] for r in prices_10d if r.get("high")]
            lows = [r["low"] for r in prices_10d if r.get("low")]
            closes = [r["close"] for r in prices_10d if r.get("close")]
            if highs:
                parts.append(f"- 近10日最高: {max(highs):.2f}元")
            if lows:
                parts.append(f"- 近10日最低: {min(lows):.2f}元")
            if closes:
                avg = sum(closes) / len(closes)
                parts.append(f"- 近10日均价: {avg:.2f}元")

            # Recent OHLCV table (last 5 days for compact reference)
            parts.append("\n| 日期 | 收盘 | 最高 | 最低 | 涨跌幅(%) |")
            parts.append("|------|------|------|------|----------|")
            for row in prices_10d[-5:]:
                parts.append(
                    f"| {row['date']} | {_fmt_num(row['close'])} "
                    f"| {_fmt_num(row['high'])} | {_fmt_num(row['low'])} "
                    f"| {_fmt_num(row['change_pct'])} |"
                )

        if self.pe_ttm is not None or self.pb is not None:
            parts.append(f"\n- PE(TTM): {_fmt_num(self.pe_ttm)} | PB: {_fmt_num(self.pb)}")

        return "\n".join(parts)


# ──────────────────────────────────────────────────────────────────────
# Individual collectors (one per API group)
# ──────────────────────────────────────────────────────────────────────

def _safe_float(val) -> Optional[float]:
    if val is None:
        return None
    try:
        v = float(val)
        return v if v == v else None  # NaN check
    except (ValueError, TypeError):
        return None


def _collect_basic_info(b: AkshareBundle):
    """stock_individual_info_em — basic info (market cap, sector, etc.).

    Fallback: XQ individual spot for name/price when EM is down.
    """
    ak = _get_ak()
    try:
        with em_proxy_session():
            df = ak.stock_individual_info_em(symbol=b.ticker)
        info = {}
        for _, row in df.iterrows():
            info[str(row.iloc[0]).strip()] = row.iloc[1]
        b.name = str(info.get("股票简称", b.name))
        b.sector = str(info.get("行业", ""))
        b.listing_date = str(info.get("上市时间", ""))
        # akshare stock_individual_info_em returns 总市值/流通市值 in yuan
        raw_cap = _safe_float(info.get("总市值"))
        b.market_cap_yi = raw_cap / 1e8 if raw_cap and raw_cap > 0 else None  # → 亿
        raw_fcap = _safe_float(info.get("流通市值"))
        b.float_cap_yi = raw_fcap / 1e8 if raw_fcap and raw_fcap > 0 else None  # → 亿
        if b.name and b.market_cap_yi:
            return
        logger.info("  [basic_info] EM data incomplete, trying XQ fallback")
    except Exception as e:
        logger.warning(f"  [basic_info] EM failed ({e}), trying XQ fallback")

    # Fallback: XQ individual spot — at least get name and price
    try:
        prefix = "SH" if b.ticker.startswith("6") else "SZ"
        spot = ak.stock_individual_spot_xq(symbol=f"{prefix}{b.ticker}")
        if spot is not None and not spot.empty:
            vals = dict(zip(spot["item"], spot["value"]))
            if not b.name:
                b.name = str(vals.get("名称", ""))
            # XQ uses "资产净值/总市值" (not "总市值") and "流通值" (not "流通市值")
            mc = _safe_float(vals.get("资产净值/总市值", 0))
            if not mc:
                mc = _safe_float(vals.get("总市值", 0))
            if mc and mc > 1e8:
                b.market_cap_yi = mc / 1e8
            fc = _safe_float(vals.get("流通值", 0))
            if fc and fc > 1e8:
                b.float_cap_yi = fc / 1e8
            # XQ provides listing date as "发行日期"
            ld = str(vals.get("发行日期", "") or "")
            if ld and not b.listing_date:
                b.listing_date = ld[:10]  # "2017-07-13 12:00:00" → "2017-07-13"
            logger.info(f"  [basic_info] XQ fallback OK: name={b.name}")
            return
    except Exception as e2:
        logger.warning(f"  [basic_info] XQ fallback also failed: {e2}")
    raise RuntimeError("basic_info: both EM and XQ failed")


# Module-level cache for full-market spot data to avoid redundant downloads
# in batch loops.  Tuple of (DataFrame, timestamp_float).
import threading as _threading
_cached_spot_df = None
_cached_spot_ts: float = 0.0
_SPOT_CACHE_TTL = 60.0  # seconds
_spot_lock = _threading.Lock()


def _collect_spot(b: AkshareBundle):
    """stock_zh_a_spot_em — real-time snapshot (PE, PB, price).

    Fallback: XQ individual spot when EM is down.
    Uses a module-level cache (60 s TTL) so batch runs don't re-download
    the full ~5500-row table for every ticker.
    """
    global _cached_spot_df, _cached_spot_ts
    ak = _get_ak()
    try:
        with _spot_lock:
            now = time.monotonic()
            if _cached_spot_df is not None and (now - _cached_spot_ts) < _SPOT_CACHE_TTL:
                df = _cached_spot_df
            else:
                with em_proxy_session():
                    df = ak.stock_zh_a_spot_em()
                if df is not None and not df.empty:
                    _cached_spot_df = df
                    _cached_spot_ts = now
        if df is None or df.empty:
            raise ValueError("empty EM spot data")
        row = df[df["代码"] == b.ticker]
        if row.empty:
            raise ValueError(f"Ticker {b.ticker} not found in spot data")
        r = row.iloc[0]
        b.current_price = _safe_float(r.get("最新价"))
        b.prev_close = _safe_float(r.get("昨收"))
        b.pe_ttm = _safe_float(r.get("市盈率-动态"))
        b.pb = _safe_float(r.get("市净率"))
        b.turnover_rate = _safe_float(r.get("换手率"))
        if not b.name:
            b.name = str(r.get("名称", ""))
        # Market cap from spot (may override basic_info)
        mc = _safe_float(r.get("总市值"))
        if mc and mc > 1e8:
            b.market_cap_yi = mc / 1e8
        return
    except Exception as e:
        logger.warning(f"  [spot_quote] EM failed ({e}), trying XQ fallback")

    # Fallback: XQ individual spot
    prefix = "SH" if b.ticker.startswith("6") else ("BJ" if b.ticker.startswith(("8", "4")) else "SZ")
    spot = ak.stock_individual_spot_xq(symbol=f"{prefix}{b.ticker}")
    if spot is None or spot.empty:
        raise ValueError("spot_quote: both EM and XQ failed")
    vals = dict(zip(spot["item"], spot["value"]))
    b.current_price = _safe_float(vals.get("现价"))
    b.prev_close = _safe_float(vals.get("昨收"))
    b.pe_ttm = _safe_float(vals.get("市盈率(动)", 0))
    b.pb = _safe_float(vals.get("市净率", 0))
    b.turnover_rate = _safe_float(vals.get("周转率", 0))
    if not b.name:
        b.name = str(vals.get("名称", ""))
    mc = _safe_float(vals.get("总市值", 0))
    if mc and mc > 1e8:
        b.market_cap_yi = mc / 1e8
    logger.info(f"  [spot_quote] XQ fallback OK: price={b.current_price}")


def _collect_price_history(b: AkshareBundle):
    """stock_zh_a_hist — 30-day daily OHLCV.

    Fallback: stock_zh_a_daily (Sina backend) when EM is down.
    """
    ak = _get_ak()
    end = datetime.strptime(b.trade_date[:10], "%Y-%m-%d") if b.trade_date else datetime.now()
    start = end - timedelta(days=60)  # fetch extra for MA calc

    df = None
    # Primary: EM backend
    try:
        with em_proxy_session():
            df = ak.stock_zh_a_hist(
                symbol=b.ticker,
                period="daily",
                start_date=start.strftime("%Y%m%d"),
                end_date=end.strftime("%Y%m%d"),
                adjust="qfq",
            )
        if df is None or df.empty:
            raise ValueError("empty EM hist data")
    except Exception as e:
        logger.warning(f"  [price_history] EM failed ({e}), trying Sina fallback")
        df = None

    # Fallback: Sina backend (stock_zh_a_daily)
    if df is None or df.empty:
        prefix = "sh" if b.ticker.startswith("6") else "sz"
        sina_symbol = f"{prefix}{b.ticker}"
        try:
            df = _retry_call(ak.stock_zh_a_daily, symbol=sina_symbol, adjust="qfq")
        except Exception as e_sina:
            logger.warning(f"  [price_history] Sina fallback also failed: {e_sina}")
            df = None
        if df is not None and not df.empty:
            # Sina returns full history — trim to last 60 days
            df = df.tail(60)
            logger.info(f"  [price_history] Sina fallback OK: {len(df)} rows")

    if df is None or df.empty:
        raise ValueError("price_history: both EM and Sina failed")

    rows = []
    for _, r in df.iterrows():
        # Try Chinese column names (EM), fall back to English (Sina)
        date_val = r.get("日期", r.get("date", str(r.name) if hasattr(r, "name") else ""))
        rows.append({
            "date": str(date_val)[:10],
            "open": _safe_float(r.get("开盘", r.get("open"))),
            "close": _safe_float(r.get("收盘", r.get("close"))),
            "high": _safe_float(r.get("最高", r.get("high"))),
            "low": _safe_float(r.get("最低", r.get("low"))),
            "volume": _safe_float(r.get("成交量", r.get("volume"))),
            "amount": _safe_float(r.get("成交额", r.get("amount"))),
            "change_pct": _safe_float(r.get("涨跌幅", r.get("change_pct"))),
            "turnover": _safe_float(r.get("换手率", r.get("turnover"))),
        })
    b.price_history = rows
    # Update current_price from latest history if spot failed
    if rows and not b.current_price:
        b.current_price = rows[-1]["close"]


def _collect_valuation_history(b: AkshareBundle):
    """stock_zh_valuation_baidu — PE/PB time series."""
    ak = _get_ak()
    pe_df = None
    pb_df = None
    try:
        with em_proxy_session():
            pe_df = ak.stock_zh_valuation_baidu(symbol=b.ticker, indicator="市盈率(TTM)")
    except Exception as e:
        logger.warning(f"  [valuation] Baidu PE failed: {e}")
    try:
        with em_proxy_session():
            pb_df = ak.stock_zh_valuation_baidu(symbol=b.ticker, indicator="市净率")
    except Exception as e:
        logger.warning(f"  [valuation] Baidu PB failed: {e}")

    # Merge PE and PB on date
    pe_map = {str(r["date"]): _safe_float(r["value"]) for _, r in pe_df.iterrows()} if pe_df is not None else {}
    pb_map = {str(r["date"]): _safe_float(r["value"]) for _, r in pb_df.iterrows()} if pb_df is not None else {}

    all_dates = sorted(set(list(pe_map.keys()) + list(pb_map.keys())))[-30:]
    rows = []
    for d in all_dates:
        rows.append({
            "date": d,
            "pe_ttm": pe_map.get(d),
            "pb": pb_map.get(d),
        })
    b.valuation_30d = rows

    # Fill current metrics if spot failed
    if rows:
        latest = rows[-1]
        if b.pe_ttm is None:
            b.pe_ttm = latest.get("pe_ttm")
        if b.pb is None:
            b.pb = latest.get("pb")


def _collect_financial_summary(b: AkshareBundle):
    """stock_financial_abstract — key financial metrics (80 rows × N periods)."""
    ak = _get_ak()
    with em_proxy_session():
        df = ak.stock_financial_abstract(symbol=b.ticker)
    if df is None or df.empty:
        return

    # Columns: ['选项', '指标', '20250930', '20250630', ...]
    # Find the latest period column (skip '选项' and '指标')
    period_cols = [c for c in df.columns if c not in ("选项", "指标") and c.isdigit()]
    if not period_cols:
        return

    latest_col = period_cols[0]  # Most recent period
    prev_col = period_cols[1] if len(period_cols) > 1 else None

    # Build lookup: indicator_name → value
    indicator_map = {}
    for _, row in df.iterrows():
        name = str(row.get("指标", "")).strip()
        if name:
            indicator_map[name] = _safe_float(row.get(latest_col))

    b.financial_summary = {
        "period": latest_col,
        "metrics": indicator_map,
    }

    # Extract key metrics
    key_map = {
        "营业总收入": "revenue_latest",
        "归母净利润": "net_profit_latest",
        "基本每股收益": "eps",
        "每股净资产": "bps",
        "净资产收益率(ROE)": "roe",
        "毛利率": "gross_margin",
    }
    for indicator_name, attr_name in key_map.items():
        val = indicator_map.get(indicator_name)
        if val is not None and getattr(b, attr_name) is None:
            setattr(b, attr_name, val)


def _collect_financial_ratios(b: AkshareBundle):
    """stock_financial_report_sina — income statement for revenue/profit growth."""
    ak = _get_ak()
    prefix = "sh" if b.ticker.startswith("6") else ("bj" if b.ticker.startswith(("8", "4")) else "sz")
    stock_code = f"{prefix}{b.ticker}"
    # akshare >=1.10 uses Chinese names; map to internal keys
    _REPORT_MAP = {"利润表": "lrb", "资产负债表": "zcfzb", "现金流量表": "xjllb"}
    for symbol, key in _REPORT_MAP.items():
        try:
            with em_proxy_session():
                df = ak.stock_financial_report_sina(stock=stock_code, symbol=symbol)
            if df is not None and not df.empty:
                b.financial_ratios[key] = {
                    "columns": df.columns.tolist()[:15],
                    "latest": {str(c): _safe_float(df.iloc[0].get(c))
                               for c in df.columns[:15]} if len(df) > 0 else {},
                }
        except Exception as e:
            logger.debug(f"  financial_ratios {symbol}: {e}")


def _collect_fund_flow(b: AkshareBundle):
    """stock_individual_fund_flow — 5-day fund flow detail."""
    ak = _get_ak()
    market = "sh" if b.ticker.startswith("6") else "sz"
    with em_proxy_session():
        df = ak.stock_individual_fund_flow(stock=b.ticker, market=market)
    if df is None or df.empty:
        return
    df = df.tail(5)
    rows = []
    for _, r in df.iterrows():
        rows.append({
            "date": str(r.get("日期", "")),
            "close": _safe_float(r.get("收盘价")),
            "change_pct": _safe_float(r.get("涨跌幅")),
            "main_net_inflow": _safe_float(r.get("主力净流入-净额")),
            "main_net_pct": _safe_float(r.get("主力净流入-净占比")),
            "large_net_inflow": _safe_float(r.get("超大单净流入-净额")),
            "medium_net_inflow": _safe_float(r.get("中单净流入-净额")),
            "small_net_inflow": _safe_float(r.get("小单净流入-净额")),
        })
    b.fund_flow_5d = rows


def _collect_top10_shareholders(b: AkshareBundle):
    """stock_gdfx_free_top_10_em — top 10 circulating shareholders."""
    ak = _get_ak()
    # Try latest quarter
    now = datetime.strptime(b.trade_date[:10], "%Y-%m-%d") if b.trade_date else datetime.now()
    quarters = []
    for year in (now.year, now.year - 1):
        for q in ("1231", "0930", "0630", "0331"):
            quarters.append(f"{year}{q}")
    for qdate in quarters:
        try:
            with em_proxy_session():
                df = ak.stock_gdfx_free_top_10_em(symbol=b.ticker, date=qdate)
            if df is not None and not df.empty:
                rows = []
                for _, r in df.iterrows():
                    rows.append({
                        "rank": _safe_float(r.get("股东排名")) or _safe_float(r.get("序号")),
                        "name": str(r.get("股东名称", "")),
                        "type": str(r.get("股东性质", "")),
                        "shares": _safe_float(r.get("持股数量")) or _safe_float(r.get("持股数")),
                        "pct": _safe_float(r.get("持股比例")),
                        "change": str(r.get("增减", "")),
                        "change_pct": _safe_float(r.get("变动比例")),
                    })
                b.top10_shareholders = rows
                return
        except Exception as _e:
            logger.debug("top10 shareholders attempt failed: %s", _e)
            continue


def _collect_northbound(b: AkshareBundle):
    """stock_hsgt_individual_em — northbound holding history.

    Note: Since 2024-08, real-time northbound per-stock data has been
    suspended by regulators.  The API returns historical data up to
    2024-08-16.  We still collect it for historical context but mark
    the staleness clearly so downstream agents don't misinterpret.
    """
    ak = _get_ak()
    df = ak.stock_hsgt_individual_em(symbol=b.ticker)
    if df is None or df.empty:
        return
    df = df.tail(20)  # last 20 trading days
    rows = []
    for _, r in df.iterrows():
        rows.append({
            "date": str(r.get("持股日期", r.get("日期", ""))),
            "hold_shares": _safe_float(r.get("持股数量")),
            "hold_pct": _safe_float(r.get("持股数量占A股百分比",
                                          r.get("持股占比"))),
            "hold_value": _safe_float(r.get("持股市值")),
        })
    # Staleness check: warn if latest data is >30 days old
    stale_days = 0
    if rows:
        latest_date_str = rows[-1].get("date", "")
        try:
            latest_dt = datetime.strptime(latest_date_str[:10], "%Y-%m-%d")
            ref_dt = datetime.strptime(b.trade_date[:10], "%Y-%m-%d") if b.trade_date else datetime.now()
            stale_days = (ref_dt - latest_dt).days
            if stale_days > 30:
                logger.warning(
                    f"{b.ticker} northbound data is {stale_days} days stale "
                    f"(latest: {latest_date_str}, ref: {b.trade_date}). "
                    f"Regulators suspended real-time northbound disclosure in Aug 2024."
                )
        except (ValueError, TypeError):
            pass
    b.northbound_history = rows
    # Tag staleness on the bundle so markdown renderer can annotate
    b.northbound_stale_days = stale_days


def _collect_news(b: AkshareBundle):
    """stock_news_em — recent stock-specific news."""
    ak = _get_ak()
    with em_proxy_session():
        df = ak.stock_news_em(symbol=b.ticker)
    if df is None or df.empty:
        return
    articles = []
    for _, r in df.head(15).iterrows():
        articles.append({
            "title": str(r.get("新闻标题", "")),
            "source": str(r.get("文章来源", "")),
            "time": str(r.get("发布时间", "")),
            "url": str(r.get("新闻链接", "")),
            "content": str(r.get("新闻内容", ""))[:200],  # truncate
        })
    b.news_articles = articles


def _collect_research_reports(b: AkshareBundle):
    """stock_research_report_em — analyst ratings/reports."""
    ak = _get_ak()
    with em_proxy_session():
        df = ak.stock_research_report_em(symbol=b.ticker)
    if df is None or df.empty:
        return
    reports = []
    for _, r in df.head(10).iterrows():
        reports.append({
            "title": str(r.get("报告标题", "")),
            "institution": str(r.get("机构名称", "")),
            "date": str(r.get("日期", r.get("研报日期", ""))),
            "rating": str(r.get("最新评级", "")),
        })
    b.research_reports = reports


def _collect_lhb(b: AkshareBundle):
    """stock_lhb_detail_em — dragon-tiger board records (30 days)."""
    ak = _get_ak()
    end = datetime.strptime(b.trade_date[:10], "%Y-%m-%d") if b.trade_date else datetime.now()
    start = end - timedelta(days=30)
    df = ak.stock_lhb_detail_em(
        start_date=start.strftime("%Y%m%d"),
        end_date=end.strftime("%Y%m%d"),
    )
    if df is None or df.empty:
        return
    # Filter for this ticker
    code_col = "代码" if "代码" in df.columns else "股票代码"
    filtered = df[df[code_col].astype(str) == b.ticker]
    if filtered.empty:
        return
    rows = []
    for _, r in filtered.head(5).iterrows():
        rows.append({
            "date": str(r.get("上榜日期", "")),
            "reason": str(r.get("解读", r.get("上榜原因", ""))),
            "net_buy": _safe_float(r.get("龙虎榜净买额")),
            "buy_amount": _safe_float(r.get("龙虎榜买入额")),
            "sell_amount": _safe_float(r.get("龙虎榜卖出额")),
        })
    b.lhb_records = rows


# ──────────────────────────────────────────────────────────────────────
# Markdown formatter
# ──────────────────────────────────────────────────────────────────────

def _fmt_num(v, decimals=2) -> str:
    if v is None:
        return "—"
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return "—"
    if abs(v) >= 1e8:
        return f"{v / 1e8:.{decimals}f}亿"
    if abs(v) >= 1e4:
        return f"{v / 1e4:.{decimals}f}万"
    return f"{v:.{decimals}f}"


def _build_markdown(b: AkshareBundle) -> str:
    lines = []
    lines.append(f"# {b.ticker} {b.name} — akshare 数据采集报告")
    lines.append(f"采集时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"API 成功: {len(b.apis_succeeded)}/{len(b.apis_succeeded)+len(b.apis_failed)}")
    if b.apis_failed:
        lines.append(f"失败接口: {', '.join(b.apis_failed)}")
    lines.append("")

    # ── Key metrics ──
    lines.append("## 核心指标")
    lines.append(f"| 指标 | 数值 |")
    lines.append(f"|------|------|")
    lines.append(f"| 最新价 | {_fmt_num(b.current_price)}元 |")
    lines.append(f"| PE(TTM) | {_fmt_num(b.pe_ttm)} |")
    lines.append(f"| PB | {_fmt_num(b.pb)} |")
    lines.append(f"| PS(TTM) | {_fmt_num(b.ps_ttm)} |")
    lines.append(f"| 总市值 | {_fmt_num(b.market_cap_yi)}亿 |")
    lines.append(f"| 流通市值 | {_fmt_num(b.float_cap_yi)}亿 |")
    lines.append(f"| 换手率 | {_fmt_num(b.turnover_rate)}% |")
    lines.append(f"| ROE | {_fmt_num(b.roe)}% |")
    lines.append(f"| 毛利率 | {_fmt_num(b.gross_margin)}% |")
    lines.append(f"| EPS | {_fmt_num(b.eps)}元 |")
    lines.append(f"| 行业 | {b.sector} |")
    lines.append("")

    # ── Price history (last 10 days) ──
    if b.price_history:
        lines.append("## 近期行情（最近10个交易日）")
        lines.append("| 日期 | 收盘 | 涨跌幅(%) | 成交额 | 换手率(%) |")
        lines.append("|------|------|----------|--------|----------|")
        for row in b.price_history[-10:]:
            lines.append(
                f"| {row['date']} | {_fmt_num(row['close'])} "
                f"| {_fmt_num(row['change_pct'])} "
                f"| {_fmt_num(row['amount'])} "
                f"| {_fmt_num(row['turnover'])} |"
            )
        lines.append("")

    # ── Fund flow ──
    if b.fund_flow_5d:
        lines.append("## 资金流向（最近5个交易日）")
        lines.append("| 日期 | 收盘 | 涨跌幅(%) | 主力净流入 | 主力净占比(%) |")
        lines.append("|------|------|----------|----------|------------|")
        for row in b.fund_flow_5d:
            lines.append(
                f"| {row['date']} | {_fmt_num(row['close'])} "
                f"| {_fmt_num(row['change_pct'])} "
                f"| {_fmt_num(row['main_net_inflow'])} "
                f"| {_fmt_num(row['main_net_pct'])} |"
            )
        lines.append("")

    # ── Top 10 shareholders ──
    if b.top10_shareholders:
        lines.append("## 十大流通股东")
        lines.append("| 排名 | 股东名称 | 性质 | 持股比例(%) | 增减 |")
        lines.append("|------|---------|------|-----------|------|")
        for sh in b.top10_shareholders[:10]:
            lines.append(
                f"| {sh.get('rank', '')} | {sh['name']} "
                f"| {sh['type']} | {_fmt_num(sh.get('pct'))} "
                f"| {sh.get('change', '')} |"
            )
        lines.append("")

    # ── Northbound ──
    if b.northbound_history:
        stale = getattr(b, 'northbound_stale_days', 0)
        if stale > 180:
            lines.append("## 北向资金持股（⚠️ 历史数据，已停止实时披露）")
            lines.append(f"> 注意：北向资金逐日持股数据自2024年8月起已停止实时披露（监管政策调整）。"
                         f"以下为停止披露前最后10个交易日数据，仅供历史参考。")
        else:
            lines.append("## 北向资金持股（最近10个交易日）")
        lines.append("| 日期 | 持股数量 | 持股占比(%) | 持股市值 |")
        lines.append("|------|---------|-----------|---------|")
        for row in b.northbound_history[-10:]:
            lines.append(
                f"| {row['date']} | {_fmt_num(row.get('hold_shares'))} "
                f"| {_fmt_num(row.get('hold_pct'))} "
                f"| {_fmt_num(row.get('hold_value'))} |"
            )
        lines.append("")

    # ── Valuation history ──
    if b.valuation_30d:
        lines.append("## 估值走势（最近10个交易日）")
        lines.append("| 日期 | PE(TTM) | PB | PS(TTM) |")
        lines.append("|------|---------|-----|---------|")
        for row in b.valuation_30d[-10:]:
            lines.append(
                f"| {row['date']} | {_fmt_num(row.get('pe_ttm'))} "
                f"| {_fmt_num(row.get('pb'))} "
                f"| {_fmt_num(row.get('ps_ttm'))} |"
            )
        lines.append("")

    # ── News ──
    if b.news_articles:
        lines.append("## 近期新闻")
        for i, art in enumerate(b.news_articles[:10], 1):
            lines.append(f"{i}. **{art['title']}** — {art['source']} ({art['time']})")
            if art.get("content"):
                lines.append(f"   > {art['content'][:150]}...")
        lines.append("")

    # ── Research reports ──
    if b.research_reports:
        lines.append("## 机构研报")
        lines.append("| 日期 | 机构 | 评级 | 标题 |")
        lines.append("|------|------|------|------|")
        for rpt in b.research_reports[:8]:
            lines.append(
                f"| {rpt['date']} | {rpt['institution']} "
                f"| {rpt['rating']} | {rpt['title'][:40]} |"
            )
        lines.append("")

    # ── LHB ──
    if b.lhb_records:
        lines.append("## 龙虎榜记录（近30天）")
        for rec in b.lhb_records:
            lines.append(
                f"- {rec['date']}: {rec['reason']} | 净买额 {_fmt_num(rec.get('net_buy'))}"
            )
        lines.append("")

    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────
# Main entry point
# ──────────────────────────────────────────────────────────────────────

# All collectors in execution order
_COLLECTORS = [
    ("basic_info",         _collect_basic_info),
    ("spot_quote",         _collect_spot),
    ("price_history",      _collect_price_history),
    ("valuation_history",  _collect_valuation_history),
    ("financial_summary",  _collect_financial_summary),
    ("financial_ratios",   _collect_financial_ratios),
    ("fund_flow",          _collect_fund_flow),
    ("top10_shareholders", _collect_top10_shareholders),
    ("northbound",         _collect_northbound),
    ("news",               _collect_news),
    ("research_reports",   _collect_research_reports),
    ("lhb",                _collect_lhb),
]


# ──────────────────────────────────────────────────────────────────────
# Market Snapshot — market-level data (run once per day, not per ticker)
# ──────────────────────────────────────────────────────────────────────

@dataclass
class MarketSnapshot:
    """Market-level data snapshot collected once per trading day."""
    trade_date: str = ""

    # Index data: {code: {name, close, change_pct, volume}}
    index_data: dict = field(default_factory=dict)

    # Sector & concept fund flow: list of {name, net_inflow, change_pct, ...}
    sector_fund_flow: list = field(default_factory=list)
    concept_fund_flow: list = field(default_factory=list)

    # Northbound summary: {direction, net_buy, ...}
    northbound_summary: dict = field(default_factory=dict)

    # Breadth
    advance_count: int = 0
    decline_count: int = 0
    limit_up_count: int = 0
    limit_down_count: int = 0
    total_stocks: int = 0
    turnover_total_yi: float = 0  # Total market turnover in 亿

    # Spot data for watchlist stocks (for heatmap)
    stock_spots: dict = field(default_factory=dict)  # {ticker: {name, price, pct_change, market_cap, ...}}

    # Formatted report
    markdown_report: str = ""

    # Collection metadata
    apis_succeeded: list = field(default_factory=list)
    apis_failed: list = field(default_factory=list)

    def to_json(self) -> str:
        """Serialize snapshot to JSON for persistence across pipeline stages."""
        import json as _json
        d = {
            "trade_date": self.trade_date,
            "index_data": self.index_data,
            "sector_fund_flow": self.sector_fund_flow,
            "concept_fund_flow": self.concept_fund_flow,
            "northbound_summary": self.northbound_summary,
            "advance_count": self.advance_count,
            "decline_count": self.decline_count,
            "limit_up_count": self.limit_up_count,
            "limit_down_count": self.limit_down_count,
            "total_stocks": self.total_stocks,
            "turnover_total_yi": self.turnover_total_yi,
            "stock_spots": self.stock_spots,
            "markdown_report": self.markdown_report,
            "apis_succeeded": self.apis_succeeded,
            "apis_failed": self.apis_failed,
        }
        return _json.dumps(d, ensure_ascii=False, indent=2, allow_nan=False, default=str)

    @classmethod
    def from_json(cls, json_str: str) -> "MarketSnapshot":
        """Deserialize snapshot from JSON."""
        import json as _json
        d = _json.loads(json_str)
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


def _collect_index_data(ms: MarketSnapshot):
    """Collect major A-share index data."""
    ak = _get_ak()
    indices = {
        "sh000001": "上证指数",
        "sz399001": "深证成指",
        "sz399006": "创业板指",
    }
    for code, name in indices.items():
        try:
            market = code[:2]
            symbol = code[2:]
            df = ak.stock_zh_index_daily(symbol=code)
            if df is not None and not df.empty:
                latest = df.iloc[-1]
                prev = df.iloc[-2] if len(df) > 1 else latest
                close = float(latest.get("close", 0))
                prev_close = float(prev.get("close", close))
                pct = ((close - prev_close) / prev_close * 100) if prev_close else 0
                ms.index_data[code] = {
                    "name": name,
                    "close": close,
                    "change_pct": round(pct, 2),
                    "volume": float(latest.get("volume", 0)),
                }
        except Exception as e:
            logger.warning(f"  [FAIL] index {code}: {e}")


def _collect_sector_flow(ms: MarketSnapshot):
    """Collect sector (industry) fund flow data.

    Primary: EM stock_sector_fund_flow_rank (push2.eastmoney.com).
    Fallback: THS stock_board_industry_summary_ths (10jqka.com) — has
    涨跌幅 and 净流入 but no 主力净流入-净占比.
    """
    ak = _get_ak()
    df = None
    source = "em"
    try:
        with em_proxy_session():
            df = ak.stock_sector_fund_flow_rank(indicator="今日")
    except Exception as e:
        logger.warning("sector_flow EM failed: %s, trying THS", e)

    if df is None or df.empty:
        # Fallback: THS industry summary
        try:
            df = _retry_call(ak.stock_board_industry_summary_ths)
            source = "ths"
        except Exception as e2:
            logger.warning("sector_flow THS fallback also failed: %s", e2)
            return

    if df is None or df.empty:
        return

    rows = []
    def _row_to_dict(r, src):
        if src == "ths":
            return {
                "name": str(r.get("板块", "")),
                "change_pct": _safe_float(r.get("涨跌幅")),
                "net_inflow": _safe_float(r.get("净流入")),
                "net_pct": 0,
            }
        return {
            "name": str(r.get("名称", "")),
            "change_pct": _safe_float(r.get("今日涨跌幅")),
            "net_inflow": _safe_float(r.get("今日主力净流入-净额")),
            "net_pct": _safe_float(r.get("今日主力净流入-净占比")),
        }

    # Collect ALL sectors, then let downstream sort by change_pct or net_inflow
    # EM returns ~496 rows sorted by net_inflow desc; we keep top 10 + bottom 10
    # by PRICE CHANGE (not net_inflow) to reflect actual market performance.
    pct_col = "涨跌幅" if source == "ths" else "今日涨跌幅"
    df_sorted = df.sort_values(pct_col, ascending=False)
    top_gainers = df_sorted.head(10)
    top_losers = df_sorted.tail(10)
    seen = set()
    for _, r in top_gainers.iterrows():
        d = _row_to_dict(r, source)
        rows.append(d)
        seen.add(d["name"])
    for _, r in top_losers.iterrows():
        d = _row_to_dict(r, source)
        if d["name"] not in seen:
            rows.append(d)
    ms.sector_fund_flow = rows


def _collect_concept_flow(ms: MarketSnapshot):
    """Collect concept theme fund flow data."""
    ak = _get_ak()
    try:
        with em_proxy_session():
            df = ak.stock_board_concept_name_em()
        if df is None or df.empty:
            return
        rows = []
        for _, r in df.head(15).iterrows():
            rows.append({
                "name": str(r.get("板块名称", "")),
                "change_pct": _safe_float(r.get("涨跌幅")),
                "total_market_cap": _safe_float(r.get("总市值")),
                "net_inflow": _safe_float(r.get("主力净流入")),
            })
        ms.concept_fund_flow = rows
    except Exception as e:
        logger.warning("concept_flow collection failed: %s", e)


def _collect_northbound_market(ms: MarketSnapshot):
    """Collect northbound (HSGT) fund flow summary.

    Since 2024-08, China regulators stopped real-time disclosure of
    northbound net inflow data.  The legacy API (stock_hsgt_north_net_flow_in_em)
    has been removed from akshare.  We now use stock_hsgt_fund_flow_summary_em
    which still provides board-level breadth (advance/decline counts within
    northbound-held stocks) even though net flow figures are zeroed out.
    """
    ak = _get_ak()
    try:
        df = ak.stock_hsgt_fund_flow_summary_em()
        if df is None or df.empty:
            ms.northbound_summary = {
                "status": "unavailable",
                "note": "北向资金实时净流入数据已于2024年8月起停止披露（监管政策调整），"
                        "仅季度报告中公布。分析时请勿将数据缺失解读为资金流出。",
            }
            return

        nb = df[df["资金方向"] == "北向"]
        if nb.empty:
            ms.northbound_summary = {
                "status": "unavailable",
                "note": "北向资金数据未返回",
            }
            return

        # Aggregate SH + SZ northbound rows
        total_net_buy = sum((_safe_float(r.get("成交净买额")) or 0) for _, r in nb.iterrows())
        total_net_flow = sum((_safe_float(r.get("资金净流入")) or 0) for _, r in nb.iterrows())
        total_up = sum(int(r.get("上涨数", 0) or 0) for _, r in nb.iterrows())
        total_down = sum(int(r.get("下跌数", 0) or 0) for _, r in nb.iterrows())
        total_flat = sum(int(r.get("持平数", 0) or 0) for _, r in nb.iterrows())
        date_str = str(nb.iloc[0].get("交易日", ""))

        # Detect whether net flow data is actually available
        # (post-2024-08 policy: values are zeroed out)
        flow_available = abs(total_net_buy) > 1e4 or abs(total_net_flow) > 1e4

        summary = {
            "date": date_str,
            "northbound_advance": total_up,
            "northbound_decline": total_down,
            "northbound_flat": total_flat,
        }
        if flow_available:
            summary["net_buy"] = total_net_buy
            summary["net_flow"] = total_net_flow
            summary["direction"] = "买入" if total_net_buy > 0 else "卖出"
            summary["status"] = "available"
        else:
            summary["status"] = "flow_suspended"
            summary["note"] = ("北向资金实时净流入数据已于2024年8月起停止披露（监管政策调整），"
                               "仅季度报告中公布。此处提供北向持股标的涨跌统计作为替代参考。"
                               "分析时请勿将数据缺失解读为资金流出。")
            # Derive directional hint from advance/decline ratio
            if total_up + total_down > 0:
                nb_ratio = total_up / (total_up + total_down)
                summary["northbound_advance_ratio"] = round(nb_ratio, 3)
                summary["direction_hint"] = ("偏多" if nb_ratio > 0.55
                                             else "偏空" if nb_ratio < 0.45
                                             else "中性")

        ms.northbound_summary = summary
    except Exception as e:
        logger.warning(f"Northbound market collection failed: {e}")
        ms.northbound_summary = {
            "status": "error",
            "note": f"北向资金数据采集失败: {e}",
        }


def _collect_breadth_ths(ms: MarketSnapshot):
    """Fallback: derive breadth from THS industry summary (advance/decline per sector)."""
    ak = _get_ak()
    df = ak.stock_board_industry_summary_ths()
    if df is None or df.empty:
        return False
    total_up = int(df["上涨家数"].sum()) if "上涨家数" in df.columns else 0
    total_down = int(df["下跌家数"].sum()) if "下跌家数" in df.columns else 0
    if total_up + total_down == 0:
        return False
    ms.advance_count = total_up
    ms.decline_count = total_down
    ms.total_stocks = total_up + total_down
    # THS summary doesn't provide limit counts directly — leave at 0
    # unless board_data fills them later
    logger.info(f"  [BREADTH] THS fallback: advance={total_up}, decline={total_down}")
    return True


def _collect_breadth(ms: MarketSnapshot, watchlist: list = None):
    """Collect market breadth stats from full A-share spot data.

    Tries EM (stock_zh_a_spot_em) first.  Falls back to THS industry
    summary (stock_board_industry_summary_ths) for advance/decline counts.
    """
    ak = _get_ak()
    try:
        with em_proxy_session():
            df = ak.stock_zh_a_spot_em()
        if df is None or df.empty:
            raise ValueError("empty EM spot data")
    except Exception as e:
        logger.warning(f"  [BREADTH] EM spot failed ({e}), trying THS fallback")
        _collect_breadth_ths(ms)
        # Watchlist spots via XQ fallback
        if watchlist:
            _collect_watchlist_spots_xq(ms, watchlist)
        return

    ms.total_stocks = len(df)
    pct_col = "涨跌幅"
    if pct_col in df.columns:
        advances = df[df[pct_col] > 0]
        declines = df[df[pct_col] < 0]
        ms.advance_count = len(advances)
        ms.decline_count = len(declines)

        # Count limit-up and limit-down with board-specific thresholds:
        # ST: ±4.9%, ChiNext(3xx)/STAR(68x): ±19.9%, main board: ±9.9%
        code_col = "代码" if "代码" in df.columns else "股票代码"
        name_col = "名称" if "名称" in df.columns else "股票名称"
        limit_up = 0
        limit_down = 0
        for _, r in df.iterrows():
            pct = r.get(pct_col, 0) or 0
            code = str(r.get(code_col, ""))
            name = str(r.get(name_col, ""))
            is_st = "ST" in name
            is_bje = code.startswith(("8", "4"))
            is_chinext_star = code.startswith("3") or code.startswith("68")
            threshold = 4.9 if is_st else (29.9 if is_bje else (19.9 if is_chinext_star else 9.9))
            if pct >= threshold:
                limit_up += 1
            elif pct <= -threshold:
                limit_down += 1
        ms.limit_up_count = limit_up
        ms.limit_down_count = limit_down

    # Total market turnover
    amt_col = "成交额" if "成交额" in df.columns else "总成交额"
    if amt_col in df.columns:
        ms.turnover_total_yi = round(float(df[amt_col].sum()) / 1e8, 2)

    # Extract spot data for watchlist stocks
    if watchlist:
        for ticker in watchlist:
            bare = ticker.replace(".SS", "").replace(".SZ", "").replace(".BJ", "")
            row = df[df["代码"] == bare]
            if not row.empty:
                r = row.iloc[0]
                ms.stock_spots[bare] = {
                    "name": str(r.get("名称", "")),
                    "price": _safe_float(r.get("最新价")),
                    "pct_change": _safe_float(r.get("涨跌幅")),
                    "market_cap": _safe_float(r.get("总市值")),
                    "pe": _safe_float(r.get("市盈率-动态")),
                    "pb": _safe_float(r.get("市净率")),
                    "turnover_rate": _safe_float(r.get("换手率")),
                }


def _collect_watchlist_spots_xq(ms: MarketSnapshot, watchlist: list):
    """Fallback: fetch watchlist stock spots from XQ (雪球) when EM is down."""
    ak = _get_ak()
    for ticker in watchlist:
        bare = ticker.replace(".SS", "").replace(".SZ", "").replace(".BJ", "")
        prefix = "SH" if bare.startswith("6") else "SZ"
        try:
            spot = ak.stock_individual_spot_xq(symbol=f"{prefix}{bare}")
            if spot is None or spot.empty:
                continue
            vals = dict(zip(spot["item"], spot["value"]))
            ms.stock_spots[bare] = {
                "name": str(vals.get("名称", "")),
                "price": _safe_float(vals.get("现价")),
                "pct_change": _safe_float(vals.get("涨幅")),
                "market_cap": _safe_float(vals.get("流通值", 0)),
                "pe": _safe_float(vals.get("市盈率(动)", 0)),
                "pb": _safe_float(vals.get("市净率", 0)),
                "turnover_rate": _safe_float(vals.get("周转率", 0)),
            }
        except Exception as _e:
            logger.debug("stock spot parse failed: %s", _e)
            continue


def _build_market_markdown(ms: MarketSnapshot) -> str:
    """Format MarketSnapshot as markdown for agent consumption."""
    lines = [f"# A股市场快照 — {ms.trade_date}"]
    lines.append("")

    # Index data
    if ms.index_data:
        lines.append("## 主要指数")
        lines.append("| 指数 | 收盘 | 涨跌幅 |")
        lines.append("|------|------|--------|")
        for code, info in ms.index_data.items():
            pct = info.get("change_pct", 0)
            sign = "+" if pct > 0 else ""
            lines.append(f"| {info['name']} | {info['close']:.2f} | {sign}{pct:.2f}% |")
        lines.append("")

    # Breadth
    lines.append("## 市场宽度")
    total = ms.advance_count + ms.decline_count
    ratio = ms.advance_count / total if total > 0 else 0
    lines.append(f"- 上涨家数: {ms.advance_count} / 下跌家数: {ms.decline_count} (涨跌比 {ratio:.2f})")
    lines.append(f"- 涨停: {ms.limit_up_count} / 跌停: {ms.limit_down_count}")
    if ms.turnover_total_yi > 0:
        lines.append(f"- 全市场成交额: {ms.turnover_total_yi:.0f}亿")
    lines.append(f"- 全市场股票数: {ms.total_stocks}")
    lines.append("")

    # Northbound
    if ms.northbound_summary:
        nb = ms.northbound_summary
        status = nb.get("status", "")
        lines.append("## 北向资金")
        if status == "available":
            lines.append(f"- 方向: {nb.get('direction', '—')}")
            net = nb.get("net_buy")
            if net is not None:
                lines.append(f"- 净流入: {net / 1e8:.2f}亿元" if abs(net) > 1e6 else f"- 净流入: {net:.0f}")
        elif status == "flow_suspended":
            lines.append(f"- ⚠️ {nb.get('note', '净流入数据暂不可用')}")
            adv = nb.get("northbound_advance", 0)
            dec = nb.get("northbound_decline", 0)
            if adv or dec:
                ratio_str = f" (涨跌比 {adv / (adv + dec):.2f})" if (adv + dec) > 0 else ""
                lines.append(f"- 北向持股标的: 上涨 {adv} / 下跌 {dec}{ratio_str}")
            hint = nb.get("direction_hint")
            if hint:
                lines.append(f"- 方向推断（基于持股标的涨跌比）: {hint}")
        else:
            note = nb.get("note", "北向资金数据不可用")
            lines.append(f"- ⚠️ {note}")
        lines.append("")

    # Sector flow — sorted by actual price change, not net_inflow
    if ms.sector_fund_flow:
        gainers = sorted([s for s in ms.sector_fund_flow if (s.get("change_pct", 0) or 0) > 0],
                         key=lambda x: x.get("change_pct", 0) or 0, reverse=True)
        losers = sorted([s for s in ms.sector_fund_flow if (s.get("change_pct", 0) or 0) < 0],
                        key=lambda x: x.get("change_pct", 0) or 0)

        def _fmt_sector_row(s):
            pct = s.get("change_pct", 0) or 0
            net = s.get("net_inflow", 0) or 0
            net_str = f"{net / 1e8:+.2f}亿" if abs(net) > 1e6 else f"{net:+.0f}"
            return f"| {s['name']} | {pct:+.2f}% | {net_str} |"

        lines.append("## 行业板块涨幅 Top 10")
        lines.append("| 板块 | 涨跌幅 | 主力净流入 |")
        lines.append("|------|--------|----------|")
        for s in gainers[:10]:
            lines.append(_fmt_sector_row(s))

        if losers:
            lines.append("")
            lines.append("## 行业板块跌幅 Top 10")
            lines.append("| 板块 | 涨跌幅 | 主力净流入 |")
            lines.append("|------|--------|----------|")
            for s in losers[:10]:
                lines.append(_fmt_sector_row(s))
        lines.append("")

    # Concept flow
    if ms.concept_fund_flow:
        lines.append("## 概念板块 (Top 10)")
        lines.append("| 板块 | 涨跌幅 | 主力净流入 |")
        lines.append("|------|--------|----------|")
        for c in ms.concept_fund_flow[:10]:
            pct = c.get("change_pct", 0) or 0
            net = c.get("net_inflow", 0) or 0
            net_str = f"+{net/1e8:.2f}亿" if net > 0 else (f"{net/1e8:.2f}亿" if net else "—")
            lines.append(f"| {c['name']} | {pct:.2f}% | {net_str} |")
        lines.append("")

    return "\n".join(lines)


# Market-level collectors
_MARKET_COLLECTORS = [
    ("index_data",      _collect_index_data),
    ("sector_flow",     _collect_sector_flow),
    ("concept_flow",    _collect_concept_flow),
    ("northbound",      _collect_northbound_market),
]


# Major CN public holidays — approximate ranges by year.
# The State Council announces exact dates each year.  Update annually.
# TODO(2027): add 2027 holidays when State Council publishes them.

_CN_HOLIDAYS_2025 = {
    # New Year's Day
    "2025-01-01",
    # Spring Festival (Feb 10 – Feb 16)
    "2025-02-10", "2025-02-11", "2025-02-12",
    "2025-02-13", "2025-02-14", "2025-02-15", "2025-02-16",
    # Qingming Festival
    "2025-04-04", "2025-04-05", "2025-04-06",
    # Labor Day
    "2025-05-01", "2025-05-02", "2025-05-03", "2025-05-04", "2025-05-05",
    # Dragon Boat Festival
    "2025-05-31", "2025-06-01", "2025-06-02",
    # Mid-Autumn Festival
    "2025-10-06", "2025-10-07", "2025-10-08",
    # National Day
    "2025-10-01", "2025-10-02", "2025-10-03", "2025-10-04",
    "2025-10-05", "2025-10-06", "2025-10-07",
}

_CN_HOLIDAYS_2026 = {
    # New Year's Day
    "2026-01-01",
    # Spring Festival (approx Jan 29 – Feb 4)
    "2026-01-29", "2026-01-30", "2026-01-31",
    "2026-02-01", "2026-02-02", "2026-02-03", "2026-02-04",
    # Qingming Festival
    "2026-04-04", "2026-04-05", "2026-04-06",
    # Labor Day
    "2026-05-01", "2026-05-02", "2026-05-03", "2026-05-04", "2026-05-05",
    # Dragon Boat Festival
    "2026-06-19", "2026-06-20", "2026-06-21",
    # Mid-Autumn Festival
    "2026-09-27", "2026-09-28", "2026-09-29",
    # National Day
    "2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04",
    "2026-10-05", "2026-10-06", "2026-10-07",
}

# Union of all year sets for efficient lookup
_CN_HOLIDAYS = _CN_HOLIDAYS_2025 | _CN_HOLIDAYS_2026
_CN_HOLIDAYS_MAX_YEAR = 2026  # bump when adding next year's holidays


def _is_cn_trading_day(date_str: str) -> bool:
    """Check if a date is a potential A-share trading day.

    WARNING: Holiday calendar only covers up to {_CN_HOLIDAYS_MAX_YEAR}.
    Dates beyond that year fall back to weekday-only check.

    Checks both weekends and major 2026 CN public holidays.
    Returns True for likely trading days, False otherwise.
    """
    try:
        dt = datetime.strptime(date_str[:10], "%Y-%m-%d")
        if dt.year > _CN_HOLIDAYS_MAX_YEAR:
            logger.warning(
                "Holiday calendar expired: %d > %d. "
                "Falling back to weekday-only check. Update _CN_HOLIDAYS.",
                dt.year, _CN_HOLIDAYS_MAX_YEAR,
            )
        if dt.weekday() >= 5:  # Sat/Sun
            return False
        if date_str[:10] in _CN_HOLIDAYS:
            return False
        return True
    except (ValueError, TypeError):
        return True  # assume trading day if date is unparseable


def _last_trading_day(date_str: str) -> str:
    """Roll back to the most recent trading day (skips weekends and CN holidays)."""
    try:
        dt = datetime.strptime(date_str[:10], "%Y-%m-%d")
        while dt.weekday() >= 5 or dt.strftime("%Y-%m-%d") in _CN_HOLIDAYS:
            dt -= timedelta(days=1)
        return dt.strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return date_str


def collect_market_snapshot(
    trade_date: str = "",
    watchlist: list = None,
) -> MarketSnapshot:
    """Collect market-level snapshot data (run once per trading day).

    Args:
        trade_date: Analysis date (default: today)
        watchlist: List of ticker codes for extracting spot data (e.g. ["601985", "300627"])

    Returns:
        MarketSnapshot with market-level data + markdown report
    """
    effective_date = trade_date or datetime.now().strftime("%Y-%m-%d")
    if not _is_cn_trading_day(effective_date):
        rolled = _last_trading_day(effective_date)
        logger.warning(
            f"Trade date {effective_date} is a weekend — "
            f"rolling back to last trading day {rolled}. "
            f"Some real-time APIs may still return stale data."
        )
        effective_date = rolled
    ms = MarketSnapshot(
        trade_date=effective_date,
    )

    # Run standard market collectors
    for api_name, collector_fn in _MARKET_COLLECTORS:
        try:
            _retry_call(collector_fn, ms)
            ms.apis_succeeded.append(api_name)
            logger.info(f"  [OK] market {api_name}")
        except Exception as e:
            ms.apis_failed.append(api_name)
            logger.warning(f"  [FAIL] market {api_name}: {e}")

    # Breadth + watchlist spots (uses same API call)
    try:
        _retry_call(_collect_breadth, ms, watchlist=watchlist)
        ms.apis_succeeded.append("breadth")
    except Exception as e:
        ms.apis_failed.append("breadth")
        logger.warning(f"  [FAIL] market breadth: {e}")

    ms.markdown_report = _build_market_markdown(ms)
    logger.info(f"Market snapshot: {len(ms.apis_succeeded)}/{len(ms.apis_succeeded)+len(ms.apis_failed)} APIs OK")
    return ms


def collect(ticker: str, trade_date: str = "", *, use_cache: bool = True) -> AkshareBundle:
    """Collect all available akshare data for a single A-share ticker.

    Args:
        ticker: 6-digit A-share code (e.g. "601985")
        trade_date: Analysis date (default: today)
        use_cache: If True, return cached bundle when available for
            the same ticker+date.  Same-day re-runs skip API calls.

    Returns:
        AkshareBundle with structured data + markdown report
    """
    from .data_cache import DataCache

    # Strip suffix if present
    bare = ticker.replace(".SS", "").replace(".SZ", "").replace(".BJ", "")
    if not re.match(r'^\d{6}$', bare):
        raise ValueError(f"Invalid A-share ticker: {bare!r}")

    effective_date = trade_date or datetime.now().strftime("%Y-%m-%d")
    if not _is_cn_trading_day(effective_date):
        rolled = _last_trading_day(effective_date)
        logger.warning(
            f"Trade date {effective_date} is a weekend — "
            f"rolling back to last trading day {rolled}."
        )
        effective_date = rolled

    # ── Cache check (bundle-level) ──
    cache = DataCache()
    if use_cache:
        cached = cache.get("collect_bundle", bare, effective_date)
        if cached is not None:
            try:
                b = AkshareBundle(**{k: v for k, v in cached.items()
                                     if k in AkshareBundle.__dataclass_fields__})
                logger.info(f"Cache HIT: {bare} {effective_date} ({b.name})")
                return b
            except (TypeError, ValueError) as e:
                logger.debug("Cache deserialize failed, re-collecting: %s", e)

    b = AkshareBundle(
        ticker=bare,
        trade_date=effective_date,
    )

    t0 = time.time()

    for api_name, collector_fn in _COLLECTORS:
        try:
            _retry_call(collector_fn, b)
            b.apis_succeeded.append(api_name)
            logger.info(f"  [OK] {bare} {api_name}")
        except Exception as e:
            b.apis_failed.append(api_name)
            logger.warning(f"  [FAIL] {bare} {api_name}: {e}")

    b.collection_seconds = time.time() - t0
    b.markdown_report = _build_markdown(b)

    # ── Cache store ──
    if use_cache and b.apis_succeeded:
        try:
            bundle_dict = {k: v for k, v in b.__dict__.items()
                          if not k.startswith("_")}
            cache.put("collect_bundle", bare, effective_date, bundle_dict)
        except Exception as e:
            logger.debug("Cache write failed: %s", e)

    logger.info(
        f"Collected {bare} {b.name}: "
        f"{len(b.apis_succeeded)}/{len(b.apis_succeeded)+len(b.apis_failed)} APIs OK, "
        f"{b.collection_seconds:.1f}s"
    )
    return b


# ──────────────────────────────────────────────────────────────────────
# Sector constituent stocks (for treemap drill-down)
# ──────────────────────────────────────────────────────────────────────

def _build_ths_to_sw_map() -> dict:
    """Build THS sector name -> SW second-level industry code mapping.

    Returns ``{ths_name: sw_code}`` e.g. ``{"半导体": "801081"}``.
    """
    ak = _get_ak()
    try:
        sw2 = ak.sw_index_second_info()
    except Exception as _e:
        logger.debug("sw_index_second_info failed: %s", _e)
        return {}

    sw_by_name: dict = {}
    sw_stripped: dict = {}
    for _, row in sw2.iterrows():
        code = str(row["行业代码"]).replace(".SI", "")
        name = str(row["行业名称"])
        sw_by_name[name] = code
        stripped = name.rstrip("Ⅱ").rstrip()
        if stripped != name:
            sw_stripped[stripped] = code

    try:
        ths = ak.stock_board_industry_name_ths()
    except Exception as _e:
        logger.debug("stock_board_industry_name_ths failed: %s", _e)
        return {}

    mapping: dict = {}
    for _, row in ths.iterrows():
        ths_name = str(row["name"])
        if ths_name in sw_by_name:
            mapping[ths_name] = sw_by_name[ths_name]
        elif ths_name in sw_stripped:
            mapping[ths_name] = sw_stripped[ths_name]
    return mapping


def _collect_sector_stocks_sw(
    sector_names: list,
    ths_sw_map: dict,
    top_n: int = 8,
    max_sectors: int = 20,
) -> dict:
    """Fallback: fetch constituent stocks via SW index + XQ spot data."""
    ak = _get_ak()
    result: dict = {}
    if not sector_names or not ths_sw_map:
        return result

    for name in sector_names[:max_sectors]:
        if not name:
            continue
        sw_code = ths_sw_map.get(name)
        if not sw_code:
            continue
        try:
            cons = ak.index_component_sw(symbol=sw_code)
            if cons is None or cons.empty:
                continue
            cons = cons.sort_values("最新权重", ascending=False).head(top_n)
            stocks = []
            for _, row in cons.iterrows():
                ticker = str(row.get("证券代码", ""))
                sname = str(row.get("证券名称", ""))
                pct_change = 0.0
                try:
                    prefix = "SH" if ticker.startswith("6") else "SZ"
                    spot = ak.stock_individual_spot_xq(symbol=f"{prefix}{ticker}")
                    pct_row = spot[spot["item"] == "涨幅"]
                    if not pct_row.empty:
                        pct_change = float(pct_row["value"].values[0] or 0)
                except Exception:
                    pass
                stocks.append({
                    "ticker": ticker,
                    "name": sname,
                    "pct_change": pct_change,
                    "market_cap_yi": 0,
                    "amount_yi": 0,
                })
            if stocks:
                result[name] = stocks
            time.sleep(0.3)
        except Exception:
            continue
    return result


def collect_sector_leader_stocks(
    sector_names: list,
    top_n: int = 8,
    max_sectors: int = 20,
) -> dict:
    """Fetch top constituent stocks per sector for treemap drill-down.

    Returns {sector_name: [{ticker, name, pct_change, market_cap_yi, amount_yi}]}.
    Primary: EM (stock_board_industry_cons_em).
    Fallback: SW index (index_component_sw) + XQ spot after 3 consecutive EM failures.
    """
    ak = _get_ak()
    result: dict = {}
    if not sector_names:
        return result

    consecutive_failures = 0
    for name in sector_names[:max_sectors]:
        if not name:
            continue
        try:
            with em_proxy_session():
                df = _retry_call(ak.stock_board_industry_cons_em, symbol=name)
            if df is None or df.empty:
                continue
            if "总市值" in df.columns:
                df = df.sort_values("总市值", ascending=False)
            stocks = []
            for _, row in df.head(top_n).iterrows():
                mcap = float(row.get("总市值", 0) or 0)
                stocks.append({
                    "ticker": str(row.get("代码", "")),
                    "name": str(row.get("名称", "")),
                    "pct_change": round(float(row.get("涨跌幅", 0) or 0), 2),
                    "market_cap_yi": round(mcap / 1e8, 2) if mcap > 0 else 0,
                    "amount_yi": round(float(row.get("成交额", 0) or 0) / 1e8, 2),
                })
            if stocks:
                result[name] = stocks
                consecutive_failures = 0
            time.sleep(0.3)
        except Exception as e:
            consecutive_failures += 1
            logger.warning(f"sector_cons {name}: {e}")
            if consecutive_failures >= 3:
                logger.warning("sector_cons EM failed 3x, switching to SW+XQ fallback")
                ths_sw_map = _build_ths_to_sw_map()
                if ths_sw_map:
                    remaining = [n2 for n2 in sector_names[:max_sectors]
                                 if n2 and n2 not in result]
                    sw_result = _collect_sector_stocks_sw(
                        remaining, ths_sw_map, top_n=top_n, max_sectors=max_sectors,
                    )
                    result.update(sw_result)
                    logger.info("SW+XQ fallback: %d sectors fetched", len(sw_result))
                break
            time.sleep(0.5)

    return result


# ---------------------------------------------------------------------------
# Board data: limit-up/down stocks, consecutive boards, sector attribution
# ---------------------------------------------------------------------------

def collect_board_data(trade_date: str, max_sectors: int = 20,
                       top_n: int = 10) -> dict:
    """Collect board data for the market report renderer.

    Returns a dict with keys: trade_date, sectors, limit_ups, limit_downs,
    consecutive_boards, limit_sector_attribution, sector_stocks.
    All akshare calls are wrapped with _retry_call + em_proxy_session.
    Fail-open: each section is independent — a single failure does not
    block the rest.
    """
    ak = _get_ak()
    date_fmt = trade_date.replace("-", "")
    board: dict = {"trade_date": trade_date}

    # 1. Sector heatmap (THS)
    try:
        df = _retry_call(ak.stock_board_industry_summary_ths)
        sectors = []
        for _, row in df.head(80).iterrows():
            sectors.append({
                "sector": str(row.get("板块", "")),
                "pct_change": float(row.get("涨跌幅", 0) or 0),
                "total_turnover_yi": round(float(row.get("总成交额", 0) or 0), 2),
                "net_flow_yi": round(float(row.get("净流入", 0) or 0), 2),
                "advance_count": int(row.get("上涨家数", 0) or 0),
                "decline_count": int(row.get("下跌家数", 0) or 0),
                "leader": str(row.get("领涨股", "") or ""),
                "leader_pct": float(row.get("领涨股-涨跌幅", 0) or 0),
            })
        board["sectors"] = sectors
        logger.info("board sectors: %d collected", len(sectors))
    except Exception as e:
        logger.warning("board sectors failed: %s", e)
        board["sectors"] = []

    # 2. Limit-up stocks (EM)
    try:
        with em_proxy_session():
            df_zt = _retry_call(ak.stock_zt_pool_em, date=date_fmt)
        limit_ups = []
        for _, row in df_zt.iterrows():
            limit_ups.append({
                "ticker": str(row.get("代码", "")),
                "name": str(row.get("名称", "")),
                "pct_change": float(row.get("涨跌幅", 0) or 0),
                "amount_yi": round(float(row.get("成交额", 0) or 0) / 1e8, 2),
                "boards": int(row.get("连板数", 1) or 1),
                "sector": str(row.get("所属行业", "") or ""),
                "seal_amount_yi": round(
                    float(row.get("封板资金", 0) or 0) / 1e8, 2),
                "first_seal": str(row.get("首次封板时间", "") or ""),
            })
        board["limit_ups"] = limit_ups
        logger.info("board limit_ups: %d stocks", len(limit_ups))
    except Exception as e:
        logger.warning("board limit_ups failed: %s", e)
        board["limit_ups"] = []

    # 3. Limit-down stocks (EM)
    try:
        with em_proxy_session():
            df_dt = _retry_call(ak.stock_zt_pool_dtgc_em, date=date_fmt)
        limit_downs = []
        for _, row in df_dt.iterrows():
            limit_downs.append({
                "ticker": str(row.get("代码", "")),
                "name": str(row.get("名称", "")),
                "pct_change": float(row.get("涨跌幅", 0) or 0),
                "amount_yi": round(
                    float(row.get("成交额", 0) or 0) / 1e8, 2),
                "sector": str(row.get("所属行业", "") or ""),
            })
        board["limit_downs"] = limit_downs
        logger.info("board limit_downs: %d stocks", len(limit_downs))
    except Exception as e:
        logger.warning("board limit_downs failed: %s", e)
        board["limit_downs"] = []

    # 4. Consecutive boards (derived from limit_ups)
    consec: dict = {}
    for s in board.get("limit_ups", []):
        b = s.get("boards", 1)
        consec.setdefault(b, []).append(s)
    board["consecutive_boards"] = {
        str(k): v for k, v in sorted(consec.items())
    }

    # 5. Sector attribution (derived from limit_ups)
    sector_agg: dict = {}
    for s in board.get("limit_ups", []):
        sec = s.get("sector", "")
        if sec:
            if sec not in sector_agg:
                sector_agg[sec] = {"count": 0, "stocks": []}
            sector_agg[sec]["count"] += 1
            sector_agg[sec]["stocks"].append(s["name"])
    board["limit_sector_attribution"] = dict(
        sorted(sector_agg.items(), key=lambda x: x[1]["count"], reverse=True)
    )

    # 6. Sector constituent stocks (for treemap drill-down)
    sector_names = [s["sector"] for s in board.get("sectors", []) if s.get("sector")]
    if sector_names:
        sector_stocks = collect_sector_leader_stocks(
            sector_names, top_n=top_n, max_sectors=max_sectors,
        )
        board["sector_stocks"] = sector_stocks
        logger.info("board sector_stocks: %d sectors, %d stocks total",
                     len(sector_stocks),
                     sum(len(v) for v in sector_stocks.values()))
    else:
        board["sector_stocks"] = {}

    return board

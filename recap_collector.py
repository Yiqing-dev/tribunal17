"""Daily recap data collectors — pure data aggregation via akshare, no LLM.

Collects: indices (with technicals), sectors, limit boards, consecutive boards,
red close screen. All via akshare APIs with graceful fallbacks.

Usage:
    from subagent_pipeline.recap_collector import collect_daily_recap
    data = collect_daily_recap("2026-03-13")
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from .akshare_collector import _retry_call

logger = logging.getLogger(__name__)

_ak = None


def _get_ak():
    global _ak
    if _ak is None:
        import akshare as ak
        _ak = ak
    return _ak


# ── Configuration ────────────────────────────────────────────────────

RECAP_CONFIG = {
    "resonance_threshold_pct": 7.0,
    "red_close_window_days": 14,
    "red_close_thresholds": [6, 8],
    "red_close_pool_size": 100,
    "sector_detail_count": 10,
    "index_history_days": 60,
    "indices": [
        ("sh000001", "上证指数"),
        ("sz399001", "深证成指"),
        ("sh000300", "沪深300"),
        ("sz399006", "创业板指"),
        ("sh000688", "科创50"),
    ],
}


# ── Technical Indicators ─────────────────────────────────────────────

def _safe_float(val) -> Optional[float]:
    if val is None:
        return None
    try:
        v = float(val)
        return v if v == v else None
    except (ValueError, TypeError):
        return None


def _sma(closes: List[float], period: int) -> List[Optional[float]]:
    """Simple Moving Average."""
    result = []
    for i in range(len(closes)):
        if i < period - 1:
            result.append(None)
        else:
            result.append(sum(closes[i - period + 1:i + 1]) / period)
    return result


def _ema(values: List[float], period: int) -> List[float]:
    """Exponential Moving Average."""
    if not values:
        return []
    k = 2.0 / (period + 1)
    result = [values[0]]
    for v in values[1:]:
        result.append(v * k + result[-1] * (1 - k))
    return result


def _compute_rsi(closes: List[float], period: int = 14) -> List[float]:
    """Relative Strength Index (Wilder smoothing)."""
    n = len(closes)
    if n < 2:
        return [50.0] * n
    deltas = [closes[i] - closes[i - 1] for i in range(1, n)]
    gains = [max(d, 0) for d in deltas]
    losses = [max(-d, 0) for d in deltas]

    result = [50.0]  # first close has no delta → neutral RSI
    if len(gains) < period:
        return [50.0] * n

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    # Pad with neutral values for the initial period where RSI is undefined.
    # We need (period - 1) padding values: indices 1..period-1 in the deltas
    # correspond to closes 1..period-1; the first real RSI is at close[period].
    for _ in range(period - 1):
        result.append(50.0)
    # First real RSI value from simple average
    if avg_loss == 0:
        result.append(100.0)
    else:
        rs = avg_gain / avg_loss
        result.append(round(100.0 - 100.0 / (1.0 + rs), 2))
    # Wilder smoothing for subsequent values
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            result.append(100.0)
        else:
            rs = avg_gain / avg_loss
            result.append(round(100.0 - 100.0 / (1.0 + rs), 2))
    return result


def _compute_macd(
    closes: List[float], fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple:
    """MACD: returns (dif[], dea[], hist[])."""
    if not closes:
        return [], [], []
    ema_fast = _ema(closes, fast)
    ema_slow = _ema(closes, slow)
    dif = [round(f - s, 4) for f, s in zip(ema_fast, ema_slow)]
    dea = _ema(dif, signal)
    dea = [round(d, 4) for d in dea]
    hist = [round(2 * (d - e), 4) for d, e in zip(dif, dea)]
    return dif, dea, hist


# ── Data Contracts ───────────────────────────────────────────────────

@dataclass
class IndexPoint:
    """Single day data point for an index."""
    date: str = ""
    open: float = 0
    high: float = 0
    low: float = 0
    close: float = 0
    volume: float = 0
    amount: float = 0
    change_pct: float = 0
    ma5: Optional[float] = None
    ma14: Optional[float] = None
    ma30: Optional[float] = None
    rsi: float = 50.0
    macd_dif: float = 0
    macd_dea: float = 0
    macd_hist: float = 0


@dataclass
class IndexInfo:
    """One index with history and current stats."""
    code: str = ""
    name: str = ""
    points: List[Dict] = field(default_factory=list)
    close: float = 0
    pct_change: float = 0
    turnover_yi: float = 0


@dataclass
class IndexSummary:
    """All-index summary for the day."""
    date: str = ""
    indices: List[Dict] = field(default_factory=list)
    turnover_total_yi: float = 0
    turnover_delta_yi: float = 0
    turnover_prev_yi: float = 0
    northbound_flow_yi: float = 0
    advancers: int = 0
    decliners: int = 0
    flat: int = 0


@dataclass
class SectorNode:
    """One sector in the heatmap."""
    sector: str = ""
    pct_change: float = 0
    turnover_yi: float = 0
    market_cap_yi: float = 0
    index_contrib: float = 0
    leaders: List[Dict] = field(default_factory=list)
    laggards: List[Dict] = field(default_factory=list)
    resonance_stocks: List[Dict] = field(default_factory=list)


@dataclass
class SectorHeatmapData:
    """Sector heatmap data."""
    date: str = ""
    nodes: List[Dict] = field(default_factory=list)


@dataclass
class LimitStock:
    """A stock at limit up or limit down."""
    ticker: str = ""
    name: str = ""
    sector: str = ""
    boards: int = 1
    pct_change: float = 0
    amount_yi: float = 0
    is_limit_up: bool = True


@dataclass
class LimitBoardSummary:
    """Limit up/down summary."""
    limit_up_count: int = 0
    limit_down_count: int = 0
    limit_up_stocks: List[Dict] = field(default_factory=list)
    limit_down_stocks: List[Dict] = field(default_factory=list)


@dataclass
class ConsecutiveBoardLevel:
    """One level in the consecutive board ladder."""
    level: int = 1
    label: str = ""
    count: int = 0
    prev_count: int = 0       # previous level's count yesterday (for promotion rate)
    promotion_rate: float = 0  # count / prev_count (0 if unknown)
    stocks: List[Dict] = field(default_factory=list)


@dataclass
class RedCloseScreen:
    """14-day red close screening result."""
    window_natural_days: int = 14
    window_trade_days: int = 0
    red_close_6: List[Dict] = field(default_factory=list)
    red_close_8: List[Dict] = field(default_factory=list)


@dataclass
class DailyRecapData:
    """Complete daily recap data bundle."""
    date: str = ""
    index_summary: Dict = field(default_factory=dict)
    sector_heatmap: Dict = field(default_factory=dict)
    limit_board: Dict = field(default_factory=dict)
    consecutive_boards: List[Dict] = field(default_factory=list)
    red_close: Dict = field(default_factory=dict)
    # Derived market assessment (data-driven, no LLM)
    market_weather: str = ""       # 上涨 / 震荡 / 下跌
    position_advice: str = ""      # 进攻 / 中性 / 防守
    risk_note: str = ""
    one_line_summary: str = ""
    collection_seconds: float = 0
    # AI market layer context (from 3 market agents, injected externally)
    market_context: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2, default=str)


# ── Collectors ───────────────────────────────────────────────────────

def _col_name(df, *candidates):
    """Find first matching column name from candidates."""
    for c in candidates:
        if c in df.columns:
            return c
    return candidates[0]


def _collect_index_history(code: str, name: str, days: int = 60) -> IndexInfo:
    """Collect index OHLCV history and compute technicals."""
    ak = _get_ak()
    df = ak.stock_zh_index_daily(symbol=code)
    if df is None or df.empty:
        return IndexInfo(code=code, name=name)

    df = df.tail(days).reset_index(drop=True)
    date_c = _col_name(df, "date", "日期")
    close_c = _col_name(df, "close", "收盘")
    open_c = _col_name(df, "open", "开盘")
    high_c = _col_name(df, "high", "最高")
    low_c = _col_name(df, "low", "最低")
    vol_c = _col_name(df, "volume", "成交量")

    closes = [float(r[close_c]) for _, r in df.iterrows()]
    ma5 = _sma(closes, 5)
    ma14 = _sma(closes, 14)
    ma30 = _sma(closes, 30)
    rsi = _compute_rsi(closes, 14)
    dif, dea, hist = _compute_macd(closes)

    points = []
    for i, (_, r) in enumerate(df.iterrows()):
        c = float(r[close_c])
        o = float(r.get(open_c, c))
        prev_c = closes[i - 1] if i > 0 else c
        pct = ((c - prev_c) / prev_c * 100) if prev_c != 0 else 0
        amt = _safe_float(r.get("amount", r.get("成交额", 0))) or 0
        points.append({
            "date": str(r[date_c])[:10],
            "open": round(o, 2),
            "high": round(float(r.get(high_c, c)), 2),
            "low": round(float(r.get(low_c, c)), 2),
            "close": round(c, 2),
            "volume": _safe_float(r.get(vol_c, 0)) or 0,
            "amount": amt,
            "change_pct": round(pct, 2),
            "ma5": round(ma5[i], 2) if ma5[i] is not None else None,
            "ma14": round(ma14[i], 2) if ma14[i] is not None else None,
            "ma30": round(ma30[i], 2) if ma30[i] is not None else None,
            "rsi": rsi[i] if i < len(rsi) else 50.0,
            "macd_dif": dif[i] if i < len(dif) else 0,
            "macd_dea": dea[i] if i < len(dea) else 0,
            "macd_hist": hist[i] if i < len(hist) else 0,
        })

    latest = points[-1] if points else {}
    # Turnover in 亿
    turnover = sum(p.get("amount", 0) for p in points[-1:]) / 1e8 if points else 0

    return IndexInfo(
        code=code, name=name,
        points=points,
        close=latest.get("close", 0),
        pct_change=latest.get("change_pct", 0),
        turnover_yi=round(turnover, 2),
    )


def collect_index_summary(trade_date: str = "") -> IndexSummary:
    """Collect all major index data + breadth stats."""
    ak = _get_ak()
    indices = []
    for code, name in RECAP_CONFIG["indices"]:
        try:
            info = _collect_index_history(code, name, RECAP_CONFIG["index_history_days"])
            indices.append(asdict(info))
            logger.info(f"  [OK] index {code} {name}")
        except Exception as e:
            logger.warning(f"  [FAIL] index {code}: {e}")
            indices.append(asdict(IndexInfo(code=code, name=name)))

    # Breadth from spot data
    advancers = decliners = flat = 0
    turnover_total = 0
    try:
        spot_df = ak.stock_zh_a_spot_em()
        pct_col = "涨跌幅"
        if pct_col in spot_df.columns:
            advancers = int((spot_df[pct_col] > 0).sum())
            decliners = int((spot_df[pct_col] < 0).sum())
            flat = int((spot_df[pct_col] == 0).sum())
        amt_col = "成交额"
        if amt_col in spot_df.columns:
            turnover_total = float(spot_df[amt_col].sum()) / 1e8
    except Exception as e:
        logger.warning(f"  [FAIL] spot breadth: {e}")

    # Previous day turnover for delta — use Shanghai index history as proxy.
    # NOTE: This is a rough approximation. Shanghai index volume does not perfectly
    # track total market turnover (misses ChiNext, STAR, Shenzhen-only stocks).
    # The result is only used for turnover_delta direction, not absolute values.
    turnover_prev = 0
    try:
        sh_idx = next((ix for ix in indices if ix.get("code") == "sh000001"), None)
        if sh_idx:
            pts = sh_idx.get("points", [])
            if len(pts) >= 2:
                today_amt = pts[-1].get("volume", 0) or pts[-1].get("amount", 0)
                prev_amt = pts[-2].get("volume", 0) or pts[-2].get("amount", 0)
                if prev_amt > 0 and today_amt > 0 and turnover_total > 0:
                    ratio = today_amt / prev_amt
                    turnover_prev = turnover_total / ratio
    except Exception:
        pass

    turnover_delta = turnover_total - turnover_prev if turnover_prev > 0 else 0

    # Northbound
    nb_flow = 0
    try:
        df = ak.stock_hsgt_north_net_flow_in_em(symbol="北上")
        if df is not None and not df.empty:
            latest = df.iloc[-1]
            nb_flow = (_safe_float(latest.get("当日净流入", latest.get("value", 0))) or 0) / 1e8
    except Exception:
        pass

    return IndexSummary(
        date=trade_date,
        indices=indices,
        turnover_total_yi=round(turnover_total, 2),
        turnover_delta_yi=round(turnover_delta, 2),
        turnover_prev_yi=round(turnover_prev, 2),
        northbound_flow_yi=round(nb_flow, 2),
        advancers=advancers,
        decliners=decliners,
        flat=flat,
    )


def collect_sector_heatmap(trade_date: str = "", spot_df=None) -> SectorHeatmapData:
    """Collect sector-level performance data for heatmap."""
    ak = _get_ak()
    threshold = RECAP_CONFIG["resonance_threshold_pct"]

    # Get spot data if not provided
    if spot_df is None:
        try:
            spot_df = ak.stock_zh_a_spot_em()
        except Exception:
            spot_df = None

    nodes = []
    try:
        df = ak.stock_sector_fund_flow_rank(indicator="今日")
        if df is not None and not df.empty:
            for _, r in df.iterrows():
                name = str(r.get("名称", ""))
                pct = _safe_float(r.get("今日涨跌幅")) or 0

                # Sector turnover and market cap from constituents
                sector_turnover_yi = 0
                sector_mcap_yi = 0

                # Try to get sector constituents for leaders/resonance
                leaders = []
                laggards = []
                resonance = []
                try:
                    cons = ak.stock_board_industry_cons_em(symbol=name)
                    if cons is not None and not cons.empty and spot_df is not None:
                        codes = cons["代码"].astype(str).tolist() if "代码" in cons.columns else []
                        if codes:
                            matched = spot_df[spot_df["代码"].isin(codes)].copy()
                            if not matched.empty:
                                # Aggregate sector turnover and market cap
                                if "成交额" in matched.columns:
                                    sector_turnover_yi = float(matched["成交额"].sum()) / 1e8
                                if "总市值" in matched.columns:
                                    sector_mcap_yi = float(matched["总市值"].sum()) / 1e8

                                if "涨跌幅" in matched.columns:
                                    matched = matched.sort_values("涨跌幅", ascending=False)
                                    for _, s in matched.head(3).iterrows():
                                        leaders.append({
                                            "ticker": str(s.get("代码", "")),
                                            "name": str(s.get("名称", "")),
                                            "pct_change": round(_safe_float(s.get("涨跌幅")) or 0, 2),
                                        })
                                    for _, s in matched.tail(3).iterrows():
                                        laggards.append({
                                            "ticker": str(s.get("代码", "")),
                                            "name": str(s.get("名称", "")),
                                            "pct_change": round(_safe_float(s.get("涨跌幅")) or 0, 2),
                                        })
                                    res = matched[matched["涨跌幅"].abs() >= threshold]
                                    for _, s in res.iterrows():
                                        resonance.append({
                                            "ticker": str(s.get("代码", "")),
                                            "name": str(s.get("名称", "")),
                                            "pct_change": round(_safe_float(s.get("涨跌幅")) or 0, 2),
                                        })
                except Exception:
                    pass

                nodes.append(asdict(SectorNode(
                    sector=name,
                    pct_change=round(pct, 2),
                    turnover_yi=round(sector_turnover_yi, 2),
                    market_cap_yi=round(sector_mcap_yi, 2),
                    leaders=leaders,
                    laggards=laggards,
                    resonance_stocks=resonance,
                )))
    except Exception as e:
        logger.warning(f"  [FAIL] sector heatmap: {e}")

    return SectorHeatmapData(date=trade_date, nodes=nodes)


def collect_limit_board(trade_date: str = "", spot_df=None) -> LimitBoardSummary:
    """Collect limit up/down stocks."""
    ak = _get_ak()

    if spot_df is None:
        try:
            spot_df = ak.stock_zh_a_spot_em()
        except Exception:
            return LimitBoardSummary()

    up_stocks = []
    down_stocks = []

    if spot_df is not None and "涨跌幅" in spot_df.columns:
        # Detect limit up: >=9.9% for main board, >=19.9% for ChiNext/STAR
        for _, r in spot_df.iterrows():
            pct = _safe_float(r.get("涨跌幅")) or 0
            code = str(r.get("代码", ""))
            is_chinext = code.startswith("3") or code.startswith("68")
            is_st = "ST" in str(r.get("名称", ""))
            limit_threshold = 4.9 if is_st else (19.9 if is_chinext else 9.9)

            amt = (_safe_float(r.get("成交额")) or 0) / 1e8

            if pct >= limit_threshold:
                up_stocks.append(asdict(LimitStock(
                    ticker=code,
                    name=str(r.get("名称", "")),
                    pct_change=round(pct, 2),
                    amount_yi=round(amt, 2),
                    is_limit_up=True,
                )))
            elif pct <= -limit_threshold:
                down_stocks.append(asdict(LimitStock(
                    ticker=code,
                    name=str(r.get("名称", "")),
                    pct_change=round(pct, 2),
                    amount_yi=round(amt, 2),
                    is_limit_up=False,
                )))

    # Try to get consecutive board data from akshare
    try:
        date_str = (trade_date or datetime.now().strftime("%Y-%m-%d")).replace("-", "")
        zt_df = ak.stock_zt_pool_em(date=date_str)
        if zt_df is not None and not zt_df.empty:
            board_col = None
            for c in ("连板数", "连续涨停天数", "连板天数"):
                if c in zt_df.columns:
                    board_col = c
                    break
            if board_col:
                code_col = "代码" if "代码" in zt_df.columns else "股票代码"
                for s in up_stocks:
                    match = zt_df[zt_df[code_col].astype(str) == s["ticker"]]
                    if not match.empty:
                        b = _safe_float(match.iloc[0].get(board_col))
                        if b and b > 0:
                            s["boards"] = int(b)
    except Exception:
        pass

    up_stocks.sort(key=lambda x: x.get("pct_change", 0), reverse=True)
    down_stocks.sort(key=lambda x: x.get("pct_change", 0))

    return LimitBoardSummary(
        limit_up_count=len(up_stocks),
        limit_down_count=len(down_stocks),
        limit_up_stocks=up_stocks,
        limit_down_stocks=down_stocks,
    )


def _fetch_prev_day_board_dist(trade_date: str = "") -> Dict[int, int]:
    """Fetch yesterday's consecutive board distribution from zt_pool.

    Returns:
        Dict mapping board_level → count for the previous trading day.
    """
    ak = _get_ak()
    # Try the previous trading day (skip weekends simply by trying recent days)
    from datetime import datetime as _dt
    base = _dt.strptime(trade_date, "%Y-%m-%d") if trade_date else _dt.now()
    for offset in range(1, 5):
        prev = base - timedelta(days=offset)
        prev_str = prev.strftime("%Y%m%d")
        try:
            df = ak.stock_zt_pool_em(date=prev_str)
            if df is None or df.empty:
                continue
            board_col = None
            for c in ("连板数", "连续涨停天数", "连板天数"):
                if c in df.columns:
                    board_col = c
                    break
            if not board_col:
                continue
            dist: Dict[int, int] = {}
            for _, r in df.iterrows():
                b = int(_safe_float(r.get(board_col)) or 1)
                dist[b] = dist.get(b, 0) + 1
            return dist
        except Exception:
            continue
    return {}


def build_consecutive_levels(
    limit_up_stocks: List[Dict],
    prev_dist: Optional[Dict[int, int]] = None,
) -> List[Dict]:
    """Group limit-up stocks by consecutive board count into levels.

    If prev_dist is provided, computes promotion rates:
    - 一进二率 = today's 二连板 count / yesterday's 首板 count
    - 二进三率 = today's 三连板 count / yesterday's 二连板 count
    """
    levels_map: Dict[int, List] = {}
    for s in limit_up_stocks:
        b = s.get("boards", 1)
        if b not in levels_map:
            levels_map[b] = []
        levels_map[b].append(s)

    labels = {1: "首板", 2: "二连板", 3: "三连板", 4: "四连板"}
    promotion_labels = {2: "一进二", 3: "二进三", 4: "三进四", 5: "四进五"}
    levels = []
    for lvl in sorted(levels_map.keys()):
        stocks = levels_map[lvl]
        count = len(stocks)

        # Promotion rate: today's N连板 came from yesterday's (N-1)连板
        prev_count = 0
        promo_rate = 0.0
        if prev_dist and lvl >= 2:
            prev_count = prev_dist.get(lvl - 1, 0)
            if prev_count > 0:
                promo_rate = round(count / prev_count * 100, 1)

        # Label: "首板" for level 1, "一进二 (8/35=22.9%)" for level 2+
        if lvl == 1:
            label = "首板"
        elif prev_count > 0:
            plabel = promotion_labels.get(lvl, f"{lvl-1}进{lvl}")
            label = f"{plabel} ({count}/{prev_count}={promo_rate:.0f}%)"
        else:
            label = labels.get(lvl, f"{lvl}连板")

        levels.append(asdict(ConsecutiveBoardLevel(
            level=lvl, label=label,
            count=count, prev_count=prev_count,
            promotion_rate=promo_rate, stocks=stocks,
        )))
    return levels


def collect_red_close_screen(
    trade_date: str = "",
    spot_df=None,
    pool_size: int = None,
) -> RedCloseScreen:
    """Screen stocks for 14-day red close streaks.

    Red close definition: today's close > previous trading day's close.
    Screens top stocks by market cap.
    """
    ak = _get_ak()
    pool_size = pool_size or RECAP_CONFIG["red_close_pool_size"]
    window = RECAP_CONFIG["red_close_window_days"]
    thresholds = RECAP_CONFIG["red_close_thresholds"]

    if spot_df is None:
        try:
            spot_df = ak.stock_zh_a_spot_em()
        except Exception:
            return RedCloseScreen(window_natural_days=window)

    if spot_df is None or spot_df.empty:
        return RedCloseScreen(window_natural_days=window)

    # Sort by market cap, take top N
    mc_col = "总市值"
    if mc_col not in spot_df.columns:
        return RedCloseScreen(window_natural_days=window)

    top = spot_df.nlargest(pool_size, mc_col)
    end = datetime.now()
    start = end - timedelta(days=window + 5)
    start_str = start.strftime("%Y%m%d")
    end_str = end.strftime("%Y%m%d")

    red_counts = {}
    trade_days_seen = 0

    for _, r in top.iterrows():
        code = str(r.get("代码", ""))
        name = str(r.get("名称", ""))
        if not code or len(code) != 6:
            continue
        try:
            hist = ak.stock_zh_a_hist(
                symbol=code, period="daily", adjust="qfq",
                start_date=start_str, end_date=end_str,
            )
            if hist is None or len(hist) < 2:
                continue

            close_col = "收盘" if "收盘" in hist.columns else "close"
            closes = hist[close_col].tolist()
            # Count red closes (close > prev close)
            reds = sum(1 for i in range(1, len(closes)) if closes[i] > closes[i - 1])
            if trade_days_seen == 0:
                trade_days_seen = len(closes) - 1

            red_counts[code] = {"ticker": code, "name": name, "red_days": reds,
                                "total_days": len(closes) - 1}
        except Exception:
            continue

    # Filter by thresholds
    t_low = min(thresholds) if thresholds else 6
    t_high = max(thresholds) if thresholds else 8
    red_6 = [v for v in red_counts.values() if v["red_days"] >= t_low]
    red_8 = [v for v in red_counts.values() if v["red_days"] >= t_high]
    red_6.sort(key=lambda x: x["red_days"], reverse=True)
    red_8.sort(key=lambda x: x["red_days"], reverse=True)

    return RedCloseScreen(
        window_natural_days=window,
        window_trade_days=trade_days_seen,
        red_close_6=red_6,
        red_close_8=red_8,
    )


def _derive_market_weather(idx_summary: IndexSummary) -> tuple:
    """Derive market weather from index data (pure data, no LLM)."""
    indices = idx_summary.indices
    if not indices:
        return "震荡", "中性", "", "市场数据不足"

    # Check index direction
    up_count = sum(1 for ix in indices if ix.get("pct_change", 0) > 0.3)
    down_count = sum(1 for ix in indices if ix.get("pct_change", 0) < -0.3)
    total = len(indices)

    # Breadth
    adv_ratio = idx_summary.advancers / max(idx_summary.advancers + idx_summary.decliners, 1)

    # Determine weather
    if up_count >= total * 0.6 and adv_ratio > 0.55:
        weather = "上涨"
        advice = "进攻"
    elif down_count >= total * 0.6 and adv_ratio < 0.45:
        weather = "下跌"
        advice = "防守"
    else:
        weather = "震荡"
        advice = "中性"

    # Risk note
    risks = []
    if idx_summary.turnover_delta_yi and idx_summary.turnover_delta_yi < -500:
        risks.append("成交额大幅萎缩")
    if idx_summary.northbound_flow_yi < -30:
        risks.append("北向资金大幅流出")
    if adv_ratio < 0.3:
        risks.append("市场宽度极差")
    risk_note = "；".join(risks) if risks else ""

    # One-line summary
    sh = next((ix for ix in indices if ix.get("code") == "sh000001"), None)
    sh_pct = sh.get("pct_change", 0) if sh else 0
    sh_close = sh.get("close", 0) if sh else 0
    sign = "+" if sh_pct > 0 else ""
    summary = f"上证{sh_close:.2f}点({sign}{sh_pct:.2f}%)，{idx_summary.advancers}涨/{idx_summary.decliners}跌"
    if idx_summary.turnover_delta_yi:
        td_sign = "+" if idx_summary.turnover_delta_yi > 0 else ""
        label = "放量" if idx_summary.turnover_delta_yi > 0 else "缩量"
        summary += f"，{label}{abs(idx_summary.turnover_delta_yi):.0f}亿"
    if idx_summary.northbound_flow_yi:
        nb_sign = "+" if idx_summary.northbound_flow_yi > 0 else ""
        summary += f"，北向{nb_sign}{idx_summary.northbound_flow_yi:.1f}亿"

    return weather, advice, risk_note, summary


def collect_daily_recap(trade_date: str = "") -> DailyRecapData:
    """Collect all daily recap data. Main entry point."""
    today = trade_date or datetime.now().strftime("%Y-%m-%d")
    t0 = time.time()

    # Get spot data once (reused across collectors)
    ak = _get_ak()
    spot_df = None
    try:
        spot_df = ak.stock_zh_a_spot_em()
        logger.info(f"  [OK] spot data: {len(spot_df)} stocks")
    except Exception as e:
        logger.warning(f"  [FAIL] spot data: {e}")

    # Collect all components
    idx_summary = IndexSummary(date=today)
    try:
        idx_summary = _retry_call(collect_index_summary, today)
        logger.info(f"  [OK] index summary: {len(idx_summary.indices)} indices")
    except Exception as e:
        logger.warning(f"  [FAIL] index summary: {e}")

    sector_hm = SectorHeatmapData(date=today)
    try:
        sector_hm = _retry_call(collect_sector_heatmap, today, spot_df)
        logger.info(f"  [OK] sector heatmap: {len(sector_hm.nodes)} sectors")
    except Exception as e:
        logger.warning(f"  [FAIL] sector heatmap: {e}")

    limit = LimitBoardSummary()
    try:
        limit = _retry_call(collect_limit_board, today, spot_df)
        logger.info(f"  [OK] limit board: {limit.limit_up_count}↑ {limit.limit_down_count}↓")
    except Exception as e:
        logger.warning(f"  [FAIL] limit board: {e}")

    # Fetch previous day's board distribution for promotion rates
    prev_dist = {}
    try:
        prev_dist = _retry_call(_fetch_prev_day_board_dist, today)
        if prev_dist:
            logger.info(f"  [OK] prev day boards: {prev_dist}")
    except Exception as e:
        logger.warning(f"  [FAIL] prev day boards: {e}")

    consecutive = build_consecutive_levels(limit.limit_up_stocks, prev_dist)

    red_close = RedCloseScreen(window_natural_days=RECAP_CONFIG["red_close_window_days"])
    try:
        red_close = _retry_call(collect_red_close_screen, today, spot_df)
        logger.info(f"  [OK] red close: {len(red_close.red_close_6)} stocks ≥6, "
                     f"{len(red_close.red_close_8)} stocks ≥8")
    except Exception as e:
        logger.warning(f"  [FAIL] red close: {e}")

    # Derive market assessment
    weather, advice, risk_note, summary = _derive_market_weather(idx_summary)

    elapsed = time.time() - t0
    logger.info(f"Daily recap collected in {elapsed:.1f}s")

    return DailyRecapData(
        date=today,
        index_summary=asdict(idx_summary),
        sector_heatmap=asdict(sector_hm),
        limit_board=asdict(limit),
        consecutive_boards=consecutive,
        red_close=asdict(red_close),
        market_weather=weather,
        position_advice=advice,
        risk_note=risk_note,
        one_line_summary=summary,
        collection_seconds=elapsed,
    )

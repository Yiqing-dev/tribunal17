"""Technical indicator calculations — shared by recap_collector and akshare_collector.

Provides: SMA, EMA, RSI(14), MACD(12,26,9), Bollinger Bands(20,2), and a
convenience function `compute_stock_indicators()` that takes AkshareBundle-format
price_history and returns a dict of indicator time series.

Pure Python, zero external imports.
"""

import math
from typing import Dict, List, Optional, Tuple


# ── Primitives ──────────────────────────────────────────────────────


def sma(closes: List[float], period: int) -> List[Optional[float]]:
    """Simple Moving Average."""
    result: List[Optional[float]] = []
    for i in range(len(closes)):
        if i < period - 1:
            result.append(None)
        else:
            result.append(sum(closes[i - period + 1 : i + 1]) / period)
    return result


def ema(values: List[float], period: int) -> List[float]:
    """Exponential Moving Average."""
    if not values:
        return []
    k = 2.0 / (period + 1)
    result = [values[0]]
    for v in values[1:]:
        result.append(v * k + result[-1] * (1 - k))
    return result


# ── Indicators ──────────────────────────────────────────────────────


def compute_rsi(closes: List[float], period: int = 14) -> List[float]:
    """Relative Strength Index (Wilder smoothing)."""
    n = len(closes)
    if n < 2:
        return [50.0] * n
    deltas = [closes[i] - closes[i - 1] for i in range(1, n)]
    gains = [max(d, 0) for d in deltas]
    losses = [max(-d, 0) for d in deltas]

    result = [50.0]  # first close → neutral
    if len(gains) < period:
        return [50.0] * n

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for _ in range(period - 1):
        result.append(50.0)
    if avg_loss == 0:
        result.append(100.0)
    else:
        rs = avg_gain / avg_loss
        result.append(round(100.0 - 100.0 / (1.0 + rs), 2))
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            result.append(100.0)
        else:
            rs = avg_gain / avg_loss
            result.append(round(100.0 - 100.0 / (1.0 + rs), 2))
    return result


def compute_macd(
    closes: List[float], fast: int = 12, slow: int = 26, signal: int = 9
) -> Tuple[List[float], List[float], List[float]]:
    """MACD: returns (dif[], dea[], hist[])."""
    if not closes:
        return [], [], []
    ema_fast = ema(closes, fast)
    ema_slow = ema(closes, slow)
    dif = [round(f - s, 4) for f, s in zip(ema_fast, ema_slow)]
    dea = ema(dif, signal)
    dea = [round(d, 4) for d in dea]
    hist = [round(2 * (d - e), 4) for d, e in zip(dif, dea)]
    return dif, dea, hist


def compute_bollinger(
    closes: List[float], period: int = 20, num_std: float = 2.0
) -> Tuple[List[Optional[float]], List[Optional[float]], List[Optional[float]]]:
    """Bollinger Bands: returns (upper[], mid[], lower[]).

    mid = SMA(period), upper/lower = mid ± num_std × rolling_std.
    """
    mid = sma(closes, period)
    upper: List[Optional[float]] = []
    lower: List[Optional[float]] = []
    for i in range(len(closes)):
        if mid[i] is None:
            upper.append(None)
            lower.append(None)
        else:
            window = closes[i - period + 1 : i + 1]
            mean = mid[i]
            variance = sum((x - mean) ** 2 for x in window) / period
            std = math.sqrt(variance)
            upper.append(round(mean + num_std * std, 4))
            lower.append(round(mean - num_std * std, 4))
    return upper, mid, lower


# ── Convenience ─────────────────────────────────────────────────────


def compute_stock_indicators(price_history: List[Dict]) -> Dict:
    """Compute all technical indicators from AkshareBundle price_history.

    Args:
        price_history: list of dicts with at least 'date' and 'close' keys.

    Returns:
        Dict with keys:
        - 'dates': list of date strings
        - 'rsi_14': list of RSI values
        - 'macd_dif', 'macd_dea', 'macd_hist': MACD components
        - 'ma5', 'ma10', 'ma20': moving averages
        - 'boll_upper', 'boll_mid', 'boll_lower': Bollinger Bands
        - 'latest': dict with the most recent values + interpretation strings
    """
    if not price_history:
        return {}

    dates = [p.get("date", "") for p in price_history]
    closes = []
    for p in price_history:
        try:
            closes.append(float(p["close"]))
        except (KeyError, ValueError, TypeError):
            closes.append(0.0)

    if len(closes) < 5:
        return {}

    rsi = compute_rsi(closes, 14)
    dif, dea, hist = compute_macd(closes)
    ma5 = sma(closes, 5)
    ma10 = sma(closes, 10)
    ma20 = sma(closes, 20)
    boll_upper, boll_mid, boll_lower = compute_bollinger(closes, 20)

    result = {
        "dates": dates,
        "rsi_14": rsi,
        "macd_dif": dif,
        "macd_dea": dea,
        "macd_hist": hist,
        "ma5": ma5,
        "ma10": ma10,
        "ma20": ma20,
        "boll_upper": boll_upper,
        "boll_mid": boll_mid,
        "boll_lower": boll_lower,
    }

    # Latest snapshot with interpretation
    latest: Dict = {}
    if rsi:
        v = rsi[-1]
        latest["rsi_14"] = v
        if v >= 70:
            latest["rsi_zone"] = "超买"
        elif v >= 55:
            latest["rsi_zone"] = "偏多"
        elif v >= 45:
            latest["rsi_zone"] = "中性"
        elif v >= 30:
            latest["rsi_zone"] = "偏空"
        else:
            latest["rsi_zone"] = "超卖"

    if dif and dea:
        latest["macd_dif"] = dif[-1]
        latest["macd_dea"] = dea[-1]
        latest["macd_hist"] = hist[-1] if hist else 0
        if dif[-1] > dea[-1]:
            if len(dif) >= 2 and dif[-2] <= dea[-2]:
                latest["macd_cross"] = "金叉(今日)"
            else:
                latest["macd_cross"] = "金叉"
        else:
            if len(dif) >= 2 and dif[-2] >= dea[-2]:
                latest["macd_cross"] = "死叉(今日)"
            else:
                latest["macd_cross"] = "死叉"

    if ma5 and ma10 and ma20:
        latest["ma5"] = ma5[-1]
        latest["ma10"] = ma10[-1]
        latest["ma20"] = ma20[-1]

    if boll_upper and boll_mid and boll_lower:
        bu, bm, bl = boll_upper[-1], boll_mid[-1], boll_lower[-1]
        if bu is not None and bl is not None and bm and bm > 0:
            latest["boll_upper"] = bu
            latest["boll_mid"] = bm
            latest["boll_lower"] = bl
            latest["boll_width_pct"] = round((bu - bl) / bm * 100, 1)
            price = closes[-1]
            if price > bu:
                latest["boll_position"] = "上轨上方(超买)"
            elif price > bm:
                latest["boll_position"] = "中轨上方"
            elif price > bl:
                latest["boll_position"] = "中轨下方"
            else:
                latest["boll_position"] = "下轨下方(超卖)"

    result["latest"] = latest
    return result

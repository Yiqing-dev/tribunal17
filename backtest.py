"""Backtest module — evaluate historical signal accuracy against forward price data.

Reads RunTrace records from ReplayStore, fetches forward daily bars via Sina Finance API,
and computes direction accuracy, win rate, and simulated P&L.

Usage:
    from subagent_pipeline.backtest import run_backtest, generate_backtest_report
    results = run_backtest(storage_dir="data/replays")
    generate_backtest_report(results, output_dir="data/reports")
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Per-ticker Sina kline cache (avoids repeated API calls for same ticker)
_sina_cache: Dict[str, List[Dict]] = {}


# ── Configuration ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class BacktestConfig:
    """Backtest evaluation parameters."""
    eval_window_days: int = 10          # Forward trading days to evaluate
    neutral_band_pct: float = 2.0       # +/- band for neutral classification
    min_age_days: int = 1               # Minimum calendar days since signal
    max_runs: int = 0                   # Max runs to evaluate (0 = no limit)
    engine_version: str = "v1"


# ── Result Models ─────────────────────────────────────────────────────────

@dataclass
class BacktestResult:
    """Evaluation result for a single historical signal."""
    run_id: str = ""
    ticker: str = ""
    ticker_name: str = ""
    trade_date: str = ""                # Signal date

    # Signal snapshot
    action: str = ""                    # BUY/HOLD/SELL/VETO
    confidence: float = -1.0
    was_vetoed: bool = False

    # Direction inference
    direction_expected: str = ""        # up / down / flat / abstain

    # Forward price data
    eval_window_days: int = 10
    start_price: float = 0.0           # Close on signal date
    end_close: float = 0.0             # Close at end of eval window
    max_high: float = 0.0              # Highest price in window
    min_low: float = 0.0               # Lowest price in window
    bars_available: int = 0            # Actual trading days fetched

    # Returns
    stock_return_pct: float = 0.0      # (end_close - start_price) / start_price * 100
    max_drawdown_pct: float = 0.0      # (min_low - start_price) / start_price * 100
    max_gain_pct: float = 0.0          # (max_high - start_price) / start_price * 100

    # Evaluation
    direction_correct: Optional[bool] = None
    outcome: str = ""                  # win / loss / neutral
    eval_status: str = "pending"       # completed / insufficient / error

    # Trade plan targets (if available)
    stop_loss: float = 0.0
    take_profit: float = 0.0
    hit_stop_loss: bool = False
    hit_take_profit: bool = False
    first_hit: str = ""                # stop_loss / take_profit / neither

    # Error info
    error_msg: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}

    @classmethod
    def from_dict(cls, d: Dict) -> "BacktestResult":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class BacktestSummary:
    """Aggregated backtest metrics."""
    scope: str = "overall"              # "overall" or ticker
    eval_window_days: int = 10
    engine_version: str = "v1"
    computed_at: str = ""

    # Counts
    total_signals: int = 0
    completed: int = 0
    insufficient: int = 0

    # By action
    buy_count: int = 0
    hold_count: int = 0
    sell_count: int = 0
    veto_count: int = 0

    # Accuracy
    direction_correct_count: int = 0
    direction_wrong_count: int = 0
    direction_accuracy_pct: float = 0.0

    # Win/loss (for directional signals only: BUY and SELL)
    win_count: int = 0
    loss_count: int = 0
    neutral_count: int = 0
    win_rate_pct: float = 0.0

    # Returns
    avg_stock_return_pct: float = 0.0
    avg_buy_return_pct: float = 0.0
    avg_sell_return_pct: float = 0.0     # Inverted: positive = correct sell

    # Target price stats
    stop_loss_hit_count: int = 0
    take_profit_hit_count: int = 0

    # Per-action breakdown
    action_breakdown: Dict[str, Dict] = field(default_factory=dict)

    # Shadow VETO analysis
    shadow_veto_count: int = 0
    shadow_veto_wins: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}


@dataclass
class BacktestReport:
    """Complete backtest output: results + summaries."""
    config: BacktestConfig = field(default_factory=BacktestConfig)
    results: List[BacktestResult] = field(default_factory=list)
    shadow_results: List[BacktestResult] = field(default_factory=list)
    overall_summary: BacktestSummary = field(default_factory=BacktestSummary)
    per_ticker_summaries: Dict[str, BacktestSummary] = field(default_factory=dict)
    generated_at: str = ""

    @property
    def summary(self) -> "BacktestSummary":
        """Alias for overall_summary for convenience."""
        return self.overall_summary

    def to_dict(self) -> Dict[str, Any]:
        return {
            "config": {
                "eval_window_days": self.config.eval_window_days,
                "neutral_band_pct": self.config.neutral_band_pct,
                "min_age_days": self.config.min_age_days,
                "engine_version": self.config.engine_version,
            },
            "results": [r.to_dict() for r in self.results],
            "shadow_results": [r.to_dict() for r in self.shadow_results],
            "overall_summary": self.overall_summary.to_dict(),
            "per_ticker_summaries": {
                k: v.to_dict() for k, v in self.per_ticker_summaries.items()
            },
            "generated_at": self.generated_at,
        }


# ── Direction Inference ───────────────────────────────────────────────────

def infer_direction(action: str) -> str:
    """Map action to expected price direction.

    Returns: 'up', 'down', 'flat', or 'abstain'.
    """
    action = action.upper().strip()
    if action in ("BUY",):
        return "up"
    elif action in ("SELL",):
        return "down"
    elif action in ("VETO",):
        return "abstain"
    elif action in ("HOLD",):
        return "flat"
    return "abstain"


# ── Forward Price Fetching ────────────────────────────────────────────────

def _sina_symbol(ticker: str) -> str:
    """Convert ticker to Sina-style symbol (e.g. '601985.SS' -> 'sh601985')."""
    if ".BJ" in ticker:
        # Beijing Exchange uses "bj" prefix in Sina
        bare = ticker.replace(".BJ", "")
        return f"bj{bare}"
    bare = ticker.replace(".SS", "").replace(".SZ", "")
    if bare.startswith("6"):
        return f"sh{bare}"
    return f"sz{bare}"


def _fetch_sina_klines(ticker: str, datalen: int = 30) -> List[Dict]:
    """Fetch daily klines from Sina Finance API (qfq).

    Returns list of dicts: date, open, high, low, close, volume.
    """
    import requests as _requests
    import time as _time

    symbol = _sina_symbol(ticker)
    url = "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
    params = {"symbol": symbol, "scale": "240", "ma": "no", "datalen": str(datalen)}
    _time.sleep(0.3)  # Rate-limit: 3 req/sec max
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://finance.sina.com.cn/",
    }
    try:
        r = _requests.get(url, params=params, headers=headers, timeout=15)
        if r.status_code != 200:
            return []
        data = r.json()
        if not isinstance(data, list):
            return []
        bars = []
        for d in data:
            bars.append({
                "date": d.get("day", ""),
                "open": float(d.get("open", 0)),
                "high": float(d.get("high", 0)),
                "low": float(d.get("low", 0)),
                "close": float(d.get("close", 0)),
                "volume": float(d.get("volume", 0)),
            })
        return bars
    except Exception as e:
        logger.warning(f"Sina kline fetch failed for {symbol}: {e}")
        return []


def fetch_forward_bars(
    ticker: str,
    signal_date: str,
    window_days: int = 10,
) -> List[Dict]:
    """Fetch daily bars for `window_days` trading days after signal_date.

    Returns list of dicts with keys: date, open, high, low, close, volume.
    Source: Sina Finance API (no fallback).
    """
    try:
        sig_dt = datetime.strptime(signal_date, "%Y-%m-%d")
    except ValueError:
        logger.warning(f"Invalid signal_date format: {signal_date}")
        return []

    # Primary: Sina (cached per ticker)
    bare_key = ticker.replace(".SS", "").replace(".SZ", "").replace(".BJ", "")
    # Calculate datalen large enough to cover from signal_date to today + window
    approx_trading_days = int((datetime.now() - sig_dt).days * 5 / 7) + window_days + 10
    datalen = max(60, approx_trading_days)
    if bare_key not in _sina_cache or len(_sina_cache[bare_key]) < datalen:
        _sina_cache[bare_key] = _fetch_sina_klines(ticker, datalen=datalen)
    all_bars = _sina_cache[bare_key]
    if all_bars:
        forward = [b for b in all_bars if b["date"] > signal_date]
        if forward:
            return forward[:window_days]

    # Sina couldn't find data — give up
    logger.info(f"No Sina data for {ticker} after {signal_date}")
    return []


def fetch_signal_day_close(ticker: str, signal_date: str) -> float:
    """Fetch the closing price on the signal date.

    Source: Sina Finance API (no fallback).
    """
    try:
        sig_dt = datetime.strptime(signal_date, "%Y-%m-%d")
    except ValueError:
        return 0.0

    # Primary: Sina (cached per ticker)
    bare_key = ticker.replace(".SS", "").replace(".SZ", "").replace(".BJ", "")
    # Calculate datalen large enough to cover back to signal_date
    approx_trading_days = int((datetime.now() - sig_dt).days * 5 / 7) + 10
    datalen = max(60, approx_trading_days)
    if bare_key not in _sina_cache or len(_sina_cache[bare_key]) < datalen:
        _sina_cache[bare_key] = _fetch_sina_klines(ticker, datalen=datalen)
    all_bars = _sina_cache[bare_key]
    if all_bars:
        # Find exact date or closest before
        for b in reversed(all_bars):
            if b["date"] <= signal_date and b["close"] > 0:
                return b["close"]

    # Sina couldn't find data
    logger.info(f"No Sina close for {ticker} on {signal_date}")
    return 0.0


# ── Signal Evaluation ─────────────────────────────────────────────────────

def evaluate_signal(
    run_id: str,
    ticker: str,
    ticker_name: str,
    trade_date: str,
    action: str,
    confidence: float,
    was_vetoed: bool,
    stop_loss: float = 0.0,
    take_profit: float = 0.0,
    config: BacktestConfig = None,
    forward_bars: List[Dict] = None,
    signal_close: float = 0.0,
    shadow_direction: str = "",
) -> BacktestResult:
    """Evaluate a single signal against forward price data.

    If forward_bars is None, fetches from Sina.
    If signal_close is 0, fetches from Sina.
    If shadow_direction is set, override the inferred direction (for VETO shadow analysis).
    """
    config = config or BacktestConfig()

    result = BacktestResult(
        run_id=run_id,
        ticker=ticker,
        ticker_name=ticker_name,
        trade_date=trade_date,
        action=action,
        confidence=confidence,
        was_vetoed=was_vetoed,
        eval_window_days=config.eval_window_days,
        stop_loss=stop_loss,
        take_profit=take_profit,
    )

    # Infer expected direction
    result.direction_expected = infer_direction(action)

    # VETO signals: skip evaluation entirely (no trade = no P&L)
    # Unless shadow_direction is provided for shadow VETO analysis.
    if result.direction_expected == "abstain" and not shadow_direction:
        result.direction_correct = None
        result.outcome = "neutral"
        result.stop_loss = 0.0
        result.take_profit = 0.0
        result.eval_status = "skipped_veto"
        return result

    # Shadow VETO: override direction for hypothetical evaluation
    if shadow_direction:
        result.direction_expected = shadow_direction

    # Fetch prices if not provided
    if signal_close <= 0:
        signal_close = fetch_signal_day_close(ticker, trade_date)
    if signal_close <= 0:
        result.eval_status = "insufficient"
        result.error_msg = "Cannot fetch signal day close price"
        return result

    result.start_price = signal_close

    if forward_bars is None:
        forward_bars = fetch_forward_bars(ticker, trade_date, config.eval_window_days)
    if not forward_bars:
        result.eval_status = "insufficient"
        result.error_msg = "No forward bars available"
        return result

    result.bars_available = len(forward_bars)

    # Compute forward metrics
    closes = [b["close"] for b in forward_bars if b.get("close", 0) > 0]
    highs = [b["high"] for b in forward_bars if b.get("high", 0) > 0]
    lows = [b["low"] for b in forward_bars if b.get("low", 0) > 0]

    if not closes:
        result.eval_status = "insufficient"
        result.error_msg = "No valid close prices in forward bars"
        return result

    result.end_close = closes[-1]
    result.max_high = max(highs) if highs else result.end_close
    result.min_low = min(lows) if lows else result.end_close

    # Returns
    result.stock_return_pct = round(
        (result.end_close - signal_close) / signal_close * 100, 2
    )
    result.max_gain_pct = round(
        (result.max_high - signal_close) / signal_close * 100, 2
    )
    result.max_drawdown_pct = round(
        (result.min_low - signal_close) / signal_close * 100, 2
    )

    # Direction check
    neutral_band = config.neutral_band_pct
    if result.direction_expected == "up":
        if result.stock_return_pct > neutral_band:
            result.direction_correct = True
            result.outcome = "win"
        elif result.stock_return_pct < -neutral_band:
            result.direction_correct = False
            result.outcome = "loss"
        else:
            result.direction_correct = None
            result.outcome = "neutral"
    elif result.direction_expected == "down":
        if result.stock_return_pct < -neutral_band:
            result.direction_correct = True
            result.outcome = "win"
        elif result.stock_return_pct > neutral_band:
            result.direction_correct = False
            result.outcome = "loss"
        else:
            result.direction_correct = None
            result.outcome = "neutral"
    elif result.direction_expected == "flat":
        if abs(result.stock_return_pct) <= neutral_band:
            result.direction_correct = True
            result.outcome = "win"
        else:
            result.direction_correct = False
            result.outcome = "loss"
    elif result.direction_expected == "abstain":
        # VETO signals: refuse to trade, not a directional bet
        result.direction_correct = None
        result.outcome = "neutral"
    else:
        result.outcome = "neutral"

    # Stop-loss / take-profit hits (direction-aware)
    if result.direction_expected == "down":
        # SELL: SL is above entry (price rising = loss), TP is below entry (price falling = profit)
        if stop_loss > 0:
            result.hit_stop_loss = result.max_high >= stop_loss
        if take_profit > 0:
            result.hit_take_profit = result.min_low <= take_profit
    elif result.direction_expected == "up":
        # BUY: SL is below entry, TP is above entry
        if stop_loss > 0:
            result.hit_stop_loss = result.min_low <= stop_loss
        if take_profit > 0:
            result.hit_take_profit = result.max_high >= take_profit

    if result.hit_stop_loss and result.hit_take_profit:
        result.first_hit = "ambiguous"
    elif result.hit_take_profit:
        result.first_hit = "take_profit"
    elif result.hit_stop_loss:
        result.first_hit = "stop_loss"
    else:
        result.first_hit = "neither"

    result.eval_status = "shadow_veto" if shadow_direction else "completed"
    return result


# ── Summary Computation ───────────────────────────────────────────────────

def compute_summary(
    results: List[BacktestResult],
    scope: str = "overall",
    config: BacktestConfig = None,
) -> BacktestSummary:
    """Aggregate BacktestResult list into summary metrics."""
    config = config or BacktestConfig()
    completed = [r for r in results if r.eval_status == "completed"]
    insufficient = [r for r in results if r.eval_status == "insufficient"]

    summary = BacktestSummary(
        scope=scope,
        eval_window_days=config.eval_window_days,
        engine_version=config.engine_version,
        computed_at=datetime.now().isoformat(),
        total_signals=len(results),
        completed=len(completed),
        insufficient=len(insufficient),
    )

    # Count skipped VETOs into veto_count (not in "completed" pool)
    skipped_veto = [r for r in results if r.eval_status == "skipped_veto"]
    summary.veto_count = len(skipped_veto)

    if not completed:
        return summary

    # Action counts (from completed signals only)
    for r in completed:
        a = r.action.upper()
        if a == "BUY":
            summary.buy_count += 1
        elif a == "HOLD":
            summary.hold_count += 1
        elif a == "SELL":
            summary.sell_count += 1
        elif a == "VETO":
            summary.veto_count += 1

    # Direction accuracy (exclude flat/neutral expected)
    directional = [r for r in completed if r.direction_expected in ("up", "down")]
    dir_decided = [r for r in directional if r.direction_correct is not None]
    if dir_decided:
        summary.direction_correct_count = sum(
            1 for r in dir_decided if r.direction_correct
        )
        summary.direction_wrong_count = len(dir_decided) - summary.direction_correct_count
        summary.direction_accuracy_pct = round(
            summary.direction_correct_count / len(dir_decided) * 100, 1
        )

    # Win rate (directional signals only)
    wins = [r for r in directional if r.outcome == "win"]
    losses = [r for r in directional if r.outcome == "loss"]
    neutrals = [r for r in directional if r.outcome == "neutral"]
    summary.win_count = len(wins)
    summary.loss_count = len(losses)
    summary.neutral_count = len(neutrals)
    decided = len(wins) + len(losses)
    if decided > 0:
        summary.win_rate_pct = round(len(wins) / decided * 100, 1)

    # Average returns — overall across all actions (see avg_buy/sell_return_pct for per-action)
    all_returns = [r.stock_return_pct for r in completed]
    summary.avg_stock_return_pct = round(sum(all_returns) / len(all_returns), 2)

    buy_returns = [r.stock_return_pct for r in completed if r.action.upper() == "BUY"]
    if buy_returns:
        summary.avg_buy_return_pct = round(sum(buy_returns) / len(buy_returns), 2)

    sell_returns = [-r.stock_return_pct for r in completed if r.action.upper() == "SELL"]
    if sell_returns:
        summary.avg_sell_return_pct = round(sum(sell_returns) / len(sell_returns), 2)

    # SL/TP hits
    summary.stop_loss_hit_count = sum(1 for r in completed if r.hit_stop_loss)
    summary.take_profit_hit_count = sum(1 for r in completed if r.hit_take_profit)

    # Per-action breakdown
    for action in ("BUY", "HOLD", "SELL", "VETO"):
        action_results = [r for r in completed if r.action.upper() == action]
        if not action_results:
            continue
        returns = [r.stock_return_pct for r in action_results]
        action_wins = [r for r in action_results if r.outcome == "win"]
        action_losses = [r for r in action_results if r.outcome == "loss"]
        ad = len(action_wins) + len(action_losses)
        summary.action_breakdown[action] = {
            "count": len(action_results),
            "avg_return_pct": round(sum(returns) / len(returns), 2),
            "win_count": len(action_wins),
            "loss_count": len(action_losses),
            "win_rate_pct": round(len(action_wins) / ad * 100, 1) if ad > 0 else 0.0,
        }

    # Shadow VETO analysis
    shadow_results = [r for r in results if r.eval_status == "shadow_veto"]
    summary.shadow_veto_count = len(shadow_results)
    summary.shadow_veto_wins = sum(1 for r in shadow_results if r.outcome == "win")

    return summary


# ── Main Entry Point ──────────────────────────────────────────────────────

def _extract_trade_plan_prices(trace_dict: Dict) -> Tuple[float, float]:
    """Extract stop_loss and take_profit from a RunTrace dict."""
    for nt in trace_dict.get("node_traces", []):
        if nt.get("node_name") == "ResearchOutput":
            sd = nt.get("structured_data", {})
            tp = sd.get("trade_plan", {})
            if not tp:
                continue
            sl = 0.0
            tgt = 0.0
            # Stop loss
            sl_obj = tp.get("stop_loss", {})
            if isinstance(sl_obj, dict):
                sl = float(sl_obj.get("price", 0) or 0)
            elif isinstance(sl_obj, (int, float)):
                sl = float(sl_obj)
            # Take profit: use first target zone midpoint
            tp_list = tp.get("take_profit", [])
            if tp_list and isinstance(tp_list, list):
                first_tp = tp_list[0]
                if isinstance(first_tp, dict):
                    zone = first_tp.get("price_zone", [])
                    try:
                        if zone and len(zone) >= 2:
                            tgt = (float(zone[0]) + float(zone[1])) / 2
                        elif zone:
                            tgt = float(zone[0])
                        elif "price" in first_tp:
                            tgt = float(first_tp["price"])
                    except (ValueError, TypeError):
                        tgt = 0.0
            return sl, tgt
    return 0.0, 0.0


def run_backtest(
    storage_dir: str = "data/replays",
    ticker: str = None,
    config: BacktestConfig = None,
    fetch_prices: bool = True,
) -> BacktestReport:
    """Run backtest on all historical signals in the replay store.

    Args:
        storage_dir: Path to replay JSON files.
        ticker: Optional ticker filter.
        config: Backtest configuration.
        fetch_prices: If True, fetch forward bars via Sina Finance API.
                      If False, skip price fetching (results will be 'insufficient').

    Returns:
        BacktestReport with results and summaries.
    """
    config = config or BacktestConfig()

    from .replay_store import ReplayStore
    store = ReplayStore(storage_dir=storage_dir)
    runs = store.list_runs(ticker=ticker, limit=config.max_runs or 10000)

    today = datetime.now()
    results = []
    # Track trace timestamps for dedup (run_id -> started_at)
    _run_timestamps: Dict[str, datetime] = {}

    for entry in runs:
        run_id = entry.get("run_id", "")
        trade_date = entry.get("trade_date", "")
        action = entry.get("research_action", "").strip()

        if not trade_date or not action:
            continue
        # Normalize non-standard actions
        if action.upper() not in ("BUY", "HOLD", "SELL", "VETO"):
            continue

        # Check min_age
        try:
            sig_dt = datetime.strptime(trade_date, "%Y-%m-%d")
            age_days = (today - sig_dt).days
            if age_days < config.min_age_days:
                continue
        except ValueError:
            continue

        # Load full trace for ticker_name and trade_plan
        trace = store.load(run_id)
        if trace is None:
            continue

        # Store timestamp for dedup ordering (skip if missing to avoid false recency)
        if trace.started_at is not None:
            _run_timestamps[run_id] = trace.started_at

        trace_dict = trace.to_dict()
        sl, tgt = _extract_trade_plan_prices(trace_dict)

        if fetch_prices:
            result = evaluate_signal(
                run_id=run_id,
                ticker=trace.ticker,
                ticker_name=trace.ticker_name,
                trade_date=trade_date,
                action=action,
                confidence=trace.final_confidence,
                was_vetoed=trace.was_vetoed,
                stop_loss=sl,
                take_profit=tgt,
                config=config,
            )
        else:
            result = BacktestResult(
                run_id=run_id,
                ticker=trace.ticker,
                ticker_name=trace.ticker_name,
                trade_date=trade_date,
                action=action,
                confidence=trace.final_confidence,
                was_vetoed=trace.was_vetoed,
                stop_loss=sl,
                take_profit=tgt,
                eval_window_days=config.eval_window_days,
                direction_expected=infer_direction(action),
                eval_status="insufficient",
                error_msg="Price fetching disabled",
            )
        results.append(result)

    # Normalize tickers: ensure suffix is present
    from subagent_pipeline.signal_ledger import normalize_ticker
    for r in results:
        r.ticker = normalize_ticker(r.ticker)

    # Deduplicate: keep latest run per ticker+date (by trace timestamp)
    seen = {}
    for r in results:
        key = (r.ticker, r.trade_date)
        if key not in seen:
            seen[key] = r
        else:
            # Prefer generated_at timestamp; fall back to run_id lexicographic
            cur_ts = _run_timestamps.get(r.run_id)
            prev_ts = _run_timestamps.get(seen[key].run_id)
            if cur_ts and prev_ts:
                if cur_ts > prev_ts:
                    seen[key] = r
            elif r.run_id > seen[key].run_id:
                seen[key] = r
    results = list(seen.values())
    results.sort(key=lambda r: r.trade_date, reverse=True)

    # Shadow VETO evaluation: re-evaluate VETO signals with their pre-veto direction
    shadow_results: List[BacktestResult] = []
    for r in results:
        if r.eval_status != "skipped_veto":
            continue
        # Determine pre-veto direction from the trace
        trace_d = _run_timestamps.get(r.run_id)  # reuse cached timestamp check
        pre_veto_action = ""
        for entry in store.list_runs(limit=500):
            if entry.get("run_id") == r.run_id:
                trace = store.load(r.run_id)
                if trace:
                    pre_veto_action = getattr(trace, "pre_veto_action", "")
                break
        if pre_veto_action and pre_veto_action.upper() in ("BUY", "SELL"):
            shadow_dir = infer_direction(pre_veto_action)
            shadow_r = evaluate_signal(
                run_id=r.run_id, ticker=r.ticker, ticker_name=r.ticker_name,
                trade_date=r.trade_date, action=r.action, confidence=r.confidence,
                was_vetoed=True, stop_loss=r.stop_loss, take_profit=r.take_profit,
                config=config, forward_bars=None if fetch_prices else [],
                signal_close=0.0, shadow_direction=shadow_dir,
            )
            shadow_results.append(shadow_r)

    # Compute summaries — shadow results are tracked separately
    overall = compute_summary(results, scope="overall", config=config)
    # Compute shadow stats from the dedicated shadow list
    shadow_completed = [r for r in shadow_results if r.eval_status == "shadow_veto"]
    overall.shadow_veto_count = len(shadow_completed)
    overall.shadow_veto_wins = sum(1 for r in shadow_completed if r.outcome == "win")

    per_ticker = {}
    ticker_groups: Dict[str, List[BacktestResult]] = {}
    for r in results:
        ticker_groups.setdefault(r.ticker, []).append(r)
    for tk, tk_results in ticker_groups.items():
        per_ticker[tk] = compute_summary(tk_results, scope=tk, config=config)

    report = BacktestReport(
        config=config,
        results=results,
        shadow_results=shadow_results,
        overall_summary=overall,
        per_ticker_summaries=per_ticker,
        generated_at=datetime.now().isoformat(),
    )
    return report


def run_backtest_from_ledger(
    ledger_path: str = "data/signals/signals.jsonl",
    config: BacktestConfig = None,
    ticker: str = None,
    after: str = None,
    before: str = None,
) -> BacktestReport:
    """Run backtest using signal ledger as input (faster, no RunTrace loading).

    Differences from run_backtest():
    - Deduplicates by (ticker, trade_date) — same as run_backtest.
    - Does NOT perform shadow VETO analysis (no RunTrace to look up pre-veto action).

    Args:
        ledger_path: Path to signal ledger JSONL.
        config: Backtest configuration.
        ticker: Optional ticker filter.
        after: Only signals on or after this date.
        before: Only signals on or before this date.
    """
    from .signal_ledger import SignalLedger

    config = config or BacktestConfig()
    ledger = SignalLedger(path=ledger_path)
    signals = ledger.read(ticker=ticker, after=after, before=before)

    today = datetime.now()
    results = []

    for sig in signals:
        if sig.action.upper() not in ("BUY", "HOLD", "SELL", "VETO"):
            continue
        try:
            sig_dt = datetime.strptime(sig.trade_date, "%Y-%m-%d")
            if (today - sig_dt).days < config.min_age_days:
                continue
        except ValueError:
            continue

        result = evaluate_signal(
            run_id=sig.run_id,
            ticker=sig.ticker,
            ticker_name=sig.ticker_name,
            trade_date=sig.trade_date,
            action=sig.action,
            confidence=sig.confidence,
            was_vetoed=sig.was_vetoed,
            stop_loss=sig.stop_loss,
            take_profit=sig.take_profit,
            config=config,
            signal_close=sig.entry_price if sig.entry_price > 0 else 0.0,
        )
        results.append(result)

    # Deduplicate: keep latest per (ticker, trade_date)
    seen: Dict[tuple, BacktestResult] = {}
    for r in results:
        key = (r.ticker, r.trade_date)
        if key not in seen or r.run_id > seen[key].run_id:
            seen[key] = r
    results = list(seen.values())
    results.sort(key=lambda r: r.trade_date, reverse=True)

    overall = compute_summary(results, scope="overall", config=config)
    per_ticker: Dict[str, BacktestSummary] = {}
    ticker_groups: Dict[str, List[BacktestResult]] = {}
    for r in results:
        ticker_groups.setdefault(r.ticker, []).append(r)
    for tk, tk_results in ticker_groups.items():
        per_ticker[tk] = compute_summary(tk_results, scope=tk, config=config)

    return BacktestReport(
        config=config,
        results=results,
        overall_summary=overall,
        per_ticker_summaries=per_ticker,
        generated_at=datetime.now().isoformat(),
    )


# ── Persistence ───────────────────────────────────────────────────────────

def save_backtest_report(report: BacktestReport, output_dir: str = "data/reports") -> Path:
    """Save backtest report as JSON."""
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"backtest-{datetime.now().strftime('%Y%m%d')}.json"

    import tempfile, os
    fd, tmp = tempfile.mkstemp(dir=str(out_dir), suffix=".tmp", prefix=".bt-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(report.to_dict(), f, ensure_ascii=False, indent=2)
        os.replace(tmp, str(path))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise

    logger.info(f"Saved backtest report: {path}")
    return path


def load_backtest_report(path: str) -> Optional[BacktestReport]:
    """Load a previously saved backtest report."""
    p = Path(path)
    if not p.exists():
        return None
    with open(p, "r", encoding="utf-8") as f:
        data = json.load(f)
    import dataclasses as _dc
    _cfg_fields = {f.name for f in _dc.fields(BacktestConfig)}
    _sum_fields = {f.name for f in _dc.fields(BacktestSummary)}
    config = BacktestConfig(**{k: v for k, v in data.get("config", {}).items() if k in _cfg_fields})
    results = [BacktestResult.from_dict(r) for r in data.get("results", [])]
    shadow = [BacktestResult.from_dict(r) for r in data.get("shadow_results", [])]
    overall = BacktestSummary(**{k: v for k, v in data.get("overall_summary", {}).items() if k in _sum_fields})
    per_ticker = {
        k: BacktestSummary(**{kk: vv for kk, vv in v.items() if kk in _sum_fields})
        for k, v in data.get("per_ticker_summaries", {}).items()
    }
    return BacktestReport(
        config=config,
        results=results,
        shadow_results=shadow,
        overall_summary=overall,
        per_ticker_summaries=per_ticker,
        generated_at=data.get("generated_at", ""),
    )


# ── Benchmark: CSI 300 (沪深300) ──────────────────────────────────────────

def _fetch_benchmark_return(signal_date: str, window_days: int) -> Optional[float]:
    """Fetch CSI 300 return over `window_days` after signal_date.

    Returns percentage return or None if data unavailable.
    """
    import requests as _requests
    import time as _time

    # Use Sina's sh000300 (CSI 300 index) — adaptive datalen like individual stocks
    url = "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
    try:
        sig_dt = datetime.strptime(signal_date, "%Y-%m-%d")
        approx_days = int((datetime.now() - sig_dt).days * 5 / 7) + window_days + 10
    except ValueError:
        approx_days = 60
    datalen = max(60, approx_days)
    params = {"symbol": "sh000300", "scale": "240", "ma": "no", "datalen": str(datalen)}
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://finance.sina.com.cn/",
    }
    _time.sleep(0.3)
    try:
        r = _requests.get(url, params=params, headers=headers, timeout=15)
        if r.status_code != 200:
            return None
        data = r.json()
        if not isinstance(data, list):
            return None
    except Exception as e:
        logger.warning(f"Benchmark fetch failed for {signal_date}/{window_days}: {e}", exc_info=True)
        return None

    # Find signal date close and forward close
    signal_close = None
    for d in reversed(data):
        if d.get("day", "") <= signal_date:
            signal_close = float(d.get("close", 0))
            break
    if not signal_close or signal_close <= 0:
        return None

    forward_bars = [d for d in data if d.get("day", "") > signal_date]
    if len(forward_bars) < window_days:
        forward_close = float(forward_bars[-1]["close"]) if forward_bars else None
    else:
        forward_close = float(forward_bars[window_days - 1]["close"])

    if not forward_close:
        return None

    return round((forward_close - signal_close) / signal_close * 100, 2)


# ── Multi-Window Backtest ─────────────────────────────────────────────────

@dataclass
class MultiWindowReport:
    """Backtest results across multiple evaluation windows."""
    windows: List[int] = field(default_factory=list)           # e.g. [5, 10, 20]
    reports: Dict[int, BacktestReport] = field(default_factory=dict)
    benchmark_returns: Dict[str, Dict[int, float]] = field(default_factory=dict)
    # benchmark_returns[trade_date][window] = CSI300 return%
    confidence_groups: Dict[str, BacktestSummary] = field(default_factory=dict)
    # "high"/"medium"/"low" -> summary
    generated_at: str = ""


def run_multi_window_backtest(
    ledger_path: str = "data/signals/signals.jsonl",
    windows: List[int] = None,
    ticker: str = None,
    after: str = None,
    before: str = None,
    fetch_benchmark: bool = True,
) -> MultiWindowReport:
    """Run backtest across multiple evaluation windows + benchmark + confidence grouping.

    Args:
        ledger_path: Path to signal ledger.
        windows: List of eval windows in trading days (default: [5, 10, 20]).
        ticker: Optional ticker filter.
        after/before: Date range filters.
        fetch_benchmark: Whether to fetch CSI 300 benchmark returns.
    """
    windows = windows or [5, 10, 20]
    multi = MultiWindowReport(windows=windows, generated_at=datetime.now().isoformat())

    for w in windows:
        # min_age_days=0: intentional — multi-window includes all signals to show
        # how evaluation window length affects results across the full sample
        config = BacktestConfig(eval_window_days=w, neutral_band_pct=2.0, min_age_days=0)
        report = run_backtest_from_ledger(
            ledger_path=ledger_path,
            config=config,
            ticker=ticker,
            after=after,
            before=before,
        )
        multi.reports[w] = report

    # Benchmark: fetch CSI 300 returns for each unique signal date × window
    if fetch_benchmark:
        # Use first window's results for date list
        first_report = multi.reports.get(windows[0])
        if first_report:
            dates = sorted(set(
                r.trade_date for r in first_report.results
                if r.eval_status == "completed"
            ))
            for d in dates:
                multi.benchmark_returns[d] = {}
                for w in windows:
                    ret = _fetch_benchmark_return(d, w)
                    if ret is not None:
                        multi.benchmark_returns[d][w] = ret

    # Confidence grouping (using first window's results)
    first_report = multi.reports.get(windows[0])
    if first_report:
        completed = [r for r in first_report.results if r.eval_status == "completed"]
        high = [r for r in completed if r.confidence >= 0.75]
        medium = [r for r in completed if 0.5 <= r.confidence < 0.75]
        low = [r for r in completed if 0 <= r.confidence < 0.5]

        config0 = BacktestConfig(eval_window_days=windows[0])
        if high:
            multi.confidence_groups["high"] = compute_summary(high, "high_conf", config0)
        if medium:
            multi.confidence_groups["medium"] = compute_summary(medium, "medium_conf", config0)
        if low:
            multi.confidence_groups["low"] = compute_summary(low, "low_conf", config0)

    return multi


# ── Multi-Window HTML Report ─────────────────────────────────────────────

def generate_multi_window_report(
    multi: MultiWindowReport,
    output_dir: str = "data/reports",
) -> str:
    """Generate comprehensive HTML backtest report with multi-window + benchmark."""
    from .renderers.decision_labels import get_signal_emoji, get_action_label

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    html = [_BT_HTML_HEAD.replace("回测验证报告", "回测验证报告（多窗口）")]

    # Hero
    html.append(
        '<div class="hero reveal"><div>'
        '<div class="eyebrow">MULTI-WINDOW BACKTEST</div>'
        '<h1>回测验证报告（多窗口）</h1>'
        f'<div class="subtitle">窗口: '
        f'{"/".join(str(w) for w in multi.windows)} 交易日</div>'
        '</div></div>'
    )

    # ── Section 1: Multi-window comparison table ──
    html.append('<h2>多窗口对比</h2>')
    html.append('<table class="bt-table"><thead><tr>')
    html.append('<th>指标</th>')
    for w in multi.windows:
        html.append(f'<th>{w}日</th>')
    html.append('</tr></thead><tbody>')

    metrics = [
        ("已评估", lambda s: str(s.completed)),
        ("方向准确率", lambda s: f"{s.direction_accuracy_pct:.1f}%"),
        ("胜率", lambda s: f"{s.win_rate_pct:.1f}%"),
        ("平均收益", lambda s: f"{s.avg_stock_return_pct:+.2f}%"),
        ("BUY 平均收益", lambda s: f"{s.avg_buy_return_pct:+.2f}%"),
        ("SELL 反向收益", lambda s: f"{s.avg_sell_return_pct:+.2f}%"),
    ]
    for label, fn in metrics:
        html.append(f'<tr><td>{label}</td>')
        for w in multi.windows:
            rpt = multi.reports.get(w)
            if rpt:
                html.append(f'<td>{fn(rpt.overall_summary)}</td>')
            else:
                html.append('<td>—</td>')
        html.append('</tr>')

    # Benchmark row
    if multi.benchmark_returns:
        html.append(f'<tr><td>沪深300 平均</td>')
        for w in multi.windows:
            rets = [v.get(w) for v in multi.benchmark_returns.values() if v.get(w) is not None]
            if rets:
                avg = sum(rets) / len(rets)
                html.append(f'<td>{avg:+.2f}%</td>')
            else:
                html.append('<td>—</td>')
        html.append('</tr>')

        # Alpha row
        html.append(f'<tr><td><strong>超额收益 (Alpha)</strong></td>')
        for w in multi.windows:
            rpt = multi.reports.get(w)
            rets = [v.get(w) for v in multi.benchmark_returns.values() if v.get(w) is not None]
            if rpt and rets:
                bench_avg = sum(rets) / len(rets)
                alpha = rpt.overall_summary.avg_stock_return_pct - bench_avg
                css = "buy" if alpha > 0 else "sell"
                html.append(f'<td class="{css}"><strong>{alpha:+.2f}%</strong></td>')
            else:
                html.append('<td>—</td>')
        html.append('</tr>')

    html.append('</tbody></table>')

    # ── Section 2: Confidence grouping ──
    if multi.confidence_groups:
        html.append('<h2>按置信度分组</h2>')
        html.append('<table class="bt-table"><thead><tr>')
        html.append('<th>置信度</th><th>信号数</th><th>方向准确率</th>'
                   '<th>胜率</th><th>平均收益</th>')
        html.append('</tr></thead><tbody>')
        labels = {"high": "高 (≥75%)", "medium": "中 (50-75%)", "low": "低 (<50%)"}
        for level in ("high", "medium", "low"):
            s = multi.confidence_groups.get(level)
            if not s:
                continue
            html.append(
                f'<tr><td>{labels[level]}</td>'
                f'<td class="num">{s.completed}</td>'
                f'<td class="num">{s.direction_accuracy_pct:.1f}%</td>'
                f'<td class="num">{s.win_rate_pct:.1f}%</td>'
                f'<td class="num">{s.avg_stock_return_pct:+.2f}%</td></tr>'
            )
        html.append('</tbody></table>')

    # ── Section 3: Per-action breakdown (first window) ──
    first_rpt = multi.reports.get(multi.windows[0])
    if first_rpt and first_rpt.overall_summary.action_breakdown:
        s = first_rpt.overall_summary
        html.append(f'<h2>分类统计（{multi.windows[0]}日窗口）</h2>')
        html.append('<table class="bt-table"><thead><tr>')
        html.append('<th>信号</th><th>次数</th><th>平均收益</th><th>胜率</th>')
        html.append('</tr></thead><tbody>')
        for action in ("BUY", "HOLD", "SELL", "VETO"):
            bd = s.action_breakdown.get(action)
            if not bd:
                continue
            emoji = get_signal_emoji(action)
            label = get_action_label(action)
            html.append(
                f'<tr><td>{emoji} {_esc(label)}</td>'
                f'<td class="num">{bd["count"]}</td>'
                f'<td class="num">{bd["avg_return_pct"]:+.2f}%</td>'
                f'<td class="num">{bd["win_rate_pct"]:.1f}%</td></tr>'
            )
        html.append('</tbody></table>')

        # HOLD performance warning (Bug 11)
        hold_bd_mw = s.action_breakdown.get("HOLD")
        if hold_bd_mw and hold_bd_mw.get("count", 0) >= 2:
            hold_wr_mw = hold_bd_mw.get("win_rate_pct", 0.0)
            if hold_wr_mw < 40.0:
                html.append(
                    f'<div style="background:rgba(251,191,36,0.12);border:1px solid rgba(251,191,36,0.3);'
                    f'border-radius:10px;padding:12px 16px;margin:12px 0;color:#fbbf24;">'
                    f'<strong>&#9888; HOLD信号表现预警</strong>: 胜率仅 {hold_wr_mw:.1f}%，低于40%阈值。</div>'
                )

    # ── Section 4: Per-date benchmark comparison ──
    if multi.benchmark_returns and first_rpt:
        w0 = multi.windows[0]
        completed = [r for r in first_rpt.results if r.eval_status == "completed"]
        dates = sorted(set(r.trade_date for r in completed))
        if dates:
            html.append(f'<h2>逐日对比 vs 沪深300（{w0}日窗口）</h2>')
            html.append('<table class="bt-table"><thead><tr>')
            html.append('<th>日期</th><th>信号数</th><th>信号平均收益</th>'
                       '<th>沪深300</th><th>Alpha</th>')
            html.append('</tr></thead><tbody>')
            for d in dates:
                day_results = [r for r in completed if r.trade_date == d]
                if not day_results:
                    continue
                avg_ret = sum(r.stock_return_pct for r in day_results) / len(day_results)
                bench = multi.benchmark_returns.get(d, {}).get(w0)
                if bench is not None:
                    alpha = avg_ret - bench
                    alpha_css = "buy" if alpha > 0 else "sell"
                    html.append(
                        f'<tr><td>{d}</td><td>{len(day_results)}</td>'
                        f'<td>{avg_ret:+.2f}%</td>'
                        f'<td>{bench:+.2f}%</td>'
                        f'<td class="{alpha_css}">{alpha:+.2f}%</td></tr>'
                    )
                else:
                    html.append(
                        f'<tr><td>{d}</td><td>{len(day_results)}</td>'
                        f'<td>{avg_ret:+.2f}%</td><td>—</td><td>—</td></tr>'
                    )
            html.append('</tbody></table>')

    # ── Section 4b: Cumulative return chart (with benchmark) ──
    if first_rpt:
        chart_completed = [r for r in first_rpt.results if r.eval_status == "completed"]
        if chart_completed:
            html.append(
                '<div class="reveal reveal-d2">'
                + _cumulative_return_svg(
                    chart_completed,
                    benchmark_returns=multi.benchmark_returns or None,
                )
                + '</div>'
            )

    # ── Section 5: Signal detail (first window) ──
    if first_rpt:
        completed = [r for r in first_rpt.results if r.eval_status == "completed"]
        if completed:
            w0 = multi.windows[0]
            html.append(f'<h2>信号明细（{w0}日窗口）</h2>')
            html.append('<table class="bt-table detail"><thead><tr>')
            html.append(
                '<th>日期</th><th>股票</th><th>信号</th>'
                '<th>置信度</th><th>入场价</th><th>出场价</th><th>收益</th>'
                '<th>最大回撤</th><th>结果</th>'
            )
            html.append('</tr></thead><tbody>')
            for r in completed:
                emoji = get_signal_emoji(r.action)
                outcome_cls = {"win": "buy", "loss": "sell", "neutral": "hold"}.get(r.outcome, "hold")
                outcome_label = {"win": "盈利", "loss": "亏损", "neutral": "持平"}.get(r.outcome, "—")
                conf = f"{r.confidence:.0%}" if r.confidence >= 0 else "—"
                html.append(
                    f'<tr>'
                    f'<td>{_esc(r.trade_date)}</td>'
                    f'<td>{_esc(r.ticker_name or r.ticker)}</td>'
                    f'<td>{emoji} {_esc(r.action)}</td>'
                    f'<td class="num">{conf}</td>'
                    f'<td class="num">{r.start_price:.2f}</td>'
                    f'<td class="num">{r.end_close:.2f}</td>'
                    f'<td class="num {outcome_cls}">{r.stock_return_pct:+.2f}%</td>'
                    f'<td class="num sell">{r.max_drawdown_pct:+.2f}%</td>'
                    f'<td class="{outcome_cls}">{outcome_label}</td>'
                    f'</tr>'
                )
            html.append('</tbody></table>')

    # Footer
    windows_str = "/".join(str(w) for w in multi.windows)
    html.append(
        f'<div class="footer">'
        f'评估窗口: {windows_str} 交易日 | '
        f'中性区间: ±2% | '
        f'基准: 沪深300 (000300.SH) | '
        f'生成时间: {multi.generated_at[:19]}<br>'
        f'<em>AI 多智能体系统回测验证，仅供研究参考</em>'
        f'</div>'
    )
    html.append(_BT_JS)
    html.append('</div></body></html>')

    path = out_dir / f"backtest-multi-{datetime.now().strftime('%Y%m%d')}.html"
    path.write_text("\n".join(html), encoding="utf-8")
    logger.info(f"Generated multi-window backtest report: {path}")
    return str(path)


# ── HTML Report Generation ────────────────────────────────────────────────

def generate_backtest_report(
    report: BacktestReport,
    output_dir: str = "data/reports",
) -> str:
    """Generate standalone HTML backtest report.

    Returns the output file path.
    """
    from .renderers.decision_labels import (
        get_signal_emoji, get_action_label, SIGNAL_EMOJI,
    )

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    s = report.overall_summary
    completed = [r for r in report.results if r.eval_status == "completed"]

    # Build HTML
    html_parts = [_BT_HTML_HEAD]

    # ── Hero section ──
    gen_date = report.generated_at[:10] if report.generated_at else ""
    html_parts.append(
        f'<div class="hero reveal">'
        f'<div class="hero-grid"><div>'
        f'<div class="eyebrow">BACKTEST VERIFICATION</div>'
        f'<h1>回测验证报告</h1>'
        f'<div class="subtitle">'
        f'评估窗口 {report.config.eval_window_days} 交易日 · '
        f'中性区间 ±{report.config.neutral_band_pct}% · {gen_date}</div>'
        f'</div><div>'
        f'<div class="summary-row">'
        + _card("总信号数", str(s.total_signals), "kpi-secondary")
        + _card("已评估", str(s.completed), "kpi-secondary")
        + _card("平均收益",
                f"{s.avg_stock_return_pct:+.2f}%" if s.completed else "—",
                "kpi-primary")
        + '</div></div></div></div>'
    )

    # ── Donut gauges ──
    if s.completed:
        dir_color = "var(--green)" if s.direction_accuracy_pct >= 50 else "var(--red)"
        wr_color = "var(--green)" if s.win_rate_pct >= 50 else "var(--red)"
        html_parts.append(
            '<div class="donut-row reveal reveal-d1">'
            + _donut_gauge(s.direction_accuracy_pct, "方向准确率", dir_color)
            + _donut_gauge(s.win_rate_pct, "胜率", wr_color)
            + '</div>'
        )

    # ── Cumulative return curve ──
    if completed:
        html_parts.append(
            '<div class="reveal reveal-d2">'
            + _cumulative_return_svg(completed)
            + '</div>'
        )

    # ── Action distribution + breakdown table ──
    dist_bar = _action_distribution_bar(s)
    if dist_bar:
        html_parts.append(f'<div class="reveal reveal-d3">{dist_bar}</div>')

    if s.action_breakdown:
        html_parts.append('<h2>分类统计</h2>')
        html_parts.append('<table class="bt-table"><thead><tr>')
        html_parts.append('<th>信号</th><th class="sortable">次数</th>'
                         '<th class="sortable">平均收益</th>'
                         '<th class="sortable">胜率</th>')
        html_parts.append('</tr></thead><tbody>')
        for action in ("BUY", "HOLD", "SELL", "VETO"):
            bd = s.action_breakdown.get(action)
            if not bd:
                continue
            emoji = get_signal_emoji(action)
            label = get_action_label(action)
            html_parts.append(
                f'<tr><td>{emoji} {_esc(label)}</td>'
                f'<td class="num">{bd["count"]}</td>'
                f'<td class="num">{bd["avg_return_pct"]:+.2f}%</td>'
                f'<td class="num">{bd["win_rate_pct"]:.1f}%</td></tr>'
            )
        html_parts.append('</tbody></table>')

        # HOLD performance warning (Bug 11)
        hold_bd = s.action_breakdown.get("HOLD")
        if hold_bd and hold_bd.get("count", 0) >= 2:
            hold_wr = hold_bd.get("win_rate_pct", 0.0)
            if hold_wr < 40.0:
                html_parts.append(
                    f'<div style="background:rgba(251,191,36,0.12);border:1px solid rgba(251,191,36,0.3);'
                    f'border-radius:10px;padding:12px 16px;margin:12px 0;color:#fbbf24;">'
                    f'<strong>&#9888; HOLD信号表现预警</strong>: 胜率仅 {hold_wr:.1f}%，低于40%阈值。'
                    f'共 {hold_bd["count"]} 次HOLD信号，建议关注HOLD决策的参考价值。</div>'
                )

        # Shadow VETO analysis section (Bug 12)
        if s.shadow_veto_count > 0:
            sw = s.shadow_veto_wins
            sc = s.shadow_veto_count
            sw_pct = round(sw / sc * 100, 1) if sc > 0 else 0.0
            html_parts.append(
                f'<div style="background:rgba(139,92,246,0.08);border:1px solid rgba(139,92,246,0.2);'
                f'border-radius:10px;padding:12px 16px;margin:12px 0;color:#a78bfa;">'
                f'<strong>VETO影子分析</strong>: {sc} 个被否决信号的假设回测中，{sw} 个本可盈利'
                f'（影子胜率 {sw_pct:.1f}%）。此数据仅供参考，不改变否决决策。</div>'
            )

    # ── Per-ticker summary ──
    if report.per_ticker_summaries:
        html_parts.append('<h2>个股统计</h2>')
        html_parts.append('<table class="bt-table"><thead><tr>')
        html_parts.append(
            '<th class="sortable">股票</th><th class="sortable">信号数</th>'
            '<th class="sortable">方向准确率</th>'
            '<th class="sortable">胜率</th>'
            '<th class="sortable">平均收益</th></tr></thead><tbody>'
        )
        for tk, ts in sorted(report.per_ticker_summaries.items()):
            name = ""
            for r in report.results:
                if r.ticker == tk and r.ticker_name:
                    name = r.ticker_name
                    break
            display = f"{_esc(name or tk)}"
            html_parts.append(
                f'<tr><td>{display}</td>'
                f'<td class="num">{ts.completed}</td>'
                f'<td class="num">{ts.direction_accuracy_pct:.1f}%</td>'
                f'<td class="num">{ts.win_rate_pct:.1f}%</td>'
                f'<td class="num">{ts.avg_stock_return_pct:+.2f}%</td></tr>'
            )
        html_parts.append('</tbody></table>')

    # ── Detail table ──
    if completed:
        html_parts.append('<h2>信号明细</h2>')
        html_parts.append('<table class="bt-table detail"><thead><tr>')
        html_parts.append(
            '<th class="sortable">日期</th><th class="sortable">股票</th>'
            '<th>信号</th>'
            '<th class="sortable">入场价</th><th class="sortable">出场价</th>'
            '<th class="sortable">收益</th>'
            '<th class="sortable">最大回撤</th><th class="sortable">最大浮盈</th>'
            '<th>走势</th><th class="sortable">结果</th>'
        )
        html_parts.append('</tr></thead><tbody>')
        for r in completed:
            emoji = get_signal_emoji(r.action)
            outcome_cls = {
                "win": "buy", "loss": "sell", "neutral": "hold"
            }.get(r.outcome, "hold")
            outcome_label = {"win": "盈利", "loss": "亏损", "neutral": "持平"}.get(
                r.outcome, "—"
            )
            spark = _signal_sparkline(r)
            html_parts.append(
                f'<tr>'
                f'<td>{_esc(r.trade_date)}</td>'
                f'<td>{_esc(r.ticker_name or r.ticker)}</td>'
                f'<td>{emoji} {_esc(r.action)}</td>'
                f'<td class="num">{r.start_price:.2f}</td>'
                f'<td class="num">{r.end_close:.2f}</td>'
                f'<td class="num {outcome_cls}">{r.stock_return_pct:+.2f}%</td>'
                f'<td class="num sell">{r.max_drawdown_pct:+.2f}%</td>'
                f'<td class="num buy">{r.max_gain_pct:+.2f}%</td>'
                f'<td class="sparkline-cell">{spark}</td>'
                f'<td class="{outcome_cls}">{outcome_label}</td>'
                f'</tr>'
            )
        html_parts.append('</tbody></table>')

    # Footer
    html_parts.append(
        f'<div class="footer">'
        f'评估窗口: {report.config.eval_window_days} 交易日 | '
        f'中性区间: ±{report.config.neutral_band_pct}% | '
        f'生成时间: {report.generated_at[:19]}<br>'
        f'<em>AI 多智能体系统回测验证，仅供研究参考</em>'
        f'</div>'
    )

    html_parts.append(_BT_JS)
    html_parts.append('</div></body></html>')
    html = "\n".join(html_parts)

    path = out_dir / f"backtest-{datetime.now().strftime('%Y%m%d')}.html"
    path.write_text(html, encoding="utf-8")
    logger.info(f"Generated backtest report: {path}")
    return str(path)


def _esc(text: str) -> str:
    """HTML-escape."""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _card(title: str, value: str, tier: str = "") -> str:
    cls = f"card {tier}" if tier else "card"
    return f'<div class="{cls}"><div class="card-title">{_esc(title)}</div><div class="card-value">{_esc(value)}</div></div>'


# ── SVG Helpers ─────────────────────────────────────────────────────────

import math as _math


def _donut_gauge(value_pct: float, label: str, color: str = "var(--green)",
                 size: int = 120) -> str:
    """SVG donut gauge with percentage in center."""
    r = size * 0.38
    circ = 2 * _math.pi * r
    dash = circ * min(max(value_pct, 0), 100) / 100
    cx = cy = size / 2
    txt = f"{value_pct:.1f}%" if value_pct > 0 else "—"
    return (
        f'<div class="donut-wrap">'
        f'<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}">'
        f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" '
        f'stroke="rgba(255,255,255,0.06)" stroke-width="10"/>'
        f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" '
        f'stroke="{color}" stroke-width="10" '
        f'stroke-dasharray="{dash:.1f} {circ:.1f}" '
        f'stroke-linecap="round" '
        f'transform="rotate(-90 {cx} {cy})" '
        f'class="donut-fill"/>'
        f'<text x="{cx}" y="{cy}" text-anchor="middle" dominant-baseline="central" '
        f'fill="var(--white)" font-size="{size * 0.18:.0f}px" font-weight="800" '
        f'font-family="var(--mono)">{txt}</text>'
        f'</svg>'
        f'<div class="donut-label">{_esc(label)}</div>'
        f'</div>'
    )


def _cumulative_return_svg(results: list, benchmark_returns: dict = None,
                           w: int = 660, h: int = 180) -> str:
    """SVG cumulative return curve with optional benchmark + drawdown shading."""
    sorted_r = sorted(results, key=lambda r: r.trade_date)
    if not sorted_r:
        return ""
    cum = []
    running = 0.0
    for r in sorted_r:
        running += r.stock_return_pct
        cum.append((r.trade_date, running))

    # Build benchmark cumulative series (if available)
    bench_cum = []
    if benchmark_returns:
        b_running = 0.0
        for date, val in cum:
            b_ret = benchmark_returns.get(date, {})
            # Use smallest window available as single-period return proxy
            b_pct = None
            for wk in sorted(b_ret.keys()):
                b_pct = b_ret[wk]
                break
            if b_pct is not None:
                b_running += b_pct
            bench_cum.append((date, b_running))

    pad_x, pad_y = 50, 24
    plot_w = w - pad_x - 10
    plot_h = h - pad_y * 2
    all_vals = [c[1] for c in cum]
    if bench_cum:
        all_vals += [c[1] for c in bench_cum]
    v_min = min(min(all_vals), 0)
    v_max = max(max(all_vals), 0)
    v_range = v_max - v_min or 1

    def sx(i: int) -> float:
        return pad_x + (i / max(len(cum) - 1, 1)) * plot_w

    def sy(v: float) -> float:
        return pad_y + (1 - (v - v_min) / v_range) * plot_h

    zero_y = sy(0)
    pts = " ".join(f"{sx(i):.1f},{sy(v):.1f}" for i, (_, v) in enumerate(cum))
    area = pts + f" {sx(len(cum) - 1):.1f},{zero_y:.1f} {sx(0):.1f},{zero_y:.1f}"
    final_color = "#34d399" if cum[-1][1] >= 0 else "#f87171"

    # Drawdown shading: area between running peak and cumulative line
    dd_path = ""
    peak = 0.0
    dd_points = []
    for i, (_, v) in enumerate(cum):
        peak = max(peak, v)
        if peak > v:  # in drawdown
            dd_points.append((i, peak, v))
        else:
            if dd_points:
                # Close the drawdown polygon
                poly = " ".join(f"{sx(j):.1f},{sy(pv):.1f}" for j, pv, _ in dd_points)
                poly += " " + " ".join(f"{sx(j):.1f},{sy(cv):.1f}" for j, _, cv in reversed(dd_points))
                dd_path += f'<polygon points="{poly}" fill="#f87171" opacity="0.08"/>'
                dd_points = []
            dd_points = []
    if dd_points:
        poly = " ".join(f"{sx(j):.1f},{sy(pv):.1f}" for j, pv, _ in dd_points)
        poly += " " + " ".join(f"{sx(j):.1f},{sy(cv):.1f}" for j, _, cv in reversed(dd_points))
        dd_path += f'<polygon points="{poly}" fill="#f87171" opacity="0.08"/>'

    # Benchmark polyline
    bench_svg = ""
    if bench_cum and len(bench_cum) == len(cum):
        b_pts = " ".join(f"{sx(i):.1f},{sy(v):.1f}" for i, (_, v) in enumerate(bench_cum))
        bench_svg = f'<polyline points="{b_pts}" fill="none" stroke="#60a5fa" stroke-width="1.5" stroke-dasharray="4 3" stroke-linejoin="round" opacity=".7"/>'

    # Legend
    legend_y = 12
    legend_svg = (
        f'<line x1="{pad_x}" y1="{legend_y}" x2="{pad_x + 20}" y2="{legend_y}" stroke="{final_color}" stroke-width="2"/>'
        f'<text x="{pad_x + 24}" y="{legend_y + 3}" fill="#8fa3b8" font-size="9">\u7b56\u7565</text>'
    )
    if bench_svg:
        legend_svg += (
            f'<line x1="{pad_x + 60}" y1="{legend_y}" x2="{pad_x + 80}" y2="{legend_y}" stroke="#60a5fa" stroke-width="1.5" stroke-dasharray="4 3"/>'
            f'<text x="{pad_x + 84}" y="{legend_y + 3}" fill="#8fa3b8" font-size="9">\u6caa\u6df1300</text>'
        )

    d_first = cum[0][0][-5:] if cum[0][0] else ""
    d_last = cum[-1][0][-5:] if cum[-1][0] else ""

    return (
        f'<div class="cum-chart card">'
        f'<h3>\u7d2f\u8ba1\u6536\u76ca\u66f2\u7ebf</h3>'
        f'<p style="margin:-0.3rem 0 0.4rem;font-size:0.75rem;color:#8fa3b8;">'
        f'\u7b80\u5355\u7d2f\u52a0\u53e3\u5f84\uff0c\u4ec5\u4f9b\u8d8b\u52bf\u53c2\u8003</p>'
        f'<svg viewBox="0 0 {w} {h}" width="100%" height="auto" '
        f'style="max-height:{h}px">'
        f'<defs><linearGradient id="cg" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0%" stop-color="{final_color}" stop-opacity="0.25"/>'
        f'<stop offset="100%" stop-color="{final_color}" stop-opacity="0.02"/>'
        f'</linearGradient></defs>'
        f'{legend_svg}'
        f'<line x1="{pad_x}" y1="{zero_y:.1f}" x2="{w - 10}" y2="{zero_y:.1f}" '
        f'stroke="rgba(255,255,255,0.1)" stroke-dasharray="4 3"/>'
        f'{dd_path}'
        f'<polygon points="{area}" fill="url(#cg)"/>'
        f'{bench_svg}'
        f'<polyline points="{pts}" fill="none" stroke="{final_color}" '
        f'stroke-width="2" stroke-linejoin="round"/>'
        f'<text x="{pad_x - 4}" y="{sy(v_max):.1f}" text-anchor="end" '
        f'fill="#8fa3b8" font-size="9" font-family="var(--mono)">'
        f'{v_max:+.1f}%</text>'
        f'<text x="{pad_x - 4}" y="{sy(v_min):.1f}" text-anchor="end" '
        f'fill="#8fa3b8" font-size="9" font-family="var(--mono)">'
        f'{v_min:+.1f}%</text>'
        f'<text x="{pad_x - 4}" y="{zero_y:.1f}" text-anchor="end" '
        f'fill="#8fa3b8" font-size="9" font-family="var(--mono)">0%</text>'
        f'<text x="{sx(0):.1f}" y="{h - 2}" text-anchor="start" '
        f'fill="#8fa3b8" font-size="9">{_esc(d_first)}</text>'
        f'<text x="{sx(len(cum) - 1):.1f}" y="{h - 2}" text-anchor="end" '
        f'fill="#8fa3b8" font-size="9">{_esc(d_last)}</text>'
        f'</svg></div>'
    )


def _action_distribution_bar(summary) -> str:
    """Horizontal stacked bar showing BUY/HOLD/SELL/VETO distribution."""
    bd = summary.action_breakdown
    if not bd:
        return ""
    total = sum(bd[a]["count"] for a in bd)
    if total == 0:
        return ""

    colors = {"BUY": "var(--green)", "HOLD": "var(--yellow)",
              "SELL": "var(--red)", "VETO": "#8b4049"}
    labels = {"BUY": "买入", "HOLD": "持有", "SELL": "卖出", "VETO": "否决"}
    segs = []
    for action in ("BUY", "HOLD", "SELL", "VETO"):
        if action not in bd:
            continue
        cnt = bd[action]["count"]
        pct = cnt / total * 100
        if pct < 1:
            continue
        lbl = f"{labels[action]} {cnt}" if pct > 15 else ""
        segs.append(
            f'<div style="width:{pct:.1f}%;background:{colors[action]};'
            f'color:#fff;font-size:.72rem;font-weight:600;'
            f'display:flex;align-items:center;justify-content:center;'
            f'white-space:nowrap;padding:0 .3rem;min-width:2px">{lbl}</div>'
        )
    return (
        '<div class="card" style="margin:1rem 0">'
        '<h3>信号分布</h3>'
        '<div style="display:flex;height:28px;border-radius:999px;overflow:hidden;'
        'background:rgba(255,255,255,0.04);margin-top:.6rem">'
        + "".join(segs)
        + '</div></div>'
    )


def _signal_sparkline(r, w: int = 80, h: int = 20) -> str:
    """Mini SVG bar showing entry→exit with stop/take markers."""
    if r.start_price <= 0:
        return ""
    prices = [r.start_price, r.end_close]
    if r.max_high > 0:
        prices.append(r.max_high)
    if r.min_low > 0:
        prices.append(r.min_low)
    if r.stop_loss > 0:
        prices.append(r.stop_loss)
    if r.take_profit > 0:
        prices.append(r.take_profit)
    p_min = min(prices)
    p_max = max(prices)
    p_range = p_max - p_min or 1

    def sx(p: float) -> float:
        return 4 + (p - p_min) / p_range * (w - 8)

    color = "var(--green)" if r.stock_return_pct >= 0 else "var(--red)"
    x1, x2 = sx(r.start_price), sx(r.end_close)
    left = min(x1, x2)
    bar_w = max(abs(x2 - x1), 1)

    parts = [
        f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}">',
        f'<rect x="2" y="{h // 2 - 1}" width="{w - 4}" height="2" '
        f'fill="rgba(255,255,255,0.06)" rx="1"/>',
        f'<rect x="{left:.1f}" y="{h // 2 - 4}" width="{bar_w:.1f}" height="8" '
        f'fill="{color}" rx="2" opacity="0.7"/>',
    ]
    if r.stop_loss > 0:
        sl_x = sx(r.stop_loss)
        parts.append(
            f'<line x1="{sl_x:.1f}" y1="2" x2="{sl_x:.1f}" y2="{h - 2}" '
            f'stroke="var(--red)" stroke-width="1" stroke-dasharray="2 1"/>'
        )
    if r.take_profit > 0:
        tp_x = sx(r.take_profit)
        parts.append(
            f'<line x1="{tp_x:.1f}" y1="2" x2="{tp_x:.1f}" y2="{h - 2}" '
            f'stroke="var(--green)" stroke-width="1" stroke-dasharray="2 1"/>'
        )
    # Entry marker
    parts.append(
        f'<circle cx="{x1:.1f}" cy="{h // 2}" r="2.5" fill="var(--white)"/>'
    )
    parts.append('</svg>')
    return "".join(parts)


# ── Table Sort JS ────────────────────────────────────────────────────────

_BT_JS = """<script>
document.querySelectorAll('th.sortable').forEach(function(th){
  th.addEventListener('click',function(){
    var table=th.closest('table'), tbody=table.querySelector('tbody');
    if(!tbody) return;
    var idx=Array.from(th.parentNode.children).indexOf(th);
    var dir=th.getAttribute('data-sort-dir')==='asc'?'desc':'asc';
    th.parentNode.querySelectorAll('th').forEach(function(t){t.removeAttribute('data-sort-dir');});
    th.setAttribute('data-sort-dir',dir);
    var rows=Array.from(tbody.querySelectorAll('tr'));
    rows.sort(function(a,b){
      var av=a.children[idx]?a.children[idx].textContent.trim():'';
      var bv=b.children[idx]?b.children[idx].textContent.trim():'';
      var an=parseFloat(av.replace(/[^\\d.\\-+]/g,'')), bn=parseFloat(bv.replace(/[^\\d.\\-+]/g,''));
      if(!isNaN(an)&&!isNaN(bn)) return dir==='asc'?an-bn:bn-an;
      return dir==='asc'?av.localeCompare(bv):bv.localeCompare(av);
    });
    rows.forEach(function(r){tbody.appendChild(r);});
  });
});
</script>"""


# ── HTML Template ────────────────────────────────────────────────────────

_BT_HTML_HEAD = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>回测验证报告</title>
<style>
:root {
  --bg: #070e1b; --fg: #dde6f0; --card: rgba(11, 20, 35, 0.85);
  --border: rgba(100, 150, 180, 0.18); --green: #34d399; --red: #f87171;
  --yellow: #fbbf24; --blue: #60a5fa; --purple: #a78bfa; --muted: #8fa3b8; --white: #f1f7fd;
  --surface: rgba(14, 24, 40, 0.92); --accent: #f59e0b;
  --mono: "JetBrains Mono", "Fira Code", "SF Mono", Menlo, monospace;
  --signal-buy: var(--green);
  --signal-sell: var(--red);
  --signal-hold: var(--yellow);
  --signal-veto: var(--red);
  --state-success: var(--green); --state-danger: var(--red);
  --state-warning: var(--yellow); --state-info: var(--blue);
  --elev-1: 0 4px 12px rgba(0,0,0,0.15);
  --elev-2: 0 12px 28px rgba(0,0,0,0.25);
  --elev-3: 0 22px 54px rgba(0,0,0,0.35);
  --ease-out: cubic-bezier(0.22, 1, 0.36, 1);
  --dur-fast: 200ms; --dur-med: 360ms;
  --sp-1: 0.5rem; --sp-2: 1rem; --sp-3: 1.5rem; --sp-4: 2rem; --sp-6: 3rem;
}
* { margin:0; padding:0; box-sizing:border-box; }
::selection { background: rgba(96, 165, 250, 0.25); color: var(--white); }
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: rgba(100, 150, 180, 0.2); border-radius: 3px; }
body {
  font-family: "PingFang SC","Microsoft YaHei","Noto Sans SC",-apple-system,
               BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;
  background:
    radial-gradient(ellipse at 15% 20%, rgba(251,191,36,0.10), transparent 32%),
    radial-gradient(ellipse at 85% 18%, rgba(96,165,250,0.08), transparent 30%),
    radial-gradient(ellipse at 50% 110%, rgba(52,211,153,0.08), transparent 38%),
    linear-gradient(180deg, #091420 0%, #070e1b 55%, #050c17 100%);
  color: var(--fg); line-height:1.75;
  -webkit-font-smoothing: antialiased; text-rendering: optimizeLegibility;
}
.container { max-width:1100px; margin:0 auto; padding:2.2rem 1.5rem 4rem; }

h1 { color:var(--white); margin-bottom:.3rem;
     font-size:clamp(1.6rem,3vw,2.2rem); font-weight:800; letter-spacing:-0.03em; }
h2 { color:var(--accent); margin:2rem 0 1rem; font-size:1rem; font-weight:700;
     letter-spacing:0.1em; text-transform:uppercase; }
h3 { color:var(--white); margin:.6rem 0 .5rem; font-size:.92rem; font-weight:700; }
.subtitle { color:var(--muted); margin-bottom:1.2rem; font-size:.85rem; }

.card {
  background: linear-gradient(180deg, rgba(12,23,35,0.94), rgba(8,16,25,0.92));
  border: 1px solid rgba(255,255,255,0.06); border-radius:20px;
  padding:1.25rem 1.3rem; margin-bottom:1rem;
  box-shadow: 0 14px 34px rgba(0,0,0,0.18), inset 0 1px 0 rgba(255,255,255,0.04);
  backdrop-filter: blur(12px);
  transition: transform 280ms ease, box-shadow 280ms ease;
}
.card:hover {
  transform:translateY(-2px);
  box-shadow: 0 18px 44px rgba(0,0,0,0.24), inset 0 1px 0 rgba(255,255,255,0.06);
}
.card-title { font-size:.72rem; color:var(--muted); margin-bottom:.25rem;
              text-transform:uppercase; letter-spacing:.06em; }
.card-value { font-size:1.8rem; font-weight:800; font-family:var(--mono); }

.hero {
  position:relative; overflow:hidden; border-radius:28px;
  border:1px solid rgba(255,255,255,0.08);
  background: linear-gradient(135deg, rgba(12,29,45,0.96), rgba(12,21,31,0.88), rgba(20,30,38,0.9));
  box-shadow:0 22px 54px rgba(0,0,0,0.26); padding:2rem; margin-bottom:1.2rem;
}
.hero::after {
  content:""; position:absolute; inset:-20% auto auto 56%;
  width:340px; height:340px; border-radius:50%;
  background:radial-gradient(circle, rgba(96,165,250,0.12), transparent 64%);
  pointer-events:none;
}
.hero-grid {
  position:relative; z-index:1; display:grid;
  grid-template-columns:minmax(0,1.2fr) minmax(260px,0.8fr);
  gap:1.2rem; align-items:start;
}
.eyebrow {
  display:inline-flex; align-items:center; gap:.5rem;
  text-transform:uppercase; letter-spacing:.18em;
  font-size:.72rem; color:var(--accent); margin-bottom:.6rem;
}

.summary-row { display:flex; gap:.75rem; flex-wrap:wrap; margin:1rem 0; }
.summary-row .card { flex:1; min-width:130px; text-align:center; padding:1rem; }

.donut-wrap { display:flex; flex-direction:column; align-items:center; gap:.3rem; }
.donut-label { font-size:.72rem; color:var(--muted); text-transform:uppercase;
               letter-spacing:.06em; text-align:center; }
.donut-fill { transition: stroke-dasharray 800ms cubic-bezier(0.22,1,0.36,1); }
.donut-row { display:flex; gap:1.5rem; justify-content:center;
             flex-wrap:wrap; margin:1.2rem 0; }

.cum-chart { padding:1rem 1.3rem; }
.cum-chart h3 { margin-bottom:.4rem; }

.bt-table { width:100%; border-collapse:collapse;
  background: linear-gradient(180deg, rgba(12,23,35,0.94), rgba(8,16,25,0.92));
  border:1px solid rgba(255,255,255,0.06); border-radius:16px; overflow:hidden; }
.bt-table th {
  background:rgba(255,255,255,0.03); padding:.6rem .75rem; text-align:left;
  font-size:.72rem; color:var(--muted); border-bottom:1px solid rgba(255,255,255,0.06);
  text-transform:uppercase; letter-spacing:.06em; font-weight:600;
}
.bt-table td { padding:.55rem .75rem; border-bottom:1px solid rgba(255,255,255,0.04);
               font-size:.82rem; }
.bt-table tr:last-child td { border-bottom:none; }
.bt-table tr:hover { background:rgba(255,255,255,0.02); }

th.sortable { cursor:pointer; user-select:none; position:relative; padding-right:1.2rem; }
th.sortable::after { content:"⇅"; position:absolute; right:.3rem; opacity:.3; font-size:.7rem; }
th.sortable[data-sort-dir="asc"]::after { content:"↑"; opacity:.7; color:var(--blue); }
th.sortable[data-sort-dir="desc"]::after { content:"↓"; opacity:.7; color:var(--blue); }

.buy { color:var(--green); } .sell { color:var(--red); } .hold { color:var(--yellow); }
.badge { display:inline-flex; align-items:center; padding:2px 10px; border-radius:999px;
         font-size:.72rem; font-weight:600; backdrop-filter:blur(8px); }
.badge-buy { background:rgba(52,211,153,0.12); color:var(--green); }
.badge-sell { background:rgba(248,113,113,0.12); color:var(--red); }
.badge-hold { background:rgba(251,191,36,0.12); color:var(--yellow); }

.footer { margin-top:2rem; padding-top:1rem; border-top:1px solid rgba(255,255,255,0.06);
          color:var(--muted); font-size:.72rem; text-align:center; }

@keyframes card-rise { from{opacity:0;transform:translateY(14px)} to{opacity:1;transform:translateY(0)} }
.reveal { animation: card-rise 520ms ease both; }
.reveal-d1{animation-delay:60ms} .reveal-d2{animation-delay:120ms}
.reveal-d3{animation-delay:180ms} .reveal-d4{animation-delay:240ms}

@media(max-width:767px){
  .hero-grid{grid-template-columns:1fr}
  .donut-row{flex-direction:column;align-items:center}
  .container{padding:.8rem}
  .reveal{animation:none!important}
}

/* ── V1: Card hierarchy ── */
.card {
  box-shadow: 0 8px 20px rgba(0,0,0,0.12), inset 0 1px 0 rgba(255,255,255,0.03);
}
.card:hover {
  box-shadow: 0 12px 28px rgba(0,0,0,0.18), inset 0 1px 0 rgba(255,255,255,0.05);
}
.hero { box-shadow: 0 22px 54px rgba(0,0,0,0.26), 0 0 0 1px rgba(255,255,255,0.06); }

/* ── V3: Numeric alignment ── */
td.num, .num { font-family: var(--mono); font-variant-numeric: tabular-nums; text-align: right; }
.card-value { font-variant-numeric: tabular-nums; }

/* ── V5a: Keyboard focus ── */
button:focus-visible, [role="button"]:focus-visible {
  outline: 2px solid var(--accent); outline-offset: 2px;
}

/* ── V5: Touch feedback ── */
@media (hover: none) and (pointer: coarse) {
  .card:active { transform: scale(0.97); transition: transform 60ms ease; }
}

/* ── V7: Table scan ── */
.bt-table tbody tr:nth-child(even) { background: rgba(255,255,255,0.025); }
.bt-table th { position: sticky; top: 0; z-index: 1; }

/* ── S1: Contrast boost ── */
.card-title { font-weight: 500; }

/* ── S4: Elevation system ── */
.card { box-shadow: var(--elev-1); }
.card:hover { box-shadow: var(--elev-2); }
.hero { box-shadow: var(--elev-3); }

/* ── S5: Unified timing ── */
.card {
  transition: transform var(--dur-fast) var(--ease-out),
              box-shadow var(--dur-fast) var(--ease-out);
}
.reveal { animation: card-rise var(--dur-med) var(--ease-out) both; }

/* ── S2: KPI hierarchy ── */
.kpi-primary .card-value { font-size: 2.4rem; text-shadow: 0 0 24px currentColor; }
.kpi-secondary .card-value { font-size: 1.4rem; opacity: .85; }

/* ── S6: Table readability ── */
.bt-table tbody tr:hover { background: rgba(255,255,255,0.045); }

/* ── S3: 8px spacing rhythm ── */
.card { padding: var(--sp-3); margin-bottom: var(--sp-2); }
.hero { padding: var(--sp-4); margin-bottom: var(--sp-3); }
.container { padding: var(--sp-4) var(--sp-3) var(--sp-6); }

@media print {
  :root{--bg:#fff;--fg:#111;--card:#fff;--border:#ddd;--muted:#666;--white:#111;--accent:#333}
  body{background:#fff!important;color:#111!important}
  .card,.hero{background:#fff!important;box-shadow:none!important;backdrop-filter:none!important;
    border:1px solid #ddd!important;border-radius:4px!important}
  .hero::after{display:none} .reveal{animation:none!important}
  .container{max-width:100%;padding:0}
  .card{page-break-inside:avoid}
  th.sortable::after{display:none}
}
</style></head>
<body><div class="container">"""

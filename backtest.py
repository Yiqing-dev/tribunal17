"""Backtest module — evaluate historical signal accuracy against forward price data.

Reads RunTrace records from ReplayStore, fetches forward daily bars via akshare,
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

# Circuit breaker: skip akshare after first failure to avoid blocking
_SKIP_AKSHARE = False


def _mark_akshare_down():
    global _SKIP_AKSHARE
    _SKIP_AKSHARE = True
    logger.info("Akshare marked as down — skipping akshare fallback for remaining requests")

# Per-ticker Sina kline cache (avoids repeated API calls for same ticker)
_sina_cache: Dict[str, List[Dict]] = {}


# ── Configuration ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class BacktestConfig:
    """Backtest evaluation parameters."""
    eval_window_days: int = 10          # Forward trading days to evaluate
    neutral_band_pct: float = 2.0       # +/- band for neutral classification
    min_age_days: int = 1               # Minimum calendar days since signal
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
    direction_expected: str = ""        # up / down / flat / not_down

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

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}


@dataclass
class BacktestReport:
    """Complete backtest output: results + summaries."""
    config: BacktestConfig = field(default_factory=BacktestConfig)
    results: List[BacktestResult] = field(default_factory=list)
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
            "overall_summary": self.overall_summary.to_dict(),
            "per_ticker_summaries": {
                k: v.to_dict() for k, v in self.per_ticker_summaries.items()
            },
            "generated_at": self.generated_at,
        }


# ── Direction Inference ───────────────────────────────────────────────────

def infer_direction(action: str, confidence: float = -1.0) -> str:
    """Map action to expected price direction.

    Returns: 'up', 'down', 'flat', or 'not_down'.
    """
    action = action.upper().strip()
    if action in ("BUY",):
        return "up"
    elif action in ("SELL", "VETO"):
        return "down"
    elif action in ("HOLD",):
        return "flat"
    return "flat"


# ── Forward Price Fetching ────────────────────────────────────────────────

def _sina_symbol(ticker: str) -> str:
    """Convert ticker to Sina-style symbol (e.g. '601985.SS' -> 'sh601985')."""
    bare = ticker.replace(".SS", "").replace(".SZ", "").replace(".BJ", "")
    if bare.startswith("6"):
        return f"sh{bare}"
    else:
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
    Primary: Sina Finance API. Fallback: akshare.
    """
    try:
        sig_dt = datetime.strptime(signal_date, "%Y-%m-%d")
    except ValueError:
        logger.warning(f"Invalid signal_date format: {signal_date}")
        return []

    # Primary: Sina (cached per ticker)
    bare_key = ticker.replace(".SS", "").replace(".SZ", "").replace(".BJ", "")
    if bare_key not in _sina_cache:
        _sina_cache[bare_key] = _fetch_sina_klines(ticker, datalen=60)
    all_bars = _sina_cache[bare_key]
    if all_bars:
        forward = [b for b in all_bars if b["date"] > signal_date]
        if forward:
            return forward[:window_days]

    # Sina couldn't find data — give up (akshare is typically also down when Sina fails)
    logger.info(f"No Sina data for {ticker} after {signal_date}")
    return []


def fetch_signal_day_close(ticker: str, signal_date: str) -> float:
    """Fetch the closing price on the signal date.

    Primary: Sina Finance API. Fallback: akshare.
    """
    try:
        sig_dt = datetime.strptime(signal_date, "%Y-%m-%d")
    except ValueError:
        return 0.0

    # Primary: Sina (cached per ticker)
    bare_key = ticker.replace(".SS", "").replace(".SZ", "").replace(".BJ", "")
    if bare_key not in _sina_cache:
        _sina_cache[bare_key] = _fetch_sina_klines(ticker, datalen=60)
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
) -> BacktestResult:
    """Evaluate a single signal against forward price data.

    If forward_bars is None, fetches from akshare.
    If signal_close is 0, fetches from akshare.
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
    result.direction_expected = infer_direction(action, confidence)

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
            result.outcome = "neutral"
        else:
            result.direction_correct = False
            result.outcome = "neutral"
    else:
        result.outcome = "neutral"

    # Stop-loss / take-profit hits
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

    result.eval_status = "completed"
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

    if not completed:
        return summary

    # Action counts
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

    # Average returns
    all_returns = [r.stock_return_pct for r in completed]
    summary.avg_stock_return_pct = round(sum(all_returns) / len(all_returns), 2)

    buy_returns = [r.stock_return_pct for r in completed if r.action.upper() == "BUY"]
    if buy_returns:
        summary.avg_buy_return_pct = round(sum(buy_returns) / len(buy_returns), 2)

    sell_returns = [-r.stock_return_pct for r in completed if r.action.upper() in ("SELL", "VETO")]
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
                    if zone and len(zone) >= 2:
                        tgt = (float(zone[0]) + float(zone[1])) / 2
                    elif zone:
                        tgt = float(zone[0])
                    elif "price" in first_tp:
                        tgt = float(first_tp["price"])
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
        fetch_prices: If True, fetch forward bars from akshare.
                      If False, skip price fetching (results will be 'insufficient').

    Returns:
        BacktestReport with results and summaries.
    """
    config = config or BacktestConfig()

    from .replay_store import ReplayStore
    store = ReplayStore(storage_dir=storage_dir)
    runs = store.list_runs(ticker=ticker, limit=500)

    today = datetime.now()
    results = []

    for entry in runs:
        run_id = entry.get("run_id", "")
        trade_date = entry.get("trade_date", "")
        action = entry.get("research_action", "")

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
                direction_expected=infer_direction(action, trace.final_confidence),
                eval_status="insufficient",
                error_msg="Price fetching disabled",
            )
        results.append(result)

    # Normalize tickers: ensure suffix is present
    for r in results:
        bare = r.ticker.replace(".SS", "").replace(".SZ", "").replace(".BJ", "")
        if r.ticker == bare and bare.isdigit():
            if bare.startswith("6"):
                r.ticker = f"{bare}.SS"
            elif bare.startswith(("0", "3")):
                r.ticker = f"{bare}.SZ"
            elif bare.startswith(("8", "4", "9")):
                r.ticker = f"{bare}.BJ"

    # Deduplicate: keep latest run per ticker+date
    seen = {}
    for r in results:
        key = (r.ticker, r.trade_date)
        if key not in seen:
            seen[key] = r
        else:
            # Keep the one with more recent run_id (lexicographic)
            if r.run_id > seen[key].run_id:
                seen[key] = r
    results = list(seen.values())
    results.sort(key=lambda r: r.trade_date, reverse=True)

    # Compute summaries
    overall = compute_summary(results, scope="overall", config=config)

    per_ticker = {}
    ticker_groups: Dict[str, List[BacktestResult]] = {}
    for r in results:
        ticker_groups.setdefault(r.ticker, []).append(r)
    for tk, tk_results in ticker_groups.items():
        per_ticker[tk] = compute_summary(tk_results, scope=tk, config=config)

    report = BacktestReport(
        config=config,
        results=results,
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
    config = BacktestConfig(**data.get("config", {}))
    results = [BacktestResult.from_dict(r) for r in data.get("results", [])]
    overall = BacktestSummary(**data.get("overall_summary", {}))
    per_ticker = {
        k: BacktestSummary(**v)
        for k, v in data.get("per_ticker_summaries", {}).items()
    }
    return BacktestReport(
        config=config,
        results=results,
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

    # Use Sina's sh000300 (CSI 300 index)
    url = "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
    params = {"symbol": "sh000300", "scale": "240", "ma": "no", "datalen": "60"}
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
    except Exception:
        return None

    # Find signal date close and forward close
    signal_close = None
    for d in reversed(data):
        if d.get("day", "") <= signal_date:
            signal_close = float(d.get("close", 0))
            break
    if not signal_close:
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
                f'<td>{s.completed}</td>'
                f'<td>{s.direction_accuracy_pct:.1f}%</td>'
                f'<td>{s.win_rate_pct:.1f}%</td>'
                f'<td>{s.avg_stock_return_pct:+.2f}%</td></tr>'
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
                f'<td>{bd["count"]}</td>'
                f'<td>{bd["avg_return_pct"]:+.2f}%</td>'
                f'<td>{bd["win_rate_pct"]:.1f}%</td></tr>'
            )
        html.append('</tbody></table>')

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
                    f'<td>{conf}</td>'
                    f'<td>{r.start_price:.2f}</td>'
                    f'<td>{r.end_close:.2f}</td>'
                    f'<td class="{outcome_cls}">{r.stock_return_pct:+.2f}%</td>'
                    f'<td class="sell">{r.max_drawdown_pct:+.2f}%</td>'
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

    # Summary cards
    html_parts.append('<div class="summary-row">')
    html_parts.append(_card("总信号数", str(s.total_signals)))
    html_parts.append(_card("已评估", str(s.completed)))
    html_parts.append(_card("方向准确率",
        f"{s.direction_accuracy_pct}%" if s.completed else "—"))
    html_parts.append(_card("胜率",
        f"{s.win_rate_pct}%" if s.completed else "—"))
    html_parts.append(_card("平均收益",
        f"{s.avg_stock_return_pct:+.2f}%" if s.completed else "—"))
    html_parts.append('</div>')

    # Action breakdown table
    if s.action_breakdown:
        html_parts.append('<h2>分类统计</h2>')
        html_parts.append('<table class="bt-table"><thead><tr>')
        html_parts.append('<th>信号</th><th>次数</th><th>平均收益</th><th>胜率</th>')
        html_parts.append('</tr></thead><tbody>')
        for action in ("BUY", "HOLD", "SELL", "VETO"):
            bd = s.action_breakdown.get(action)
            if not bd:
                continue
            emoji = get_signal_emoji(action)
            label = get_action_label(action)
            html_parts.append(
                f'<tr><td>{emoji} {_esc(label)}</td>'
                f'<td>{bd["count"]}</td>'
                f'<td>{bd["avg_return_pct"]:+.2f}%</td>'
                f'<td>{bd["win_rate_pct"]:.1f}%</td></tr>'
            )
        html_parts.append('</tbody></table>')

    # Per-ticker summary
    if report.per_ticker_summaries:
        html_parts.append('<h2>个股统计</h2>')
        html_parts.append('<table class="bt-table"><thead><tr>')
        html_parts.append('<th>股票</th><th>信号数</th><th>方向准确率</th>'
                         '<th>胜率</th><th>平均收益</th></tr></thead><tbody>')
        for tk, ts in sorted(report.per_ticker_summaries.items()):
            name = ""
            for r in report.results:
                if r.ticker == tk and r.ticker_name:
                    name = r.ticker_name
                    break
            display = f"{_esc(name or tk)}"
            html_parts.append(
                f'<tr><td>{display}</td>'
                f'<td>{ts.completed}</td>'
                f'<td>{ts.direction_accuracy_pct:.1f}%</td>'
                f'<td>{ts.win_rate_pct:.1f}%</td>'
                f'<td>{ts.avg_stock_return_pct:+.2f}%</td></tr>'
            )
        html_parts.append('</tbody></table>')

    # Detail table
    if completed:
        html_parts.append('<h2>信号明细</h2>')
        html_parts.append('<table class="bt-table detail"><thead><tr>')
        html_parts.append(
            '<th>日期</th><th>股票</th><th>信号</th>'
            '<th>入场价</th><th>出场价</th><th>收益</th>'
            '<th>最大回撤</th><th>最大浮盈</th><th>结果</th>'
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
            html_parts.append(
                f'<tr>'
                f'<td>{_esc(r.trade_date)}</td>'
                f'<td>{_esc(r.ticker_name or r.ticker)}</td>'
                f'<td>{emoji} {_esc(r.action)}</td>'
                f'<td>{r.start_price:.2f}</td>'
                f'<td>{r.end_close:.2f}</td>'
                f'<td class="{outcome_cls}">{r.stock_return_pct:+.2f}%</td>'
                f'<td class="sell">{r.max_drawdown_pct:+.2f}%</td>'
                f'<td class="buy">{r.max_gain_pct:+.2f}%</td>'
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


def _card(title: str, value: str) -> str:
    return f'<div class="card"><div class="card-title">{_esc(title)}</div><div class="card-value">{value}</div></div>'


_BT_HTML_HEAD = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>回测验证报告</title>
<style>
:root { --bg: #0d1117; --card: #161b22; --border: #30363d; --text: #e6edf3;
        --muted: #8b949e; --green: #3fb950; --red: #da3633; --yellow: #d29922; }
* { margin: 0; padding: 0; box-sizing: border-box; }
body { background: var(--bg); color: var(--text); font-family: -apple-system, sans-serif;
       font-size: 14px; line-height: 1.6; }
.container { max-width: 1200px; margin: 0 auto; padding: 24px; }
h1 { font-size: 22px; margin-bottom: 8px; }
h2 { font-size: 17px; margin: 24px 0 12px; color: var(--muted); }
.summary-row { display: flex; gap: 12px; flex-wrap: wrap; margin: 16px 0; }
.card { background: var(--card); border: 1px solid var(--border); border-radius: 8px;
        padding: 16px; min-width: 140px; flex: 1; text-align: center; }
.card-title { font-size: 12px; color: var(--muted); margin-bottom: 4px; }
.card-value { font-size: 24px; font-weight: 600; }
.bt-table { width: 100%; border-collapse: collapse; background: var(--card);
            border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
.bt-table th { background: #1c2128; padding: 10px 12px; text-align: left;
               font-size: 12px; color: var(--muted); border-bottom: 1px solid var(--border); }
.bt-table td { padding: 8px 12px; border-bottom: 1px solid var(--border); font-size: 13px; }
.bt-table tr:last-child td { border-bottom: none; }
.bt-table tr:hover { background: #1c2128; }
.buy { color: var(--green); }
.sell { color: var(--red); }
.hold { color: var(--yellow); }
.footer { margin-top: 32px; padding-top: 16px; border-top: 1px solid var(--border);
          color: var(--muted); font-size: 12px; text-align: center; }
</style></head>
<body><div class="container">
<h1>回测验证报告</h1>"""

"""Batch process raw agent research outputs into 3-tier HTML reports.

Usage:
    python -m subagent_pipeline.batch_process
    python -m subagent_pipeline.batch_process --tickers 600519,000858
    python -m subagent_pipeline.batch_process --tickers-file watchlist.txt
    python -m subagent_pipeline.batch_process "论衡十七司，升堂！【600519，000858】"
"""

import argparse
import json
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Sequence
from .bridge import (
    generate_report,
    parse_macro_output,
    parse_breadth_output,
    parse_sector_output,
    assemble_market_context,
    format_market_context_block,
    StaleMarketDataError,
)
from .config import _today, get_env_bool
from .watchlist import WatchlistItem, load_watchlist, normalize_watchlist_ticker, save_watchlist

logger = logging.getLogger(__name__)

# Section delimiter pattern used by research agents
SECTION_RE = re.compile(
    r'===\s*SECTION:\s*(\w+)\s*===\s*\n(.*?)(?=\n===\s*SECTION:|\n===\s*END\s*===|\Z)',
    re.DOTALL,
)

TICKERS = [
    ("601985", "中国核电"),
    ("300627", "华测导航"),
    ("002131", "利欧股份"),
    ("603065", "宿迁联盛"),
    ("300676", "华大基因"),
    ("600529", "山东药玻"),
]

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = _PROJECT_ROOT / "agent_artifacts" / "results"
REPORTS_DIR = _PROJECT_ROOT / "data" / "reports"
_REPLAYS_DIR = _PROJECT_ROOT / "data" / "replays"


def parse_sections(text: str) -> dict[str, str]:
    """Split agent output into {section_key: content} dict."""
    sections = {}
    for m in SECTION_RE.finditer(text):
        key = m.group(1).strip()
        content = m.group(2).strip()
        if content:
            sections[key] = content
    return sections


def process_one(ticker: str, name: str, text: str,
                trade_date: str = "",
                market_context_block: str = "",
                market_context: dict = None) -> dict[str, str]:
    """Parse raw output and generate 3-tier reports for one ticker."""
    outputs = parse_sections(text)
    if not outputs:
        print(f"  [WARN] {ticker} {name}: no sections found, skipping")
        return {}

    print(f"  {ticker} {name}: parsed {len(outputs)} sections "
          f"({', '.join(outputs.keys())})")

    return generate_report(
        outputs=outputs,
        ticker=ticker,
        ticker_name=name,
        trade_date=trade_date or _today(),
        output_dir=str(REPORTS_DIR),
        storage_dir=str(_REPLAYS_DIR),
        market_context_block=market_context_block,
        market_context=market_context,
    )


def _load_market_agent_outputs(results_dir: Path) -> dict:
    """Load market-level agent outputs from files if available."""
    agents = {}
    for key in ("macro_analyst", "market_breadth_agent", "sector_rotation_agent"):
        path = results_dir / f"{key}_output.txt"
        if path.exists():
            text = path.read_text(encoding="utf-8")
            if len(text.strip()) > 50:
                agents[key] = text
    return agents


def _build_market_context(agent_outputs: dict, trade_date: str,
                          *, strict_date_check: bool = False) -> dict:
    """Parse market agent outputs and assemble market_context.

    When ``strict_date_check`` is True, a date mismatch in the L1 outputs raises
    ``StaleMarketDataError`` instead of silently injecting yesterday's market
    data into today's per-stock reports (XC-03).
    """
    macro_text = agent_outputs.get("macro_analyst", "")
    breadth_text = agent_outputs.get("market_breadth_agent", "")
    sector_text = agent_outputs.get("sector_rotation_agent", "")
    macro = parse_macro_output(macro_text)
    breadth = parse_breadth_output(breadth_text)
    sector = parse_sector_output(sector_text)
    return assemble_market_context(
        macro, breadth, sector, trade_date,
        strict_date_check=strict_date_check,
        raw_texts={
            "macro": macro_text,
            "breadth": breadth_text,
            "sector": sector_text,
        },
    )


def _build_ths_to_sw_map() -> dict:
    """Build THS sector name → SW second-level industry code mapping.

    Delegates to the canonical implementation in akshare_collector.
    """
    from .akshare_collector import _build_ths_to_sw_map as _impl
    return _impl()


def process_all(
    trade_date: str = "",
    tickers: Sequence[WatchlistItem | tuple[str, str] | str] | None = None,
):
    """Process all ticker output files in agent_artifacts/results/.

    Args:
        trade_date: Override trade date (YYYY-MM-DD). Defaults to today.
    """
    today = trade_date or _today()
    active_tickers = _resolve_tickers(tickers)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    if tickers:
        save_watchlist(
            [WatchlistItem(normalize_watchlist_ticker(ticker), name) for ticker, name in active_tickers],
            REPORTS_DIR,
        )
    # Structured degradation tracker: {step: {status, fallback, error}}
    _degradations: list = []

    def _track_degradation(step: str, error: str, fallback: str = "skipped"):
        _degradations.append({"step": step, "error": str(error)[:200], "fallback": fallback})

    # --- Step 1: Try to collect market snapshot ---
    market_snapshot = None
    market_context = {}
    market_context_block = ""
    watchlist = [t for t, _ in active_tickers]

    try:
        from .akshare_collector import collect_market_snapshot
        print("  [MARKET] Collecting market snapshot...")
        market_snapshot = collect_market_snapshot(trade_date=today, watchlist=watchlist)
        print(f"  [MARKET] Snapshot: {len(market_snapshot.apis_succeeded)} APIs OK, "
              f"{len(market_snapshot.apis_failed)} failed")
    except Exception as e:
        print(f"  [MARKET] Snapshot collection failed: {e}")
        _track_degradation("market_snapshot", e, "no snapshot data")

    # --- Step 1b: Try to collect board data (sector heatmap, limits) ---
    # Delegates to akshare_collector.collect_board_data() — single source of truth.
    board_data = None
    board_path = _REPLAYS_DIR / f"market_board_{today}.json"
    if board_path.exists():
        try:
            board_data = json.loads(board_path.read_text(encoding="utf-8"))
            print(f"  [BOARD] Loaded cached board data: {len(board_data.get('sectors', []))} sectors, "
                  f"{len(board_data.get('limit_ups', []))} limit-ups")
        except Exception as e:
            print(f"  [BOARD] Failed to load cached board data: {e}")

    if board_data is None:
        try:
            from .akshare_collector import collect_board_data as _collect_board
            print("  [BOARD] Collecting board data...")
            _REPLAYS_DIR.mkdir(parents=True, exist_ok=True)
            board_data = _collect_board(today)
            print(f"  [BOARD] Collected: {len(board_data.get('sectors', []))} sectors, "
                  f"{len(board_data.get('limit_ups', []))} limit-ups")

            # Persist atomically
            fd, tmp = tempfile.mkstemp(
                dir=str(board_path.parent), suffix=".tmp", prefix=".board-"
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(board_data, f, ensure_ascii=False, indent=2, allow_nan=False)
                os.replace(tmp, str(board_path))
            except BaseException:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
        except Exception as e:
            print(f"  [BOARD] Board data collection failed: {e}")
            _track_degradation("board_data", e, "no limit/sector detail")

    # --- Step 2: Parse market agent outputs (if available) ---
    market_agent_outputs = _load_market_agent_outputs(RESULTS_DIR)
    if market_agent_outputs:
        print(f"  [MARKET] Found {len(market_agent_outputs)} market agent outputs")
        # XC-03: reject STALE L1 outputs (date mismatch) rather than silently
        # injecting yesterday's market data into every stock report today.
        _strict = get_env_bool("TA_STRICT_DATE_CHECK", True)
        # XC-STRICT-1: compare against the effective TRADING day. On a non-trading
        # day (weekend/holiday) the L1 market data legitimately carries the last
        # trading day's date — collect_market_snapshot rolls likewise — so don't
        # false-reject it. Only genuinely stale (older) data is then rejected.
        _mkt_date = today
        try:
            from .akshare_collector import _is_cn_trading_day, _last_trading_day
            if not _is_cn_trading_day(today):
                _mkt_date = _last_trading_day(today) or today
        except Exception:
            pass
        try:
            market_context = _build_market_context(
                market_agent_outputs, _mkt_date, strict_date_check=_strict)
            market_context_block = format_market_context_block(market_context)
            print(f"  [MARKET] Context: regime={market_context.get('regime')}, "
                  f"breadth={market_context.get('breadth_state')}")
        except StaleMarketDataError as e:
            print(f"  [MARKET] STALE L1 data rejected ({e}); "
                  f"skipping today's market context (no stale injection)")
            _track_degradation("market_context", e,
                               "stale L1 outputs rejected; no market context injected")
            market_context = {}
            market_context_block = ""

    # --- Step 3: Persist market_context ---
    if market_context is not None:
        _REPLAYS_DIR.mkdir(parents=True, exist_ok=True)
        ctx_path = _REPLAYS_DIR / f"market_context_{today}.json"
        # Atomic write: temp file + os.replace
        _fd, _tmp = tempfile.mkstemp(dir=str(_REPLAYS_DIR), suffix=".tmp", prefix=".ctx-")
        try:
            with os.fdopen(_fd, "w", encoding="utf-8") as _f:
                json.dump(market_context, _f, ensure_ascii=False, indent=2, allow_nan=False)
            os.replace(_tmp, str(ctx_path))
        except BaseException:
            try:
                os.unlink(_tmp)
            except OSError:
                pass
            raise
        print(f"  [MARKET] Context saved: {ctx_path}")

    # --- Step 4: Process individual tickers ---
    results = {}
    for ticker, name in active_tickers:
        path = RESULTS_DIR / f"{ticker}_output.txt"
        if not path.exists():
            print(f"  [SKIP] {ticker} {name}: {path} not found")
            continue

        text = path.read_text(encoding="utf-8")
        if len(text.strip()) < 100:
            print(f"  [SKIP] {ticker} {name}: output too short ({len(text)} chars)")
            continue

        try:
            report_paths = process_one(
                ticker, name, text,
                trade_date=today,
                market_context_block=market_context_block,
                market_context=market_context,
            )
            if report_paths:
                results[ticker] = report_paths
                print(f"  [OK] {ticker} {name}: {report_paths.get('snapshot', '?')}")
        except Exception as e:
            print(f"  [ERROR] {ticker} {name}: {e}")

    # --- Step 5: Generate pool report with heatmap ---
    run_ids = [r["run_id"] for r in results.values() if "run_id" in r]
    pool_path = None
    if len(run_ids) >= 2:
        from .renderers.report_renderer import generate_pool_report
        pool_path = generate_pool_report(
            run_ids=run_ids,
            output_dir=str(REPORTS_DIR),
            storage_dir=str(_REPLAYS_DIR),
            trade_date=today,
            market_context=market_context,
            market_snapshot=market_snapshot,
        )

    # --- Step 6: Generate committee reports per ticker ---
    committee_paths = {}
    for ticker, paths in results.items():
        rid = paths.get("run_id")
        if not rid:
            continue
        try:
            from .renderers.debate_renderer import generate_committee_report
            from .replay_store import ReplayStore as _RS
            _store = _RS(storage_dir=str(_REPLAYS_DIR))
            trace = _store.load(rid)
            if trace:
                cp = generate_committee_report(trace, output_dir=str(REPORTS_DIR))
                if cp:
                    committee_paths[ticker] = cp
        except Exception as e:
            print(f"  [WARN] Committee report for {ticker} failed: {e}")

    # --- Step 6b: Append signals to ledger ---
    if run_ids:
        try:
            from .signal_ledger import SignalLedger
            ledger = SignalLedger()
            recs = ledger.append_batch_from_traces(
                run_ids=run_ids,
                storage_dir=str(_REPLAYS_DIR),
                market_regime=market_context.get("regime", ""),
                position_cap_multiplier=market_context.get("position_cap_multiplier", 1.0),
            )
            print(f"  [LEDGER] Appended {len(recs)} signals to {ledger.path}")
        except Exception as e:
            print(f"  [WARN] Signal ledger append failed: {e}")

    # --- Step 6e: Post-run health check (silent-failure detection) ---
    # XC-01: previously this engine was written but never called in production.
    # Runs after the ledger append (traces exist; flip detection compares vs the
    # strictly-prior ledger signal — see check_batch_health/XC-05).
    if run_ids:
        try:
            from .health_check import check_batch_health
            health = check_batch_health(
                today_run_ids=run_ids, storage_dir=str(_REPLAYS_DIR))
            for w in health.get("warnings", []):
                print(f"  [HEALTH] warning: {w}")
            if health.get("alerts"):
                print(f"  [HEALTH] ⚠ {len(health['alerts'])} ALERT(S):")
                for a in health["alerts"]:
                    print(f"           ALERT: {a}")
                _track_degradation(
                    "health_check", "; ".join(health["alerts"])[:200], "alerts raised")
            elif not health.get("warnings"):
                print("  [HEALTH] OK — no anomalies detected")
        except Exception as e:
            print(f"  [WARN] Health check failed: {e}")

    # --- Step 6f: Analysis-process-quality audit (local, cheap) ---
    # Wires analysis_audit (was written but never called) — evidence coverage,
    # PM citation rate, falsifiability across today's runs.
    if run_ids:
        try:
            from .analysis_audit import audit_batch
            audit = audit_batch(run_ids, storage_dir=str(_REPLAYS_DIR))
            ap = audit.save_json(str(REPORTS_DIR))
            print(f"  [AUDIT] process quality: evidence {audit.evidence_coverage_pct:.0f}% · "
                  f"PM-cites {audit.pm_evidence_pct:.0f}% · falsifiable {audit.falsifiability_pct:.0f}% → {ap}")
        except Exception as e:
            print(f"  [WARN] Analysis audit failed: {e}")

    # --- Step 6g: Rolling drift monitor (per-run; needs network for backtest) ---
    # Wires monitoring.compute_rolling_monitor (was written but never called) —
    # rolling per-regime/action/pillar accuracy from the ledger. Best-effort: a
    # network/akshare failure must not block report generation.
    try:
        from .monitoring import compute_rolling_monitor
        mon = compute_rolling_monitor(today, storage_dir=str(_REPLAYS_DIR))
        print(f"  [MONITOR] rolling drift report written ({mon.trade_date})")
    except Exception as e:
        print(f"  [WARN] Rolling monitor failed (non-fatal): {e}")

    # --- Step 6c: Generate brief report ---
    if run_ids:
        try:
            from .renderers.report_renderer import generate_brief_report_file
            brief_path = generate_brief_report_file(
                run_ids=run_ids,
                storage_dir=str(_REPLAYS_DIR),
                trade_date=today,
            )
            if brief_path:
                print(f"  [BRIEF] {brief_path}")
        except Exception as e:
            print(f"  [WARN] Brief report generation failed: {e}")

    # --- Step 6d: Generate product workbench / report library ---
    workbench_path = None
    if run_ids:
        try:
            from .renderers.report_renderer import generate_workbench_report
            names = dict(active_tickers)
            workbench_path = generate_workbench_report(
                output_dir=str(REPORTS_DIR),
                storage_dir=str(_REPLAYS_DIR),
                tickers=[t for t, _ in active_tickers],
                ticker_names=names,
            )
            print(f"  [WORKBENCH] {workbench_path}")
        except Exception as e:
            print(f"  [WARN] Workbench generation failed: {e}")

    # --- Step 7: Generate market report ---
    market_report_path = None
    if market_context is not None:
        try:
            from .renderers.report_renderer import generate_market_report
            market_report_path = generate_market_report(
                market_context=market_context,
                market_snapshot=market_snapshot,
                output_dir=str(REPORTS_DIR),
                trade_date=today,
                board_data=board_data,
            )
        except Exception as e:
            print(f"  [WARN] Market report generation failed: {e}")

    print(f"\n{'=' * 60}")
    print(f"  Processed {len(results)}/{len(active_tickers)} tickers")
    print(f"{'=' * 60}")
    name_lookup = dict(active_tickers)
    for ticker, paths in results.items():
        name = name_lookup.get(ticker, "")
        print(f"  {ticker} {name}:")
        for tier, p in paths.items():
            if tier != "run_id":
                print(f"    {tier:12s}: {p}")
    if pool_path:
        print(f"\n  [POOL] {pool_path}")
    if committee_paths:
        print(f"\n  [COMMITTEE] {len(committee_paths)} reports:")
        for t, p in committee_paths.items():
            print(f"    {t}: {p}")
    if market_report_path:
        print(f"  [MARKET] {market_report_path}")
    if workbench_path:
        print(f"  [WORKBENCH] {workbench_path}")

    # --- Degradation summary (D1: persist provenance, don't only print) ---
    # Always write a record so a degraded run's data-provenance is auditable
    # after the fact, not just visible in transient console output.
    try:
        _REPLAYS_DIR.mkdir(parents=True, exist_ok=True)
        deg_path = _REPLAYS_DIR / f"degradations_{today}.json"
        _fd, _tmp = tempfile.mkstemp(dir=str(_REPLAYS_DIR), suffix=".tmp", prefix=".deg-")
        with os.fdopen(_fd, "w", encoding="utf-8") as _f:
            json.dump({"trade_date": today, "count": len(_degradations),
                       "degradations": _degradations}, _f,
                      ensure_ascii=False, indent=2, allow_nan=False)
        os.replace(_tmp, str(deg_path))
    except Exception as _e:
        print(f"  [WARN] degradation record write failed: {_e}")
    if _degradations:
        print(f"\n⚠ 降级矩阵 ({len(_degradations)} 项):")
        for d in _degradations:
            print(f"  [{d['step']}] {d['error'][:80]} → {d['fallback']}")
    else:
        print("\n✓ 无数据降级")

    return results


def _resolve_tickers(
    tickers: Sequence[WatchlistItem | tuple[str, str] | str] | None,
) -> list[tuple[str, str]]:
    if not tickers:
        return list(TICKERS)
    out: list[tuple[str, str]] = []
    for item in tickers:
        if isinstance(item, WatchlistItem):
            out.append((_bare_ticker(item.ticker), item.name))
        elif isinstance(item, tuple):
            ticker = _bare_ticker(str(item[0] if item else "").strip())
            name = str(item[1] if len(item) > 1 else "").strip()
            out.append((ticker, name))
        else:
            out.append((_bare_ticker(str(item).strip()), ""))
    return [(t, n) for t, n in out if t]


def _bare_ticker(ticker: str) -> str:
    normalized = normalize_watchlist_ticker(ticker)
    return normalized.replace(".SS", "").replace(".SZ", "").replace(".BJ", "")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build HTML reports from existing agent outputs.")
    parser.add_argument("--trade-date", default="", help="Override trade date (YYYY-MM-DD).")
    parser.add_argument(
        "--tickers",
        nargs="+",
        help="Daily ticker list, separated by commas or spaces. Example: --tickers 600519,000858",
    )
    parser.add_argument(
        "--tickers-file",
        help="Path to a daily watchlist file. Lines may be '600519' or '600519 贵州茅台'.",
    )
    parser.add_argument(
        "command_text",
        nargs="*",
        help="Optional launch phrase, e.g. 论衡十七司，升堂！【600519，000858】",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    watchlist = load_watchlist(
        tickers=args.tickers,
        tickers_file=args.tickers_file,
        command_text=" ".join(args.command_text),
    )
    process_all(trade_date=args.trade_date, tickers=watchlist or None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

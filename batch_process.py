"""Batch process raw agent research outputs into 3-tier HTML reports.

Usage:
    python -m subagent_pipeline.batch_process
"""

import json
import os
import re
import sys
import tempfile
from datetime import date
from pathlib import Path
from .bridge import (
    generate_report,
    parse_macro_output,
    parse_breadth_output,
    parse_sector_output,
    assemble_market_context,
    format_market_context_block,
)

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
        trade_date=trade_date or date.today().isoformat(),
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


def _build_market_context(agent_outputs: dict, trade_date: str) -> dict:
    """Parse market agent outputs and assemble market_context."""
    macro_text = agent_outputs.get("macro_analyst", "")
    breadth_text = agent_outputs.get("market_breadth_agent", "")
    sector_text = agent_outputs.get("sector_rotation_agent", "")
    macro = parse_macro_output(macro_text)
    breadth = parse_breadth_output(breadth_text)
    sector = parse_sector_output(sector_text)
    return assemble_market_context(
        macro, breadth, sector, trade_date,
        raw_texts={
            "macro": macro_text,
            "breadth": breadth_text,
            "sector": sector_text,
        },
    )


def _build_ths_to_sw_map() -> dict:
    """Build THS sector name → SW second-level industry code mapping.

    Returns ``{ths_name: sw_code}`` e.g. ``{"半导体": "801081"}``.
    Uses exact match first, then fuzzy match (strip trailing ``Ⅱ``).
    """
    try:
        import akshare as ak
        sw2 = ak.sw_index_second_info()
    except Exception:
        return {}

    sw_by_name: dict[str, str] = {}
    sw_stripped: dict[str, str] = {}
    for _, row in sw2.iterrows():
        code = str(row["行业代码"]).replace(".SI", "")
        name = str(row["行业名称"])
        sw_by_name[name] = code
        stripped = name.rstrip("Ⅱ").rstrip()
        if stripped != name:
            sw_stripped[stripped] = code

    try:
        ths = ak.stock_board_industry_name_ths()
    except Exception:
        return {}

    mapping: dict[str, str] = {}
    for _, row in ths.iterrows():
        ths_name = str(row["name"])
        if ths_name in sw_by_name:
            mapping[ths_name] = sw_by_name[ths_name]
        elif ths_name in sw_stripped:
            mapping[ths_name] = sw_stripped[ths_name]
    return mapping


def _collect_sector_stocks_sw(sectors: list, ths_sw_map: dict,
                              max_sectors: int = 20, top_n: int = 10) -> dict:
    """Fallback: fetch constituent stocks via SW index + XQ spot data.

    Uses ``index_component_sw`` for constituent list (sorted by weight)
    and ``stock_individual_spot_xq`` for realtime price/pct_change.
    """
    import time
    result: dict[str, list] = {}
    if not sectors or not ths_sw_map:
        return result

    try:
        import akshare as ak
    except ImportError:
        return result

    sorted_sectors = sorted(sectors,
                            key=lambda s: float(s.get("total_turnover_yi", 0) or 0),
                            reverse=True)

    for s in sorted_sectors[:max_sectors]:
        sector_name = str(s.get("sector", ""))
        sw_code = ths_sw_map.get(sector_name)
        if not sw_code:
            continue
        try:
            cons = ak.index_component_sw(symbol=sw_code)
            if cons is None or cons.empty:
                continue
            # Sort by weight descending, take top_n
            cons = cons.sort_values("最新权重", ascending=False).head(top_n)

            stocks = []
            for _, row in cons.iterrows():
                ticker = str(row.get("证券代码", ""))
                name = str(row.get("证券名称", ""))
                weight = float(row.get("最新权重", 0) or 0)
                pct_change = 0.0
                # Fetch realtime pct_change from XQ
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
                    "name": name,
                    "pct_change": pct_change,
                    "market_cap_yi": 0,  # SW doesn't provide mcap
                    "amount_yi": 0,
                    "weight": weight,
                })
            if stocks:
                result[sector_name] = stocks
            time.sleep(0.3)
        except Exception:
            continue

    return result


def _collect_sector_stocks(sectors: list, max_sectors: int = 20,
                           top_n: int = 10) -> dict:
    """Fetch top constituent stocks per sector for treemap drill-down.

    Tries EM (stock_board_industry_cons_em) first.  After 3 consecutive
    failures, falls back to SW (index_component_sw) + XQ (stock_individual_spot_xq).
    """
    import time
    result: dict[str, list] = {}
    if not sectors:
        return result

    try:
        from .akshare_collector import _retry_call
        import akshare as ak
    except ImportError:
        return result

    sorted_sectors = sorted(sectors, key=lambda s: float(s.get("total_turnover_yi", 0) or 0),
                            reverse=True)

    consecutive_failures = 0
    for s in sorted_sectors[:max_sectors]:
        sector_name = str(s.get("sector", ""))
        if not sector_name:
            continue
        try:
            from .proxy_pool import em_proxy_session
            with em_proxy_session():
                df = _retry_call(ak.stock_board_industry_cons_em, symbol=sector_name)
            if df is None or df.empty:
                continue

            # Sort by market cap descending, take top_n
            if "总市值" in df.columns:
                df = df.sort_values("总市值", ascending=False)

            stocks = []
            for _, row in df.head(top_n).iterrows():
                mcap = float(row.get("总市值", 0) or 0)
                stocks.append({
                    "ticker": str(row.get("代码", "")),
                    "name": str(row.get("名称", "")),
                    "pct_change": float(row.get("涨跌幅", 0) or 0),
                    "market_cap_yi": round(mcap / 1e8, 2) if mcap > 0 else 0,
                    "amount_yi": round(float(row.get("成交额", 0) or 0) / 1e8, 2),
                })
            if stocks:
                result[sector_name] = stocks
                consecutive_failures = 0
            time.sleep(0.5)
        except Exception:
            consecutive_failures += 1
            if consecutive_failures >= 3:
                print(f"  [BOARD] EM failed 3x, switching to SW+XQ fallback")
                ths_sw_map = _build_ths_to_sw_map()
                if ths_sw_map:
                    print(f"  [BOARD] THS→SW mapping: {len(ths_sw_map)} sectors matched")
                    remaining = [s2 for s2 in sorted_sectors[:max_sectors]
                                 if str(s2.get("sector", "")) not in result]
                    sw_result = _collect_sector_stocks_sw(
                        remaining, ths_sw_map, max_sectors=max_sectors, top_n=top_n,
                    )
                    result.update(sw_result)
                    if sw_result:
                        print(f"  [BOARD] SW fallback: {len(sw_result)} sectors fetched")
                else:
                    print(f"  [BOARD] SW fallback: mapping build failed")
                break
            time.sleep(1)

    return result


def process_all(trade_date: str = ""):
    """Process all ticker output files in agent_artifacts/results/.

    Args:
        trade_date: Override trade date (YYYY-MM-DD). Defaults to today.
    """
    today = trade_date or date.today().isoformat()
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    # --- Step 1: Try to collect market snapshot ---
    market_snapshot = None
    market_context = {}
    market_context_block = ""
    watchlist = [t for t, _ in TICKERS]

    try:
        from .akshare_collector import collect_market_snapshot
        print("  [MARKET] Collecting market snapshot...")
        market_snapshot = collect_market_snapshot(trade_date=today, watchlist=watchlist)
        print(f"  [MARKET] Snapshot: {len(market_snapshot.apis_succeeded)} APIs OK, "
              f"{len(market_snapshot.apis_failed)} failed")
    except Exception as e:
        print(f"  [MARKET] Snapshot collection failed: {e}")

    # --- Step 1b: Try to collect board data (sector heatmap, limits) ---
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
            from .akshare_collector import _retry_call
            import akshare as ak

            print("  [BOARD] Collecting board data...")
            _REPLAYS_DIR.mkdir(parents=True, exist_ok=True)
            board_data = {"trade_date": today}

            # Sector heatmap (THS)
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
                board_data["sectors"] = sectors
            except Exception as e:
                print(f"  [BOARD] Sector collection failed: {e}")
                board_data["sectors"] = []

            # Limit-up stocks
            date_fmt = today.replace("-", "")
            try:
                from .proxy_pool import em_proxy_session
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
                        "seal_amount_yi": round(float(row.get("封板资金", 0) or 0) / 1e8, 2),
                        "first_seal": str(row.get("首次封板时间", "") or ""),
                    })
                board_data["limit_ups"] = limit_ups
            except Exception as e:
                print(f"  [BOARD] Limit-up collection failed: {e}")
                board_data["limit_ups"] = []

            # Limit-down stocks
            try:
                from .proxy_pool import em_proxy_session
                with em_proxy_session():
                    df_dt = _retry_call(ak.stock_zt_pool_dtgc_em, date=date_fmt)
                limit_downs = []
                for _, row in df_dt.iterrows():
                    limit_downs.append({
                        "ticker": str(row.get("代码", "")),
                        "name": str(row.get("名称", "")),
                        "pct_change": float(row.get("涨跌幅", 0) or 0),
                        "amount_yi": round(float(row.get("成交额", 0) or 0) / 1e8, 2),
                        "sector": str(row.get("所属行业", "") or ""),
                    })
                board_data["limit_downs"] = limit_downs
            except Exception as e:
                print(f"  [BOARD] Limit-down collection failed: {e}")
                board_data["limit_downs"] = []

            # Consecutive boards (derived from limit_ups)
            consec = {}
            for s in board_data.get("limit_ups", []):
                b = s.get("boards", 1)
                consec.setdefault(b, []).append(s)
            board_data["consecutive_boards"] = {str(k): v for k, v in sorted(consec.items())}

            # Sector attribution
            sector_agg = {}
            for s in board_data.get("limit_ups", []):
                sec = s.get("sector", "")
                if sec:
                    if sec not in sector_agg:
                        sector_agg[sec] = {"count": 0, "stocks": []}
                    sector_agg[sec]["count"] += 1
                    sector_agg[sec]["stocks"].append(s["name"])
            board_data["limit_sector_attribution"] = dict(
                sorted(sector_agg.items(), key=lambda x: x[1]["count"], reverse=True)
            )

            # Sector constituent stocks (top N per sector, for treemap drill-down)
            sector_stocks = _collect_sector_stocks(
                board_data.get("sectors", []), max_sectors=20, top_n=10,
            )
            if sector_stocks:
                board_data["sector_stocks"] = sector_stocks
                total_st = sum(len(v) for v in sector_stocks.values())
                print(f"  [BOARD] Sector stocks: {len(sector_stocks)} sectors, "
                      f"{total_st} stocks total")

            # Save atomically (temp file + rename)
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
            print(f"  [BOARD] Saved: {len(board_data.get('sectors', []))} sectors, "
                  f"{len(board_data.get('limit_ups', []))} limit-ups")
        except Exception as e:
            print(f"  [BOARD] Board data collection failed: {e}")

    # --- Step 2: Parse market agent outputs (if available) ---
    market_agent_outputs = _load_market_agent_outputs(RESULTS_DIR)
    if market_agent_outputs:
        print(f"  [MARKET] Found {len(market_agent_outputs)} market agent outputs")
        market_context = _build_market_context(market_agent_outputs, today)
        market_context_block = format_market_context_block(market_context)
        print(f"  [MARKET] Context: regime={market_context.get('regime')}, "
              f"breadth={market_context.get('breadth_state')}")

    # --- Step 3: Persist market_context ---
    if market_context is not None:
        _REPLAYS_DIR.mkdir(parents=True, exist_ok=True)
        ctx_path = _REPLAYS_DIR / f"market_context_{today}.json"
        ctx_path.write_text(json.dumps(market_context, ensure_ascii=False, indent=2),
                            encoding="utf-8")
        print(f"  [MARKET] Context saved: {ctx_path}")

    # --- Step 4: Process individual tickers ---
    results = {}
    for ticker, name in TICKERS:
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
    print(f"  Processed {len(results)}/{len(TICKERS)} tickers")
    print(f"{'=' * 60}")
    for ticker, paths in results.items():
        name = dict(TICKERS).get(ticker, "")
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
    return results


if __name__ == "__main__":
    process_all()

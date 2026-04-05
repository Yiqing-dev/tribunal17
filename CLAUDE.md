# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# subagent_pipeline

Self-contained A-share research system. Uses akshare for data, 17 prompt templates to drive LLM agents, bridge module to parse free-text into structured RunTrace, and outputs 8 layers of reports (Layer 0-7). **Zero external imports** — all dependencies (trace_models, replay_store, renderers) are vendored locally.

## Prerequisites

```bash
pip install akshare>=1.10
# No other Python deps required — everything else is vendored in this directory
```

The LLM calls are made via Claude Code's `Agent` tool — no API keys needed in Python code.

## Quick Start

```bash
# Demo report from mock data (no API key, no akshare)
python -m subagent_pipeline.demo_601985

# Batch-generate reports from existing agent outputs in agent_artifacts/results/
python -m subagent_pipeline.batch_process
```

## Automated Pipeline via Commands

When the user sends a command matching one of the patterns below, read `tribunal.md` and execute the corresponding flow automatically:

| Command | Action |
|---------|--------|
| `论衡十七司，升堂！{ticker} {name} {date?}` | Full L0-L7 pipeline |
| `复盘司，点卯！{date}` | L0 daily recap only |
| `太史令、户部司、舆图司，会同议事！{date}` | L1 market agents only |
| `观星度支通政察言，四司齐奏！{ticker} {name}` | L2 four analysts only |

See `tribunal.md` for the full orchestration spec with step-by-step execution order, parallel/sequential rules, and status output format.

## File Overview

```
subagent_pipeline/
│
│  ── Foundation ──
├── shared.py              Common prompt fragments + TAG_* output tag constants
├── config.py              PIPELINE_STAGES DAG + model assignments + import-time validation
├── agent_protocol.py      Unified AgentRequest/AgentResult + AGENT_REGISTRY (17 agents)
│                          build_prompt(req) + parse_output() + list_agents(category)
│
│  ── Data Layer (no LLM) ──
├── akshare_collector.py   Stock data → AkshareBundle (12 APIs) + _retry_call() utility
│                          Market data → MarketSnapshot (indices/sectors/northbound/limits)
│                          collect(use_cache=True) skips API calls on same-day re-runs
├── data_cache.py          SHA1-keyed file cache: DataCache.get/put/invalidate/clear
│                          Storage: data/cache/{sha1}.json, thread-safe, stats tracking
├── recap_collector.py     Daily recap → DailyRecapData (index K/MACD/RSI, sector heatmap, limits)
│                          Uses _retry_call from akshare_collector for transient failure retry
├── verification.py        Cross-validation prompt + PASS/FAIL parse
├── reflection.py          Post-hoc analysis: prediction vs actual outcome
│                          ReflectionRecord (error_type, pillar_blame, lesson)
│                          ReflectionReport (aggregation, markdown, save_json)
│                          generate_reflection_prompt() for LLM-based deep analysis
│
│  ── Prompt Layer ──
├── prompts.py             17 agent prompt functions, each returns rendered string
│
│  ── Transform Layer ──
├── bridge.py              Text → RunTrace: 17 parsers + _AGENT_PARSERS dispatch dict + report gen
├── heatmap.py             HeatmapNode / HeatmapData: pure data aggregation for treemap
├── proxy_pool.py          EM API proxy rotation: em_proxy_session() context manager, build_rotating_get()
├── backtest.py            Signal accuracy verification: forward bar eval, win rate, direction accuracy
├── signal_ledger.py       Append-only JSONL signal log for daily accumulation + backfill
├── opinion_tracker.py     Cross-ticker opinion drift: DailySnapshot, OpinionDrift, WatchlistReport
│
│  ── Orchestration ──
├── batch_process.py       Batch: read raw outputs → bridge → write HTML
├── pipeline.py            Reference doc: shows subagent call pattern (not executable)
├── demo_601985.py         Generate demo report from mock data
├── gen_*.py               Ad-hoc per-ticker report generators (read from agent_artifacts/)
│
│  ── Vendored: Observability ──
├── trace_models.py        NodeStatus, NodeTrace, RunTrace, RunMetrics, compute_hash
├── replay_store.py        ReplayStore: persist/load RunTrace as JSON (atomic writes)
├── replay_service.py      ReplayService: high-level replay operations
│
│  ── Vendored: Renderers ──
├── renderers/
│   ├── shared_css.py          Shared CSS tokens, JS helpers, brand logos (single source)
│   ├── shared_utils.py        15 shared utility functions (_esc, _html_wrap, _pct_to_hex, etc.)
│   ├── snapshot_renderer.py   Tier 1 — single-screen conclusion card
│   ├── research_renderer.py   Tier 2 — full research war room
│   ├── audit_renderer.py      Tier 3 — evidence chain audit
│   ├── pool_renderer.py       Divergence pool report
│   ├── market_renderer.py     Market command center report
│   ├── report_renderer.py     Facade — re-exports all above + generate_all_tiers/brief
│   ├── debate_renderer.py     Committee debate HTML
│   ├── recap_renderer.py      Daily recap cockpit HTML
│   ├── views.py               View models (data contract for templates)
│   ├── debate_view.py         Debate-specific view models
│   └── decision_labels.py     Node name → Chinese labels
│
│
│  ── Web Enhancement ──
├── web_collector.py       Web search layer (supplements akshare when APIs fail)
│                          5 prompt generators + 5 parsers + merge/format/apply helpers
│                          Covers: global macro, snapshot recovery, ticker enhancement,
│                          concept board fallback, top-10 shareholders fallback
│
│  ── Tests ──
├── tests/
│   ├── test_market_layer.py   78 tests — market layer + report rendering
│   ├── test_daily_recap.py    96 tests — daily recap collector + renderer
│   ├── test_debate.py         84 tests — debate + committee report
│   ├── test_trade_plan.py     31 tests — trade plan parsing + views
│   ├── test_dashboard.py     125 tests — dashboard views + routes
│   ├── test_opinion_tracker.py 61 tests — opinion drift analysis
│   └── test_web_collector.py  46 tests — web collector parsers + integration
│
├── requirements.txt       akshare>=1.10
```

## Pipeline Execution via Claude Code Agent Tool

This is the primary way to run the pipeline. Claude Code orchestrates 19+ LLM agent calls using the `Agent` tool, writing outputs to `agent_artifacts/results/`, then runs bridge to generate HTML reports.

### Directory Convention

There are two modes for storing agent outputs:

**Mode A — Per-agent files (Claude Code orchestration):**
Used when Claude Code orchestrates the pipeline directly. Each agent's output is saved individually.
```
agent_artifacts/results/
  # Market layer (per-agent, no ticker prefix)
  macro_analyst_output.txt         ← batch_process reads these
  market_breadth_agent_output.txt
  sector_rotation_agent_output.txt
  global_macro_output.txt          ← web search (optional, may not exist)

  # Per-ticker agent outputs
  {ticker}_market_report.txt
  {ticker}_fundamentals_report.txt
  {ticker}_news_report.txt
  {ticker}_sentiment_report.txt
  {ticker}_catalyst_report.txt
  {ticker}_bull_r1.txt, {ticker}_bull_r2.txt
  {ticker}_bear_r1.txt, {ticker}_bear_r2.txt
  {ticker}_scenario_report.txt
  {ticker}_research_manager.txt
  {ticker}_risk_aggressive.txt
  {ticker}_risk_conservative.txt
  {ticker}_risk_neutral.txt
  {ticker}_risk_manager.txt
  {ticker}_research_output.txt

  # Market context (assembled from market layer)
  market_context.json
  market_context_block.txt
```

**Mode B — Aggregated section files (batch_process):**
`batch_process.py` reads `{ticker}_output.txt` containing all sections delimited by `=== SECTION: key ===`.
```
agent_artifacts/results/
  {ticker}_output.txt              ← batch_process reads these
  macro_analyst_output.txt
  market_breadth_agent_output.txt
  sector_rotation_agent_output.txt

data/reports/                      Generated HTML reports
data/replays/                      RunTrace JSON persistence
```

### Full 8-Layer Execution Order (Layer 0-7)

Each step below uses Claude Code's `Agent` tool. Agents marked **(parallel)** can be launched simultaneously.

#### Layer 0: Daily Recap (optional, no LLM)

```python
from subagent_pipeline.recap_collector import collect_daily_recap
recap = collect_daily_recap(trade_date="2026-03-14")
# Save: recap.to_json() → data/replays/recap_2026-03-14.json
# Render: from subagent_pipeline.renderers.recap_renderer import generate_daily_recap_report
```

`DailyRecapData` fields: `date`, `index_summary` (Dict), `sector_heatmap` (Dict), `limit_board` (Dict), `consecutive_boards` (List[Dict]), `red_close` (Dict), `market_weather` (str), `position_advice` (str), `risk_note` (str), `one_line_summary` (str), `collection_seconds` (float), `market_context` (Dict). Serialize with `recap.to_json()`.

#### Layer 1: Market Agents (parallel, run once per day)

Four agents run in parallel. The first three receive `market_snapshot_md` from `snapshot.markdown_report` (attribute, NOT a method) after calling `akshare_collector.collect_market_snapshot(trade_date, watchlist=[...])`. The optional `watchlist` param (list of ticker strings) fetches spot data for those stocks alongside market breadth.

The 4th agent (Global Macro) uses WebSearch/WebFetch to gather international context that akshare cannot provide. It is optional — if it fails, the pipeline continues without it.

| Agent | Prompt | Model | Output Key |
|-------|--------|-------|------------|
| macro_analyst | `prompts.macro_analyst(current_date, market_snapshot_md)` | sonnet | `MACRO_OUTPUT:` block |
| market_breadth_agent | `prompts.market_breadth_agent(current_date, market_snapshot_md)` | sonnet | `BREADTH_OUTPUT:` block |
| sector_rotation_agent | `prompts.sector_rotation_agent(current_date, market_snapshot_md)` | sonnet | `SECTOR_OUTPUT:` block |
| global_macro (web) | `web_collector.global_macro_prompt(current_date, market_snapshot_md)` | sonnet | `GLOBAL_MACRO_OUTPUT:` block |

After all 4 complete, assemble market context:

```python
from subagent_pipeline.bridge import (
    parse_macro_output, parse_breadth_output, parse_sector_output,
    assemble_market_context, format_market_context_block,
)
from subagent_pipeline.web_collector import parse_global_macro_output

macro = parse_macro_output(macro_text)
breadth = parse_breadth_output(breadth_text)
sector = parse_sector_output(sector_text)
global_macro = parse_global_macro_output(global_macro_text) if global_macro_text else None

market_context = assemble_market_context(macro, breadth, sector, trade_date, global_macro=global_macro)
market_context_block = format_market_context_block(market_context)
# Save market_context.json and market_context_block.txt
```

The `global_macro` parameter adds `market_context["global_macro"]` dict and appends geopolitical risks to `risk_alerts`. The `format_market_context_block()` automatically appends a "国际宏观情报:" section when `global_macro` is present.

#### Layer 2: Individual Stock Analysis (per ticker)

**Step 0 — Data Collection (Python, no LLM):**

```python
from subagent_pipeline.akshare_collector import collect
bundle = collect(ticker="601985", trade_date="2026-03-14")
# bundle.name is auto-populated from akshare spot data
akshare_md = bundle.markdown_report  # attribute, NOT a method call
```

**Step 1 — 4 Analysts (parallel):**

| Agent | Prompt call | Key kwargs |
|-------|-------------|------------|
| market_analyst | `prompts.market_analyst(ticker, date, market_context_block=..., akshare_md=...)` | receives `market_context_block` |
| fundamentals_analyst | `prompts.fundamentals_analyst(ticker, date, akshare_md=...)` | |
| news_analyst | `prompts.news_analyst(ticker, date, akshare_md=...)` | |
| sentiment_analyst | `prompts.sentiment_analyst(ticker, date, akshare_md=...)` | |

All use model=sonnet. Save outputs as `{ticker}_market_report.txt`, etc.

**Step 1b — Evidence Block (Python, no LLM, after Step 1):**

```python
from subagent_pipeline.bridge import build_evidence_block
evidence_block = build_evidence_block(
    market_report=market_report_text,
    fundamentals_report=fundamentals_text,
    news_report=news_text,
    sentiment_report=sentiment_text,
)
```

Pass `evidence_block=evidence_block` to all subsequent agent calls (Steps 2-7). Step 8 (`research_output`) does not use `evidence_block`.

**Step 2 — Catalyst Agent (sequential, depends on Step 1):**

```
prompts.catalyst_agent(ticker, news_report=..., fundamentals_report=..., market_report=...,
                       evidence_block=evidence_block, current_date=current_date)
```

**Step 3 — Bull/Bear Debate (parallel per round, 2 rounds):**

Round 1: bull and bear run in parallel, no debate_history.
Round 2: bull gets `last_bear_argument=bear_r1`, bear gets `last_bull_argument=bull_r1`, both get `debate_history`.

```
prompts.bull_researcher(ticker, market_report, sentiment_report, news_report, fundamentals_report,
                        debate_history=..., last_bear_argument=..., evidence_block=..., current_date=trade_date)
prompts.bear_researcher(ticker, market_report, sentiment_report, news_report, fundamentals_report,
                        debate_history=..., last_bull_argument=..., evidence_block=..., current_date=trade_date)
```

**IMPORTANT**: bridge expects merged outputs per direction:
```python
bull_merged = f"=== Round 1 ===\n{bull_r1}\n\n=== Round 2 ===\n{bull_r2}"
bear_merged = f"=== Round 1 ===\n{bear_r1}\n\n=== Round 2 ===\n{bear_r2}"
```

**Step 4 — Scenario Agent (sequential, depends on Step 3):**

```
prompts.scenario_agent(ticker, bull_history=bull_merged, bear_history=bear_merged, current_date=trade_date)
```

**Step 5 — Research Manager (sequential, depends on Steps 2+3+4):**

```
prompts.research_manager(ticker, debate_input=combined_debate,
                         scenario_block=scenario_output,
                         market_context_block=market_context_block,
                         current_date=trade_date)
```

Model=opus. `debate_input` = concatenated bull+bear+catalyst.

**Step 6 — Risk Debate (parallel, 3 debaters):**

```
prompts.aggressive_debator(research_conclusion=pm_output, market_report=..., sentiment_report=...,
                           news_report=..., fundamentals_report=...,
                           evidence_block=evidence_block, current_date=trade_date)
prompts.conservative_debator(research_conclusion=pm_output, ..., evidence_block=evidence_block, current_date=trade_date)
prompts.neutral_debator(research_conclusion=pm_output, ..., evidence_block=evidence_block, current_date=trade_date)
```

**Note**: Risk debaters take `evidence_block` and `current_date` but do NOT take `market_context_block`.
Each debater outputs a `RISK_DEBATER_OUTPUT:` block (recommendation, position_size_pct, key_risk) parsed by `bridge.parse_risk_debater_output()`.

**Step 7 — Risk Manager (sequential, depends on Steps 5+6):**

```
prompts.risk_manager(company_name=ticker_name, trader_plan=pm_output,
                     risk_debate_history=combined_risk_debate,
                     evidence_block=evidence_block,
                     market_context_block=market_context_block,
                     current_date=trade_date)
```

Model=opus.

**Step 8 — Research Output (sequential, depends on Step 7):**

```
prompts.research_output(company_name=ticker_name, investment_plan=combined_conclusion,
                        ticker=ticker, akshare_md=akshare_md)
```

`investment_plan` = PM conclusion + risk manager output concatenated.

#### Layer 3: Report Generation (Python, no LLM)

```python
from subagent_pipeline.bridge import generate_report

# Build outputs dict — keys MUST match bridge.AGENT_NODE_MAP:
outputs = {
    "market_analyst": market_report_text,
    "fundamentals_analyst": fundamentals_text,
    "news_analyst": news_text,
    "sentiment_analyst": sentiment_text,
    "catalyst_agent": catalyst_text,
    "bull_researcher": bull_merged,      # R1+R2 merged
    "bear_researcher": bear_merged,      # R1+R2 merged
    "scenario_agent": scenario_text,
    "research_manager": pm_text,
    "aggressive_debator": aggressive_text,
    "conservative_debator": conservative_text,
    "neutral_debator": neutral_text,
    "risk_manager": risk_text,
    "research_output": output_text,
}

paths = generate_report(
    outputs=outputs,
    ticker=ticker,
    ticker_name=name,
    trade_date=trade_date,
    output_dir="data/reports",
    storage_dir="data/replays",
    market_context_block=market_context_block,
    market_context=market_context,
)
# Returns {"snapshot": "...html", "research": "...html", "audit": "...html", "run_id": "..."}
```

#### Layer 4: Committee Debate Report

```python
from subagent_pipeline.renderers.debate_renderer import generate_committee_report
from subagent_pipeline.replay_store import ReplayStore
store = ReplayStore(storage_dir="data/replays")
trace = store.load(run_id)
generate_committee_report(trace, output_dir="data/reports")
```

#### Layer 5: Divergence Pool Report

```python
from subagent_pipeline.renderers.report_renderer import generate_pool_report
generate_pool_report(
    run_ids=[...],  # list of run_id strings (>=2 required)
    output_dir="data/reports",
    storage_dir="data/replays",
    trade_date=trade_date,
    market_context=market_context,
    market_snapshot=market_snapshot,
)
```

#### Layer 6: Market Overview Report

```python
from subagent_pipeline.renderers.report_renderer import generate_market_report
generate_market_report(
    market_context=market_context,        # dict from assemble_market_context()
    market_snapshot=market_snapshot,       # MarketSnapshot instance or dict (optional)
    output_dir="data/reports",
    trade_date=trade_date,
    heatmap_data=None,                    # optional HeatmapData
)
```

#### Layer 7: Backtest Verification Report

```python
from subagent_pipeline.backtest import run_backtest, BacktestConfig, generate_backtest_report, save_backtest_report

config = BacktestConfig(
    eval_window_days=10,     # Forward trading days to evaluate
    neutral_band_pct=2.0,    # +/- band for neutral classification
    min_age_days=1,          # Min calendar days since signal
)

# Run backtest (fetch_prices=True requires akshare connectivity)
report = run_backtest(storage_dir="data/replays", config=config, fetch_prices=True)

# Generate HTML report
html_path = generate_backtest_report(report, output_dir="data/reports")

# Save JSON for later analysis
json_path = save_backtest_report(report, output_dir="data/reports")
```

**BacktestResult fields:** run_id, ticker, trade_date, action, confidence, direction_expected (up/down/flat), start_price, end_close, max_high, min_low, stock_return_pct, max_drawdown_pct, max_gain_pct, direction_correct, outcome (win/loss/neutral), stop_loss, take_profit, hit_stop_loss, hit_take_profit, eval_status.

**BacktestSummary fields:** direction_accuracy_pct, win_rate_pct, avg_stock_return_pct, avg_buy_return_pct, avg_sell_return_pct, action_breakdown (per-action win rate/avg return).

**BacktestReport access:** Use `report.overall_summary` (primary) or `report.summary` (convenience alias) to access the aggregated `BacktestSummary`.

#### Signal Ledger (daily accumulation)

```python
from subagent_pipeline.signal_ledger import SignalLedger, backfill_ledger

# After each pipeline run: append signal to ledger
ledger = SignalLedger()                        # default: data/signals/signals.jsonl
ledger.append_from_trace(run_id, storage_dir="data/replays", entry_price=9.16)

# Batch append from multiple runs
ledger.append_batch_from_traces(run_ids, storage_dir="data/replays", spot_data=spot_data)

# Backfill from all existing replays (one-time init)
backfill_ledger(storage_dir="data/replays")

# Read / query
signals = ledger.read(ticker="601985.SS", after="2026-03-10")
ledger.print_summary()
print(ledger.to_markdown())

# Run backtest directly from ledger (faster than loading RunTraces)
from subagent_pipeline.backtest import run_backtest_from_ledger
report = run_backtest_from_ledger(config=config, ticker="601985.SS")
```

**SignalRecord fields:** run_id, trade_date, ticker, ticker_name, action, confidence, entry_price, stop_loss, take_profit, market/fundamental/news/sentiment_score, risk_score, risk_flags, market_regime.

#### Opinion Tracker (cross-day drift analysis)

```python
from subagent_pipeline.opinion_tracker import (
    build_watchlist_report, track_ticker, latest_drift,
)

# Multi-ticker watchlist report
report = build_watchlist_report(
    tickers=["601985.SS", "000710.SZ"],
    date_from="2026-03-14", date_to="2026-03-19",
    storage_dir="data/replays",
)
print(report.to_markdown())    # Markdown summary with drift highlights
report.save_json("data/reports")  # JSON persistence

# Single-ticker quick view
snapshots, drifts = track_ticker("601985.SS", limit=30)

# Most recent day-over-day change
drift = latest_drift("601985.SS")
if drift and drift.action_changed:
    print(f"{drift.action_prev} -> {drift.action_curr}")
```

**DailySnapshot fields:** action, confidence, pillar scores (market/fundamental/news/sentiment), risk_score, risk_flags, bull/bear thesis + claims + overall_confidence, scenario probabilities, pm_conclusion, trade plan prices, market_regime.

**OpinionDrift fields:** action_changed, confidence_delta, pillar score deltas, risk_flags_added/removed, bull/bear claims_added/dropped, scenario prob deltas, drift_magnitude (major/minor/stable), drift_direction (bullish_shift/bearish_shift/unchanged).

**WatchlistReport highlights:** action_flips, biggest_confidence_moves, new_risk_flags — auto-collected from all drifts across tickers.

## Key bridge.py Rules

### Output Key Mapping

`bridge.AGENT_NODE_MAP` maps output dict keys to internal node names. These keys are what `generate_report(outputs=...)` expects. Use exactly these keys:

`market_analyst`, `fundamentals_analyst`, `news_analyst`, `sentiment_analyst`, `catalyst_agent`, `bull_researcher`, `bear_researcher`, `scenario_agent`, `research_manager`, `aggressive_debator`, `conservative_debator`, `neutral_debator`, `risk_manager`, `research_output`

### Evidence Citation

`bridge.build_evidence_block()` extracts key facts from the 4 analyst reports and assigns sequential `[E#]` IDs. This block is passed to all downstream agents (Stages 2-7).

Agents cite evidence in two formats (both handled by `parse_claims()`):
1. **E# references**: `[E1, E3]` — when Evidence Bundle is provided (preferred)
2. **Report-section references**: `[基本面报告-ROE数据, 技术面报告-MACD]` — fallback when no Evidence Bundle

Parser fallback chain: bracket-list → prose with E# refs → substantive prose (>=10 chars gets synthetic ID).

### Parser Tolerance

All parsers use priority: exact JSON → `key=value` lines → regex fallback. Do not change parser order without running tests.

## Agent Table (Quick Reference)

| # | Agent | Prompt Function | Model | Parallel | Input From | Structured Output |
|---|-------|----------------|-------|----------|------------|-------------------|
| 0 | Data Collection | — (Python) | — | no | akshare API | AkshareBundle |
| 0.8a | Macro Analyst | `macro_analyst()` | sonnet | yes | MarketSnapshot | `MACRO_OUTPUT:` |
| 0.8b | Market Breadth | `market_breadth_agent()` | sonnet | yes | MarketSnapshot | `BREADTH_OUTPUT:` |
| 0.8c | Sector Rotation | `sector_rotation_agent()` | sonnet | yes | MarketSnapshot | `SECTOR_OUTPUT:` |
| 0.8d | Global Macro (web) | `web_collector.global_macro_prompt()` | sonnet | yes | MarketSnapshot + WebSearch | `GLOBAL_MACRO_OUTPUT:` |
| 1a | Technical Analyst | `market_analyst()` | sonnet | yes | AkshareBundle + market_context_block | `pillar_score` |
| 1b | Fundamentals | `fundamentals_analyst()` | sonnet | yes | AkshareBundle | `pillar_score` |
| 1c | News Analyst | `news_analyst()` | sonnet | yes | AkshareBundle | `pillar_score` |
| 1d | Sentiment Analyst | `sentiment_analyst()` | sonnet | yes | AkshareBundle | `pillar_score` |
| 1e | Evidence Block | `bridge.build_evidence_block()` | — | no | 4 analyst outputs | `[E#]` numbered bundle |
| 2 | Catalyst Agent | `catalyst_agent()` | sonnet | no | 4 reports + evidence_block + current_date | `CATALYST_OUTPUT:` |
| 3a | Bull Researcher | `bull_researcher()` | sonnet | yes | 4 reports + evidence_block + debate history | CLAIM/EVIDENCE/CONFIDENCE |
| 3b | Bear Researcher | `bear_researcher()` | sonnet | yes | 4 reports + evidence_block + debate history | CLAIM/EVIDENCE/CONFIDENCE |
| 4 | Scenario Agent | `scenario_agent()` | sonnet | no | bull+bear merged + evidence_block | `SCENARIO_OUTPUT:` |
| 5 | Research Manager | `research_manager()` | **opus** | no | catalyst+debate+scenario+market_ctx+evidence_block | `SYNTHESIS_OUTPUT:` |
| 6a | Aggressive Risk | `aggressive_debator()` | sonnet | yes | PM output + 4 reports | `RISK_DEBATER_OUTPUT:` |
| 6b | Conservative Risk | `conservative_debator()` | sonnet | yes | PM output + 4 reports | `RISK_DEBATER_OUTPUT:` |
| 6c | Neutral Risk | `neutral_debator()` | sonnet | yes | PM output + 4 reports | `RISK_DEBATER_OUTPUT:` |
| 7 | Risk Manager | `risk_manager()` | **opus** | no | PM output + risk debate + evidence_block | `RISK_OUTPUT:` |
| 8 | Research Output | `research_output()` | sonnet | no | PM + risk manager output | TRADECARD/TRADE_PLAN/ORDER JSON |

## Common Modifications

### Add new agent
1. `prompts.py`: New prompt function returning string. Include a structured output block (e.g. `MY_OUTPUT:` with `key = value` lines) for bridge parsing.
2. `config.py`: Add to `PIPELINE_STAGES` (with `depends_on`) and `PIPELINE_CONFIG["models"]`. Import-time validation will catch mismatches.
3. `bridge.py`: Add parser function `_parse_xxx(agent_key, text, nt)`, add entry to `_AGENT_PARSERS` dispatch dict, add entries in `AGENT_NODE_MAP` and `AGENT_SEQ`.

### Add data source
`akshare_collector.py`: Add `_collect_xxx(bundle)`, call in `collect()` via `_COLLECTORS` list, add field to `AkshareBundle`. API calls are automatically retried via `_retry_call`.

### Modify report rendering
Renderers are split into focused modules under `renderers/`. Edit the specific renderer (e.g. `snapshot_renderer.py` for Tier 1, `market_renderer.py` for market page). Shared utilities are in `shared_utils.py`, CSS tokens in `shared_css.py`. `report_renderer.py` is a facade that re-exports everything — downstream imports are unchanged.

### Modify evidence extraction
`bridge._extract_evidence_items()` controls what gets pulled from analyst reports into the Evidence Bundle. Add new extraction patterns there. Max 8 items per report, 32 total.

## Data Reliability

### API Retry

`_retry_call(fn, *args, max_retries=2, base_delay=1.0)` in `akshare_collector.py` wraps all akshare API calls with exponential backoff. Only retries on transient errors (timeout, connection reset, rate limit, 429/503). Non-transient errors (ValueError, empty data) pass through immediately.

Used in:
- `akshare_collector.collect()` — all per-ticker API calls
- `akshare_collector.collect_market_snapshot()` — all market-level API calls
- `recap_collector.collect_daily_recap()` — all recap collector calls (imports `_retry_call` from akshare_collector)

### Proxy Rotation for East Money APIs

`proxy_pool.py` provides `em_proxy_session()` — a context manager that routes East Money (EM) domain requests through a rotating proxy pool. Non-EM requests (Sina, XQ, THS, Baidu) pass through unchanged. **No-op when `PROXY_API_URL` env var is unset.**

```bash
export PROXY_API_URL="https://your-proxy-api.com/get?num=5&format=txt"
export PROXY_TIMEOUT=20   # optional, default 20s
```

Usage in collector code:
```python
from .proxy_pool import em_proxy_session
with em_proxy_session():
    df = ak.stock_zh_a_spot_em()  # proxied
df2 = ak.stock_zh_a_daily(...)    # not proxied (outside context)
```

Key mechanics: URL-selective patching (only `*.eastmoney.com`), multi-proxy rotation with pool refresh, per-proxy urllib3 retry, direct-connection fallback, recursion prevention for proxy fetching.

Integrated in: `akshare_collector.py` (8 sites), `recap_collector.py` (~10 sites), `batch_process.py` (3 sites).

### Multi-Source Fallback Chains

Market data collection uses fallback chains when primary APIs are down:
- **Breadth**: EM spot (`stock_zh_a_spot_em`) → THS industry summary (`stock_board_industry_summary_ths`) for advance/decline counts
- **Watchlist spots**: EM spot → XQ individual spot (`stock_individual_spot_xq`) per ticker
- **Sector flow**: EM fund flow (`stock_sector_fund_flow_rank`) → THS industry summary (`stock_board_industry_summary_ths`) with column mapping (`板块→名称`, `涨跌幅→今日涨跌幅`)
- **Sector stocks**: EM sector constituents (`stock_board_industry_cons_em`) → SW index (`index_component_sw`) + XQ spot for price data. Uses cached THS→SW mapping (`_build_ths_to_sw_map`).
- **Concept boards**: EM concept names (`stock_board_concept_name_em`) → Web search fallback via `web_collector.concept_board_web_prompt()` (Agent tool with WebSearch/WebFetch)
- **Top 10 shareholders**: EM top-10 (`stock_gdfx_free_top_10_em`, akshare bug) → Web search fallback via `web_collector.top10_shareholders_web_prompt()` (Agent tool with WebSearch/WebFetch)

Fallbacks degrade gracefully — some fields (e.g., limit counts from THS, net_pct from THS sector flow) may be zero but the pipeline continues. Web search fallbacks require the Agent tool and are slower than API fallbacks.

### Atomic File Writes

`replay_store.ReplayStore.save()` uses write-to-temp-then-rename (`tempfile.mkstemp()` → `os.replace()`). If the process crashes mid-write, the previous file remains intact. Temp files use `.trace-` prefix and `.tmp` suffix in the same directory.

### Ticker Validation

`akshare_collector.collect()` validates that the bare ticker matches `^\d{6}$` after stripping exchange suffixes. Raises `ValueError` on invalid input.

### Pipeline Config Validation

`config.validate_pipeline_config()` runs at import time and checks:
- All `depends_on` references point to existing stage IDs
- All agents with model assignments have a corresponding pipeline stage
- Non-LLM agents (in stages but not in models) are auto-detected, not hardcoded

### Filename Sanitization

`renderers.report_renderer._safe_filename(part)` strips all non-alphanumeric characters (except `._-`) from a string before using it in file paths. All renderers that construct output file names from ticker or run_id must use this function to prevent path traversal via `../` in user-supplied values.

### NaN Protection

`MarketSnapshot.to_json()` uses `allow_nan=False` — any `NaN` or `Infinity` in snapshot data will raise `ValueError` at serialization time rather than producing invalid JSON. This prevents downstream parsers from silently consuming bad data.

## Critical Data Integrity Rules

These rules exist because of past bugs that produced silently wrong reports. Violating them will produce misleading data.

### Market Report Data Flow
1. **Snapshot must be persisted at L1**: `snapshot.to_json()` → `market_snapshot.json`. L5/L6 must load via `MarketSnapshot.from_json()` and pass to renderers. Never pass `market_snapshot=None` — it causes limit_up/limit_down to show 0.
2. **Sectors sorted by 涨跌幅, not 主力净流入**: EM's net_inflow metric often contradicts actual price direction (e.g., +15亿 inflow but -1.28% price). `_collect_sector_flow()` sorts by price change. `generate_market_report()` overrides `sector_momentum` with snapshot ground-truth data.
3. **Board data from recap**: Pass `board_data` (from `recap_{date}.json`) to renderers for limit-up/limit-down stock detail lists.

### Signal Direction Integrity
4. **Risk Judge does not default to HOLD**: If RISK_OUTPUT omits `research_action`, the PM's direction is preserved. Never hardcode a default action.
5. **AVOID ≠ SELL**: TRADE_PLAN bias=AVOID means "don't participate" (risk_cleared=FALSE or VETO). It maps to HOLD, not SELL.
6. **Stale threshold is 0.02**: Confidence is on a 0.0–1.0 scale. The stale-signal threshold in `opinion_tracker.py` is `abs(confidence_delta) < 0.02`, not 2.0.
7. **Confidence normalization uses >= 10**: `parse_claims()` normalizes confidence values ≥10 by dividing by 100 (0-100 scale → 0-1). Values >1.0 but <10 are divided by 10 (1-10 scale → 0-1). Result is clamped to [0, 1].
8. **Chinese negation window is 12 characters**: `_has_positive()` looks back 12 characters (not 5) before a keyword to detect negation. This catches multi-char modifiers like "坚决不建议买入".

## Known Limitations

### Naming quirks
- **Parameter naming**: `risk_manager()` and `research_output()` use `company_name` as first param while analysts use `ticker`. Callers must pass ticker value as `company_name` for those two.
- **All prompt functions accept `**kw`**: Forward-compatible — new keyword args can be added without breaking existing callers.
- **`current_date` must be set explicitly**: `PIPELINE_CONFIG["current_date"]` defaults to `""`. Callers must set it (use `config._today()` utility). This prevents stale dates from import-time evaluation.

### By design
- **ASTOCK_RULES injected 4x**: Each of the 4 Stage 1 analysts gets the full A-share rules block (~500 tokens). This is intentional — analysts run independently and each needs the rules.
- **Turnover delta estimation**: `recap_collector` estimates previous-day total market turnover using Shanghai index volume ratio as proxy. This is approximate (misses ChiNext/STAR/Shenzhen-only stocks) but sufficient for directional delta.
- **Fail-open batch processing**: `batch_process.process_all()` continues processing remaining tickers when one fails. Individual failures are logged but don't block the batch.
- **Confidence sentinel -1.0**: `NodeTrace.confidence` and `RunTrace.final_confidence` use `-1.0` to mean "not set". `RunTrace.finalize()` skips nodes with `confidence < 0` when picking the final confidence. Do not change to `None` — 7+ files compare numerically.
- **Publishing Compliance is lightweight**: The subagent_pipeline runs P1 (evidence presence) and P5 (veto consistency) checks. The full 5-rule engine lives in `tradingagents/publishing_compliance.py` (parent project, not importable due to zero-external-import policy). Compliance node seq=18 (after research_output=17).
- **Output tag constants in shared.py**: All agent output markers (`TAG_CATALYST_OUTPUT`, `TAG_RISK_OUTPUT`, etc.) are defined once in `shared.py`. Bridge parsers import them. Prompts still embed the string literals in f-strings (LLM-facing text), but the tag names are centralized for parser maintenance.
- **Timestamps are CST (UTC+8)**: `trace_models._now_cst()` produces timezone-aware datetimes. Old traces with naive timestamps are still loadable via `fromisoformat()`.
- **_sina_cache capped at 500 entries**: Thread-safe with FIFO eviction when limit reached (`backtest._cached_klines()`).
- **Replay trace size limit**: `ReplayStore.load()` rejects files >50 MB to prevent OOM.
- **pm_confidence survives JSON roundtrip**: `RunTrace.to_dict()` serializes `_pm_confidence` as `"pm_confidence"`; `from_dict()` restores it. This preserves the confidence fallback chain across serialization boundaries.
- **confidence_raw in structured_data**: The pre-normalization confidence value from TRADECARD_JSON is stored as `structured_data["confidence_raw"]` for audit traceability.

## Tests

Run from the **project root** (parent of `subagent_pipeline/`), not from `subagent_pipeline/` itself — some tests import from `dashboard.*` which requires the project root on `sys.path`. 897 tests, no API keys needed:

```bash
# All tests
pytest subagent_pipeline/tests/ -q

# Single module
pytest subagent_pipeline/tests/test_market_layer.py -v   # 108 tests
pytest subagent_pipeline/tests/test_daily_recap.py -v    # 96 tests
pytest subagent_pipeline/tests/test_debate.py -v         # 84 tests
pytest subagent_pipeline/tests/test_trade_plan.py -v     # 31 tests
pytest subagent_pipeline/tests/test_dashboard.py -v      # 125 tests
pytest subagent_pipeline/tests/test_opinion_tracker.py -v # 65 tests

# Single test
pytest subagent_pipeline/tests/test_trade_plan.py::TestViewIntegration::test_no_trade_plan_no_card -v
```

## Output Directory

```
data/reports/           HTML reports
  {ticker}-run-{id}-snapshot.html
  {ticker}-run-{id}-research.html
  {ticker}-run-{id}-audit.html
  pool-{date}-{n}stocks.html
  market-{date}.html
  recap-{date}.html
  committee-{ticker}-{id}.html
  backtest-{date}.html
  backtest-{date}.json
  brief-{date}.md

data/signals/           Signal ledger
  signals.jsonl           Append-only JSONL, one signal per line

data/replays/           RunTrace JSON
  {run_id}.json
  market_context_{date}.json
  recap_{date}.json
```

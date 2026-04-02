# CHANGELOG

## 2026-04-02 — Major Quality & Architecture Release

### Bug Fixes (5 rounds, ~120 issues)

#### Round 1: STATIC_REVIEW_FINDINGS.md (10 fixes)
- `bridge.py`: Unified risk_cleared fallback to False
- `report_renderer.py`: Guard confidence sentinel -1.0 from rendering as -100%
- `akshare_collector.py`: Anchor date to trade_date instead of datetime.now()
- `recap_collector.py`: Replace removed legacy northbound API, fix bare except:pass
- `verification.py`: Remove unsafe PASS substring fallback
- `replay_store.py`/`signal_ledger.py`: normalize_ticker on both sides of comparison
- `backtest.py`: Strip action, remove unused confidence param, unknown→abstain
- `backtest.py`: Add SVG cumulative return annotation
- `proxy_pool.py`: Document thread-safety limitation

#### Round 2: Chart/Text Audit (8 fixes)
- Label estimated turnover delta with ≈ prefix
- Label synthetic treemap tiles when board_data unavailable
- Annotate emotion thermometer heuristic weights
- Track and label flat_estimated, northbound_status, breadth_estimated
- Flag defaulted scenario probabilities and PM confidence in reports

#### Round 3: Static Review Round 2 (10 fixes)
- `bridge.py`: pillar_score regex (\d)→(\d+) with clamp to 0-4
- `bridge.py`: Log + flag risk_flags JSON parse failure
- `web_collector.py`: Guard global_macro full-text fallback for long text
- `report_renderer.py`: copy.copy(market_context) before mutation
- `replay_store.py`: try/except on load(), add reconcile() method
- `batch_process.py`: Pass raw_texts for date validation
- `backtest.py`: Separate shadow_results from results in BacktestReport

#### Round 4: External Audit (39 fixes across P0-P3)
- **P0 (8)**: pe_ttm/pb falsy→is None, gen_688298 load_run→load, XSS innerHTML+escHtml, script injection ensure_ascii, BacktestConfig/Summary field filtering, confidence clamp [0,1], PM confidence fallback in finalize, MarketSnapshot.to_json turnover
- **P1 (12)**: Remove "no tables found" from transient, Sina retry, northbound_stale_days field, Baidu PE/PB independent try/except, red close trade_date, red close retry+proxy, OSError→specific exceptions, scenario prob normalization, TOCTOU fix, reconcile flock, repair_ledger encoding, THS turnover unit detection
- **P2 (10)**: Dead col_map, BSE prefix, proxy URL sanitize, PM action word boundary, DAG cycle detection, verification regex \Z, signal_ledger O(1) dedup, ReplayStore loop fix, _html_wrap title escape
- **P3 (9)**: _fmt_num unit, BSE financial_ratios prefix, _collect_index_history retry, _compute_5d_return zero guard, FAIL word boundary, compute_hash deterministic, compliance denominator fix, signal_close is None, FRESHNESS_STATUS_LABELS consistency

#### Round 5: AUDIT_REPORT.md (19 fixes)
- **Critical**: Chinese negation 5-char window scan, benchmark ZeroDivisionError, recap/market </script> injection
- **High**: Claim ID collision clm-u/clm-r, PM claim regex match, format_market_context_block safe join, _pm_confidence leak filter, XQ fallback PB, concept_flow logging, volume/amount consistency
- **Rendering**: audit lag _esc, thesis_cn _esc, pillar_score try/except, debate claim .get(), repair_ledger encoding
- **Prompts**: research_output current_date, docstring 14→17

#### Runtime Fixes
- `_fmt_num` NameError (stale {unit} references)
- sector_momentum flow value cleaning (+33.92亿→33.92)
- Date validation downgraded from exception to warning
- DailyRecapData.from_json() classmethod added

### Architecture Refactoring

#### Phase A: Shared Extraction
- `shared_css.py` (625 lines): CSS tokens, JS helpers, brand logos — single source of truth
- `shared_utils.py` (312 lines): 15 utility functions extracted from report_renderer

#### Phase B: Renderer Split
- `report_renderer.py`: 5758 → 285 lines (facade only)
- `snapshot_renderer.py` (479 lines): Tier 1 conclusion card
- `research_renderer.py` (530 lines): Tier 2 war room
- `audit_renderer.py` (283 lines): Tier 3 evidence audit
- `pool_renderer.py` (1423 lines): Divergence pool report
- `market_renderer.py` (2050 lines): Market command center

#### Phase C: CSS Deduplication
- recap_renderer.py: Remove 68-line duplicated :root block, import from shared_css
- debate_renderer.py: Same treatment, import _BASE_CSS + _esc from shared modules

#### Phase D: Bridge Dispatch
- `_populate_structured_data()` 371-line if/elif → 9 standalone functions + `_AGENT_PARSERS` dispatch dict

#### Phase E: Prompt Parameters
- `current_date` added to 8 functions (bull/bear, scenario, PM, risk_manager, 3 debaters, research_output)
- `evidence_block` added to 3 risk debater functions

### Visual Improvements
- A-share convention: red=up, green=down across all market/recap reports
- K-line MA legend (MA5/MA14/MA30 color labels)
- Emotion thermometer numeric score display
- Recap heatmap SVG native tooltips
- Limit board attribution donut chart
- Cross-links between recap ↔ market command center
- Market snapshot markdown: total turnover + concept board net_inflow
- Sector treemap annotation for synthetic data
- Prompt template: flow field format clarified with examples

### Flow Improvements
- L0+L1 date freshness check before L2 entry
- ticker_name single-source-of-truth from bundle.name
- L4 committee report + signal ledger append mandatory after L3
- tribunal.md updated with all new parameters

### Testing
- **125 new unit tests** (test_bridge_parsers.py: 68, test_signal_and_trace.py: 57)
- Total: **678 → 803 tests passing**
- Coverage: parse_pillar_score, build_evidence_block, parse_claims (ID format), Chinese negation detection, parse_risk_output, assemble_market_context flow cleaning, format_market_context_block list-of-dicts, normalize_ticker, SignalLedger append/read/dedup, _esc, _pct_to_hex, _squarify, NodeTrace/RunTrace.from_dict mutation safety, compute_hash

### Validation Runs
- L0+L1: 2 days (2026-04-01, 2026-04-02)
- L2-L8: 601985 中国核电 (HOLD 0.55) + 603065 宿迁联盛 (HOLD/AVOID 0.50)
- L5: Pool divergence report (2 stocks)
- L7: Backtest (104 signals, 73 completed, 41.2% accuracy)

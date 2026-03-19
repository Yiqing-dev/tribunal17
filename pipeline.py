"""Pipeline orchestrator — shows how to run the full TradingAgents pipeline using Claude Code subagents.

This file is a REFERENCE IMPLEMENTATION showing the subagent invocation pattern.
It cannot be executed directly as a Python script — it is designed to be translated
into sequential/parallel Agent tool calls within a Claude Code conversation.

Usage pattern in Claude Code:
    1. Read this file to understand the pipeline
    2. Call Agent tool for each stage, passing the rendered prompt from prompts.py
    3. Feed outputs from earlier stages into later stages as specified

The key adaptation from LangGraph:
    - LangGraph: tools → LLM → tool-calling loop → structured state
    - Subagent: WebSearch → LLM reasoning → text output → manual state threading
"""

from .config import PIPELINE_CONFIG as cfg
from . import prompts


# ============================================================
# Stage 0: Data Collection (Python, no LLM)
# ============================================================
# Collect all structured data via akshare APIs.
# This is a pure-Python step — no subagent call needed.
#
# from .akshare_collector import collect
# bundle = collect(ticker=cfg["ticker"], trade_date=cfg.get("trade_date", ""))
#
# Output: AkshareBundle with price, fundamentals, news, research reports


# ============================================================
# Stage 0.5: Data Verification (SEQUENTIAL, depends on Stage 0)
# ============================================================
# Cross-check akshare data via WebSearch. FAIL → stop pipeline.
#
# from .verification import verification_prompt, parse_verification_result
#
# Agent(
#     description=f"Data verification {cfg['ticker']}",
#     subagent_type="general-purpose",
#     model=cfg["models"]["verification_agent"],
#     prompt=verification_prompt(bundle),
# )
#
# verification = parse_verification_result(agent_result)
#
# if not verification.can_proceed:
#     print(f"PIPELINE HALTED: verification {verification.overall}")
#     print(f"  Discrepancies: {verification.discrepancies}")
#     # *** STOP HERE — do not proceed to Stage 1 ***
#     return  # or raise, depending on orchestration style
#
# Output: VerificationResult (can_proceed=True → continue, False → halt)


# ============================================================
# Stage 1: Four Analysts (PARALLEL)
# ============================================================
# Each analyst receives akshare structured data (from Stage 0) as primary data source.
# WebSearch is used only for supplementary info not covered by akshare.
#
# Agent(
#     description="Market analyst {ticker}",
#     subagent_type="general-purpose",
#     model=cfg["models"]["market_analyst"],
#     prompt=prompts.market_analyst(
#         ticker, current_date,
#         market_context_block=market_context_block,
#         akshare_md=bundle.render_market_analyst_md(),
#     ),
# )
# Agent(
#     description="Fundamentals analyst {ticker}",
#     model=cfg["models"]["fundamentals_analyst"],
#     prompt=prompts.fundamentals_analyst(
#         ticker, current_date,
#         akshare_md=bundle.render_fundamentals_analyst_md(),
#     ),
# )
# Agent(
#     description="News analyst {ticker}",
#     model=cfg["models"]["news_analyst"],
#     prompt=prompts.news_analyst(
#         ticker, current_date,
#         akshare_md=bundle.render_news_analyst_md(),
#     ),
# )
# Agent(
#     description="Sentiment analyst {ticker}",
#     model=cfg["models"]["sentiment_analyst"],
#     prompt=prompts.sentiment_analyst(
#         ticker, current_date,
#         akshare_md=bundle.render_sentiment_analyst_md(),
#     ),
# )
#
# Collect outputs:
#   market_report = agent_result_1
#   fundamentals_report = agent_result_2
#   news_report = agent_result_3
#   sentiment_report = agent_result_4


# ============================================================
# Stage 2: Catalyst Agent (SEQUENTIAL, depends on Stage 1)
# ============================================================
# Reads analyst reports, extracts forward-looking events.
#
# Agent(
#     description="Catalyst extraction {ticker}",
#     model=cfg["models"]["catalyst_agent"],
#     prompt=prompts.catalyst_agent(
#         ticker=ticker,
#         news_report=news_report,
#         fundamentals_report=fundamentals_report,
#         market_report=market_report,
#     ),
# )
#
# Output: catalyst_report (contains CATALYST_OUTPUT JSON block)


# ============================================================
# Stage 3: Bull/Bear Debate (PARALLEL per round, multi-round)
# ============================================================
# Round 1: Bull and Bear work from analyst reports (parallel)
# Round 2+: Each reads opponent's previous round output (parallel)
#
# for round_num in range(1, cfg["bull_bear_rounds"] + 1):
#     if round_num == 1:
#         bull_prompt = prompts.bull_researcher(
#             ticker, market_report, sentiment_report, news_report,
#             fundamentals_report,
#         )
#         bear_prompt = prompts.bear_researcher(
#             ticker, market_report, sentiment_report, news_report,
#             fundamentals_report,
#         )
#     else:
#         bull_prompt = prompts.bull_researcher(
#             ticker, market_report, sentiment_report, news_report,
#             fundamentals_report,
#             debate_history=full_debate_history,
#             last_bear_argument=last_bear_output,
#         )
#         bear_prompt = prompts.bear_researcher(
#             ticker, market_report, sentiment_report, news_report,
#             fundamentals_report,
#             debate_history=full_debate_history,
#             last_bull_argument=last_bull_output,
#         )
#
#     # Launch both in parallel
#     Agent(prompt=bull_prompt, model=cfg["models"]["bull_researcher"])
#     Agent(prompt=bear_prompt, model=cfg["models"]["bear_researcher"])
#
#     # Accumulate history
#     full_debate_history += f"\n--- Round {round_num} ---\n"
#     full_debate_history += f"Bull: {bull_output}\n"
#     full_debate_history += f"Bear: {bear_output}\n"
#     last_bull_output = bull_output
#     last_bear_output = bear_output


# ============================================================
# Stage 4: Scenario Agent (SEQUENTIAL, depends on Stage 3)
# ============================================================
# Agent(
#     description="Scenario tree {ticker}",
#     model=cfg["models"]["scenario_agent"],
#     prompt=prompts.scenario_agent(
#         ticker=ticker,
#         bull_history=bull_history,
#         bear_history=bear_history,
#     ),
# )
#
# Output: scenario_report (contains SCENARIO_OUTPUT block)


# ============================================================
# Stage 5: Research Manager / PM (SEQUENTIAL, depends on 2,3,4)
# ============================================================
# Agent(
#     description="PM synthesis {ticker}",
#     model=cfg["models"]["research_manager"],
#     prompt=prompts.research_manager(
#         ticker=ticker,
#         debate_input=full_debate_history,
#         scenario_block=scenario_report,
#     ),
# )
#
# Output: pm_decision (contains SYNTHESIS_OUTPUT block)


# ============================================================
# Stage 6: Risk Debate — 3-way (PARALLEL per round)
# ============================================================
# Round 1: All three read PM decision + analyst reports (parallel)
# Round 2+: Each reads other two's previous output (parallel)
#
# for round_num in range(1, cfg["risk_debate_rounds"] + 1):
#     Agent(prompt=prompts.aggressive_debator(
#         research_conclusion=pm_decision, ...
#         last_conservative=last_conservative, last_neutral=last_neutral,
#     ))
#     Agent(prompt=prompts.conservative_debator(
#         research_conclusion=pm_decision, ...
#         last_aggressive=last_aggressive, last_neutral=last_neutral,
#     ))
#     Agent(prompt=prompts.neutral_debator(
#         research_conclusion=pm_decision, ...
#         last_aggressive=last_aggressive, last_conservative=last_conservative,
#     ))


# ============================================================
# Stage 7: Risk Judge (SEQUENTIAL, depends on 5,6)
# ============================================================
# Agent(
#     description="Risk judge {ticker}",
#     model=cfg["models"]["risk_manager"],
#     prompt=prompts.risk_manager(
#         company_name=ticker,
#         trader_plan=pm_decision,
#         risk_debate_history=risk_debate_history,
#     ),
# )
#
# Output: risk_decision (contains RISK_OUTPUT block)


# ============================================================
# Stage 8: Research Output / Trade Card (SEQUENTIAL, depends on 7)
# ============================================================
# Agent(
#     description="Trade card {ticker}",
#     model=cfg["models"]["research_output"],
#     prompt=prompts.research_output(
#         company_name=ticker,
#         investment_plan=f"{pm_decision}\n\nRisk Decision:\n{risk_decision}",
#         ticker=ticker,
#         akshare_md=bundle.render_price_reference_md(),
#     ),
# )
#
# Output: Final TRADECARD_JSON + TRADE_PLAN_JSON + ORDER_PROPOSAL_JSON


# ============================================================
# Summary: Total Subagent Calls
# ============================================================
#
# With default config (2 debate rounds, 1 risk debate round):
#
# Stage 0:    Python-only            — Data Collection (akshare)
# Stage 0.5:  1 agent                — Data Verification (FAIL → halt)
# Stage 1:    4 agents (parallel)    — Analysts
# Stage 2:    1 agent                — Catalyst
# Stage 3:    4 agents (2 rounds × 2)— Bull/Bear Debate
# Stage 4:    1 agent                — Scenario
# Stage 5:    1 agent                — PM
# Stage 6:    3 agents (parallel)    — Risk Debate
# Stage 7:    1 agent                — Risk Judge
# Stage 8:    1 agent                — Research Output
# ─────────────────────────────────
# Total:   17 subagent calls per ticker (16 if verification is skipped)
#
# Wall-clock time estimate:
#   Stage 1: ~60-90s (parallel, akshare data injected, reduced WebSearch)
#   Stage 2: ~30s
#   Stage 3: ~120s (2 rounds × ~60s, parallel within round)
#   Stage 4: ~30s
#   Stage 5: ~60s
#   Stage 6: ~60s (parallel)
#   Stage 7: ~45s
#   Stage 8: ~30s
#   ─────────────────
#   Total: ~8-10 minutes per ticker

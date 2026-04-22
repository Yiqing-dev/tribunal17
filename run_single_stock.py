"""Run full L2 pipeline for a single stock — designed to be called by Claude Code Agent.

This script is executed by a mega-agent that plays all 14 roles sequentially.
It handles all non-LLM steps (data collection, evidence, report generation)
and writes prompts for each role to files, then reads back the agent's analysis.

Usage (from Claude Code Agent prompt):
    Read and execute /path/to/run_single_stock.py with:
    TICKER=688114 TICKER_NAME=华大智�� TRADE_DATE=2026-04-03

The agent calling this must:
1. For each step, read the prompt file, perform the analysis, write the output file
2. Follow the exact step order (some steps are sequential, some could be done together)
"""

# This file is a REFERENCE for the mega-agent prompt builder.
# It is NOT executed directly — the mega-agent prompt includes all steps inline.

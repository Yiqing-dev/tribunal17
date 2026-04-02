"""Subagent pipeline — TradingAgents prompts adapted for Claude Code subagent execution."""

__all__ = [
    # Data collection
    "akshare_collector",
    "recap_collector",
    "web_collector",
    # Prompt layer
    "prompts",
    "shared",
    "config",
    # Transform layer
    "bridge",
    "heatmap",
    "backtest",
    "signal_ledger",
    "opinion_tracker",
    # Orchestration
    "batch_process",
    # Vendored observability
    "trace_models",
    "replay_store",
    "replay_service",
    # Renderers (subpackage)
    "renderers",
]

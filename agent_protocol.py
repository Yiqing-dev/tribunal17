"""Agent Protocol — unified interface for all pipeline agents.

Standardizes the 17 heterogeneous prompt functions into a single
AgentRequest → AgentResult contract with a central AGENT_REGISTRY.

Usage:
    from subagent_pipeline.agent_protocol import (
        AgentRequest, AgentResult, build_prompt, parse_output, agent_spec,
    )

    # Build prompt for any agent
    req = AgentRequest(
        agent_name="market_analyst",
        ticker="601985", trade_date="2026-04-04",
        akshare_md=bundle.markdown_report,
        market_context_block=mkt_block,
    )
    prompt_text = build_prompt(req)

    # Parse raw LLM output into structured result
    result = parse_output(req.agent_name, raw_text, run_id="run-abc")

    # Inspect agent metadata
    spec = agent_spec("research_manager")
    print(spec.model, spec.node_name, spec.seq)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from . import prompts
from .bridge import AGENT_NODE_MAP, AGENT_SEQ, build_node_trace
from .config import PIPELINE_CONFIG
from .shared import (
    TAG_CATALYST_OUTPUT, TAG_RISK_OUTPUT, TAG_RISK_DEBATER_OUTPUT,
    TAG_MACRO_OUTPUT, TAG_BREADTH_OUTPUT, TAG_SECTOR_OUTPUT,
    TAG_SYNTHESIS_OUTPUT, TAG_TRADECARD_JSON, TAG_TRADE_PLAN_JSON,
)


# ── Data Models ──────────────────────────────────────────────────────────


@dataclass
class AgentRequest:
    """Unified input for all pipeline agents.

    Common fields cover 90% of use cases.  Agent-specific parameters
    go into ``extra`` to avoid an ever-growing signature.
    """
    agent_name: str
    ticker: str = ""
    ticker_name: str = ""
    trade_date: str = ""

    # Data inputs
    akshare_md: str = ""
    market_snapshot_md: str = ""
    market_context_block: str = ""
    evidence_block: str = ""

    # Reports from upstream agents
    reports: Dict[str, str] = field(default_factory=dict)
    # Keys: market_report, fundamentals_report, news_report, sentiment_report,
    #        catalyst_report, bull_merged, bear_merged, scenario_output,
    #        research_manager, risk_debate_history, investment_plan

    # Debate state
    debate_history: str = ""
    last_opponent_argument: str = ""

    # Agent-specific overrides (avoids adding fields for rare params)
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentResult:
    """Unified output from any pipeline agent."""
    agent_name: str
    raw_text: str = ""
    node_name: str = ""
    model: str = ""
    seq: int = -1
    output_tag: str = ""               # e.g. TAG_CATALYST_OUTPUT
    error: str = ""

    def ok(self) -> bool:
        return not self.error and bool(self.raw_text)


@dataclass(frozen=True)
class AgentSpec:
    """Registry entry describing a single agent."""
    name: str                          # e.g. "market_analyst"
    node_name: str                     # e.g. "Market Analyst"
    seq: int                           # execution order
    model: str                         # "sonnet" | "opus"
    output_tag: str                    # primary output tag (for parsers)
    prompt_builder: Callable           # (AgentRequest) → str
    category: str = ""                 # "market_layer" | "analyst" | "debate" | "risk" | "synthesis"


# ── Prompt Builders ──────────────────────────────────────────────────────
# Each translates an AgentRequest into the specific prompt function call.


def _build_macro(r: AgentRequest) -> str:
    return prompts.macro_analyst(r.trade_date, r.market_snapshot_md)


def _build_breadth(r: AgentRequest) -> str:
    return prompts.market_breadth_agent(r.trade_date, r.market_snapshot_md)


def _build_sector(r: AgentRequest) -> str:
    return prompts.sector_rotation_agent(r.trade_date, r.market_snapshot_md)


def _build_market_analyst(r: AgentRequest) -> str:
    return prompts.market_analyst(
        r.ticker, r.trade_date,
        market_context_block=r.market_context_block,
        akshare_md=r.akshare_md,
    )


def _build_fundamentals(r: AgentRequest) -> str:
    return prompts.fundamentals_analyst(r.ticker, r.trade_date, akshare_md=r.akshare_md)


def _build_news(r: AgentRequest) -> str:
    return prompts.news_analyst(r.ticker, r.trade_date, akshare_md=r.akshare_md)


def _build_sentiment(r: AgentRequest) -> str:
    return prompts.sentiment_analyst(r.ticker, r.trade_date, akshare_md=r.akshare_md)


def _build_catalyst(r: AgentRequest) -> str:
    rp = r.reports
    return prompts.catalyst_agent(
        r.ticker,
        news_report=rp.get("news_report", ""),
        fundamentals_report=rp.get("fundamentals_report", ""),
        market_report=rp.get("market_report", ""),
        sentiment_report=rp.get("sentiment_report", ""),
        evidence_block=r.evidence_block,
        current_date=r.trade_date,
    )


def _build_bull(r: AgentRequest) -> str:
    rp = r.reports
    return prompts.bull_researcher(
        r.ticker,
        market_report=rp.get("market_report", ""),
        sentiment_report=rp.get("sentiment_report", ""),
        news_report=rp.get("news_report", ""),
        fundamentals_report=rp.get("fundamentals_report", ""),
        debate_history=r.debate_history,
        last_bear_argument=r.last_opponent_argument,
        evidence_block=r.evidence_block,
        current_date=r.trade_date,
    )


def _build_bear(r: AgentRequest) -> str:
    rp = r.reports
    return prompts.bear_researcher(
        r.ticker,
        market_report=rp.get("market_report", ""),
        sentiment_report=rp.get("sentiment_report", ""),
        news_report=rp.get("news_report", ""),
        fundamentals_report=rp.get("fundamentals_report", ""),
        debate_history=r.debate_history,
        last_bull_argument=r.last_opponent_argument,
        evidence_block=r.evidence_block,
        current_date=r.trade_date,
    )


def _build_scenario(r: AgentRequest) -> str:
    rp = r.reports
    return prompts.scenario_agent(
        r.ticker,
        bull_history=rp.get("bull_merged", ""),
        bear_history=rp.get("bear_merged", ""),
        evidence_block=r.evidence_block,
        current_date=r.trade_date,
    )


def _build_research_manager(r: AgentRequest) -> str:
    rp = r.reports
    return prompts.research_manager(
        r.ticker,
        debate_input=r.debate_history or rp.get("debate_input", ""),
        evidence_block=r.evidence_block,
        scenario_block=rp.get("scenario_output", ""),
        market_context_block=r.market_context_block,
        current_date=r.trade_date,
    )


def _build_aggressive(r: AgentRequest) -> str:
    rp = r.reports
    return prompts.aggressive_debator(
        research_conclusion=rp.get("research_manager", ""),
        market_report=rp.get("market_report", ""),
        sentiment_report=rp.get("sentiment_report", ""),
        news_report=rp.get("news_report", ""),
        fundamentals_report=rp.get("fundamentals_report", ""),
        evidence_block=r.evidence_block,
        current_date=r.trade_date,
    )


def _build_conservative(r: AgentRequest) -> str:
    rp = r.reports
    return prompts.conservative_debator(
        research_conclusion=rp.get("research_manager", ""),
        market_report=rp.get("market_report", ""),
        sentiment_report=rp.get("sentiment_report", ""),
        news_report=rp.get("news_report", ""),
        fundamentals_report=rp.get("fundamentals_report", ""),
        evidence_block=r.evidence_block,
        current_date=r.trade_date,
    )


def _build_neutral(r: AgentRequest) -> str:
    rp = r.reports
    return prompts.neutral_debator(
        research_conclusion=rp.get("research_manager", ""),
        market_report=rp.get("market_report", ""),
        sentiment_report=rp.get("sentiment_report", ""),
        news_report=rp.get("news_report", ""),
        fundamentals_report=rp.get("fundamentals_report", ""),
        evidence_block=r.evidence_block,
        current_date=r.trade_date,
    )


def _build_risk_manager(r: AgentRequest) -> str:
    rp = r.reports
    return prompts.risk_manager(
        company_name=r.ticker_name or r.ticker,
        trader_plan=rp.get("research_manager", ""),
        risk_debate_history=rp.get("risk_debate_history", ""),
        evidence_block=r.evidence_block,
        market_context_block=r.market_context_block,
        current_date=r.trade_date,
    )


def _build_research_output(r: AgentRequest) -> str:
    rp = r.reports
    return prompts.research_output(
        company_name=r.ticker_name or r.ticker,
        investment_plan=rp.get("investment_plan", ""),
        current_date=r.trade_date,
        ticker=r.ticker,
        akshare_md=r.akshare_md,
    )


# ── Registry ─────────────────────────────────────────────────────────────


def _build_registry() -> Dict[str, AgentSpec]:
    """Build the agent registry from existing config mappings."""
    models = PIPELINE_CONFIG.get("models", {})

    entries = [
        # Market layer
        ("macro_analyst",        _build_macro,            TAG_MACRO_OUTPUT,          "market_layer"),
        ("market_breadth_agent", _build_breadth,          TAG_BREADTH_OUTPUT,        "market_layer"),
        ("sector_rotation_agent", _build_sector,          TAG_SECTOR_OUTPUT,         "market_layer"),
        # Analysts
        ("market_analyst",       _build_market_analyst,   "",                        "analyst"),
        ("fundamentals_analyst", _build_fundamentals,     "",                        "analyst"),
        ("news_analyst",         _build_news,             "",                        "analyst"),
        ("sentiment_analyst",    _build_sentiment,        "",                        "analyst"),
        # Pipeline
        ("catalyst_agent",       _build_catalyst,         TAG_CATALYST_OUTPUT,       "catalyst"),
        ("bull_researcher",      _build_bull,             "",                        "debate"),
        ("bear_researcher",      _build_bear,             "",                        "debate"),
        ("scenario_agent",       _build_scenario,         "",                        "scenario"),
        ("research_manager",     _build_research_manager, TAG_SYNTHESIS_OUTPUT,      "synthesis"),
        # Risk
        ("aggressive_debator",   _build_aggressive,       TAG_RISK_DEBATER_OUTPUT,   "risk"),
        ("conservative_debator", _build_conservative,     TAG_RISK_DEBATER_OUTPUT,   "risk"),
        ("neutral_debator",      _build_neutral,          TAG_RISK_DEBATER_OUTPUT,   "risk"),
        ("risk_manager",         _build_risk_manager,     TAG_RISK_OUTPUT,           "risk"),
        # Output
        ("research_output",      _build_research_output,  TAG_TRADECARD_JSON,        "output"),
    ]

    registry = {}
    for name, builder, tag, category in entries:
        registry[name] = AgentSpec(
            name=name,
            node_name=AGENT_NODE_MAP.get(name, name),
            seq=AGENT_SEQ.get(name, 99),
            model=models.get(name, "sonnet"),
            output_tag=tag,
            prompt_builder=builder,
            category=category,
        )
    return registry


AGENT_REGISTRY: Dict[str, AgentSpec] = _build_registry()


# ── Public API ───────────────────────────────────────────────────────────


def agent_spec(agent_name: str) -> AgentSpec:
    """Look up an agent's spec. Raises KeyError if not found."""
    if agent_name not in AGENT_REGISTRY:
        raise KeyError(
            f"Unknown agent: {agent_name!r}. "
            f"Available: {sorted(AGENT_REGISTRY)}"
        )
    return AGENT_REGISTRY[agent_name]


def build_prompt(request: AgentRequest) -> str:
    """Build the prompt string for an agent from a unified request."""
    spec = agent_spec(request.agent_name)
    return spec.prompt_builder(request)


def parse_output(agent_name: str, raw_text: str, run_id: str = "") -> AgentResult:
    """Parse raw LLM output into a structured AgentResult.

    Delegates to bridge.build_node_trace() for the actual parsing,
    then wraps in an AgentResult.
    """
    spec = agent_spec(agent_name)
    nt = build_node_trace(agent_name, raw_text, run_id=run_id, seq=spec.seq)
    return AgentResult(
        agent_name=agent_name,
        raw_text=raw_text,
        node_name=spec.node_name,
        model=spec.model,
        seq=spec.seq,
        output_tag=spec.output_tag,
    )


def list_agents(category: str = "") -> List[str]:
    """List registered agent names, optionally filtered by category."""
    if not category:
        return sorted(AGENT_REGISTRY)
    return sorted(n for n, s in AGENT_REGISTRY.items() if s.category == category)

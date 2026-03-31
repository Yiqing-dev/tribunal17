"""Pipeline configuration for subagent execution."""

from datetime import date


# ── Model name mapping ──────────────────────────────────────────────────
# Short names used in PIPELINE_CONFIG → full Claude Code Agent model param
MODEL_MAP = {
    "haiku":  "haiku",                  # claude-haiku-4-5
    "sonnet": "sonnet",                 # claude-sonnet-4-6
    "opus":   "opus",                   # claude-opus-4-6
}


def _today() -> str:
    """Return today's date as YYYY-MM-DD string."""
    return date.today().isoformat()


# Default pipeline config — override per-run as needed
PIPELINE_CONFIG = {
    # Target
    "ticker": "601985",
    "ticker_name": "中国核电",
    "current_date": "",                  # callers must set explicitly; use _today() as utility

    # Market
    "market": "CN_A",
    "currency": "CNY",
    "language": "Chinese",

    # Capital / Risk
    "mode": "STANDARD",
    "capital": 200_000,
    "max_single_pct": 0.05,
    "max_dd": 0.06,

    # Debate rounds
    "bull_bear_rounds": 2,     # number of Bull/Bear debate rounds
    "risk_debate_rounds": 1,   # number of Aggressive/Conservative/Neutral rounds

    # Trend override: auto-downgrade pillar scores when recent trend is strongly negative
    "trend_override_window": 5,        # trading days to measure
    "trend_override_threshold": -0.05, # return below this triggers downgrade
    "trend_override_downgrade": 1,     # points to subtract from each pillar_score

    # Model assignments per stage (short names from MODEL_MAP)
    "models": {
        # Stage 0.8: Market Agents (parallel, once per day)
        "macro_analyst": "sonnet",
        "market_breadth_agent": "sonnet",
        "sector_rotation_agent": "sonnet",
        # Stage 0.5: Data Verification (FAIL → stop pipeline)
        "verification_agent": "sonnet",
        # Stage 1: Analysts (parallel, fast)
        "market_analyst": "sonnet",
        "fundamentals_analyst": "sonnet",
        "news_analyst": "sonnet",
        "sentiment_analyst": "sonnet",
        # Stage 2: Researchers (parallel per round)
        "catalyst_agent": "sonnet",
        "bull_researcher": "sonnet",
        "bear_researcher": "sonnet",
        # Stage 3: Scenario
        "scenario_agent": "sonnet",
        # Stage 4: PM (needs deeper reasoning)
        "research_manager": "opus",
        # Stage 5: Risk debate (parallel per round)
        "aggressive_debator": "sonnet",
        "conservative_debator": "sonnet",
        "neutral_debator": "sonnet",
        # Stage 6: Risk Judge
        "risk_manager": "opus",
        # Stage 7: Output
        "research_output": "sonnet",
    },
}


# Full pipeline execution order
# Stages marked (parallel) can be launched simultaneously
PIPELINE_STAGES = [
    {
        "stage": 0,
        "name": "Data Collection",
        "parallel": False,
        "agents": ["akshare_collector"],
        "description": "Collect ALL structured data via akshare APIs (Python, no LLM)",
    },
    {
        "stage": 0.5,
        "name": "Data Verification",
        "parallel": False,
        "agents": ["verification_agent"],
        "depends_on": [0],
        "description": "WebSearch cross-check of akshare data; FAIL → stop pipeline",
    },
    {
        "stage": 0.8,
        "name": "Market Agents",
        "parallel": True,
        "run_once_per_day": True,
        "agents": [
            "macro_analyst",
            "market_breadth_agent",
            "sector_rotation_agent",
        ],
        "depends_on": [0],
        "description": "Market-level regime, breadth, and sector rotation (once per day)",
    },
    {
        "stage": 1,
        "name": "Analysts",
        "parallel": True,
        "agents": [
            "market_analyst",
            "fundamentals_analyst",
            "news_analyst",
            "sentiment_analyst",
        ],
        "depends_on": [0.8],
        "description": "4 analysts receive akshare data (primary) + WebSearch (supplementary) and produce pillar_score reports",
    },
    {
        "stage": 2,
        "name": "Catalyst Agent",
        "parallel": False,
        "agents": ["catalyst_agent"],
        "depends_on": [1],
        "description": "Extract forward-looking catalysts from analyst reports",
    },
    {
        "stage": 3,
        "name": "Bull/Bear Debate",
        "parallel": True,
        "agents": ["bull_researcher", "bear_researcher"],
        "depends_on": [1],
        "rounds": "bull_bear_rounds",
        "description": "Multi-round structured debate with evidence protocol",
    },
    {
        "stage": 4,
        "name": "Scenario Agent",
        "parallel": False,
        "agents": ["scenario_agent"],
        "depends_on": [3],
        "description": "Probabilistic scenario tree from debate output",
    },
    {
        "stage": 5,
        "name": "Research Manager",
        "parallel": False,
        "agents": ["research_manager"],
        "depends_on": [2, 3, 4],
        "description": "PM synthesizes all inputs into actionable decision",
    },
    {
        "stage": 6,
        "name": "Risk Debate",
        "parallel": True,
        "agents": [
            "aggressive_debator",
            "conservative_debator",
            "neutral_debator",
        ],
        "depends_on": [5],
        "rounds": "risk_debate_rounds",
        "description": "3-way risk debate: aggressive vs conservative vs neutral",
    },
    {
        "stage": 7,
        "name": "Risk Judge",
        "parallel": False,
        "agents": ["risk_manager"],
        "depends_on": [5, 6],
        "description": "Risk Control Officer with VETO power (R1-R4 framework)",
    },
    {
        "stage": 8,
        "name": "Research Output",
        "parallel": False,
        "agents": ["research_output"],
        "depends_on": [7],
        "description": "Final trade card + order proposal generation",
    },
]


def validate_pipeline_config() -> None:
    """Validate PIPELINE_STAGES DAG and model assignments are consistent.

    Raises ValueError on misconfiguration. Called at import time.
    """
    stage_ids = {s["stage"] for s in PIPELINE_STAGES}
    models = PIPELINE_CONFIG["models"]
    all_stage_agents = set()

    for s in PIPELINE_STAGES:
        # Check depends_on references exist
        for dep in s.get("depends_on", []):
            if dep not in stage_ids:
                raise ValueError(
                    f"Pipeline stage {s['stage']} ({s['name']}) depends on "
                    f"non-existent stage {dep}"
                )
        for agent in s.get("agents", []):
            all_stage_agents.add(agent)

    # Agents in stages but not in models are non-LLM (e.g. akshare_collector)
    non_llm_agents = all_stage_agents - set(models.keys())

    # Check every agent in models has a corresponding pipeline stage
    for agent in models:
        if agent not in all_stage_agents:
            raise ValueError(
                f"Model assigned to agent '{agent}' but it has no pipeline stage"
            )


validate_pipeline_config()

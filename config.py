"""Pipeline configuration for subagent execution."""

import os
from dataclasses import dataclass
from datetime import date


def _today() -> str:
    """Return today's date as YYYY-MM-DD string."""
    # Naming: underscore prefix indicates internal utility; CLAUDE.md references it for caller convenience.
    return date.today().isoformat()


@dataclass(frozen=True)
class PipelineRunConfig:
    """Immutable per-run configuration. Thread-safe — each run gets its own instance.

    Use ``PipelineRunConfig.from_defaults(current_date="2026-04-02")`` to create
    with overrides from PIPELINE_CONFIG defaults.
    """
    current_date: str = ""
    ticker: str = ""
    ticker_name: str = ""
    market: str = "CN_A"
    currency: str = "CNY"
    language: str = "Chinese"
    mode: str = "STANDARD"
    capital: float = 200_000
    max_single_pct: float = 0.05
    max_dd: float = 0.06
    bull_bear_rounds: int = 2
    risk_debate_rounds: int = 1
    trend_override_window: int = 5
    trend_override_threshold: float = -0.05
    trend_override_downgrade: int = 1

    @classmethod
    def from_defaults(cls, **overrides) -> "PipelineRunConfig":
        """Create from PIPELINE_CONFIG defaults with optional overrides."""
        defaults = {k: v for k, v in PIPELINE_CONFIG.items()
                    if k in cls.__dataclass_fields__}
        defaults.update(overrides)
        return cls(**{k: v for k, v in defaults.items()
                      if k in cls.__dataclass_fields__})

    @classmethod
    def from_env(cls, **overrides) -> "PipelineRunConfig":
        """Create from environment variables (TA_*) with fallback to PIPELINE_CONFIG.

        Env var mapping (all optional):
            TA_TRADE_DATE          → current_date
            TA_TICKER              → ticker
            TA_TICKER_NAME         → ticker_name
            TA_MARKET              → market
            TA_CURRENCY            → currency
            TA_LANGUAGE            → language
            TA_MODE                → mode
            TA_CAPITAL             → capital (float)
            TA_MAX_SINGLE_PCT      → max_single_pct (float)
            TA_MAX_DD              → max_dd (float)
            TA_BULL_BEAR_ROUNDS    → bull_bear_rounds (int)
            TA_RISK_DEBATE_ROUNDS  → risk_debate_rounds (int)
            TA_TREND_WINDOW        → trend_override_window (int)
            TA_TREND_THRESHOLD     → trend_override_threshold (float)
            TA_TREND_DOWNGRADE     → trend_override_downgrade (int)

        Model overrides (per-agent):
            TA_MODEL_DEFAULT       → default model for all agents
            TA_MODEL_{AGENT_NAME}  → per-agent override (uppercase, e.g. TA_MODEL_RESEARCH_MANAGER)

        Feature flags:
            TA_CACHE_ENABLED       → "true"/"false" (read by data_cache, not stored here)
            TA_STRICT_DATE_CHECK   → "true"/"false" (read by callers, not stored here)
            TA_API_MIN_INTERVAL    → float seconds (read by akshare_collector throttle)
        """
        # Start from PIPELINE_CONFIG defaults
        defaults = {k: v for k, v in PIPELINE_CONFIG.items()
                    if k in cls.__dataclass_fields__}

        # Env var → field mapping
        _ENV_MAP = {
            "TA_TRADE_DATE": ("current_date", str),
            "TA_TICKER": ("ticker", str),
            "TA_TICKER_NAME": ("ticker_name", str),
            "TA_MARKET": ("market", str),
            "TA_CURRENCY": ("currency", str),
            "TA_LANGUAGE": ("language", str),
            "TA_MODE": ("mode", str),
            "TA_CAPITAL": ("capital", float),
            "TA_MAX_SINGLE_PCT": ("max_single_pct", float),
            "TA_MAX_DD": ("max_dd", float),
            "TA_BULL_BEAR_ROUNDS": ("bull_bear_rounds", int),
            "TA_RISK_DEBATE_ROUNDS": ("risk_debate_rounds", int),
            "TA_TREND_WINDOW": ("trend_override_window", int),
            "TA_TREND_THRESHOLD": ("trend_override_threshold", float),
            "TA_TREND_DOWNGRADE": ("trend_override_downgrade", int),
        }

        for env_key, (field_name, cast) in _ENV_MAP.items():
            val = os.environ.get(env_key)
            if val is not None:
                try:
                    defaults[field_name] = cast(val)
                except (ValueError, TypeError):
                    pass  # ignore unparseable env values, keep default

        # Apply explicit overrides last (highest priority)
        defaults.update(overrides)
        cfg = cls(**{k: v for k, v in defaults.items()
                     if k in cls.__dataclass_fields__})

        # Apply model overrides to PIPELINE_CONFIG["models"] (side effect)
        _apply_model_env_overrides()

        return cfg


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

    # Model assignments per stage
    "models": {
        # Stage 0.8: Market Agents (parallel, once per day)
        "macro_analyst": "sonnet",
        "market_breadth_agent": "sonnet",
        "sector_rotation_agent": "sonnet",
        # Stage 0.5: Data Verification (FAIL → stop pipeline)
        # Note: verification_agent uses verification.py (verification_prompt +
        # parse_verification_result) directly, not prompts.py.
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


def _apply_model_env_overrides() -> None:
    """Apply TA_MODEL_* env vars to PIPELINE_CONFIG["models"].

    TA_MODEL_DEFAULT overrides all agents.
    TA_MODEL_{AGENT_NAME} overrides a specific agent (takes precedence).
    """
    models = PIPELINE_CONFIG.get("models", {})
    default_model = os.environ.get("TA_MODEL_DEFAULT")
    if default_model:
        for name in models:
            models[name] = default_model

    for name in list(models):
        env_key = f"TA_MODEL_{name.upper()}"
        val = os.environ.get(env_key)
        if val:
            models[name] = val


def get_env_bool(key: str, default: bool = False) -> bool:
    """Read a boolean env var (true/1/yes → True, else default)."""
    val = os.environ.get(key, "").strip().lower()
    if val in ("true", "1", "yes"):
        return True
    if val in ("false", "0", "no"):
        return False
    return default


def get_env_float(key: str, default: float = 0.0) -> float:
    """Read a float env var with fallback."""
    val = os.environ.get(key)
    if val is not None:
        try:
            return float(val)
        except ValueError:
            pass
    return default


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
        "stage": 5,
        "name": "Data Verification",
        "parallel": False,
        "agents": ["verification_agent"],
        "depends_on": [0],
        "description": "WebSearch cross-check of akshare data; FAIL → stop pipeline",
    },
    {
        "stage": 8,
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
        "stage": 10,
        "name": "Analysts",
        "parallel": True,
        "agents": [
            "market_analyst",
            "fundamentals_analyst",
            "news_analyst",
            "sentiment_analyst",
        ],
        "depends_on": [8],
        "description": "4 analysts receive akshare data (primary) + WebSearch (supplementary) and produce pillar_score reports",
    },
    {
        "stage": 20,
        "name": "Catalyst Agent",
        "parallel": False,
        "agents": ["catalyst_agent"],
        "depends_on": [10],
        "description": "Extract forward-looking catalysts from analyst reports",
    },
    {
        "stage": 30,
        "name": "Bull/Bear Debate",
        "parallel": True,
        "agents": ["bull_researcher", "bear_researcher"],
        "depends_on": [10],
        "rounds": "bull_bear_rounds",
        "description": "Multi-round structured debate with evidence protocol",
    },
    {
        "stage": 40,
        "name": "Scenario Agent",
        "parallel": False,
        "agents": ["scenario_agent"],
        "depends_on": [30],
        "description": "Probabilistic scenario tree from debate output",
    },
    {
        "stage": 50,
        "name": "Research Manager",
        "parallel": False,
        "agents": ["research_manager"],
        "depends_on": [20, 30, 40],
        "description": "PM synthesizes all inputs into actionable decision",
    },
    {
        "stage": 60,
        "name": "Risk Debate",
        "parallel": True,
        "agents": [
            "aggressive_debator",
            "conservative_debator",
            "neutral_debator",
        ],
        "depends_on": [50],
        "rounds": "risk_debate_rounds",
        "description": "3-way risk debate: aggressive vs conservative vs neutral",
    },
    {
        "stage": 70,
        "name": "Risk Judge",
        "parallel": False,
        "agents": ["risk_manager"],
        "depends_on": [50, 60],
        "description": "Risk Control Officer with VETO power (R1-R4 framework)",
    },
    {
        "stage": 80,
        "name": "Research Output",
        "parallel": False,
        "agents": ["research_output"],
        "depends_on": [70],
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

    # Check every agent in models has a corresponding pipeline stage
    _KNOWN_MODELS = {"sonnet", "opus", "haiku"}
    for agent in models:
        if agent not in all_stage_agents:
            raise ValueError(
                f"Model assigned to agent '{agent}' but it has no pipeline stage"
            )
        if models[agent] not in _KNOWN_MODELS:
            import warnings
            warnings.warn(
                f"Agent '{agent}' uses model '{models[agent]}' not in "
                f"known set {sorted(_KNOWN_MODELS)}; may be intentional for custom providers",
                stacklevel=2,
            )

    # Cycle detection (topological sort attempt)
    dep_map = {s["stage"]: set(s.get("depends_on", [])) for s in PIPELINE_STAGES}
    visited: set = set()
    temp: set = set()
    def _visit(node):
        if node in temp:
            raise ValueError(f"Cycle detected in pipeline DAG involving stage {node}")
        if node in visited:
            return
        temp.add(node)
        for dep in dep_map.get(node, []):
            _visit(dep)
        temp.remove(node)
        visited.add(node)
    for s in dep_map:
        _visit(s)


# Run validation at import time — warn instead of crashing so that
# simple imports (e.g. `from .config import _today`) still work even
# if PIPELINE_STAGES has a temporary misconfiguration.
try:
    validate_pipeline_config()
except ValueError as _e:
    import warnings as _w
    _w.warn(f"Pipeline config validation failed: {_e}", stacklevel=1)

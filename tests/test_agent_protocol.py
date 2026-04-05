"""Tests for agent_protocol.py — unified agent interface.

Covers:
1. AGENT_REGISTRY completeness — all 17 agents registered
2. AgentSpec fields — model, seq, node_name populated correctly
3. build_prompt — produces non-empty string for each agent
4. parse_output — returns AgentResult
5. list_agents — all and filtered by category
6. Unknown agent — KeyError
7. AgentRequest → prompt builder integration
"""

import sys
import pytest
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from subagent_pipeline.agent_protocol import (
    AgentRequest, AgentResult, AgentSpec,
    AGENT_REGISTRY, agent_spec, build_prompt, parse_output, list_agents,
)
from subagent_pipeline.bridge import AGENT_NODE_MAP, AGENT_SEQ
from subagent_pipeline.config import PIPELINE_CONFIG


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  1. Registry Completeness                                           ║
# ╚══════════════════════════════════════════════════════════════════════╝


class TestRegistryCompleteness:

    def test_all_17_agents_registered(self):
        assert len(AGENT_REGISTRY) == 17

    def test_all_node_map_agents_present(self):
        # Every agent in AGENT_NODE_MAP (except verification_agent) should be in registry
        for name in AGENT_NODE_MAP:
            if name == "verification_agent":
                continue  # uses verification.py, not prompts.py
            assert name in AGENT_REGISTRY, f"{name} missing from AGENT_REGISTRY"

    def test_all_model_agents_present(self):
        models = PIPELINE_CONFIG.get("models", {})
        for name in models:
            if name == "verification_agent":
                continue
            assert name in AGENT_REGISTRY, f"{name} has model but no registry entry"


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  2. AgentSpec Fields                                                ║
# ╚══════════════════════════════════════════════════════════════════════╝


class TestAgentSpec:

    def test_node_name_matches_bridge(self):
        for name, spec in AGENT_REGISTRY.items():
            expected = AGENT_NODE_MAP.get(name, name)
            assert spec.node_name == expected, f"{name}: {spec.node_name} != {expected}"

    def test_seq_matches_bridge(self):
        for name, spec in AGENT_REGISTRY.items():
            expected = AGENT_SEQ.get(name, 99)
            assert spec.seq == expected, f"{name}: seq {spec.seq} != {expected}"

    def test_model_matches_config(self):
        models = PIPELINE_CONFIG.get("models", {})
        for name, spec in AGENT_REGISTRY.items():
            expected = models.get(name, "sonnet")
            assert spec.model == expected, f"{name}: model {spec.model} != {expected}"

    def test_opus_agents(self):
        opus = [n for n, s in AGENT_REGISTRY.items() if s.model == "opus"]
        assert "research_manager" in opus
        assert "risk_manager" in opus

    def test_every_spec_has_category(self):
        for name, spec in AGENT_REGISTRY.items():
            assert spec.category, f"{name} has no category"

    def test_frozen(self):
        spec = agent_spec("market_analyst")
        with pytest.raises(AttributeError):
            spec.model = "gpt-5"


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  3. build_prompt                                                    ║
# ╚══════════════════════════════════════════════════════════════════════╝


class TestBuildPrompt:

    def _req(self, agent_name: str, **kw) -> AgentRequest:
        defaults = dict(
            ticker="601985", ticker_name="中国核电", trade_date="2026-04-04",
            akshare_md="# mock data", market_snapshot_md="# market snapshot",
            market_context_block="regime=RISK_ON", evidence_block="[E1] test",
            reports={
                "market_report": "mock market",
                "fundamentals_report": "mock fundamentals",
                "news_report": "mock news",
                "sentiment_report": "mock sentiment",
                "bull_merged": "mock bull",
                "bear_merged": "mock bear",
                "scenario_output": "mock scenario",
                "research_manager": "mock pm conclusion",
                "risk_debate_history": "mock risk debate",
                "investment_plan": "mock investment plan",
                "debate_input": "mock debate input",
            },
        )
        defaults.update(kw)
        return AgentRequest(agent_name=agent_name, **defaults)

    @pytest.mark.parametrize("agent_name", sorted(AGENT_REGISTRY.keys()))
    def test_all_agents_produce_nonempty_prompt(self, agent_name):
        req = self._req(agent_name)
        prompt = build_prompt(req)
        assert isinstance(prompt, str)
        assert len(prompt) > 50, f"{agent_name} prompt too short: {len(prompt)} chars"

    def test_market_analyst_includes_context_block(self):
        req = self._req("market_analyst", market_context_block="REGIME: RISK_ON")
        prompt = build_prompt(req)
        assert "RISK_ON" in prompt

    def test_bull_includes_evidence(self):
        req = self._req("bull_researcher", evidence_block="[E1] ROE=12%")
        prompt = build_prompt(req)
        assert "[E1]" in prompt

    def test_research_manager_includes_market_context(self):
        req = self._req("research_manager", market_context_block="宏观利好")
        prompt = build_prompt(req)
        assert "宏观利好" in prompt


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  4. parse_output                                                    ║
# ╚══════════════════════════════════════════════════════════════════════╝


class TestParseOutput:

    def test_returns_agent_result(self):
        result = parse_output("market_analyst", "pillar_score = 3\nSome analysis...", run_id="run-test")
        assert isinstance(result, AgentResult)
        assert result.agent_name == "market_analyst"
        assert result.node_name == "Market Analyst"
        assert result.model == "sonnet"

    def test_ok_with_text(self):
        result = parse_output("market_analyst", "Some output", run_id="run-test")
        assert result.ok()

    def test_not_ok_with_empty_text(self):
        result = parse_output("market_analyst", "", run_id="run-test")
        assert not result.ok()


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  5. list_agents                                                     ║
# ╚══════════════════════════════════════════════════════════════════════╝


class TestListAgents:

    def test_all_agents(self):
        all_agents = list_agents()
        assert len(all_agents) == 17

    def test_filter_by_category(self):
        analysts = list_agents("analyst")
        assert "market_analyst" in analysts
        assert "fundamentals_analyst" in analysts
        assert len(analysts) == 4

    def test_market_layer(self):
        market = list_agents("market_layer")
        assert len(market) == 3

    def test_risk(self):
        risk = list_agents("risk")
        assert len(risk) == 4  # 3 debators + risk_manager

    def test_empty_category_returns_empty(self):
        assert list_agents("nonexistent") == []


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  6. Error Handling                                                  ║
# ╚══════════════════════════════════════════════════════════════════════╝


class TestErrorHandling:

    def test_unknown_agent_raises(self):
        with pytest.raises(KeyError, match="Unknown agent"):
            agent_spec("nonexistent_agent")

    def test_unknown_agent_build_prompt_raises(self):
        req = AgentRequest(agent_name="nonexistent_agent")
        with pytest.raises(KeyError):
            build_prompt(req)

    def test_unknown_agent_parse_raises(self):
        with pytest.raises(KeyError):
            parse_output("nonexistent_agent", "text")

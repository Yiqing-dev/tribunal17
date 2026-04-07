"""Tests for AI Investment Committee — debate_view + debate_renderer."""

import pytest

pytest.importorskip("dashboard", reason="dashboard package not installed")

from dashboard.debate_view import (
    DebateView,
    ParticipantView,
    ClaimView,
    TimelineEntry,
    DebateRound,
    VerdictView,
    COMMITTEE_ROSTER,
    STANCE_LABELS,
    ACTION_LABELS,
    build_debate_view,
    build_demo_debate_view,
    _stance_for_agent,
    _one_line_summary,
    _position_label,
)
from dashboard.debate_renderer import (
    render_debate_page,
    generate_committee_report,
    _esc,
    _render_hero,
    _render_timeline,
    _render_arena,
    _render_controversies,
    _render_verdict,
    _render_audit,
    _render_market_wind,
)


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  Data contract tests                                                   ║
# ╚══════════════════════════════════════════════════════════════════════════╝


class TestConstants:
    """Verify all constant mappings are consistent."""

    def test_committee_roster_has_11_members(self):
        assert len(COMMITTEE_ROSTER) == 11

    def test_roster_all_fields(self):
        for key, (cn, en, avatar, phase) in COMMITTEE_ROSTER.items():
            assert cn, f"{key} missing Chinese role"
            assert en, f"{key} missing English role"
            assert avatar.startswith("avatar-"), f"{key} bad avatar: {avatar}"
            assert phase, f"{key} missing phase"

    def test_stance_labels_coverage(self):
        expected = {"bullish", "bearish", "neutral", "cautious", "aggressive",
                    "conservative", "balanced"}
        assert set(STANCE_LABELS.keys()) == expected

    def test_action_labels_coverage(self):
        assert set(ACTION_LABELS.keys()) == {"BUY", "HOLD", "SELL", "VETO"}

    def test_action_labels_have_class(self):
        for k, (label, css) in ACTION_LABELS.items():
            assert label
            assert css.startswith("action-")


class TestHelpers:
    """Test helper functions."""

    def test_stance_for_bull(self):
        assert _stance_for_agent("bull_researcher", {}) == "bullish"

    def test_stance_for_bear(self):
        assert _stance_for_agent("bear_researcher", {}) == "bearish"

    def test_stance_for_neutral_debator(self):
        assert _stance_for_agent("neutral_debator", {}) == "neutral"

    def test_stance_from_pillar_score_high(self):
        assert _stance_for_agent("fundamentals_analyst", {"pillar_score": 2}) == "bullish"

    def test_stance_from_pillar_score_zero(self):
        assert _stance_for_agent("fundamentals_analyst", {"pillar_score": 0}) == "bearish"

    def test_stance_from_action_buy(self):
        assert _stance_for_agent("research_manager", {"research_action": "BUY"}) == "bullish"

    def test_stance_from_action_sell(self):
        assert _stance_for_agent("risk_manager", {"research_action": "SELL"}) == "bearish"

    def test_stance_default_neutral(self):
        assert _stance_for_agent("sentiment_analyst", {}) == "neutral"

    def test_one_line_summary_conclusion(self):
        sd = {"conclusion": "This is the conclusion."}
        assert _one_line_summary("research_manager", sd, "") == "This is the conclusion."

    def test_one_line_summary_claims(self):
        sd = {"supporting_claims": [{"text": "Claim one text here"}]}
        assert _one_line_summary("bull_researcher", sd, "") == "Claim one text here"

    def test_one_line_summary_excerpt(self):
        assert "hello" in _one_line_summary("news_analyst", {}, "hello world。rest")

    def test_one_line_summary_empty(self):
        assert _one_line_summary("news_analyst", {}, "") == ""

    def test_position_label_xiqing(self):
        assert _position_label(0.01) == "极轻仓"

    def test_position_label_light(self):
        assert _position_label(0.025) == "轻仓"

    def test_position_label_medium(self):
        assert _position_label(0.04) == "中仓"

    def test_position_label_heavy(self):
        assert _position_label(0.08) == "重仓"


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  Demo fixture tests                                                    ║
# ╚══════════════════════════════════════════════════════════════════════════╝


class TestDemoFixture:
    """Verify demo fixture is complete and self-consistent."""

    @pytest.fixture
    def demo(self):
        return build_demo_debate_view()

    def test_ticker(self, demo):
        assert demo.ticker == "601985.SS"
        assert demo.ticker_name == "中国核电"

    def test_participants_count(self, demo):
        assert len(demo.participants) == 11

    def test_all_participants_contributed(self, demo):
        for p in demo.participants:
            assert p.contributed

    def test_all_participants_have_stance(self, demo):
        for p in demo.participants:
            assert p.stance in ("bullish", "bearish", "neutral")
            assert p.stance_label
            assert p.stance_class

    def test_rounds_count(self, demo):
        assert demo.total_rounds == 5
        assert len(demo.rounds) == 5

    def test_round_labels(self, demo):
        labels = [r.phase_label for r in demo.rounds]
        assert labels == ["初判", "多空辩论", "场景推演", "风控质疑", "最终裁决"]

    def test_round_1_has_4_analysts(self, demo):
        assert len(demo.rounds[0].entries) == 4

    def test_round_2_has_bull_bear(self, demo):
        r2 = demo.rounds[1]
        speakers = [e.speaker_cn for e in r2.entries]
        assert "多方研究员" in speakers
        assert "空方研究员" in speakers

    def test_round_4_has_3_risk(self, demo):
        assert len(demo.rounds[3].entries) == 3

    def test_bull_claims(self, demo):
        assert len(demo.bull_claims) == 3
        for c in demo.bull_claims:
            assert c.text
            assert c.confidence > 0
            assert c.strength > 0

    def test_bear_claims(self, demo):
        assert len(demo.bear_claims) == 3
        for c in demo.bear_claims:
            assert c.text
            assert c.confidence > 0

    def test_scores_consistent(self, demo):
        bs = sum(c.confidence for c in demo.bull_claims)
        brs = sum(c.confidence for c in demo.bear_claims)
        assert abs(demo.bull_score - bs) < 0.01
        assert abs(demo.bear_score - brs) < 0.01

    def test_bull_ratio_reasonable(self, demo):
        assert 30 < demo.bull_ratio < 70  # neither side dominates completely

    def test_controversies(self, demo):
        assert len(demo.controversies) >= 3
        for c in demo.controversies:
            assert len(c) > 5

    def test_verdict(self, demo):
        v = demo.verdict
        assert v.action == "BUY"
        assert v.action_label == "建议关注"
        assert v.confidence_pct == 72
        assert v.position_label == "中仓"
        assert v.trigger
        assert v.invalidator
        assert v.core_reason
        assert v.risk_score == 4
        assert v.risk_cleared is True
        assert len(v.risk_flags) == 2

    def test_market_context(self, demo):
        assert demo.market_regime == "RISK_ON"
        assert demo.market_regime_label == "进攻"
        assert demo.market_wind == "顺风"
        assert demo.market_wind_reason
        assert demo.market_weather
        assert "核电" in demo.sector_leaders
        assert "房地产" in demo.avoid_sectors
        assert demo.position_cap_multiplier == 1.0

    def test_audit(self, demo):
        assert demo.total_evidence == 11
        assert demo.total_claims == 6
        assert demo.conflict_level in ("high", "medium", "low")
        assert demo.consensus_level in ("high", "medium", "low")


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  Builder tests — build_debate_view from dict                           ║
# ╚══════════════════════════════════════════════════════════════════════════╝


class TestBuildFromDict:
    """Test build_debate_view with dict inputs (simulating JSON-loaded RunTrace)."""

    def _make_trace(self, nodes=None):
        return {
            "meta": {
                "run_id": "run-test-001",
                "ticker": "300627",
                "ticker_name": "华测导航",
                "trade_date": "2026-03-13",
            },
            "nodes": nodes or [],
        }

    def test_empty_nodes(self):
        v = build_debate_view(self._make_trace())
        assert v.ticker == "300627"
        assert v.total_rounds == 0
        assert len(v.participants) == 11
        for p in v.participants:
            assert not p.contributed  # no nodes

    def test_analyst_nodes_create_round_1(self):
        nodes = [
            {"node_name": "Market Analyst", "seq": 1,
             "structured_data": {"pillar_score": 2},
             "output_excerpt": "技术面看多", "parse_status": "strict_ok",
             "evidence_ids_referenced": ["E1"], "claim_ids_produced": []},
            {"node_name": "Fundamentals Analyst", "seq": 2,
             "structured_data": {"pillar_score": 1},
             "output_excerpt": "基本面中性", "parse_status": "strict_ok",
             "evidence_ids_referenced": ["E2"], "claim_ids_produced": []},
        ]
        v = build_debate_view(self._make_trace(nodes))
        assert v.total_rounds >= 1
        assert v.rounds[0].phase_label == "初判"
        assert len(v.rounds[0].entries) == 2

    def test_bull_bear_nodes_create_arena(self):
        nodes = [
            {"node_name": "Bull Researcher", "seq": 6,
             "structured_data": {"supporting_claims": [
                 {"claim_id": "clm-001", "text": "Revenue growing", "confidence": 0.8,
                  "dimension": "基本面", "supports": ["E1"]},
             ]},
             "output_excerpt": "", "parse_status": "strict_ok",
             "evidence_ids_referenced": ["E1"], "claim_ids_produced": ["clm-001"]},
            {"node_name": "Bear Researcher", "seq": 7,
             "structured_data": {"supporting_claims": [
                 {"claim_id": "clm-002", "text": "PE too high", "confidence": 0.7,
                  "dimension": "估值", "supports": ["E2"]},
             ]},
             "output_excerpt": "", "parse_status": "strict_ok",
             "evidence_ids_referenced": ["E2"], "claim_ids_produced": ["clm-002"]},
        ]
        v = build_debate_view(self._make_trace(nodes))
        assert len(v.bull_claims) == 1
        assert len(v.bear_claims) == 1
        assert v.bull_claims[0].text == "Revenue growing"
        assert v.bear_claims[0].text == "PE too high"
        assert v.bull_score > 0
        assert v.bear_score > 0

    def test_pm_creates_verdict(self):
        nodes = [
            {"node_name": "Research Manager", "seq": 9,
             "structured_data": {
                 "research_action": "BUY", "confidence": 0.75,
                 "conclusion": "值得关注", "bull_case": "突破前高",
                 "invalidation": "跌破支撑", "target_position_pct": 0.04,
                 "open_questions": ["估值是否已透支"],
             },
             "output_excerpt": "", "parse_status": "strict_ok",
             "evidence_ids_referenced": [], "claim_ids_produced": []},
        ]
        v = build_debate_view(self._make_trace(nodes))
        assert v.verdict.action == "BUY"
        assert v.verdict.confidence_pct == 75
        assert v.verdict.position_label == "中仓"
        assert "突破前高" in v.verdict.trigger
        assert "跌破支撑" in v.verdict.invalidator
        assert "估值是否已透支" in v.controversies

    def test_veto_overrides_buy(self):
        nodes = [
            {"node_name": "Research Manager", "seq": 9,
             "structured_data": {"research_action": "BUY", "confidence": 0.8},
             "output_excerpt": "", "parse_status": "strict_ok",
             "evidence_ids_referenced": [], "claim_ids_produced": []},
            {"node_name": "Risk Judge", "seq": 13,
             "structured_data": {
                 "research_action": "VETO", "risk_score": 2,
                 "risk_cleared": False,
                 "risk_flags": [{"category": "事件锁定", "severity": "high"}],
             },
             "output_excerpt": "", "parse_status": "strict_ok",
             "evidence_ids_referenced": [], "claim_ids_produced": []},
        ]
        v = build_debate_view(self._make_trace(nodes))
        assert v.verdict.action == "VETO"
        assert v.verdict.action_label == "风控否决"
        assert not v.verdict.risk_cleared
        assert v.verdict.was_vetoed

    def test_market_context_from_trace(self):
        """Market context in trace → populates wind fields."""
        trace = {
            "meta": {"run_id": "run-mkt", "ticker": "601985"},
            "market_context": {
                "regime": "RISK_OFF",
                "market_weather": "市场偏弱",
                "position_cap_multiplier": 0.5,
                "sector_leaders": ["半导体"],
                "avoid_sectors": ["房地产"],
            },
            "nodes": [
                {"node_name": "Research Manager", "seq": 9,
                 "structured_data": {"research_action": "BUY", "confidence": 0.7},
                 "output_excerpt": "", "parse_status": "strict_ok",
                 "evidence_ids_referenced": [], "claim_ids_produced": []},
            ],
        }
        v = build_debate_view(trace)
        assert v.market_regime == "RISK_OFF"
        assert v.market_regime_label == "防御"
        assert v.market_wind == "逆风"  # RISK_OFF + BUY = headwind
        assert v.position_cap_multiplier == 0.5
        assert "半导体" in v.sector_leaders
        assert "房地产" in v.avoid_sectors

    def test_no_market_context(self):
        """No market context → empty wind fields."""
        trace = {
            "meta": {"run_id": "run-nomkt", "ticker": "300627"},
            "nodes": [],
        }
        v = build_debate_view(trace)
        assert v.market_wind == ""
        assert v.market_regime == ""

    def test_to_dict_serialization(self):
        v = build_demo_debate_view()
        d = v.to_dict()
        assert isinstance(d, dict)
        assert "ticker" in d
        assert "rounds" in d
        assert "bull_claims" in d
        assert "verdict" in d
        assert "market_regime" in d
        assert "market_wind" in d
        assert len(d["participants"]) == 11


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  Renderer tests                                                        ║
# ╚══════════════════════════════════════════════════════════════════════════╝


class TestEscape:
    def test_html_entities(self):
        assert _esc('<script>alert("xss")</script>') == (
            '&lt;script&gt;alert(&quot;xss&quot;)&lt;/script&gt;'
        )

    def test_none(self):
        assert _esc(None) == ""

    def test_empty(self):
        assert _esc("") == ""


class TestRenderSections:
    """Verify each section renderer returns valid HTML with key content."""

    @pytest.fixture
    def demo(self):
        return build_demo_debate_view()

    def test_hero_contains_ticker(self, demo):
        html = _render_hero(demo)
        assert "中国核电" in html
        assert "601985" in html
        assert "投研委员会成员" in html

    def test_hero_roster_cards(self, demo):
        html = _render_hero(demo)
        assert "基本面分析师" in html
        assert "风控官" in html
        assert html.count("roster-card") == 11

    def test_timeline_has_5_rounds(self, demo):
        html = _render_timeline(demo)
        assert "Round 1" in html
        assert "Round 5" in html
        assert "初判" in html
        assert "最终裁决" in html

    def test_timeline_entries(self, demo):
        html = _render_timeline(demo)
        assert "基本面分析师" in html
        assert "多方研究员" in html
        assert "看多" in html
        assert "看空" in html

    def test_timeline_evidence_chips(self, demo):
        html = _render_timeline(demo)
        assert "ev-chip" in html
        assert "E1" in html

    def test_arena_bull_bear(self, demo):
        html = _render_arena(demo)
        assert "看多论据" in html
        assert "看空论据" in html
        assert "核电审批" in html
        assert "电价" in html

    def test_arena_strength_bar(self, demo):
        html = _render_arena(demo)
        assert "strength-bar" in html
        assert "strength-bull" in html
        assert "strength-bear" in html

    def test_arena_claim_confidence(self, demo):
        html = _render_arena(demo)
        assert "claim-conf-bar" in html
        assert "85%" in html  # bull claim 1

    def test_arena_invalidation(self, demo):
        html = _render_arena(demo)
        assert "失效条件" in html

    def test_controversies(self, demo):
        html = _render_controversies(demo)
        assert "分歧焦点" in html
        assert "估值" in html
        assert "电价" in html
        assert html.count("controversy-item") >= 3

    def test_verdict(self, demo):
        html = _render_verdict(demo)
        assert "投委会裁决" in html
        assert "建议关注" in html
        assert "72%" in html
        assert "中仓" in html
        assert "4/10" in html
        assert "通过" in html

    def test_verdict_conditions(self, demo):
        html = _render_verdict(demo)
        assert "确认买入信号" in html
        assert "放量突破" in html
        assert "失效" in html
        assert "跌破14日均线" in html

    def test_verdict_risk_flags(self, demo):
        html = _render_verdict(demo)
        assert "估值风险" in html
        assert "政策风险" in html

    def test_market_wind_section(self, demo):
        html = _render_market_wind(demo)
        assert "market-wind-card" in html
        assert "市场感知" in html
        assert "进攻" in html
        assert "RISK_ON" in html
        assert "顺风" in html
        assert "核电" in html     # sector leader chip
        assert "房地产" in html   # avoid sector chip

    def test_market_wind_headwind(self):
        v = DebateView(
            market_regime="RISK_OFF", market_regime_label="防御",
            market_wind="逆风", market_wind_reason="市场防御但个股看多",
        )
        html = _render_market_wind(v)
        assert "wind-headwind" in html
        assert "逆风" in html

    def test_market_wind_empty(self):
        v = DebateView()
        assert _render_market_wind(v) == ""

    def test_audit_section(self, demo):
        html = _render_audit(demo)
        assert "审计摘要" in html
        assert "讨论轮次" in html
        assert "发言次数" in html
        assert "论据总数" in html
        assert "证据引用" in html
        assert "分歧水平" in html
        assert "收敛状态" in html


class TestFullRender:
    """Test the complete page render."""

    @pytest.fixture
    def demo(self):
        return build_demo_debate_view()

    def test_full_page_structure(self, demo):
        html = render_debate_page(demo)
        assert html.startswith("<!DOCTYPE html>")
        assert "AI 生成内容" in html
        assert "debate-shell" in html
        assert "debate-hero" in html
        assert "market-wind-card" in html  # market wind section
        assert "debate-timeline" in html
        assert "arena-wrap" in html
        assert "controversy-list" in html
        assert "verdict-card" in html
        assert "audit-grid" in html
        assert "debate-footer" in html

    def test_page_title(self, demo):
        html = render_debate_page(demo)
        assert "<title>" in html
        assert "AI投研委员会" in html

    def test_css_inlined(self, demo):
        html = render_debate_page(demo)
        assert "<style>" in html
        assert "debate-hero" in html
        # No external CSS links
        assert '<link rel="stylesheet"' not in html

    def test_responsive_css(self, demo):
        html = render_debate_page(demo)
        assert "@media" in html
        assert "max-width: 700px" in html

    def test_page_size_reasonable(self, demo):
        html = render_debate_page(demo)
        assert 15_000 < len(html) < 100_000

    def test_no_script_injection(self, demo):
        """Verify HTML escaping prevents injection."""
        demo.ticker_name = '<script>alert("xss")</script>'
        html = render_debate_page(demo)
        assert '<script>alert' not in html
        assert '&lt;script&gt;' in html

    def test_empty_view_renders(self):
        """An empty DebateView should still produce valid HTML."""
        v = DebateView()
        html = render_debate_page(v)
        assert "<!DOCTYPE html>" in html
        assert "debate-footer" in html


class TestVerdictEdgeCases:
    """Edge cases for verdict rendering."""

    def test_veto_verdict(self):
        v = DebateView(
            verdict=VerdictView(
                action="VETO", action_label="风控否决", action_class="action-veto",
                confidence=0.0, confidence_pct=0,
                risk_cleared=False, was_vetoed=True, risk_score=2,
            ),
        )
        html = _render_verdict(v)
        assert "风控否决" in html
        assert "否决" in html

    def test_sell_verdict(self):
        v = DebateView(
            verdict=VerdictView(
                action="SELL", action_label="建议回避", action_class="action-sell",
                confidence=0.6, confidence_pct=60,
            ),
        )
        html = _render_verdict(v)
        assert "建议回避" in html

    def test_no_conditions(self):
        v = DebateView(verdict=VerdictView())
        html = _render_verdict(v)
        assert "verdict-conditions" not in html

    def test_no_risk_flags(self):
        v = DebateView(verdict=VerdictView())
        html = _render_verdict(v)
        assert "verdict-flags" not in html


class TestEmptySections:
    """Verify sections degrade gracefully with no data."""

    def test_empty_timeline(self):
        v = DebateView()
        assert _render_timeline(v) == ""

    def test_empty_arena(self):
        v = DebateView()
        assert _render_arena(v) == ""

    def test_empty_controversies(self):
        v = DebateView()
        assert _render_controversies(v) == ""


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  Static export test                                                    ║
# ╚══════════════════════════════════════════════════════════════════════════╝


class TestGenerateReport:
    def test_generate_from_demo(self, tmp_path):
        demo = build_demo_debate_view()
        # build_debate_view expects a trace dict, so we mock one
        trace = {
            "meta": {
                "run_id": "run-test-export",
                "ticker": "601985.SS",
                "ticker_name": "中国核电",
                "trade_date": "2026-03-13",
            },
            "nodes": [
                {"node_name": "Market Analyst", "seq": 1,
                 "structured_data": {"pillar_score": 2},
                 "output_excerpt": "看多", "parse_status": "strict_ok",
                 "evidence_ids_referenced": ["E1"], "claim_ids_produced": []},
                {"node_name": "Fundamentals Analyst", "seq": 2,
                 "structured_data": {"pillar_score": 1},
                 "output_excerpt": "", "parse_status": "strict_ok",
                 "evidence_ids_referenced": [], "claim_ids_produced": []},
            ],
        }
        path = generate_committee_report(trace, output_dir=str(tmp_path))
        assert path is not None
        assert path.endswith("-committee.html")
        content = open(path, encoding="utf-8").read()
        assert "<!DOCTYPE html>" in content
        assert "中国核电" in content

    def test_empty_trace_returns_none(self, tmp_path):
        trace = {
            "meta": {"run_id": "run-empty", "ticker": "000001"},
            "nodes": [],
        }
        path = generate_committee_report(trace, output_dir=str(tmp_path))
        assert path is None


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  Route tests                                                           ║
# ╚══════════════════════════════════════════════════════════════════════════╝


class TestRouteImport:
    """Verify the committee route module can be imported and registered."""

    def test_import_route(self):
        from dashboard.routes.committee import router
        routes = [r.path for r in router.routes]
        assert "/committee/demo" in routes
        assert "/committee/{run_id}" in routes

    def test_app_includes_committee(self):
        from dashboard.app import app
        paths = [r.path for r in app.routes]
        assert "/committee/demo" in paths
        assert "/committee/{run_id}" in paths

"""Tests for P7: Dashboard views, routes, rendering, and 3-tier report system."""

import pytest
from datetime import datetime

from tradingagents.observability.trace_models import NodeTrace, RunTrace, RunMetrics, NodeStatus
from tradingagents.observability.replay_store import ReplayStore
from tradingagents.observability.replay_service import ReplayService

from dashboard.views import (
    BannerView,
    RunSummaryView,
    NodeTraceView,
    WarRoomView,
    SnapshotView,
    ResearchView,
    AuditView,
    StockDivergenceRow,
    DivergencePoolView,
    _strip_internal_tokens,
    _enforce_thesis_limit,
    _check_degradation,
)
from dashboard.decision_labels import (
    ACTION_MAP,
    get_action_label,
    get_action_class,
    get_action_explanation,
    compute_audit_conclusion,
)
from dashboard.report_renderer import (
    render_snapshot, render_research, render_audit,
    render_divergence_pool, generate_pool_report,
    _render_sparkline,
)


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def sample_trace():
    """Create a realistic RunTrace for testing."""
    run_id = "test-dashboard-001"
    now = datetime.now()
    nodes = [
        NodeTrace(
            run_id=run_id, node_name="Market Analyst", seq=0,
            timestamp=now, duration_ms=1200,
            output_hash="aaaa", output_excerpt="Market report...",
            parse_status="strict_ok", parse_confidence=1.0,
        ),
        NodeTrace(
            run_id=run_id, node_name="Bull Researcher", seq=1,
            timestamp=now, duration_ms=2000,
            output_hash="bbbb", output_excerpt="Bull case...",
            claims_produced=3, claims_attributed=2, claims_unattributed=1,
            claim_ids_produced=["clm-a", "clm-b", "clm-c"],
            evidence_ids_referenced=["E1", "E2"],
            parse_status="strict_ok", parse_confidence=0.85,
        ),
        NodeTrace(
            run_id=run_id, node_name="Bear Researcher", seq=2,
            timestamp=now, duration_ms=1800,
            output_hash="cccc", output_excerpt="Bear case...",
            claims_produced=2, claims_attributed=2, claims_unattributed=0,
            claim_ids_produced=["clm-d", "clm-e"],
            evidence_ids_referenced=["E3"],
            parse_status="strict_ok", parse_confidence=0.80,
        ),
        NodeTrace(
            run_id=run_id, node_name="Research Manager", seq=3,
            timestamp=now, duration_ms=2500,
            output_hash="dddd", output_excerpt="PM synthesis...",
            research_action="BUY", confidence=0.75, thesis_effect="strengthen",
            evidence_ids_referenced=["E1", "E2", "E3"],
            claim_ids_referenced=["clm-a", "clm-d"],
            parse_status="strict_ok", parse_confidence=1.0,
        ),
        NodeTrace(
            run_id=run_id, node_name="Risk Judge", seq=4,
            timestamp=now, duration_ms=2000,
            output_hash="eeee", output_excerpt="Risk review...",
            research_action="BUY", confidence=0.70,
            risk_score=5, risk_cleared=True,
            risk_flag_count=1, risk_flag_categories=["concentration"],
            parse_status="strict_ok", parse_confidence=1.0,
        ),
        NodeTrace(
            run_id=run_id, node_name="Publishing Compliance", seq=5,
            timestamp=now, duration_ms=50,
            output_hash="ffff", output_excerpt="Compliance pass",
            compliance_status="allow",
            compliance_reasons=[],
            compliance_rules_fired=["P1_source_tier", "P2_evidence_binding"],
        ),
    ]

    trace = RunTrace(
        run_id=run_id,
        ticker="300750.SZ",
        trade_date="2026-03-10",
        started_at=now,
        market="cn",
        language="zh",
        llm_provider="deepseek",
        node_traces=nodes,
    )
    trace.finalize()
    return trace


@pytest.fixture
def store_with_trace(sample_trace, tmp_path):
    """Create a ReplayStore with one trace loaded."""
    store = ReplayStore(storage_dir=str(tmp_path))
    store.save(sample_trace)
    return store, sample_trace.run_id


@pytest.fixture
def service_with_trace(store_with_trace):
    store, run_id = store_with_trace
    return ReplayService(store=store), run_id


# ── View Model Tests ──────────────────────────────────────────────────────

class TestBannerView:
    def test_from_trace(self, sample_trace):
        banner = BannerView.from_trace(sample_trace)
        assert banner.compliance_status == "allow"
        assert banner.compliance_class == "allow"
        assert banner.source_count > 0
        assert "AI 辅助生成" in banner.ai_label
        assert banner.timestamp  # not empty

    def test_compliance_class_mapping(self):
        trace = RunTrace(compliance_status="block")
        trace.total_evidence_ids = ["E1"]
        trace.started_at = datetime.now()
        banner = BannerView.from_trace(trace)
        assert banner.compliance_class == "block"


class TestRunSummaryView:
    def test_from_manifest(self):
        entry = {
            "run_id": "run-abc",
            "ticker": "300750.SZ",
            "trade_date": "2026-03-10",
            "started_at": "2026-03-10T14:30:00",
            "total_nodes": 10,
            "error_count": 0,
            "research_action": "BUY",
            "was_vetoed": False,
            "compliance_status": "allow",
        }
        view = RunSummaryView.from_manifest(entry)
        assert view.run_id == "run-abc"
        assert view.status_badge == "success"
        assert view.research_action == "BUY"

    def test_error_badge(self):
        entry = {"run_id": "x", "error_count": 2}
        view = RunSummaryView.from_manifest(entry)
        assert view.status_badge == "error"

    def test_veto_badge(self):
        entry = {"run_id": "x", "error_count": 0, "was_vetoed": True}
        view = RunSummaryView.from_manifest(entry)
        assert view.status_badge == "warning"


class TestNodeTraceView:
    def test_from_service_output(self):
        node_out = {
            "node_name": "Research Manager",
            "seq": 3,
            "status": "ok",
            "duration_ms": 2500,
            "output_hash": "dddd",
            "output_excerpt": "PM synthesis...",
            "research_action": "BUY",
            "confidence": 0.75,
            "thesis_effect": "strengthen",
            "parse_status": "strict_ok",
            "parse_confidence": 1.0,
            "evidence_ids_referenced": ["E1", "E2"],
            "claim_ids_referenced": ["clm-a"],
        }
        view = NodeTraceView.from_service_output(node_out)
        assert view.node_name == "Research Manager"
        assert view.research_action == "BUY"
        assert view.duration_formatted == "2.5s"
        assert view.has_evidence is True

    def test_from_list_entry(self):
        entry = {
            "node_name": "Market Analyst",
            "seq": 0,
            "status": "ok",
            "duration_ms": 450,
            "research_action": "",
            "parse_status": "strict_ok",
        }
        view = NodeTraceView.from_list_entry(entry)
        assert view.duration_formatted == "450ms"
        assert view.status_class == "ok"

    def test_duration_formatting(self):
        view = NodeTraceView.from_service_output({"duration_ms": 0, "status": "ok"})
        assert view.duration_formatted == "0ms"

        view = NodeTraceView.from_service_output({"duration_ms": 3200, "status": "ok"})
        assert view.duration_formatted == "3.2s"


class TestWarRoomView:
    def test_build(self, service_with_trace):
        service, run_id = service_with_trace
        view = WarRoomView.build(service, run_id)
        assert view is not None
        assert view.ticker == "300750.SZ"
        assert view.research_action == "BUY"
        assert view.synthesis_node is not None
        assert view.synthesis_node.research_action == "BUY"
        assert view.risk_node is not None
        assert view.risk_node.risk_score == 5
        assert view.bull_node is not None
        assert view.bear_node is not None
        assert view.total_evidence > 0
        assert view.total_claims > 0
        assert view.banner is not None

    def test_build_nonexistent(self, service_with_trace):
        service, _ = service_with_trace
        view = WarRoomView.build(service, "nonexistent-run")
        assert view is None


class TestAuditView:
    def test_build(self, service_with_trace):
        service, run_id = service_with_trace
        view = AuditView.build(service, run_id)
        assert view is not None
        assert view.ticker == "300750.SZ"
        assert view.metrics is not None
        assert view.metrics.strict_parse_rate > 0
        assert view.metrics.replay_completeness_rate > 0
        assert isinstance(view.failures, list)
        assert view.banner is not None

    def test_compliance_nodes_populated(self, service_with_trace):
        service, run_id = service_with_trace
        view = AuditView.build(service, run_id)
        assert len(view.compliance_nodes) > 0
        assert view.compliance_nodes[0].compliance_status == "allow"

    def test_parse_table(self, service_with_trace):
        service, run_id = service_with_trace
        view = AuditView.build(service, run_id)
        assert len(view.parse_table) > 0
        assert all(p["parse_status"] for p in view.parse_table)


# ── Route / HTTP Tests ────────────────────────────────────────────────────

class TestHTTPRoutes:
    """Test all dashboard routes using FastAPI TestClient."""

    @pytest.fixture(autouse=True)
    def setup_client(self, store_with_trace):
        from fastapi.testclient import TestClient
        from dashboard.app import app

        store, self.run_id = store_with_trace
        service = ReplayService(store=store)
        app.state.service = service
        self.client = TestClient(app)

    def test_root_redirect(self):
        resp = self.client.get("/", follow_redirects=False)
        assert resp.status_code == 307
        assert "/runs" in resp.headers["location"]

    def test_run_list(self):
        resp = self.client.get("/runs")
        assert resp.status_code == 200
        assert "300750.SZ" in resp.text
        assert self.run_id[:12] in resp.text

    def test_run_detail(self):
        resp = self.client.get(f"/runs/{self.run_id}")
        assert resp.status_code == 200
        assert "Market Analyst" in resp.text
        assert "Research Manager" in resp.text
        assert "Risk Judge" in resp.text

    def test_node_detail(self):
        resp = self.client.get(f"/runs/{self.run_id}/nodes/Research Manager")
        assert resp.status_code == 200
        assert "BUY" in resp.text
        assert "strengthen" in resp.text

    def test_node_detail_risk(self):
        resp = self.client.get(f"/runs/{self.run_id}/nodes/Risk Judge")
        assert resp.status_code == 200
        assert "风险评分" in resp.text
        assert "concentration" in resp.text

    def test_node_detail_compliance(self):
        resp = self.client.get(f"/runs/{self.run_id}/nodes/Publishing Compliance")
        assert resp.status_code == 200
        assert "allow" in resp.text
        assert "P1_source_tier" in resp.text

    def test_war_room(self):
        resp = self.client.get(f"/runs/{self.run_id}/war-room")
        assert resp.status_code == 200
        assert "研究报告" in resp.text
        assert "300750.SZ" in resp.text
        assert "BUY" in resp.text
        assert "看多研究员" in resp.text
        assert "看空研究员" in resp.text

    def test_audit(self):
        resp = self.client.get(f"/runs/{self.run_id}/audit")
        assert resp.status_code == 200
        assert "审计" in resp.text
        assert "严格解析率" in resp.text
        assert "论据" in resp.text

    def test_banner_on_all_run_pages(self):
        """Every run-scoped page should show the AI content banner."""
        for path in [
            f"/runs/{self.run_id}",
            f"/runs/{self.run_id}/war-room",
            f"/runs/{self.run_id}/audit",
        ]:
            resp = self.client.get(path)
            assert resp.status_code == 200
            assert "AI 辅助生成" in resp.text, f"Banner missing on {path}"

    def test_nonexistent_run(self):
        resp = self.client.get("/runs/nonexistent-abc")
        assert resp.status_code == 200  # renders error in template, not 404
        assert "未找到" in resp.text

    def test_nonexistent_node(self):
        resp = self.client.get(f"/runs/{self.run_id}/nodes/FakeNode")
        assert resp.status_code == 200
        assert "未找到" in resp.text

    def test_navigation_links(self):
        """Run detail page should have links to war room and audit."""
        resp = self.client.get(f"/runs/{self.run_id}")
        assert "war-room" in resp.text
        assert "audit" in resp.text

    def test_run_list_empty(self):
        """Empty store should show empty state, not crash."""
        from fastapi.testclient import TestClient
        from dashboard.app import app
        import tempfile, os

        empty_dir = tempfile.mkdtemp()
        app.state.service = ReplayService(store=ReplayStore(storage_dir=empty_dir))
        client = TestClient(app)
        resp = client.get("/runs")
        assert resp.status_code == 200
        assert "未找到运行记录" in resp.text


# ── Structured Data Fixture ──────────────────────────────────────────────

@pytest.fixture
def structured_trace():
    """Create a trace WITH structured_data for the 3-tier report tests."""
    run_id = "test-structured-001"
    now = datetime.now()
    nodes = [
        NodeTrace(
            run_id=run_id, node_name="Market Analyst", seq=0,
            timestamp=now, duration_ms=1200,
            output_hash="aaaa", output_excerpt="Market report...",
            parse_status="strict_ok", parse_confidence=1.0,
        ),
        NodeTrace(
            run_id=run_id, node_name="Fundamentals Analyst", seq=0,
            timestamp=now, duration_ms=1100,
            output_hash="aab1", output_excerpt="Fundamentals...",
            parse_status="strict_ok", parse_confidence=1.0,
        ),
        NodeTrace(
            run_id=run_id, node_name="News Analyst", seq=0,
            timestamp=now, duration_ms=1000,
            output_hash="aab2", output_excerpt="News...",
            parse_status="strict_ok", parse_confidence=1.0,
        ),
        NodeTrace(
            run_id=run_id, node_name="Social Analyst", seq=0,
            timestamp=now, duration_ms=900,
            output_hash="aab3", output_excerpt="Social...",
            parse_status="strict_ok", parse_confidence=1.0,
        ),
        NodeTrace(
            run_id=run_id, node_name="Catalyst Agent", seq=1,
            timestamp=now, duration_ms=800,
            output_hash="aabb",
            output_excerpt="催化剂...",
            parse_status="strict_ok", parse_confidence=0.9,
            structured_data={
                "catalysts": [
                    {
                        "event_description": "业绩预增公告",
                        "expected_date": "2026-04-30",
                        "direction": "bullish",
                        "magnitude": "high",
                        "source_evidence_ids": ["E1"],
                    },
                ],
            },
        ),
        NodeTrace(
            run_id=run_id, node_name="Bull Researcher", seq=2,
            timestamp=now, duration_ms=2000,
            output_hash="bbbb", output_excerpt="看多论点...",
            claims_produced=2, claims_attributed=2, claims_unattributed=0,
            claim_ids_produced=["clm-a", "clm-b"],
            evidence_ids_referenced=["E1", "E2"],
            parse_status="strict_ok", parse_confidence=0.85,
            structured_data={
                "thesis": "基本面强劲",
                "direction": "bullish",
                "overall_confidence": 0.8,
                "dimension_scores": {"fundamentals": 9},
                "supporting_claims": [
                    {
                        "claim_id": "clm-a",
                        "text": "净利润同比增长50%",
                        "dimension": "fundamentals",
                        "dimension_score": 9,
                        "confidence": 0.9,
                        "invalidation": "增速低于30%",
                        "direction": "bullish",
                        "supports": ["E1"],
                        "opposes": [],
                    },
                    {
                        "claim_id": "clm-b",
                        "text": "储能业务打开第二增长曲线",
                        "dimension": "growth",
                        "dimension_score": 8,
                        "confidence": 0.75,
                        "invalidation": "",
                        "direction": "bullish",
                        "supports": ["E2"],
                        "opposes": [],
                    },
                ],
                "opposing_claims": [],
                "unresolved_conflicts": [],
                "missing_evidence": [],
            },
        ),
        NodeTrace(
            run_id=run_id, node_name="Bear Researcher", seq=3,
            timestamp=now, duration_ms=1800,
            output_hash="cccc", output_excerpt="看空论点...",
            claims_produced=1, claims_attributed=1, claims_unattributed=0,
            claim_ids_produced=["clm-c"],
            evidence_ids_referenced=["E3"],
            parse_status="strict_ok", parse_confidence=0.80,
            structured_data={
                "thesis": "估值偏高",
                "direction": "bearish",
                "overall_confidence": 0.55,
                "dimension_scores": {"valuation": 4},
                "supporting_claims": [
                    {
                        "claim_id": "clm-c",
                        "text": "PE处于近3年80分位",
                        "dimension": "valuation",
                        "dimension_score": 4,
                        "confidence": 0.65,
                        "invalidation": "PE回到50分位",
                        "direction": "bearish",
                        "supports": ["E3"],
                        "opposes": [],
                    },
                ],
                "opposing_claims": [],
                "unresolved_conflicts": [],
                "missing_evidence": [],
            },
        ),
        NodeTrace(
            run_id=run_id, node_name="Scenario Agent", seq=4,
            timestamp=now, duration_ms=1000,
            output_hash="dddd", output_excerpt="情景分析...",
            parse_status="strict_ok", parse_confidence=0.9,
            structured_data={
                "base_prob": 0.55,
                "bull_prob": 0.25,
                "bear_prob": 0.20,
                "base_case_trigger": "业绩如期增长",
                "bull_case_trigger": "超预期增长",
                "bear_case_trigger": "原材料涨价",
            },
        ),
        NodeTrace(
            run_id=run_id, node_name="Research Manager", seq=5,
            timestamp=now, duration_ms=2500,
            output_hash="eeee", output_excerpt="PM综合研判...",
            research_action="BUY", confidence=0.75, thesis_effect="strengthen",
            evidence_ids_referenced=["E1", "E2", "E3"],
            claim_ids_referenced=["clm-a", "clm-c"],
            parse_status="strict_ok", parse_confidence=1.0,
            structured_data={
                "conclusion": "业绩高增长与储能新业务构成强支撑，维持看多判断",
                "base_case": "增长50-60%，股价上涨10-15%",
                "bull_case": "超70%增长，股价上涨25%+",
                "bear_case": "原材料成本上涨，股价回调10%",
                "invalidation_conditions": ["净利润增速低于30%", "储能投产延期"],
                "open_questions": ["产能利用率能否达标"],
                "supporting_evidence_ids": ["E1", "E2"],
                "opposing_evidence_ids": ["E3"],
            },
        ),
        NodeTrace(
            run_id=run_id, node_name="Risk Judge", seq=6,
            timestamp=now, duration_ms=2000,
            output_hash="ffff", output_excerpt="风控审查...",
            research_action="BUY", confidence=0.70,
            risk_score=5, risk_cleared=True,
            risk_flag_count=1, risk_flag_categories=["concentration"],
            parse_status="strict_ok", parse_confidence=1.0,
            structured_data={
                "conclusion": "整体风险可控",
                "invalidation_conditions": ["碳酸锂价格月涨超30%"],
                "risk_flags": [
                    {
                        "flag_id": "rf-001",
                        "category": "concentration",
                        "severity": "medium",
                        "description": "新能源板块持仓集中度较高",
                        "bound_evidence_ids": ["E1"],
                        "mitigant": "限制单票仓位不超过4%",
                    },
                ],
            },
        ),
        NodeTrace(
            run_id=run_id, node_name="Publishing Compliance", seq=7,
            timestamp=now, duration_ms=50,
            output_hash="gggg", output_excerpt="Compliance pass",
            compliance_status="allow",
            compliance_reasons=[],
            compliance_rules_fired=["P1_source_tier", "P2_evidence_binding"],
        ),
    ]

    trace = RunTrace(
        run_id=run_id,
        ticker="300750.SZ",
        trade_date="2026-03-10",
        started_at=now,
        market="cn",
        language="zh",
        llm_provider="deepseek",
        node_traces=nodes,
    )
    trace.finalize()
    return trace


@pytest.fixture
def structured_service(structured_trace, tmp_path):
    """ReplayService with a structured trace loaded."""
    store = ReplayStore(storage_dir=str(tmp_path))
    store.save(structured_trace)
    return ReplayService(store=store), structured_trace.run_id


# ── 3-Tier Report Tests ─────────────────────────────────────────────────

class TestStructuredDataRoundTrip:
    """Phase 0: structured_data field persists through serialize/deserialize."""

    def test_node_trace_round_trip(self):
        nt = NodeTrace(
            run_id="test", node_name="Bull Researcher", seq=0,
            structured_data={"thesis": "test thesis", "claims": [{"id": "c1"}]},
        )
        d = nt.to_dict()
        assert d["structured_data"]["thesis"] == "test thesis"

        restored = NodeTrace.from_dict(d)
        assert restored.structured_data["thesis"] == "test thesis"
        assert restored.structured_data["claims"][0]["id"] == "c1"

    def test_old_trace_gets_empty_dict(self):
        """Old traces without structured_data get {} by default."""
        d = {"run_id": "old", "node_name": "X", "seq": 0}
        nt = NodeTrace.from_dict(d)
        assert nt.structured_data == {}

    def test_store_round_trip(self, structured_trace, tmp_path):
        """structured_data survives ReplayStore save/load."""
        store = ReplayStore(storage_dir=str(tmp_path))
        store.save(structured_trace)
        loaded = store.load(structured_trace.run_id)
        bull = [n for n in loaded.node_traces if n.node_name == "Bull Researcher"][0]
        assert bull.structured_data["thesis"] == "基本面强劲"
        assert len(bull.structured_data["supporting_claims"]) == 2


class TestDecisionLabels:
    """Phase 1: decision_labels.py maps all actions correctly."""

    def test_all_actions_have_labels(self):
        for action in ("BUY", "HOLD", "SELL", "VETO"):
            assert action in ACTION_MAP
            label, css, explanation = ACTION_MAP[action]
            assert label  # non-empty
            assert css  # non-empty
            assert explanation  # non-empty

    def test_buy_label(self):
        assert get_action_label("BUY") == "建议关注"

    def test_sell_label(self):
        assert get_action_label("SELL") == "建议回避"

    def test_veto_label(self):
        assert get_action_label("VETO") == "风控否决"

    def test_hold_label(self):
        assert get_action_label("HOLD") == "维持观察"

    def test_unknown_action_returns_itself(self):
        assert get_action_label("UNKNOWN") == "UNKNOWN"

    def test_explanation_non_empty(self):
        for action in ("BUY", "HOLD", "SELL", "VETO"):
            assert len(get_action_explanation(action)) > 5


class TestSnapshotStructured:
    """Phase 2/3: SnapshotView with structured_data produces clean output."""

    def test_snapshot_structured_clean(self, structured_service):
        service, run_id = structured_service
        view = SnapshotView.build(service, run_id)
        assert view is not None
        assert view.action_label == "建议关注"
        assert view.action_class == "buy"
        assert view.action_explanation  # non-empty
        # one_line_summary should come from structured conclusion, not raw excerpt
        assert "业绩高增长" in view.one_line_summary or "维持看多" in view.one_line_summary
        # No LLM preambles in summary
        for preamble in ("好的", "作为", "针对", "让我"):
            assert preamble not in view.one_line_summary

    def test_snapshot_core_drivers_from_structured(self, structured_service):
        service, run_id = structured_service
        view = SnapshotView.build(service, run_id)
        assert len(view.core_drivers) >= 1
        # Drivers should be clean claim text, not raw markdown
        for d in view.core_drivers:
            assert "**" not in d
            assert "#" not in d

    def test_snapshot_catalysts_structured(self, structured_service):
        service, run_id = structured_service
        view = SnapshotView.build(service, run_id)
        assert len(view.catalysts) >= 1
        cat = view.catalysts[0]
        assert isinstance(cat, dict)
        assert "event" in cat
        assert "date" in cat

    def test_snapshot_risks_structured(self, structured_service):
        service, run_id = structured_service
        view = SnapshotView.build(service, run_id)
        assert len(view.main_risks) >= 1
        risk = view.main_risks[0]
        assert isinstance(risk, dict)
        assert "category" in risk
        assert "severity" in risk

    def test_snapshot_fallback_no_crash(self, service_with_trace):
        """Old trace (no structured_data) should degrade gracefully."""
        service, run_id = service_with_trace
        view = SnapshotView.build(service, run_id)
        assert view is not None
        assert view.action_label  # has a label
        assert view.action_class  # has a CSS class


class TestResearchStructured:
    """Phase 2: ResearchView populates claim text from structured_data."""

    def test_claims_from_structured(self, structured_service):
        service, run_id = structured_service
        view = ResearchView.build(service, run_id)
        assert view is not None
        # Bull claims should have text, not just IDs
        assert len(view.bull_claims) >= 1
        assert "text" in view.bull_claims[0]
        assert view.bull_claims[0]["text"]  # non-empty

    def test_synthesis_from_structured(self, structured_service):
        service, run_id = structured_service
        view = ResearchView.build(service, run_id)
        # synthesis_excerpt should be the structured conclusion
        assert "业绩高增长" in view.synthesis_excerpt or "维持看多" in view.synthesis_excerpt
        # synthesis_detail should have base/bull/bear cases
        assert view.synthesis_detail.get("base_case")
        assert view.synthesis_detail.get("bull_case")

    def test_scenario_probs_from_structured(self, structured_service):
        service, run_id = structured_service
        view = ResearchView.build(service, run_id)
        assert view.scenario_probs
        assert view.scenario_probs["base_prob"] == 0.55
        assert view.scenario_probs["bull_prob"] == 0.25

    def test_risk_flags_detail(self, structured_service):
        service, run_id = structured_service
        view = ResearchView.build(service, run_id)
        assert len(view.risk_flags_detail) >= 1
        assert view.risk_flags_detail[0]["description"]

    def test_invalidation_from_structured(self, structured_service):
        service, run_id = structured_service
        view = ResearchView.build(service, run_id)
        assert len(view.invalidation_signals) >= 1
        assert "净利润" in view.invalidation_signals[0] or "增速" in view.invalidation_signals[0]


class TestAuditTrustSignals:
    """Phase 2: AuditView computes trust_signals and weakest_node."""

    def test_trust_signals_populated(self, structured_service):
        service, run_id = structured_service
        view = AuditView.build(service, run_id)
        assert view is not None
        assert len(view.trust_signals) == 5
        for ts in view.trust_signals:
            assert "label" in ts
            assert "value" in ts
            assert "status" in ts
            assert "explanation" in ts
            assert ts["status"] in ("good", "warn", "bad")

    def test_weakest_node_identified(self, structured_service):
        service, run_id = structured_service
        view = AuditView.build(service, run_id)
        # The weakest node should be one with lowest parse_confidence (now Chinese labels)
        # Bear Researcher has 0.80 which is the lowest → 看空研究员
        assert view.weakest_node  # not empty
        assert any(label in view.weakest_node for label in ("看空研究员", "看多研究员", "催化剂分析师", "情景分析师"))


class TestRendererNoLLMLeakage:
    """Phase 3: rendered HTML must not contain LLM preambles."""

    def test_snapshot_no_leakage(self, structured_service):
        service, run_id = structured_service
        view = SnapshotView.build(service, run_id)
        html = render_snapshot(view)
        for preamble in ("好的", "作为研究", "针对您的", "让我来"):
            assert preamble not in html

    def test_research_no_leakage(self, structured_service):
        service, run_id = structured_service
        view = ResearchView.build(service, run_id)
        html = render_research(view)
        for preamble in ("好的", "作为研究", "针对您的", "让我来"):
            assert preamble not in html


class TestRendererDecisionSemantics:
    """Phase 3: rendered HTML uses Chinese decision labels, not raw English."""

    def test_snapshot_uses_chinese_labels(self, structured_service):
        service, run_id = structured_service
        view = SnapshotView.build(service, run_id)
        html = render_snapshot(view)
        assert "建议关注" in html  # BUY → 建议关注
        assert "研究结论偏积极" in html  # action explanation

    def test_veto_renders_as_chinese(self):
        """VETO action should render as 风控否决."""
        # Construct a minimal VETO SnapshotView
        view = SnapshotView(
            run_id="test-veto",
            ticker="000001.SZ",
            trade_date="2026-03-10",
            research_action="VETO",
            action_label="风控否决",
            action_class="veto",
            action_explanation="证据链不完整或触发风控硬规则，建议暂不操作",
            confidence=0.3,
            one_line_summary="风控否决此标的",
            was_vetoed=True,
        )
        html = render_snapshot(view)
        assert "风控否决" in html
        assert "VETO" not in html or "风控否决" in html  # VETO should be expressed in Chinese

    def test_audit_trust_signals_render(self, structured_service):
        service, run_id = structured_service
        view = AuditView.build(service, run_id)
        html = render_audit(view)
        assert "信任审计报告" in html
        assert "信任信号" in html
        assert "AI输出解析率" in html
        assert "论据有据可查" in html


# ── Token Stripping Tests ────────────────────────────────────────────

class TestTokenStripping:
    """Internal system tokens must never appear in Tier 1/2."""

    def test_strip_claim_ids(self):
        text = "基于对 Bull Claim 1, 3, 4 和 Bear Claim [clm-9bc27511, ab5df0c6] 的仲裁"
        result = _strip_internal_tokens(text)
        assert "clm-" not in result
        assert "Bull Claim" not in result
        assert "Bear Claim" not in result
        assert "仲裁" not in result  # replaced with 综合判断

    def test_strip_evidence_ids(self):
        text = "根据 E1, E2, E3 的数据支持"
        result = _strip_internal_tokens(text)
        assert "E1" not in result
        assert "E2" not in result
        assert "E3" not in result
        assert "数据支持" in result

    def test_strip_cited_evidence_block(self):
        text = "分析结论\n**CITED_EVIDENCE**: [E1, E2, E3, E4, E5, E6]\n后续分析"
        result = _strip_internal_tokens(text)
        assert "CITED_EVIDENCE" not in result
        assert "后续分析" in result

    def test_strip_markdown_artifacts(self):
        text = "**核心结论**: 估值合理"
        result = _strip_internal_tokens(text)
        assert "**" not in result
        assert "估值合理" in result

    def test_empty_text(self):
        assert _strip_internal_tokens("") == ""
        assert _strip_internal_tokens(None) is None

    def test_thesis_limit(self):
        long_text = "这是一段非常长的分析结论，包含了大量的细节和论证。盈利修复与长期趋势仍提供支撑，但技术面确认信号不足。"
        result = _enforce_thesis_limit(long_text, max_chars=50)
        assert len(result) <= 50

    def test_thesis_limit_sentence_boundary(self):
        text = "盈利修复趋势明显，值得关注。但短期需要等待催化剂确认，暂时维持观察。"
        result = _enforce_thesis_limit(text, max_chars=50)
        # Should cut at the first sentence boundary
        assert result.endswith("。")
        assert len(result) <= 50

    def test_snapshot_no_internal_tokens(self, structured_service):
        """Rendered snapshot must not contain any internal tokens."""
        service, run_id = structured_service
        view = SnapshotView.build(service, run_id)
        html = render_snapshot(view)
        for token in ("clm-", "Bull Claim", "Bear Claim", "CITED_EVIDENCE"):
            assert token not in html, f"Internal token '{token}' found in snapshot HTML"

    def test_research_no_internal_tokens(self, structured_service):
        """Rendered research must not contain raw evidence IDs."""
        service, run_id = structured_service
        view = ResearchView.build(service, run_id)
        html = render_research(view)
        assert "CITED_EVIDENCE" not in html

    def test_strip_hex_id_brackets(self):
        """Bracket-enclosed hex ID lists must be stripped."""
        text = "基于看空观点[-1, 79107dc0-2, 79107dc0-5]所依据的增长动能"
        result = _strip_internal_tokens(text)
        assert "79107dc0" not in result
        assert "[-1," not in result
        assert "增长动能" in result

    def test_strip_chinese_internal_terms(self):
        """Chinese internal terms must be replaced with neutral equivalents."""
        text = "根据熊派主张和牛派主张的对比分析"
        result = _strip_internal_tokens(text)
        assert "熊派主张" not in result
        assert "牛派主张" not in result
        assert "看空观点" in result
        assert "看多观点" in result

    def test_strip_llm_preamble(self):
        """LLM self-introduction preambles must be removed."""
        text = "好的，我将以研究经理的身份进行综合判断\n当前估值合理，建议关注。"
        result = _strip_internal_tokens(text)
        assert "好的" not in result
        assert "建议关注" in result

    def test_strip_structured_claim_term(self):
        """'结构化主张' is internal and must be removed."""
        text = "基于结构化主张和决策框架进行分析"
        result = _strip_internal_tokens(text)
        assert "结构化主张" not in result

    def test_strip_bracketed_evidence(self):
        """Bracketed evidence refs like [E8] must be stripped."""
        text = "支撑/阻力区域[E8]上沿，MACD转负[E6]"
        result = _strip_internal_tokens(text)
        assert "[E8]" not in result
        assert "[E6]" not in result
        assert "支撑/阻力区域" in result

    def test_tone_moderation(self):
        """Extreme superlatives must be softened for product output."""
        text = "现金流创造能力极强，财务状况极其健康"
        result = _strip_internal_tokens(text)
        assert "极强" not in result
        assert "极其" not in result
        assert "较强" in result
        assert "较为" in result

    def test_tone_moderation_preserves_content(self):
        """Tone moderation must not remove factual content."""
        text = "毛利率从15.0%增至28.2%，趋势结构完好无损"
        result = _strip_internal_tokens(text)
        assert "15.0%" in result
        assert "28.2%" in result
        assert "基本完整" in result


# ── Degradation Tests ────────────────────────────────────────────────

class TestDegradation:
    """Degraded mode triggers when output quality is poor."""

    @pytest.fixture
    def degraded_trace(self):
        """Trace with poor parse quality — should trigger degraded mode."""
        run_id = "test-degraded-001"
        now = datetime.now()
        nodes = [
            NodeTrace(
                run_id=run_id, node_name="Market Analyst", seq=0,
                timestamp=now, duration_ms=1200,
                output_hash="aaaa", output_excerpt="Market report...",
                parse_status="strict_ok", parse_confidence=1.0,
            ),
            NodeTrace(
                run_id=run_id, node_name="Bull Researcher", seq=1,
                timestamp=now, duration_ms=2000,
                output_hash="bbbb", output_excerpt="Bull case...",
                claims_produced=1, claims_attributed=0, claims_unattributed=1,
                claim_ids_produced=["clm-a"],
                parse_status="fallback_used", parse_confidence=0.3,
            ),
            NodeTrace(
                run_id=run_id, node_name="Bear Researcher", seq=2,
                timestamp=now, duration_ms=1800,
                output_hash="cccc", output_excerpt="Bear case...",
                claims_produced=1, claims_attributed=0, claims_unattributed=1,
                claim_ids_produced=["clm-b"],
                parse_status="fallback_used", parse_confidence=0.3,
            ),
            NodeTrace(
                run_id=run_id, node_name="Catalyst Agent", seq=3,
                timestamp=now, duration_ms=800,
                output_hash="ddee",
                output_excerpt="催化剂...",
                parse_status="fallback_used", parse_confidence=0.2,
            ),
            NodeTrace(
                run_id=run_id, node_name="Research Manager", seq=4,
                timestamp=now, duration_ms=2500,
                output_hash="dddd", output_excerpt="PM synthesis...",
                research_action="HOLD", confidence=0.70,
                parse_status="fallback_used", parse_confidence=0.4,
            ),
            NodeTrace(
                run_id=run_id, node_name="Risk Judge", seq=5,
                timestamp=now, duration_ms=2000,
                output_hash="eeee", output_excerpt="Risk review...",
                research_action="HOLD", confidence=0.60,
                risk_score=6, risk_cleared=True,
                parse_status="fallback_used", parse_confidence=0.3,
            ),
        ]
        trace = RunTrace(
            run_id=run_id,
            ticker="600519.SS",
            trade_date="2026-03-11",
            started_at=now,
            market="cn",
            language="zh",
            llm_provider="deepseek",
            node_traces=nodes,
        )
        trace.finalize()
        return trace

    @pytest.fixture
    def degraded_service(self, degraded_trace, tmp_path):
        store = ReplayStore(storage_dir=str(tmp_path))
        store.save(degraded_trace)
        return ReplayService(store=store), degraded_trace.run_id

    def test_degradation_detected(self, degraded_service):
        """Poor parse quality should trigger is_degraded=True."""
        service, run_id = degraded_service
        view = SnapshotView.build(service, run_id)
        assert view.is_degraded is True
        assert len(view.degradation_reasons) >= 1

    def test_degraded_snapshot_shows_warning(self, degraded_service):
        """Degraded snapshot should show warning banner, not full content."""
        service, run_id = degraded_service
        view = SnapshotView.build(service, run_id)
        html = render_snapshot(view)
        assert "输出质量退化" in html
        assert "结构化退化" in html
        # Should NOT show full content sections
        assert "核心驱动" not in html
        assert "证据强度" not in html

    def test_degraded_research_shows_warning(self, degraded_service):
        """Degraded research should show warning banner."""
        service, run_id = degraded_service
        view = ResearchView.build(service, run_id)
        assert view.is_degraded is True
        html = render_research(view)
        assert "输出质量退化" in html
        assert "结构化退化" in html
        # Should NOT show bull/bear cards
        assert "看多论点" not in html
        assert "看空论点" not in html

    def test_normal_trace_not_degraded(self, structured_service):
        """Good quality trace should NOT be degraded."""
        service, run_id = structured_service
        view = SnapshotView.build(service, run_id)
        assert view.is_degraded is False
        html = render_snapshot(view)
        assert "输出质量退化" not in html

    def test_check_degradation_thresholds(self):
        """Unit test for _check_degradation() logic."""
        # Mock metrics with low parse rate and binding rate
        metrics = RunMetrics()
        metrics.strict_parse_rate = 0.30
        metrics.claim_to_evidence_binding_rate = 0.0
        metrics.replay_completeness_rate = 0.60
        is_deg, reasons = _check_degradation(metrics, [], [])
        assert is_deg is True
        assert len(reasons) >= 2  # parse rate + binding rate

    def test_check_degradation_weak_nodes(self):
        """≥2 fallback nodes should trigger degradation."""
        metrics = RunMetrics()
        metrics.strict_parse_rate = 0.80
        metrics.claim_to_evidence_binding_rate = 0.80
        metrics.replay_completeness_rate = 0.90
        nodes = [
            {"node_name": "Bull Researcher", "parse_status": "fallback_used"},
            {"node_name": "Bear Researcher", "parse_status": "fallback_used"},
            {"node_name": "Research Manager", "parse_status": "strict_ok"},
        ]
        is_deg, reasons = _check_degradation(metrics, nodes, [])
        assert is_deg is True
        assert any("回退解析" in r for r in reasons)


# ── Audit Conclusion Tests ───────────────────────────────────────────

class TestAuditConclusion:
    """Audit page must have a computed audit conclusion."""

    def test_compute_high(self):
        signals = [
            {"status": "good"}, {"status": "good"},
            {"status": "good"}, {"status": "good"}, {"status": "good"},
        ]
        level, label, text = compute_audit_conclusion(signals)
        assert level == "high"
        assert label == "高可信"

    def test_compute_medium(self):
        signals = [
            {"status": "good"}, {"status": "good"},
            {"status": "warn"}, {"status": "warn"}, {"status": "good"},
        ]
        level, label, text = compute_audit_conclusion(signals)
        assert level == "medium"

    def test_compute_low(self):
        signals = [
            {"status": "bad"}, {"status": "bad"},
            {"status": "good"}, {"status": "good"}, {"status": "good"},
        ]
        level, label, text = compute_audit_conclusion(signals)
        assert level == "low"
        assert label == "低可信"

    def test_compute_with_weakest_node_medium(self):
        signals = [
            {"status": "bad"}, {"status": "good"},
            {"status": "good"}, {"status": "good"}, {"status": "good"},
        ]
        level, label, text = compute_audit_conclusion(signals, "催化剂分析师")
        assert level == "medium"
        assert "催化剂分析师" in text
        assert "人工复核" in text

    def test_compute_with_weakest_node_low(self):
        """Low-level must use distinct stronger warning, not same text as medium."""
        signals = [
            {"status": "bad"}, {"status": "bad"},
            {"status": "good"}, {"status": "good"}, {"status": "good"},
        ]
        level, label, text = compute_audit_conclusion(signals, "催化剂分析师")
        assert level == "low"
        assert "催化剂分析师" in text
        assert "不建议" in text  # distinct from medium's "可参考"

    def test_audit_conclusion_rendered(self, structured_service):
        service, run_id = structured_service
        view = AuditView.build(service, run_id)
        html = render_audit(view)
        assert "审计结论" in html
        # Should contain one of the conclusion labels
        assert any(label in html for label in ("高可信", "中等可信", "低可信"))

    def test_no_compliance_wording(self):
        """Empty compliance should use product-friendly wording, not '无合规节点记录'."""
        view = AuditView(
            run_id="test", ticker="000001.SZ", trade_date="2026-03-11",
        )
        html = render_audit(view)
        assert "无合规节点记录" not in html
        assert "合规轨迹" in html or "合规" in html


# ── Chart Data Tests ────────────────────────────────────────────────

class TestChartData:
    """Tests for chart_data.py parsing and rendering."""

    def test_parse_number(self):
        from dashboard.chart_data import _parse_number
        assert _parse_number("18.5") == 18.5
        assert _parse_number("2,800,000") == 2800000.0
        assert _parse_number("-3.2%") == -3.2
        assert _parse_number("") is None
        assert _parse_number(None) is None

    def test_format_market_cap(self):
        from dashboard.chart_data import _format_market_cap
        assert _format_market_cap(None) == "—"
        assert "万亿" in _format_market_cap(1.5e12)
        assert "亿" in _format_market_cap(3e10)
        assert "万" in _format_market_cap(5e6)

    def test_parse_fundamentals_text(self):
        from dashboard.chart_data import _parse_fundamentals_text
        text = "PE Ratio (TTM): 25.3\nMarket Cap: 800000000\nROE: 0.18"
        result = _parse_fundamentals_text(text)
        assert result.get("PE Ratio (TTM)") == 25.3
        assert result.get("ROE") == 0.18

    def test_parse_price_csv(self):
        from dashboard.chart_data import _parse_price_csv
        csv = "Date,Open,High,Low,Close,Volume\n2025-01-01,10,12,9,11,1000\n2025-01-02,11,13,10,12,2000"
        rows = _parse_price_csv(csv)
        assert len(rows) == 2
        assert rows[0]["close"] == 11.0
        assert rows[1]["close"] == 12.0
        assert rows[0]["date"] == "2025-01-01"

    def test_parse_price_csv_empty(self):
        from dashboard.chart_data import _parse_price_csv
        assert _parse_price_csv("no header here") == []
        assert _parse_price_csv("") == []

    def test_render_metrics_card_minimal(self):
        from dashboard.chart_data import render_metrics_card
        data = {"metrics": {"pe": 25.0, "pb": 3.5}, "prices": []}
        html = render_metrics_card(data)
        assert "25.00" in html
        assert "3.50" in html
        assert "基本面速览" in html

    def test_render_metrics_card_with_sparkline(self):
        from dashboard.chart_data import render_metrics_card
        prices = [{"date": f"2025-01-{i:02d}", "close": 10 + i * 0.1, "volume": 1000}
                  for i in range(1, 31)]
        data = {"metrics": {}, "prices": prices, "price_current": 13.0, "price_change_pct": 1.5}
        html = render_metrics_card(data)
        assert "近" in html and "日走势" in html
        assert "¥13.00" in html

    def test_render_research_charts_empty(self):
        from dashboard.chart_data import render_research_charts
        data = {"metrics": {}, "indicators": {}, "prices": []}
        assert render_research_charts(data) == ""

    def test_render_research_charts_with_data(self):
        from dashboard.chart_data import render_research_charts
        data = {
            "metrics": {"pe": 20.0, "roe": 0.15, "market_cap": 5e10},
            "indicators": {"rsi": 65.0, "macd": 0.5},
            "prices": [{"date": f"2025-01-{i:02d}", "close": 10 + i * 0.2, "volume": 1000}
                       for i in range(1, 21)],
            "price_current": 14.0,
        }
        html = render_research_charts(data)
        assert "财务数据" in html
        assert "RSI" in html
        assert "MACD" in html
        assert "价格走势" in html


# ── Divergence Pool Fixtures ─────────────────────────────────────────────

def _make_pool_trace(run_id, ticker, ticker_name, action, confidence):
    """Helper: create a minimal RunTrace for pool testing."""
    now = datetime.now()
    nodes = [
        NodeTrace(
            run_id=run_id, node_name="Fundamentals Analyst", seq=0,
            timestamp=now, duration_ms=1000,
            output_hash="fa01", output_excerpt="基本面...",
            parse_status="strict_ok", parse_confidence=1.0,
            structured_data={"metrics_fallback": {"pe": "25.3", "pb": "1.8", "market_cap": "500"}},
        ),
        NodeTrace(
            run_id=run_id, node_name="Bull Researcher", seq=1,
            timestamp=now, duration_ms=1500,
            output_hash="bu01", output_excerpt="看多...",
            claims_produced=2, claims_attributed=2,
            claim_ids_produced=["clm-b1", "clm-b2"],
            evidence_ids_referenced=["E1", "E2"],
            parse_status="strict_ok", parse_confidence=0.85,
            structured_data={
                "supporting_claims": [
                    {"claim_id": "clm-b1", "text": f"{ticker_name}核心竞争力突出",
                     "confidence": 0.85, "supports": ["E1"], "direction": "bullish"},
                    {"claim_id": "clm-b2", "text": f"{ticker_name}增长空间广阔",
                     "confidence": 0.70, "supports": ["E2"], "direction": "bullish"},
                ],
            },
        ),
        NodeTrace(
            run_id=run_id, node_name="Bear Researcher", seq=2,
            timestamp=now, duration_ms=1500,
            output_hash="be01", output_excerpt="看空...",
            claims_produced=1, claims_attributed=1,
            claim_ids_produced=["clm-c1"],
            evidence_ids_referenced=["E3"],
            parse_status="strict_ok", parse_confidence=0.80,
            structured_data={
                "supporting_claims": [
                    {"claim_id": "clm-c1", "text": f"{ticker_name}估值偏高风险",
                     "confidence": 0.60, "supports": ["E3"], "direction": "bearish"},
                ],
            },
        ),
        NodeTrace(
            run_id=run_id, node_name="Research Manager", seq=3,
            timestamp=now, duration_ms=2000,
            output_hash="pm01", output_excerpt="综合判断...",
            research_action=action, confidence=confidence,
            parse_status="strict_ok", parse_confidence=1.0,
        ),
        NodeTrace(
            run_id=run_id, node_name="Risk Judge", seq=4,
            timestamp=now, duration_ms=1500,
            output_hash="rj01", output_excerpt="风控...",
            research_action=action, confidence=confidence,
            risk_score=5, risk_cleared=(action != "VETO"),
            parse_status="strict_ok", parse_confidence=1.0,
            structured_data={
                "risk_flags": [
                    {"flag_id": "rf-001", "category": "concentration", "severity": "medium"},
                ],
            },
        ),
    ]
    trace = RunTrace(
        run_id=run_id,
        ticker=ticker,
        ticker_name=ticker_name,
        trade_date="2026-03-13",
        started_at=now,
        market="cn", language="zh",
        node_traces=nodes,
    )
    trace.finalize()
    return trace


@pytest.fixture
def pool_service(tmp_path):
    """ReplayService with 3 distinct stocks for pool testing."""
    store = ReplayStore(storage_dir=str(tmp_path))
    traces = [
        _make_pool_trace("run-pool-001", "601985.SS", "中国核电", "BUY", 0.72),
        _make_pool_trace("run-pool-002", "002131.SZ", "利欧股份", "SELL", 0.82),
        _make_pool_trace("run-pool-003", "300627.SZ", "华测导航", "HOLD", 0.55),
    ]
    for t in traces:
        store.save(t)
    run_ids = [t.run_id for t in traces]
    return ReplayService(store=store), run_ids


# ── Divergence Pool View Tests ───────────────────────────────────────────

class TestStockDivergenceRow:
    def test_build_extracts_claims(self, pool_service):
        service, run_ids = pool_service
        row = StockDivergenceRow.build(service, run_ids[0])
        assert row is not None
        assert row.ticker == "601985.SS"
        assert row.action == "BUY"
        assert row.action_label == "建议关注"
        assert row.action_class == "buy"
        assert row.confidence == pytest.approx(0.72)
        assert len(row.bull_claims) == 2
        assert len(row.bear_claims) == 1
        assert row.bull_claims[0]["confidence"] >= row.bull_claims[1]["confidence"]

    def test_build_extracts_risk_flags(self, pool_service):
        service, run_ids = pool_service
        row = StockDivergenceRow.build(service, run_ids[0])
        assert len(row.risk_flags) == 1
        assert row.risk_flags[0]["category"] == "concentration"

    def test_build_extracts_metrics(self, pool_service):
        service, run_ids = pool_service
        row = StockDivergenceRow.build(service, run_ids[0])
        assert row.pe == "25.3"
        assert row.pb == "1.8"
        assert row.market_cap == "500"

    def test_build_returns_none_for_missing(self, pool_service):
        service, _ = pool_service
        assert StockDivergenceRow.build(service, "run-nonexistent") is None


class TestDivergencePoolView:
    def test_build_aggregates_rows(self, pool_service):
        service, run_ids = pool_service
        view = DivergencePoolView.build(service, run_ids)
        assert view.total_stocks == 3
        assert view.buy_count == 1
        assert view.sell_count == 1
        assert view.hold_count == 1

    def test_rows_sorted_by_action_then_confidence(self, pool_service):
        service, run_ids = pool_service
        view = DivergencePoolView.build(service, run_ids)
        actions = [r.action for r in view.rows]
        # BUY first, then HOLD, then SELL
        assert actions == ["BUY", "HOLD", "SELL"]

    def test_trade_date_from_first_row(self, pool_service):
        service, run_ids = pool_service
        view = DivergencePoolView.build(service, run_ids)
        assert view.trade_date == "2026-03-13"

    def test_empty_run_ids(self, pool_service):
        service, _ = pool_service
        view = DivergencePoolView.build(service, [])
        assert view.total_stocks == 0
        assert view.rows == []


# ── Divergence Pool Render Tests ─────────────────────────────────────────

class TestRenderDivergencePool:
    def test_renders_all_stocks(self, pool_service):
        service, run_ids = pool_service
        view = DivergencePoolView.build(service, run_ids)
        html = render_divergence_pool(view)
        assert "多空分歧池" in html
        assert "601985.SS" in html or "中国核电" in html
        assert "002131.SZ" in html or "利欧股份" in html
        assert "300627.SZ" in html or "华测导航" in html

    def test_renders_summary_stats(self, pool_service):
        service, run_ids = pool_service
        view = DivergencePoolView.build(service, run_ids)
        html = render_divergence_pool(view)
        assert "标的总数" in html
        assert "建议关注" in html
        assert "建议回避" in html

    def test_renders_bull_bear_claims(self, pool_service):
        service, run_ids = pool_service
        view = DivergencePoolView.build(service, run_ids)
        html = render_divergence_pool(view)
        assert "看多核心论据" in html
        assert "看空核心论据" in html
        assert "核心竞争力突出" in html
        assert "估值偏高风险" in html

    def test_renders_action_labels_chinese(self, pool_service):
        service, run_ids = pool_service
        view = DivergencePoolView.build(service, run_ids)
        html = render_divergence_pool(view)
        assert "建议关注" in html  # BUY
        assert "建议回避" in html  # SELL
        assert "维持观察" in html  # HOLD

    def test_renders_metrics(self, pool_service):
        service, run_ids = pool_service
        view = DivergencePoolView.build(service, run_ids)
        html = render_divergence_pool(view)
        assert "PE 25.3" in html
        assert "PB 1.8" in html

    def test_renders_risk_tags(self, pool_service):
        service, run_ids = pool_service
        view = DivergencePoolView.build(service, run_ids)
        html = render_divergence_pool(view)
        assert "concentration" in html or "risk-tag" in html

    def test_renders_customer_facing_sections(self, pool_service):
        service, run_ids = pool_service
        view = DivergencePoolView.build(service, run_ids)
        html = render_divergence_pool(view)
        assert "建议分布图" in html
        assert "置信度景深图" in html
        assert "风险热度图" in html
        assert "决策总表" in html
        assert "阅读指南" in html

    def test_no_llm_leakage(self, pool_service):
        service, run_ids = pool_service
        view = DivergencePoolView.build(service, run_ids)
        html = render_divergence_pool(view)
        for preamble in ("好的", "作为研究", "针对您的", "让我来"):
            assert preamble not in html

    def test_renders_ai_banner(self, pool_service):
        service, run_ids = pool_service
        view = DivergencePoolView.build(service, run_ids)
        html = render_divergence_pool(view)
        assert "仅供研究参考" in html

    def test_renders_cover_page(self, pool_service):
        service, run_ids = pool_service
        view = DivergencePoolView.build(service, run_ids)
        html = render_divergence_pool(view)
        assert "cover-page" in html
        assert "cover-title" in html
        assert "研究报告" in html

    def test_renders_brand_logo(self, pool_service):
        service, run_ids = pool_service
        view = DivergencePoolView.build(service, run_ids)
        html = render_divergence_pool(view)
        assert "brand-mark" in html
        assert '<svg' in html
        # Logo appears in hero eyebrow and footer
        assert html.count("brand-mark") >= 1

    def test_renders_brand_footer(self, pool_service):
        service, run_ids = pool_service
        view = DivergencePoolView.build(service, run_ids)
        html = render_divergence_pool(view)
        assert "brand-footer" in html
        assert "TradingAgents" in html
        assert "AI 多智能体研究系统" in html

    def test_print_css_present(self, pool_service):
        service, run_ids = pool_service
        view = DivergencePoolView.build(service, run_ids)
        html = render_divergence_pool(view)
        assert "@media print" in html
        assert "page-break-after" in html

    def test_renders_filter_bar(self, pool_service):
        service, run_ids = pool_service
        view = DivergencePoolView.build(service, run_ids)
        html = render_divergence_pool(view)
        assert "filter-bar" in html
        assert "data-filter" in html
        # Should have ALL button and at least one action button
        assert 'data-filter="ALL"' in html
        assert "全部" in html

    def test_stock_cards_have_data_action(self, pool_service):
        service, run_ids = pool_service
        view = DivergencePoolView.build(service, run_ids)
        html = render_divergence_pool(view)
        # Each stock card should have data-action attribute
        import re
        card_actions = re.findall(r'stock-card\s[^"]*" data-action="(\w+)"', html)
        assert len(card_actions) == len(view.rows)

    def test_table_rows_have_data_action(self, pool_service):
        service, run_ids = pool_service
        view = DivergencePoolView.build(service, run_ids)
        html = render_divergence_pool(view)
        import re
        row_actions = re.findall(r'<tr data-action="(\w+)">', html)
        assert len(row_actions) == len(view.rows)

    def test_filter_js_present(self, pool_service):
        service, run_ids = pool_service
        view = DivergencePoolView.build(service, run_ids)
        html = render_divergence_pool(view)
        assert "<script>" in html
        assert "data-filter" in html
        assert "filter-status" in html


# ── Sparkline Rendering ──────────────────────────────────────────────────

class TestSparkline:
    def test_empty_for_insufficient_data(self):
        assert _render_sparkline([]) == ""
        assert _render_sparkline([10.0]) == ""

    def test_renders_svg_polyline(self):
        prices = [10.0, 10.5, 11.0, 10.8, 11.2]
        html = _render_sparkline(prices)
        assert "<svg" in html
        assert "polyline" in html
        assert "sparkline-wrap" in html

    def test_green_for_rising(self):
        prices = [10.0, 10.5, 11.0, 11.5, 12.0]
        html = _render_sparkline(prices)
        assert "#34d399" in html  # green

    def test_red_for_falling(self):
        prices = [12.0, 11.5, 11.0, 10.5, 10.0]
        html = _render_sparkline(prices)
        assert "#f87171" in html  # red

    def test_shows_percent_change(self):
        prices = [10.0, 10.5, 11.0, 10.8, 11.0]
        html = _render_sparkline(prices)
        assert "sparkline-label" in html
        assert "%" in html

    def test_custom_dimensions(self):
        prices = [5, 6, 7, 6, 8]
        html = _render_sparkline(prices, width=80, height=24)
        assert 'width="80"' in html
        assert 'height="24"' in html

    def test_sparkline_in_pool_card_with_prices(self, pool_service):
        """When sparkline_prices are set on a row, pool renders SVG."""
        service, run_ids = pool_service
        view = DivergencePoolView.build(service, run_ids)
        # Inject prices into the first row for testing
        if view.rows:
            view.rows[0].sparkline_prices = [10 + i * 0.5 for i in range(20)]
        html = render_divergence_pool(view)
        assert "sparkline" in html
        assert "polyline" in html


# ── Pool Report Generation Integration ───────────────────────────────────

class TestGeneratePoolReport:
    def test_generates_html_file(self, pool_service, tmp_path):
        service, run_ids = pool_service
        # Patch storage_dir to use the same tmp_path as pool_service
        store_dir = service.store.storage_dir
        out_dir = str(tmp_path / "reports")
        path = generate_pool_report(
            run_ids=run_ids,
            output_dir=out_dir,
            storage_dir=store_dir,
            trade_date="2026-03-13",
        )
        assert path is not None
        assert path.endswith(".html")
        from pathlib import Path
        content = Path(path).read_text(encoding="utf-8")
        assert "多空分歧池" in content
        assert "3stocks" in path or "6stocks" in path or "pool-" in path

    def test_returns_none_for_empty_ids(self, pool_service, tmp_path):
        service, _ = pool_service
        path = generate_pool_report(
            run_ids=[],
            output_dir=str(tmp_path / "reports"),
            storage_dir=service.store.storage_dir,
        )
        assert path is None

    def test_filename_includes_date_and_count(self, pool_service, tmp_path):
        service, run_ids = pool_service
        path = generate_pool_report(
            run_ids=run_ids,
            output_dir=str(tmp_path / "reports"),
            storage_dir=service.store.storage_dir,
            trade_date="2026-03-13",
        )
        assert "20260313" in path
        assert "3stocks" in path

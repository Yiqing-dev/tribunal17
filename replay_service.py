"""
Replay Service — programmatic replay and lineage queries.

Provides the six required replay operations:
    load_run(run_id)
    list_nodes(run_id)
    show_node_input(run_id, node_name)
    show_node_output(run_id, node_name)
    show_lineage(run_id)
    show_failures(run_id)

Plus metrics computation.
"""

import logging
from typing import Dict, List, Optional, Tuple

from .trace_models import NodeTrace, RunTrace, RunMetrics, NodeStatus
from .replay_store import ReplayStore

logger = logging.getLogger(__name__)


class ReplayService:
    """Programmatic interface for replaying and inspecting analysis runs."""

    def __init__(self, store: Optional[ReplayStore] = None):
        self.store = store or ReplayStore()

    # ── Core Replay Operations ───────────────────────────────────────────

    def load_run(self, run_id: str) -> Optional[RunTrace]:
        """Load a complete run trace."""
        return self.store.load(run_id)

    def list_nodes(self, run_id: str) -> List[Dict[str, str]]:
        """List all nodes in execution order with status summary.

        Returns list of dicts: {seq, node_name, status, duration_ms, research_action}
        """
        trace = self.store.load(run_id)
        if not trace:
            return []

        return [
            {
                "seq": nt.seq,
                "node_name": nt.node_name,
                "status": nt.status.value if isinstance(nt.status, NodeStatus) else nt.status,
                "duration_ms": nt.duration_ms,
                "research_action": nt.research_action or "",
                "parse_status": nt.parse_status or "",
            }
            for nt in sorted(trace.node_traces, key=lambda n: n.seq)
        ]

    def show_node_input(self, run_id: str, node_name: str) -> Optional[Dict]:
        """Show input metadata for a specific node.

        Returns input hash, upstream dependencies, and evidence/claim context.
        """
        nt = self._find_node(run_id, node_name)
        if not nt:
            return None

        return {
            "node_name": nt.node_name,
            "seq": nt.seq,
            "input_hash": nt.input_hash,
            "evidence_ids_referenced": nt.evidence_ids_referenced,
            "claim_ids_referenced": nt.claim_ids_referenced,
        }

    def show_node_output(self, run_id: str, node_name: str) -> Optional[Dict]:
        """Show output metadata for a specific node.

        Returns output hash, excerpt, parse quality, structured fields.
        """
        nt = self._find_node(run_id, node_name)
        if not nt:
            return None

        result = {
            "node_name": nt.node_name,
            "seq": nt.seq,
            "status": nt.status.value if isinstance(nt.status, NodeStatus) else nt.status,
            "output_hash": nt.output_hash,
            "output_excerpt": nt.output_excerpt,
            "parse_status": nt.parse_status,
            "parse_confidence": nt.parse_confidence,
            "parse_missing_fields": nt.parse_missing_fields,
            "parse_warnings": nt.parse_warnings,
        }

        # Add role-specific fields
        if nt.claims_produced > 0:
            result["claims_produced"] = nt.claims_produced
            result["claims_attributed"] = nt.claims_attributed
            result["claims_unattributed"] = nt.claims_unattributed
            result["claim_ids_produced"] = nt.claim_ids_produced

        if nt.research_action:
            result["research_action"] = nt.research_action
            result["confidence"] = nt.confidence
            result["thesis_effect"] = nt.thesis_effect
            result["evidence_ids_referenced"] = nt.evidence_ids_referenced
            result["claim_ids_referenced"] = nt.claim_ids_referenced

        if nt.risk_score is not None:
            result["risk_score"] = nt.risk_score
            result["risk_cleared"] = nt.risk_cleared
            result["risk_flag_count"] = nt.risk_flag_count
            result["risk_flag_categories"] = nt.risk_flag_categories
            result["vetoed"] = nt.vetoed
            result["veto_reasons"] = nt.veto_reasons

        if nt.compliance_status:
            result["compliance_status"] = nt.compliance_status
            result["compliance_reasons"] = nt.compliance_reasons
            result["compliance_rules_fired"] = nt.compliance_rules_fired

        if nt.ledger_new_status:
            result["ledger_prev_status"] = nt.ledger_prev_status
            result["ledger_new_status"] = nt.ledger_new_status
            result["ledger_transition_reason"] = nt.ledger_transition_reason

        if nt.errors:
            result["errors"] = nt.errors

        # Always expose structured_data (empty dict for old traces)
        result["structured_data"] = nt.structured_data

        return result

    def show_lineage(self, run_id: str) -> Optional[Dict]:
        """Show full evidence → claim → synthesis → risk → compliance lineage.

        Answers: "For the final decision, what evidence was cited, what claims
        were made, how were they arbitrated, and what compliance gate fired?"
        """
        trace = self.store.load(run_id)
        if not trace:
            return None

        lineage = {
            "run_id": run_id,
            "ticker": trace.ticker,
            "trade_date": trace.trade_date,
            "research_action": trace.research_action,
            "was_vetoed": trace.was_vetoed,
            "compliance_status": trace.compliance_status,
            "stages": [],
        }

        # Group by node, in execution order
        for nt in sorted(trace.node_traces, key=lambda n: n.seq):
            stage = {
                "seq": nt.seq,
                "node": nt.node_name,
                "status": nt.status.value if isinstance(nt.status, NodeStatus) else nt.status,
            }

            # Evidence layer
            if nt.evidence_ids_referenced:
                stage["evidence_consumed"] = nt.evidence_ids_referenced

            # Claim layer
            if nt.claim_ids_produced:
                stage["claims_produced"] = nt.claim_ids_produced
                stage["attributed"] = nt.claims_attributed
                stage["unattributed"] = nt.claims_unattributed
            if nt.claim_ids_referenced:
                stage["claims_consumed"] = nt.claim_ids_referenced

            # Synthesis layer
            if nt.research_action:
                stage["decision"] = {
                    "action": nt.research_action,
                    "confidence": nt.confidence,
                    "thesis_effect": nt.thesis_effect,
                }

            # Risk layer
            if nt.risk_flag_count > 0 or nt.vetoed:
                stage["risk"] = {
                    "flags": nt.risk_flag_count,
                    "categories": nt.risk_flag_categories,
                    "vetoed": nt.vetoed,
                    "veto_reasons": nt.veto_reasons,
                }

            # Compliance layer
            if nt.compliance_status:
                stage["compliance"] = {
                    "status": nt.compliance_status,
                    "reasons": nt.compliance_reasons,
                    "rules_fired": nt.compliance_rules_fired,
                }

            # Ledger layer
            if nt.ledger_new_status:
                stage["ledger"] = {
                    "prev": nt.ledger_prev_status,
                    "new": nt.ledger_new_status,
                    "reason": nt.ledger_transition_reason,
                }

            lineage["stages"].append(stage)

        return lineage

    def show_failures(self, run_id: str) -> Optional[List[Dict]]:
        """Show all nodes that errored, warned, or had degraded parse quality.

        This is the primary debugging entry point.
        """
        trace = self.store.load(run_id)
        if not trace:
            return None

        failures = []
        for nt in sorted(trace.node_traces, key=lambda n: n.seq):
            issues = []

            if nt.status == NodeStatus.ERROR:
                issues.append({"type": "error", "details": nt.errors})

            if nt.parse_status in ("fallback_used", "failed"):
                issues.append({
                    "type": "parse_degraded",
                    "parse_status": nt.parse_status,
                    "missing_fields": nt.parse_missing_fields,
                    "warnings": nt.parse_warnings,
                })

            if nt.vetoed:
                issues.append({
                    "type": "vetoed",
                    "reasons": nt.veto_reasons,
                })

            if nt.compliance_status in ("block", "review"):
                issues.append({
                    "type": "compliance_escalation",
                    "status": nt.compliance_status,
                    "reasons": nt.compliance_reasons,
                })

            if nt.claims_unattributed > 0:
                issues.append({
                    "type": "unattributed_claims",
                    "count": nt.claims_unattributed,
                })

            if issues:
                failures.append({
                    "seq": nt.seq,
                    "node_name": nt.node_name,
                    "status": nt.status.value if isinstance(nt.status, NodeStatus) else nt.status,
                    "issues": issues,
                })

        return failures

    # ── Metrics Computation ──────────────────────────────────────────────

    def compute_metrics(self, run_id: str) -> Optional[RunMetrics]:
        """Compute RunMetrics from a stored trace."""
        trace = self.store.load(run_id)
        if not trace:
            return None
        return self._metrics_from_trace(trace)

    def compute_metrics_from_trace(self, trace: RunTrace) -> RunMetrics:
        """Compute RunMetrics from an in-memory trace (no store lookup)."""
        return self._metrics_from_trace(trace)

    def _metrics_from_trace(self, trace: RunTrace) -> RunMetrics:
        """Internal: compute all metrics from a RunTrace."""
        m = RunMetrics(run_id=trace.run_id)

        # --- Parse quality rates ---
        parseable_nodes = [
            nt for nt in trace.node_traces if nt.parse_status != ""
        ]
        if parseable_nodes:
            m.strict_parse_rate = (
                sum(1 for n in parseable_nodes if n.parse_status == "strict_ok")
                / len(parseable_nodes)
            )
            m.fallback_rate = (
                sum(1 for n in parseable_nodes if n.parse_status == "fallback_used")
                / len(parseable_nodes)
            )
            m.failed_rate = (
                sum(1 for n in parseable_nodes if n.parse_status == "failed")
                / len(parseable_nodes)
            )

        # --- Claim / evidence binding ---
        total_produced = 0
        total_attributed = 0
        pm_consumed_claims = set()
        has_structured_claims = False

        for nt in trace.node_traces:
            total_produced += nt.claims_produced
            total_attributed += nt.claims_attributed
            m.total_evidence_referenced += len(nt.evidence_ids_referenced)

            if nt.node_name in ("Bull Researcher", "Bear Researcher") and nt.claims_produced > 0:
                has_structured_claims = True

            if nt.node_name == "Research Manager":
                pm_consumed_claims.update(nt.claim_ids_referenced)

        m.total_claims_produced = total_produced
        m.total_claims_attributed = total_attributed

        if total_produced > 0:
            m.claim_to_evidence_binding_rate = total_attributed / total_produced
            m.pm_claim_consumption_rate = len(pm_consumed_claims) / total_produced
        m.narrative_dependency_rate = 0.0 if has_structured_claims else 1.0

        # --- Risk flag traceability ---
        risk_nodes = [nt for nt in trace.node_traces if nt.risk_flag_count > 0]
        total_flags = sum(nt.risk_flag_count for nt in risk_nodes)
        # Flags with evidence = flags whose categories are captured (proxy: categories list length)
        flags_with_evidence = sum(
            min(nt.risk_flag_count, len(nt.risk_flag_categories))
            for nt in risk_nodes
        )
        m.total_risk_flags = total_flags
        m.risk_flags_with_evidence = flags_with_evidence
        if total_flags > 0:
            m.risk_flag_traceability_rate = flags_with_evidence / total_flags

        # --- Compliance ---
        compliance_nodes = [nt for nt in trace.node_traces if nt.compliance_status]
        if compliance_nodes:
            total_rules = sum(len(nt.compliance_rules_fired) for nt in compliance_nodes)
            # We check 5 rules per node; capture rate = rules fired / (5 * nodes)
            expected_rules = 5 * len(compliance_nodes)
            m.compliance_reason_capture_rate = total_rules / expected_rules if expected_rules else 0.0

        # --- Replay completeness ---
        # Expected nodes depends on graph path; approximate from known core nodes
        CORE_NODES = {
            "Market Analyst", "Social Analyst", "News Analyst", "Fundamentals Analyst",
            "Catalyst Agent", "Bull Researcher", "Bear Researcher", "Scenario Agent",
            "Research Manager", "Risk Judge", "ResearchOutput",
        }
        traced_core = {nt.node_name for nt in trace.node_traces} & CORE_NODES
        m.replay_completeness_rate = len(traced_core) / len(CORE_NODES)

        return m

    # ── Internal Helpers ────────────────────────────────────────────────

    def _find_node(self, run_id: str, node_name: str) -> Optional[NodeTrace]:
        """Find a specific node trace within a run."""
        trace = self.store.load(run_id)
        if not trace:
            return None
        for nt in trace.node_traces:
            if nt.node_name == node_name:
                return nt
        return None

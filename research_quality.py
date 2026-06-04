"""Research-quality evaluation — measures the *internal* quality of a research
report (论据完整度、证据覆盖率、辩论交锋强度、可证伪条件具体度等), without
needing forward price data.

Why this exists: Win-rate / direction-accuracy framing assumes the system is a
price predictor, but the LLM 17-司 architecture is better positioned as a
"research report factory" (信息综合 + 风险列举 + 多视角论证). This module gives
the project a **price-free** quality yardstick.

Output:
    ResearchQualityRecord — per-run scorecard with 7 sub-scores + composite
    grade (A/B/C/D). Aggregatable via build_quality_summary().

Inputs are RunTrace dicts or RunTrace JSONs already persisted in a replay
store. No external network calls, no LLM calls.
"""

import json
import re
import statistics
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Dict, List, Optional, Any


# ── Data model ──────────────────────────────────────────────────────────


@dataclass
class ResearchQualityRecord:
    """Per-run research-quality scorecard."""
    run_id: str = ""
    ticker: str = ""
    ticker_name: str = ""
    trade_date: str = ""

    # Seven sub-scores (each 0.0 - 1.0)
    pillar_coverage: float = 0.0          # 4 analyst pillars all scored
    evidence_binding_rate: float = 0.0    # claims with [E#] binding ratio
    debate_engagement: float = 0.0        # R2 cross-references R1 claim_ids
    falsifiability_score: float = 0.0     # invalidators have concrete triggers
    data_freshness: float = 0.0           # node completion / api success proxy
    scenario_diversity: float = 0.0       # base/bull/bear probs not all-base
    industry_context_present: float = 0.0  # 0 or 1

    # Aggregates
    composite_score: float = 0.0          # 0.0 - 1.0 weighted average
    composite_grade: str = "D"            # A / B / C / D

    # Diagnostic flags (text)
    weak_dimensions: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ── Sub-score helpers ───────────────────────────────────────────────────


_ANALYST_NODES = (
    "Market Analyst", "Fundamentals Analyst",
    "News Analyst", "Social Analyst",
)


def _score_pillar_coverage(trace: dict) -> float:
    """4/4 pillars score with non-negative pillar_score → full credit."""
    found = 0
    for nt in trace.get("node_traces", []):
        if nt.get("node_name") in _ANALYST_NODES:
            sd = nt.get("structured_data") or {}
            ps = sd.get("pillar_score")
            if ps is not None and isinstance(ps, (int, float)) and ps >= 0:
                found += 1
    return min(found / 4.0, 1.0)


def _score_evidence_binding(trace: dict) -> float:
    """Fraction of bull/bear claims that bind to at least one [E#] / claim_id.

    Uses the same data the renderers consume. Falls back to 0 when there are
    no claims at all (a degraded run).
    """
    bound = total = 0
    for nt in trace.get("node_traces", []):
        if nt.get("node_name") not in ("Bull Researcher", "Bear Researcher"):
            continue
        sd = nt.get("structured_data") or {}
        for key in ("supporting_claims", "opposing_claims"):
            for c in sd.get(key) or []:
                if not isinstance(c, dict):
                    continue
                total += 1
                supports = c.get("supports") or []
                opposes = c.get("opposes") or []
                if (isinstance(supports, list) and supports) or (
                    isinstance(opposes, list) and opposes
                ):
                    bound += 1
    return (bound / total) if total else 0.0


def _score_debate_engagement(trace: dict) -> float:
    """Crude proxy: did Round 2 add new claims / reply structure?

    We don't have R1 vs R2 cleanly separated in the trace (claims are merged),
    but we can detect engagement by counting:
      - Whether bear has any opposing_claims at all (vs only its own thesis)
      - Whether unresolved_conflicts list is non-empty (means debaters
        identified disagreements rather than echo each other)
      - Total bull + bear claim count >= 8 (rich debate)
    """
    bull_node = bear_node = None
    for nt in trace.get("node_traces", []):
        if nt.get("node_name") == "Bull Researcher":
            bull_node = nt
        elif nt.get("node_name") == "Bear Researcher":
            bear_node = nt

    if not bull_node or not bear_node:
        return 0.0

    bull_sd = bull_node.get("structured_data") or {}
    bear_sd = bear_node.get("structured_data") or {}

    bull_claims = len(bull_sd.get("supporting_claims") or [])
    bear_claims = len(bear_sd.get("supporting_claims") or []) + len(
        bear_sd.get("opposing_claims") or []
    )

    rich_count = 1.0 if (bull_claims + bear_claims) >= 8 else (
        0.5 if (bull_claims + bear_claims) >= 4 else 0.0
    )

    # AQ-01: real clash is now measurable via opposing_claims (REBUT blocks
    # targeting the other side's specific claims). No rebuttals AND no flagged
    # conflicts = two monologues → a genuine low score, not the old undeserved
    # 0.5 soft default that gave hollow debates half credit.
    n_rebuttals = len(bull_sd.get("opposing_claims") or []) + len(
        bear_sd.get("opposing_claims") or []
    )
    has_conflicts = bool(
        (bull_sd.get("unresolved_conflicts") or [])
        or (bear_sd.get("unresolved_conflicts") or [])
    )
    if has_conflicts or n_rebuttals >= 2:
        conflict_score = 1.0
    elif n_rebuttals == 1:
        conflict_score = 0.5
    else:
        conflict_score = 0.2

    # Both sides scored dimensions = real engagement
    has_dim_scores = bool(
        (bull_sd.get("dimension_scores") or {})
        and (bear_sd.get("dimension_scores") or {})
    )
    dim_score = 1.0 if has_dim_scores else 0.5

    return (rich_count * 0.5) + (conflict_score * 0.25) + (dim_score * 0.25)


_PRICE_LIKE_RE = re.compile(
    r"\d+\.\d{1,3}|\d+\s*%|\d+\s*亿|\d+\s*万|\d+\s*元|\d{4}-\d{2}-\d{2}|\d{1,2}\s*月\s*\d{1,2}\s*日"
)
_VAGUE_TOKENS = ("市场转弱", "情况恶化", "风险上升", "若发生不利", "如果失败")


def _score_falsifiability(trace: dict) -> float:
    """Fraction of invalidation_conditions that contain concrete triggers
    (numeric thresholds, dates, percentages) rather than vague language.
    """
    conditions: List[str] = []
    for nt in trace.get("node_traces", []):
        if nt.get("node_name") in ("Research Manager", "Risk Judge"):
            sd = nt.get("structured_data") or {}
            for c in sd.get("invalidation_conditions") or []:
                if c:
                    conditions.append(str(c))

    if not conditions:
        return 0.0

    concrete = 0
    for c in conditions:
        has_number = bool(_PRICE_LIKE_RE.search(c))
        is_vague = any(vt in c for vt in _VAGUE_TOKENS) and not has_number
        if has_number and not is_vague:
            concrete += 1
    return concrete / len(conditions)


def _score_data_freshness(trace: dict) -> float:
    """Proxy: fraction of nodes that completed without error.

    A real freshness measure would use akshare apis_failed list, but that's
    captured at collection time, not in the trace. node-level completion is a
    reasonable runtime proxy.
    """
    total = trace.get("total_nodes", 0) or 0
    err = trace.get("error_count", 0) or 0
    if total == 0:
        return 0.0
    ok = max(total - err, 0)
    return ok / total


def _score_scenario_diversity(trace: dict) -> float:
    """Three-scenario probabilities should not collapse onto one bucket.

    Healthy: all three between 0.10 and 0.70.
    Degenerate: any single bucket >= 0.85 (no real disagreement modeled).
    """
    for nt in trace.get("node_traces", []):
        if nt.get("node_name") == "Scenario Agent":
            sd = nt.get("structured_data") or {}
            base = float(sd.get("base_prob") or 0)
            bull = float(sd.get("bull_prob") or 0)
            bear = float(sd.get("bear_prob") or 0)
            total = base + bull + bear
            if total <= 0:
                return 0.0
            # Normalize defensively (LLM outputs sometimes don't sum to 1)
            base /= total
            bull /= total
            bear /= total
            if max(base, bull, bear) >= 0.85:
                return 0.3  # degenerate
            if min(base, bull, bear) < 0.05:
                return 0.6  # mildly degenerate
            return 1.0
    return 0.0


def _score_industry_context(trace: dict) -> float:
    """1 if Fundamentals Analyst node has industry_compare dict populated."""
    for nt in trace.get("node_traces", []):
        if nt.get("node_name") == "Fundamentals Analyst":
            sd = nt.get("structured_data") or {}
            ic = sd.get("industry_compare") or {}
            if ic and ic.get("industry_name"):
                return 1.0
    return 0.0


# ── Composite + grading ────────────────────────────────────────────────


_WEIGHTS = {
    "pillar_coverage":       0.18,
    "evidence_binding_rate": 0.20,
    "debate_engagement":     0.18,
    "falsifiability_score":  0.16,
    "data_freshness":        0.10,
    "scenario_diversity":    0.10,
    "industry_context_present": 0.08,
}


def _grade(score: float) -> str:
    if score >= 0.85:
        return "A"
    if score >= 0.70:
        return "B"
    if score >= 0.55:
        return "C"
    return "D"


def evaluate_run_quality(
    run_id: str,
    storage_dir: str = "data/replays",
) -> Optional[ResearchQualityRecord]:
    """Load a RunTrace JSON and compute its quality scorecard."""
    path = Path(storage_dir) / f"{run_id}.json"
    if not path.exists():
        return None
    try:
        trace = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

    rec = evaluate_trace_quality(trace)
    rec.run_id = run_id
    return rec


def evaluate_trace_quality(trace: dict) -> ResearchQualityRecord:
    """Compute a quality scorecard from an in-memory RunTrace dict.

    Renderers often receive traces from a caller-provided ReplayStore rather
    than the default ``data/replays`` directory. Keeping the scoring path
    in-memory prevents quality badges from silently disappearing when a custom
    replay path is used.
    """
    meta = trace.get("meta", {}) if isinstance(trace.get("meta", {}), dict) else {}
    rec = ResearchQualityRecord(
        run_id=trace.get("run_id", "") or meta.get("run_id", ""),
        ticker=trace.get("ticker", "") or meta.get("ticker", ""),
        ticker_name=trace.get("ticker_name", "") or meta.get("ticker_name", ""),
        trade_date=trace.get("trade_date", "") or meta.get("trade_date", ""),
    )

    rec.pillar_coverage = _score_pillar_coverage(trace)
    rec.evidence_binding_rate = _score_evidence_binding(trace)
    rec.debate_engagement = _score_debate_engagement(trace)
    rec.falsifiability_score = _score_falsifiability(trace)
    rec.data_freshness = _score_data_freshness(trace)
    rec.scenario_diversity = _score_scenario_diversity(trace)
    rec.industry_context_present = _score_industry_context(trace)

    rec.composite_score = sum(
        getattr(rec, k) * w for k, w in _WEIGHTS.items()
    )
    rec.composite_grade = _grade(rec.composite_score)

    # Diagnostic notes — list dimensions below 0.5
    for k in _WEIGHTS:
        if getattr(rec, k) < 0.5:
            rec.weak_dimensions.append(k)
    if not rec.weak_dimensions:
        rec.notes.append("无显著薄弱维度")

    return rec


# ── Aggregation ────────────────────────────────────────────────────────


@dataclass
class ResearchQualitySummary:
    """Aggregate quality stats across a batch of runs."""
    n: int = 0
    grade_dist: Dict[str, int] = field(default_factory=dict)
    avg_composite: float = 0.0
    dimension_avgs: Dict[str, float] = field(default_factory=dict)
    weakest_dimension: str = ""
    weakest_dim_avg: float = 1.0
    records: List[ResearchQualityRecord] = field(default_factory=list)

    def to_markdown(self) -> str:
        lines = [
            f"# 研究质量汇总（{self.n} 份报告）",
            "",
            f"综合得分均值: **{self.avg_composite:.2f}** / 1.00",
            "",
            "## 等级分布",
        ]
        for g in ("A", "B", "C", "D"):
            n = self.grade_dist.get(g, 0)
            bar = "█" * n
            lines.append(f"- {g}: {n} 份  {bar}")
        lines.append("")
        lines.append("## 维度均值")
        lines.append("| 维度 | 均分 |")
        lines.append("|------|------|")
        for k in _WEIGHTS:
            v = self.dimension_avgs.get(k, 0)
            lines.append(f"| {k} | {v:.2f} |")
        lines.append("")
        lines.append(f"**最薄弱维度**: `{self.weakest_dimension}` (均分 {self.weakest_dim_avg:.2f})")
        lines.append("")
        lines.append("## 个股明细")
        lines.append("| 标的 | Grade | 综合 | 薄弱维度 |")
        lines.append("|------|-------|------|---------|")
        for r in self.records:
            wk = ", ".join(r.weak_dimensions[:3]) if r.weak_dimensions else "—"
            lines.append(
                f"| {r.ticker} {r.ticker_name} | {r.composite_grade} | "
                f"{r.composite_score:.2f} | {wk} |"
            )
        return "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "n": self.n,
            "grade_dist": self.grade_dist,
            "avg_composite": self.avg_composite,
            "dimension_avgs": self.dimension_avgs,
            "weakest_dimension": self.weakest_dimension,
            "weakest_dim_avg": self.weakest_dim_avg,
            "records": [r.to_dict() for r in self.records],
        }


def build_quality_summary(
    run_ids: List[str],
    storage_dir: str = "data/replays",
) -> ResearchQualitySummary:
    """Aggregate quality across a batch of runs."""
    s = ResearchQualitySummary()
    for rid in run_ids:
        rec = evaluate_run_quality(rid, storage_dir=storage_dir)
        if rec is None:
            continue
        s.records.append(rec)
        s.grade_dist[rec.composite_grade] = (
            s.grade_dist.get(rec.composite_grade, 0) + 1
        )

    s.n = len(s.records)
    if s.n == 0:
        return s

    s.avg_composite = statistics.mean(r.composite_score for r in s.records)
    for k in _WEIGHTS:
        s.dimension_avgs[k] = statistics.mean(getattr(r, k) for r in s.records)

    weakest = min(s.dimension_avgs.items(), key=lambda kv: kv[1])
    s.weakest_dimension = weakest[0]
    s.weakest_dim_avg = weakest[1]
    return s

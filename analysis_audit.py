"""Analysis quality audit — measures *process* quality, not prediction accuracy.

This module is the deliberate counterweight to `backtest.py`.  Backtest asks
"were we right?"  Audit asks "did we reason well?"  Long-term analytical
health depends on the second question, not the first — a system that reasons
rigorously will eventually calibrate; a system that chases short-term
accuracy via rule patches will overfit and collapse.

Five quality dimensions, all derived from existing RunTrace fields (no new
LLM calls):

  1. Evidence chain completeness — did the pipeline cite concrete evidence?
  2. Falsifiability — did bull/bear cases state invalidation conditions?
  3. HOLD explicitness — when action=HOLD, are buy/sell triggers defined?
  4. Claim adjudication — did PM actually resolve bull/bear conflicts (M2a)?
  5. Confidence distribution — is confidence varied or stuck at defaults?

Usage:
    from subagent_pipeline.analysis_audit import audit_batch
    report = audit_batch(run_ids, storage_dir="data/replays")
    print(report.to_markdown())
    report.save_json("data/reports")

Design:
  - No accuracy / outcome comparison — that's backtest.py's job.
  - All metrics are *observable at write-time* — no forward-looking data needed.
  - Deliberately tolerant: a single low-quality run doesn't fail the batch;
    we report distributions so systemic issues surface.
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .replay_store import ReplayStore
from .trace_models import RunTrace

logger = logging.getLogger(__name__)


# ── Heuristic regexes for falsifiability / trigger detection ─────────────

# "若...则" / "if...then" / "break below X" / specific price+date patterns
_FALSIFIABLE_PATTERNS = [
    re.compile(r"若.{1,40}(破|跌破|低于|失守|高于|突破)"),
    re.compile(r"如果.{1,40}(小于|大于|低于|高于|未能)"),
    re.compile(r"若.{1,40}(无法|未|不能)"),
    re.compile(r"invalidat", re.IGNORECASE),
    re.compile(r"break(s|ing)?\s+(below|above)", re.IGNORECASE),
    re.compile(r"(目标|止损|stop[_\s]?loss|target)\s*[:=：]?\s*\d"),
]

_TRIGGER_PATTERNS_BUY = [
    re.compile(r"(买入|加仓|买点|多头|BUY).{0,30}(触发|条件|trigger)", re.IGNORECASE),
    re.compile(r"(buy|加仓)[_\s-]?(trigger|point)", re.IGNORECASE),
    re.compile(r"(突破|收盘站上|站稳|向上).{0,30}\d"),
]

_TRIGGER_PATTERNS_SELL = [
    re.compile(r"(卖出|减仓|卖点|空头|SELL|止损).{0,30}(触发|条件|trigger)", re.IGNORECASE),
    re.compile(r"(sell|stop|exit)[_\s-]?(trigger|loss)", re.IGNORECASE),
    re.compile(r"(跌破|失守|收盘跌破|破位).{0,30}\d"),
]


# ── Data models ──────────────────────────────────────────────────────────


@dataclass
class AuditRecord:
    """Per-run process quality assessment."""

    run_id: str = ""
    ticker: str = ""
    ticker_name: str = ""
    trade_date: str = ""

    # 1. Evidence chain
    evidence_citation_count: int = 0     # total unique [E#] references across nodes
    analysts_with_evidence: int = 0      # 0-4 (market/fund/news/sentiment)
    pm_cites_evidence: bool = False
    risk_mgr_binds_evidence: bool = False # risk_flags have bound_evidence_ids

    # 2. Falsifiability
    bull_case_falsifiable: bool = False
    bear_case_falsifiable: bool = False
    invalidation_count: int = 0          # how many invalidation conditions

    # 3. HOLD explicitness
    action: str = ""
    hold_has_buy_trigger: Optional[bool] = None  # None if not HOLD
    hold_has_sell_trigger: Optional[bool] = None

    # 4. Claim adjudication
    pm_claim_references: int = 0         # # of clm-* refs in PM output
    claims_produced_total: int = 0       # total claims from bull+bear

    # 5. Confidence quality
    confidence: float = -1.0
    confidence_at_default: bool = False  # in (0.48-0.52, 0.58-0.62) — stuck cluster

    # Warnings: human-readable quality issues
    warnings: List[str] = field(default_factory=list)

    # Computed summary
    quality_score: float = 0.0           # 0-10 composite, see compute_quality_score()

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AuditReport:
    """Batch audit — process quality across many runs."""

    generated_at: str = ""
    run_count: int = 0
    records: List[AuditRecord] = field(default_factory=list)

    # Aggregate percentages (0-100)
    evidence_coverage_pct: float = 0.0          # % runs with ≥1 analyst citing evidence
    pm_evidence_pct: float = 0.0                # % runs where PM cites evidence
    falsifiability_pct: float = 0.0             # % runs where bull+bear both falsifiable
    hold_explicitness_pct: float = 0.0          # % HOLD runs with both buy+sell triggers
    avg_claim_adjudication: float = 0.0         # avg # of clm-* refs by PM

    # Confidence distribution
    confidence_buckets: Dict[str, int] = field(default_factory=dict)
    confidence_default_cluster_pct: float = 0.0 # % runs stuck at 0.5/0.58/0.62

    # Action distribution
    action_distribution: Dict[str, int] = field(default_factory=dict)

    # Top recurring warnings (systemic issues)
    top_warnings: List[Dict[str, Any]] = field(default_factory=list)

    # Composite health score
    overall_quality_score: float = 0.0          # avg of per-run scores

    def to_markdown(self) -> str:
        lines = [
            f"# 分析质量审计 ({self.generated_at})",
            "",
            f"样本: **{self.run_count}** 次分析 | 整体质量评分: **{self.overall_quality_score:.1f}/10**",
            "",
            "> 本报告衡量**推理过程质量**，不是预测准确率。目标是长期健康的分析，不是短期命中。",
            "",
            "## 一、证据链完整度",
            f"- 至少一位分析师引用证据: **{self.evidence_coverage_pct:.0f}%**",
            f"- 研究总监 (PM) 引用证据: **{self.pm_evidence_pct:.0f}%**",
            "",
            "## 二、可证伪性（bull/bear 是否给出失败条件）",
            f"- 双方均含可证伪条件: **{self.falsifiability_pct:.0f}%**",
            "",
            "## 三、HOLD 明确性（HOLD 是否有具体触发）",
            f"- HOLD 同时含 buy+sell 触发: **{self.hold_explicitness_pct:.0f}%**",
            "",
            "## 四、Claim 裁决深度",
            f"- PM 平均引用 claim 数: **{self.avg_claim_adjudication:.1f}** (目标 ≥5)",
            "",
            "## 五、置信度分布",
        ]
        for bucket, count in sorted(self.confidence_buckets.items()):
            lines.append(f"- {bucket}: {count}")
        lines.extend([
            f"- 陷入默认值簇 (0.50/0.58/0.62): **{self.confidence_default_cluster_pct:.0f}%**",
            "",
            "## 六、Action 分布",
        ])
        for a, c in sorted(self.action_distribution.items()):
            pct = 100.0 * c / self.run_count if self.run_count else 0
            lines.append(f"- {a}: {c} ({pct:.0f}%)")
        lines.extend(["", "## 七、Top 质量警告（系统性问题）"])
        if self.top_warnings:
            for w in self.top_warnings[:10]:
                lines.append(f"- **{w['warning']}** — {w['count']} 次")
        else:
            lines.append("- *无系统性警告*")
        lines.extend([
            "",
            "---",
            "*此审计只看过程，不看结果。想改善预测准确率请看 backtest 报告。*",
            "*想改善这些指标：在 prompt 层强化 evidence/falsifiability/trigger 要求，而非加新规则。*",
        ])
        return "\n".join(lines)

    def save_json(self, output_dir: str) -> Path:
        path = Path(output_dir) / f"analysis_audit_{self.generated_at.replace(':', '-')}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        data = asdict(self)
        # atomic write
        tmp_fd, tmp_path = tempfile.mkstemp(
            prefix=".audit-", suffix=".tmp", dir=str(path.parent)
        )
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2, default=str, allow_nan=False)
            os.replace(tmp_path, path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
        return path


# ── Core audit logic ─────────────────────────────────────────────────────


def _confidence_bucket(c: float) -> str:
    if c < 0:
        return "unset"
    if c < 0.3:
        return "0.0-0.3"
    if c < 0.5:
        return "0.3-0.5"
    if c < 0.7:
        return "0.5-0.7"
    if c < 0.85:
        return "0.7-0.85"
    return "0.85+"


def _is_default_cluster(c: float) -> bool:
    """True if confidence is suspiciously close to commonly-defaulted values."""
    if c < 0:
        return False
    for default in (0.50, 0.55, 0.58, 0.60, 0.62):
        if abs(c - default) < 0.015:
            return True
    return False


def _text_is_falsifiable(text: str) -> bool:
    if not text:
        return False
    return any(p.search(text) for p in _FALSIFIABLE_PATTERNS)


def _has_trigger(text: str, direction: str) -> bool:
    patterns = _TRIGGER_PATTERNS_BUY if direction == "buy" else _TRIGGER_PATTERNS_SELL
    return any(p.search(text) for p in patterns)


def audit_run(trace: RunTrace) -> AuditRecord:
    """Compute a process-quality record for a single RunTrace."""
    rec = AuditRecord(
        run_id=trace.run_id,
        ticker=trace.ticker,
        ticker_name=getattr(trace, "ticker_name", ""),
        trade_date=trace.trade_date,
        action=trace.research_action or "",
        confidence=getattr(trace, "final_confidence", -1.0),
    )
    rec.confidence_at_default = _is_default_cluster(rec.confidence)

    # Collect per-node
    all_evidence_ids: set = set()
    analyst_names = {"Market Analyst", "Fundamentals Analyst", "News Analyst", "Social Analyst"}
    analysts_with_ev = 0

    pm_output = ""
    pm_structured: Dict[str, Any] = {}
    rm_structured: Dict[str, Any] = {}
    bull_structured: Dict[str, Any] = {}
    bear_structured: Dict[str, Any] = {}
    claims_total = 0

    for nt in trace.node_traces:
        all_evidence_ids.update(nt.evidence_ids_referenced or [])
        if nt.node_name in analyst_names and nt.evidence_ids_referenced:
            analysts_with_ev += 1
        if nt.node_name == "Research Manager":
            rec.pm_cites_evidence = bool(nt.evidence_ids_referenced)
            pm_output = nt.output_excerpt or ""
            pm_structured = nt.structured_data or {}
            rec.pm_claim_references = len(nt.claim_ids_referenced or [])
        elif nt.node_name == "Risk Judge":
            rm_structured = nt.structured_data or {}
            rf = rm_structured.get("risk_flags", []) if isinstance(rm_structured, dict) else []
            rec.risk_mgr_binds_evidence = any(
                bool(f.get("bound_evidence_ids")) for f in rf if isinstance(f, dict)
            )
        elif nt.node_name == "Bull Researcher":
            bull_structured = nt.structured_data or {}
            claims_total += nt.claims_produced or 0
        elif nt.node_name == "Bear Researcher":
            bear_structured = nt.structured_data or {}
            claims_total += nt.claims_produced or 0

    rec.evidence_citation_count = len(all_evidence_ids)
    rec.analysts_with_evidence = analysts_with_ev
    rec.claims_produced_total = claims_total

    # Falsifiability: check PM's bull/bear cases
    bull_text = str(pm_structured.get("bull_case", ""))
    bear_text = str(pm_structured.get("bear_case", ""))
    rec.bull_case_falsifiable = _text_is_falsifiable(bull_text)
    rec.bear_case_falsifiable = _text_is_falsifiable(bear_text)

    invalidations = pm_structured.get("invalidation_conditions", [])
    if isinstance(invalidations, list):
        rec.invalidation_count = len([x for x in invalidations if x])

    # HOLD explicitness: check PM's output for buy/sell triggers
    if rec.action == "HOLD":
        combined = pm_output + "\n" + bull_text + "\n" + bear_text + "\n" + str(invalidations)
        rec.hold_has_buy_trigger = _has_trigger(combined, "buy")
        rec.hold_has_sell_trigger = _has_trigger(combined, "sell")

    # Warnings
    if rec.analysts_with_evidence < 2:
        rec.warnings.append("<2 analysts cited evidence")
    if not rec.pm_cites_evidence:
        rec.warnings.append("PM did not cite evidence")
    if not (rec.bull_case_falsifiable and rec.bear_case_falsifiable):
        rec.warnings.append("bull or bear case not falsifiable")
    if rec.action == "HOLD" and not (rec.hold_has_buy_trigger and rec.hold_has_sell_trigger):
        rec.warnings.append("HOLD without explicit buy+sell triggers")
    if rec.pm_claim_references < 3:
        rec.warnings.append("PM adjudicated <3 claims (M2a weak)")
    if rec.confidence_at_default:
        rec.warnings.append(f"confidence stuck at default cluster ({rec.confidence:.2f})")
    if not rec.risk_mgr_binds_evidence:
        rec.warnings.append("risk flags not bound to evidence")

    rec.quality_score = _compute_quality_score(rec)
    return rec


def _compute_quality_score(rec: AuditRecord) -> float:
    """Composite 0-10 score — evenly weighted across the 5 dimensions."""
    score = 0.0
    # Evidence (2 pts)
    score += 1.0 * min(rec.analysts_with_evidence, 4) / 4.0 * 2
    # PM evidence (2 pts)
    if rec.pm_cites_evidence:
        score += 2.0
    # Falsifiability (2 pts)
    if rec.bull_case_falsifiable:
        score += 1.0
    if rec.bear_case_falsifiable:
        score += 1.0
    # HOLD triggers (2 pts — full if not HOLD, else based on triggers)
    if rec.action != "HOLD":
        score += 2.0
    else:
        if rec.hold_has_buy_trigger:
            score += 1.0
        if rec.hold_has_sell_trigger:
            score += 1.0
    # Claim adjudication + confidence quality (2 pts)
    score += min(rec.pm_claim_references, 6) / 6.0 * 1.5
    if not rec.confidence_at_default and rec.confidence > 0:
        score += 0.5
    return round(score, 2)


def audit_batch(
    run_ids: List[str],
    storage_dir: str = "data/replays",
) -> AuditReport:
    """Audit many runs; return aggregated report."""
    store = ReplayStore(storage_dir=storage_dir)
    records: List[AuditRecord] = []
    for rid in run_ids:
        try:
            trace = store.load(rid)
        except Exception as e:
            logger.warning("Audit: failed to load %s: %s", rid, e)
            continue
        if not trace:
            continue
        try:
            records.append(audit_run(trace))
        except Exception as e:
            logger.warning("Audit: failed on %s: %s", rid, e)

    report = AuditReport(
        generated_at=datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        run_count=len(records),
        records=records,
    )
    if not records:
        return report

    n = len(records)
    report.evidence_coverage_pct = 100.0 * sum(1 for r in records if r.analysts_with_evidence >= 1) / n
    report.pm_evidence_pct = 100.0 * sum(1 for r in records if r.pm_cites_evidence) / n
    report.falsifiability_pct = 100.0 * sum(
        1 for r in records if r.bull_case_falsifiable and r.bear_case_falsifiable
    ) / n
    hold_rs = [r for r in records if r.action == "HOLD"]
    if hold_rs:
        report.hold_explicitness_pct = 100.0 * sum(
            1 for r in hold_rs if r.hold_has_buy_trigger and r.hold_has_sell_trigger
        ) / len(hold_rs)
    report.avg_claim_adjudication = sum(r.pm_claim_references for r in records) / n
    report.confidence_default_cluster_pct = 100.0 * sum(
        1 for r in records if r.confidence_at_default
    ) / n

    # Buckets
    bucket_counter: Counter = Counter()
    for r in records:
        bucket_counter[_confidence_bucket(r.confidence)] += 1
    report.confidence_buckets = dict(bucket_counter)

    action_counter: Counter = Counter()
    for r in records:
        action_counter[r.action or "UNSET"] += 1
    report.action_distribution = dict(action_counter)

    warning_counter: Counter = Counter()
    for r in records:
        for w in r.warnings:
            warning_counter[w] += 1
    report.top_warnings = [
        {"warning": w, "count": c}
        for w, c in warning_counter.most_common(15)
    ]

    report.overall_quality_score = sum(r.quality_score for r in records) / n
    return report

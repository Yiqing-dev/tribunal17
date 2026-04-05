"""
Discussion quality review report renderer.

Renders a DiscussionReview into a self-contained HTML report with:
1. Hero -- ticker, date, debate grade badge, overall score
2. Radar chart -- 5 coverage dimensions (SVG, no JS)
3. Bull vs Bear comparison -- claims, confidence, PM consumption
4. Evidence utilization heatmap -- E# citation matrix
5. Prompt improvement suggestions -- severity-coded cards
6. Prediction review (optional) -- predicted vs actual
7. Footer with generation timestamp

All CSS/JS inline -- self-contained HTML for static export.
All user-facing text is in Chinese (A-share product).
"""

import math
from datetime import datetime
from typing import Optional

from .shared_utils import _esc, _html_wrap
from .shared_css import _BASE_CSS


# ── Review-specific CSS ──────────────────────────────────────────────

_REVIEW_CSS = """
/* ── Review-specific additions ── */
.grade-badge {
  display: inline-flex; align-items: center; justify-content: center;
  width: 56px; height: 56px; border-radius: 50%;
  font-size: 1.6rem; font-weight: 800;
  font-family: var(--mono);
  border: 3px solid currentColor;
}
.grade-A { color: var(--green); background: rgba(52, 211, 153, 0.12); }
.grade-B { color: var(--blue); background: rgba(96, 165, 250, 0.12); }
.grade-C { color: var(--yellow); background: rgba(251, 191, 36, 0.12); }
.grade-D { color: var(--red); background: rgba(248, 113, 113, 0.12); }
.review-hero {
  position: relative; overflow: hidden;
  border-radius: 28px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  background:
    linear-gradient(135deg, rgba(12, 29, 45, 0.96) 0%, rgba(12, 21, 31, 0.88) 45%, rgba(24, 34, 28, 0.9) 100%);
  box-shadow: 0 22px 54px rgba(0, 0, 0, 0.26);
  padding: 2rem;
  margin-bottom: 1.2rem;
}
.review-hero-grid {
  position: relative; z-index: 1;
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 1.5rem; align-items: center;
}
.score-display {
  font-size: 2.6rem; font-weight: 800;
  font-family: var(--mono); line-height: 1;
  margin-top: .5rem;
}
.radar-card {
  display: flex; justify-content: center; align-items: center;
  padding: 1.5rem;
}
.comparison-grid {
  display: grid; grid-template-columns: 1fr 1fr; gap: 1rem;
}
.side-card {
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 18px;
  padding: 1.1rem;
}
.side-bull { border-left: 3px solid var(--green); }
.side-bear { border-left: 3px solid var(--red); }
.side-title {
  font-size: .88rem; font-weight: 700;
  margin-bottom: .6rem;
}
.side-stat {
  display: flex; justify-content: space-between;
  font-size: .84rem; padding: .25rem 0;
  border-bottom: 1px solid rgba(255, 255, 255, 0.04);
}
.side-stat:last-child { border-bottom: none; }
.stat-label { color: var(--muted); }
.stat-value { color: var(--white); font-family: var(--mono); font-weight: 600; }
.pm-consumption {
  background: rgba(96, 165, 250, 0.06);
  border: 1px solid rgba(96, 165, 250, 0.15);
  border-radius: 14px;
  padding: .85rem 1rem;
  margin-top: 1rem;
  font-size: .85rem;
  color: var(--fg);
}
.heatmap-table { width: 100%; border-collapse: collapse; font-size: .82rem; }
.heatmap-table th {
  padding: .5rem .6rem; text-align: center;
  color: var(--muted); font-weight: 600; font-size: .72rem;
  letter-spacing: .04em; text-transform: uppercase;
}
.heatmap-table td { padding: .5rem .6rem; text-align: center; }
.heatmap-table td.eid { text-align: left; font-weight: 600; font-family: var(--mono); color: var(--accent); }
.hm-yes {
  color: var(--green); font-weight: 700;
}
.hm-no {
  color: rgba(255, 255, 255, 0.15);
}
.suggestion-card {
  position: relative;
  background: rgba(255, 255, 255, 0.03);
  border-radius: 14px;
  padding: 1rem 1.1rem;
  margin-bottom: .75rem;
  border-left: 4px solid var(--muted);
}
.suggestion-card.sev-high { border-left-color: var(--red); }
.suggestion-card.sev-medium { border-left-color: var(--yellow); }
.suggestion-card.sev-low { border-left-color: var(--green); }
.sev-badge {
  display: inline-flex; align-items: center;
  padding: 2px 10px; border-radius: 999px;
  font-size: .7rem; font-weight: 600;
  margin-bottom: .5rem;
}
.sev-badge.sev-high { background: rgba(248, 113, 113, 0.14); color: var(--red); }
.sev-badge.sev-medium { background: rgba(251, 191, 36, 0.14); color: var(--yellow); }
.sev-badge.sev-low { background: rgba(52, 211, 153, 0.14); color: var(--green); }
.suggestion-desc { font-size: .88rem; color: var(--fg); margin-bottom: .4rem; }
.suggestion-example {
  font-size: .82rem; color: var(--muted);
  background: rgba(255, 255, 255, 0.02);
  border-radius: 8px; padding: .5rem .7rem;
  font-style: italic;
}
.prediction-grid {
  display: grid; grid-template-columns: 1fr 1fr; gap: 1rem;
}
.pred-card {
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 18px;
  padding: 1.1rem; text-align: center;
}
.pred-label { font-size: .78rem; color: var(--muted); margin-bottom: .4rem; text-transform: uppercase; letter-spacing: .06em; }
.pred-value { font-size: 1.4rem; font-weight: 800; font-family: var(--mono); }
.pred-detail { font-size: .82rem; color: var(--muted); margin-top: .3rem; }
@media (max-width: 760px) {
  .review-hero-grid { grid-template-columns: 1fr; }
  .comparison-grid { grid-template-columns: 1fr; }
  .prediction-grid { grid-template-columns: 1fr; }
  .grade-badge { width: 44px; height: 44px; font-size: 1.3rem; }
  .score-display { font-size: 2rem; }
}
"""


# ── Helper: safe attribute/dict access ───────────────────────────────

def _get(obj, key, default=None):
    """Get value from dict or object attribute."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


# ── Radar SVG (5 axes) ──────────────────────────────────────────────

def _radar_svg_5(dimensions, size=220):
    """SVG radar chart for 5 coverage dimensions (0-100 scale).

    Args:
        dimensions: list of dicts with 'label' and 'value' (0-100).
        size: SVG canvas size.

    Returns:
        SVG string.
    """
    cx = cy = size / 2
    max_r = size * 0.36
    n = 5
    # Start from top, go clockwise
    angles = [(-math.pi / 2 + i * 2 * math.pi / n) for i in range(n)]

    fill_color = "#60a5fa"
    stroke_color = "#60a5fa"

    def polar(angle, r):
        return (cx + r * math.cos(angle), cy + r * math.sin(angle))

    svg = [f'<svg viewBox="0 0 {size} {size}" width="{size}" height="{size}">']

    # Grid polygons at 25%, 50%, 75%, 100%
    for frac in (0.25, 0.5, 0.75, 1.0):
        pts = " ".join(
            f"{polar(a, max_r * frac)[0]:.1f},{polar(a, max_r * frac)[1]:.1f}"
            for a in angles
        )
        svg.append(
            f'<polygon points="{pts}" fill="none" '
            f'stroke="rgba(255,255,255,0.08)" stroke-width="1"/>'
        )

    # Axis lines
    for a in angles:
        ex, ey = polar(a, max_r)
        svg.append(
            f'<line x1="{cx}" y1="{cy}" x2="{ex:.1f}" y2="{ey:.1f}" '
            f'stroke="rgba(255,255,255,0.06)" stroke-width="1"/>'
        )

    # Data polygon
    values = []
    for i in range(n):
        if i < len(dimensions):
            v = _get(dimensions[i], "value", 0)
            try:
                v = float(v)
            except (TypeError, ValueError):
                v = 0
        else:
            v = 0
        values.append(max(0, min(100, v)))

    if values:
        data_pts = " ".join(
            f"{polar(angles[i], max_r * v / 100)[0]:.1f},"
            f"{polar(angles[i], max_r * v / 100)[1]:.1f}"
            for i, v in enumerate(values)
        )
        svg.append(
            f'<polygon points="{data_pts}" fill="{fill_color}" '
            f'fill-opacity="0.15" stroke="{stroke_color}" stroke-width="1.5"/>'
        )
        for i, v in enumerate(values):
            dx, dy = polar(angles[i], max_r * v / 100)
            svg.append(f'<circle cx="{dx:.1f}" cy="{dy:.1f}" r="3" fill="{fill_color}"/>')

    # Labels
    labels = []
    for i in range(n):
        if i < len(dimensions):
            labels.append(_get(dimensions[i], "label", f"D{i+1}"))
        else:
            labels.append(f"D{i+1}")

    for i, lbl in enumerate(labels):
        lx, ly = polar(angles[i], max_r + 20)
        # Adjust anchor based on position
        if abs(lx - cx) < 5:
            anchor = "middle"
        elif lx > cx:
            anchor = "start"
        else:
            anchor = "end"
        # Vertical nudge
        if ly < cy - max_r * 0.5:
            ly -= 6
        elif ly > cy + max_r * 0.5:
            ly += 12
        svg.append(
            f'<text x="{lx:.1f}" y="{ly:.1f}" text-anchor="{anchor}" '
            f'fill="var(--muted)" font-size="10" font-weight="600">'
            f'{_esc(str(lbl))}</text>'
        )
        # Value annotation
        svg.append(
            f'<text x="{lx:.1f}" y="{ly + 12:.1f}" text-anchor="{anchor}" '
            f'fill="var(--fg)" font-size="9" font-family="var(--mono)">'
            f'{values[i]:.0f}%</text>'
        )

    svg.append('</svg>')
    return "\n".join(svg)


# ── Section builders ─────────────────────────────────────────────────

def _render_hero(review) -> str:
    """Section 1: Hero with ticker, date, grade badge, overall score."""
    ticker = _esc(str(_get(review, "ticker", "")))
    ticker_name = _esc(str(_get(review, "ticker_name", "")))
    trade_date = _esc(str(_get(review, "trade_date", "")))
    grade = str(_get(review, "grade", "C")).upper()
    overall_score = _get(review, "overall_score", 0)
    try:
        overall_score = float(overall_score)
    except (TypeError, ValueError):
        overall_score = 0

    grade_cls = f"grade-{grade}" if grade in ("A", "B", "C", "D") else "grade-C"

    # Score color
    if overall_score >= 80:
        score_color = "var(--green)"
    elif overall_score >= 60:
        score_color = "var(--blue)"
    elif overall_score >= 40:
        score_color = "var(--yellow)"
    else:
        score_color = "var(--red)"

    display = f"{ticker} {ticker_name}".strip() or "Unknown"
    run_id = _esc(str(_get(review, "run_id", ""))[:12])

    return f"""
    <div class="review-hero reveal">
      <div class="review-hero-grid">
        <div>
          <div class="eyebrow">DISCUSSION QUALITY REVIEW</div>
          <h1>{display}</h1>
          <div class="subtitle">{trade_date} &middot; {run_id}</div>
          <div class="score-display" style="color:{score_color}">
            {overall_score:.0f}<span style="font-size:.5em;color:var(--muted)">/100</span>
          </div>
        </div>
        <div style="text-align:center">
          <div class="grade-badge {grade_cls}">{_esc(grade)}</div>
          <div style="font-size:.78rem;color:var(--muted);margin-top:.5rem">辩论等级</div>
        </div>
      </div>
    </div>"""


def _render_radar(review) -> str:
    """Section 2: 5-dimension radar chart."""
    coverage = _get(review, "coverage", None)
    if not coverage:
        # Build default dimensions with zero values
        default_labels = ["基本面覆盖度", "估值覆盖度", "技术面覆盖度", "资金面覆盖度", "催化剂覆盖度"]
        coverage = [{"label": lbl, "value": 0} for lbl in default_labels]

    # Ensure we have 5 dimensions with expected labels
    default_labels = ["基本面覆盖度", "估值覆盖度", "技术面覆盖度", "资金面覆盖度", "催化剂覆盖度"]
    dims = []
    for i in range(5):
        if i < len(coverage):
            item = coverage[i]
            label = _get(item, "label", default_labels[i] if i < len(default_labels) else f"D{i+1}")
            value = _get(item, "value", 0)
        else:
            label = default_labels[i] if i < len(default_labels) else f"D{i+1}"
            value = 0
        dims.append({"label": label, "value": value})

    svg = _radar_svg_5(dims)

    return f"""
    <div class="card reveal reveal-d1">
      <h2>辩论质量雷达图</h2>
      <div class="radar-card">{svg}</div>
    </div>"""


def _render_bull_bear(review) -> str:
    """Section 3: Bull vs Bear comparison with PM consumption."""
    bull = _get(review, "bull", {}) or {}
    bear = _get(review, "bear", {}) or {}
    pm = _get(review, "pm_consumption", {}) or {}

    bull_claims = int(_get(bull, "claims_count", 0) or 0)
    bull_conf = _get(bull, "confidence", 0)
    try:
        bull_conf = float(bull_conf)
    except (TypeError, ValueError):
        bull_conf = 0

    bear_claims = int(_get(bear, "claims_count", 0) or 0)
    bear_conf = _get(bear, "confidence", 0)
    try:
        bear_conf = float(bear_conf)
    except (TypeError, ValueError):
        bear_conf = 0

    # Balance bar
    total = bull_claims + bear_claims
    if total > 0:
        bp = int(bull_claims / total * 100)
    else:
        bp = 50
    balance_bar = f"""
    <div style="margin-top:.8rem">
      <div class="bb-label"><span>多方 ({bull_claims})</span><span>空方 ({bear_claims})</span></div>
      <div class="bb-bar">
        <div class="bb-bull" style="width:{bp}%"></div>
        <div class="bb-bear" style="width:{100-bp}%"></div>
      </div>
    </div>"""

    # PM consumption
    pm_bull_used = int(_get(pm, "bull_used", 0) or 0)
    pm_bull_total = int(_get(pm, "bull_total", bull_claims) or bull_claims)
    pm_bear_used = int(_get(pm, "bear_used", 0) or 0)
    pm_bear_total = int(_get(pm, "bear_total", bear_claims) or bear_claims)

    pm_html = ""
    if pm:
        pm_html = f"""
        <div class="pm-consumption">
          PM 引用了 <strong>{pm_bull_used}/{pm_bull_total}</strong> 多方论据,
          <strong>{pm_bear_used}/{pm_bear_total}</strong> 空方论据
        </div>"""

    return f"""
    <div class="card reveal reveal-d2">
      <h2>Bull vs Bear 对比</h2>
      <div class="comparison-grid">
        <div class="side-card side-bull">
          <div class="side-title" style="color:var(--green)">多方 (Bull)</div>
          <div class="side-stat"><span class="stat-label">论据数量</span><span class="stat-value">{bull_claims}</span></div>
          <div class="side-stat"><span class="stat-label">整体置信度</span><span class="stat-value">{bull_conf:.0%}</span></div>
        </div>
        <div class="side-card side-bear">
          <div class="side-title" style="color:var(--red)">空方 (Bear)</div>
          <div class="side-stat"><span class="stat-label">论据数量</span><span class="stat-value">{bear_claims}</span></div>
          <div class="side-stat"><span class="stat-label">整体置信度</span><span class="stat-value">{bear_conf:.0%}</span></div>
        </div>
      </div>
      {balance_bar}
      {pm_html}
    </div>"""


def _render_evidence_heatmap(review) -> str:
    """Section 4: Evidence utilization heatmap table."""
    evidence_matrix = _get(review, "evidence_matrix", None)
    if not evidence_matrix:
        return ""

    # evidence_matrix expected format:
    # {
    #   "agents": ["agent1", "agent2", ...],
    #   "evidence": [
    #     {"id": "E1", "text": "...", "cited_by": ["agent1", "agent3"]},
    #     ...
    #   ]
    # }
    agents = _get(evidence_matrix, "agents", []) or []
    evidence_items = _get(evidence_matrix, "evidence", []) or []

    if not evidence_items:
        return ""

    # Header
    agent_headers = "".join(f"<th>{_esc(str(a))}</th>" for a in agents)
    header = f"<tr><th>证据编号</th>{agent_headers}</tr>"

    # Rows
    rows = []
    for ev in evidence_items:
        eid = _esc(str(_get(ev, "id", "")))
        cited_by = _get(ev, "cited_by", []) or []
        cells = ""
        for agent in agents:
            if agent in cited_by:
                cells += '<td class="hm-yes">\u2713</td>'
            else:
                cells += '<td class="hm-no">\u2717</td>'
        rows.append(f"<tr><td class='eid'>{eid}</td>{cells}</tr>")

    rows_html = "\n".join(rows)

    return f"""
    <div class="card reveal reveal-d3">
      <h2>证据利用热力图</h2>
      <div style="overflow-x:auto">
        <table class="heatmap-table">
          <thead>{header}</thead>
          <tbody>{rows_html}</tbody>
        </table>
      </div>
    </div>"""


def _render_suggestions(review) -> str:
    """Section 5: Prompt improvement suggestions."""
    suggestions = _get(review, "suggestions", None)
    if not suggestions:
        return ""

    # Severity labels and ordering
    sev_labels = {"high": "HIGH", "medium": "MEDIUM", "low": "LOW"}

    cards = []
    for s in suggestions:
        severity = str(_get(s, "severity", "low")).lower()
        description = _esc(str(_get(s, "description", "")))
        example = _get(s, "example", "")
        sev_cls = f"sev-{severity}" if severity in ("high", "medium", "low") else "sev-low"
        sev_text = sev_labels.get(severity, "LOW")

        example_html = ""
        if example:
            example_html = f'<div class="suggestion-example">{_esc(str(example))}</div>'

        cards.append(f"""
        <div class="suggestion-card {sev_cls}">
          <div class="sev-badge {sev_cls}">{sev_text}</div>
          <div class="suggestion-desc">{description}</div>
          {example_html}
        </div>""")

    return f"""
    <div class="card reveal reveal-d4">
      <h2>Prompt 改进建议</h2>
      {"".join(cards)}
    </div>"""


def _render_prediction_review(review) -> str:
    """Section 6: Prediction review (optional)."""
    pred = _get(review, "prediction_review", None)
    if not pred:
        return ""

    predicted_action = _esc(str(_get(pred, "predicted_action", "--")))
    actual_outcome = _esc(str(_get(pred, "actual_outcome", "--")))
    predicted_confidence = _get(pred, "predicted_confidence", 0)
    try:
        predicted_confidence = float(predicted_confidence)
    except (TypeError, ValueError):
        predicted_confidence = 0

    actual_return = _get(pred, "actual_return_pct", None)
    direction_correct = _get(pred, "direction_correct", None)

    # Color for predicted
    action_lower = predicted_action.lower()
    if action_lower in ("buy", "strong_buy", "加仓", "买入"):
        pred_color = "var(--green)"
    elif action_lower in ("sell", "strong_sell", "减仓", "卖出"):
        pred_color = "var(--red)"
    else:
        pred_color = "var(--yellow)"

    # Direction correct indicator
    dir_html = ""
    if direction_correct is not None:
        if direction_correct:
            dir_html = '<div style="color:var(--green);font-size:.88rem;margin-top:.5rem;font-weight:600">方向正确</div>'
        else:
            dir_html = '<div style="color:var(--red);font-size:.88rem;margin-top:.5rem;font-weight:600">方向错误</div>'

    # Actual return
    return_html = ""
    if actual_return is not None:
        try:
            ret = float(actual_return)
            ret_color = "var(--green)" if ret >= 0 else "var(--red)"  # A-share: red=positive
            return_html = f'<div class="pred-detail" style="color:{ret_color}">{ret:+.2f}%</div>'
        except (TypeError, ValueError):
            return_html = f'<div class="pred-detail">{_esc(str(actual_return))}</div>'

    return f"""
    <div class="card reveal reveal-d5">
      <h2>预测回顾</h2>
      <div class="prediction-grid">
        <div class="pred-card">
          <div class="pred-label">预测</div>
          <div class="pred-value" style="color:{pred_color}">{predicted_action}</div>
          <div class="pred-detail">置信度 {predicted_confidence:.0%}</div>
        </div>
        <div class="pred-card">
          <div class="pred-label">实际</div>
          <div class="pred-value">{actual_outcome}</div>
          {return_html}
        </div>
      </div>
      {dir_html}
    </div>"""


# ── Main render function ─────────────────────────────────────────────

def render_review_page(review) -> str:
    """Render discussion quality review as self-contained HTML.

    Args:
        review: DiscussionReview object or dict with review data.

    Returns:
        Complete HTML string.
    """
    ticker = str(_get(review, "ticker", ""))
    ticker_name = str(_get(review, "ticker_name", ""))
    display = f"{ticker} {ticker_name}".strip() or "Review"

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    sections = [
        _render_hero(review),
        _render_radar(review),
        _render_bull_bear(review),
        _render_evidence_heatmap(review),
        _render_suggestions(review),
        _render_prediction_review(review),
        f'<div style="text-align:center;color:var(--muted);font-size:.75rem;margin-top:1.5rem">'
        f'Generated {_esc(now)}</div>',
    ]

    body = "\n".join(s for s in sections if s)
    title = f"Discussion Review - {display}"

    return _html_wrap(title, body, "Discussion Review", extra_css=_REVIEW_CSS)


# ── File generation ──────────────────────────────────────────────────

def generate_review_report(review, output_dir: str = "data/reports") -> Optional[str]:
    """Generate and save discussion quality review HTML report.

    Args:
        review: DiscussionReview object or dict with review data.
            Expected keys/attrs: ticker, ticker_name, trade_date, grade,
            overall_score, coverage, bull, bear, pm_consumption,
            evidence_matrix, suggestions, prediction_review, run_id.
        output_dir: Output directory path.

    Returns:
        Path to generated HTML file, or None if insufficient data.
    """
    from pathlib import Path

    ticker = str(_get(review, "ticker", ""))
    run_id = str(_get(review, "run_id", ""))

    if not ticker and not run_id:
        return None

    html = render_review_page(review)

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    from .report_renderer import _safe_filename
    ticker_slug = _safe_filename(ticker) or "unknown"
    run_slug = run_id[:12] if run_id else "no-run"
    path = out_dir / f"review-{ticker_slug}-{run_slug}.html"
    path.write_text(html, encoding="utf-8")
    return str(path)

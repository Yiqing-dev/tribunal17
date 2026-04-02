"""
Shared utility functions for HTML report renderers.

Extracted from report_renderer.py to allow reuse across
report_renderer, recap_renderer, and other renderer modules
without circular imports.
"""

import math
from typing import Optional

from .decision_labels import EVIDENCE_STRENGTH_LABELS
from .shared_css import _BASE_CSS


def _esc(text: str) -> str:
    """Escape HTML special characters."""
    return (text.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;")
            .replace("'", "&#39;"))


def _html_wrap(title: str, body: str, tier_label: str, extra_css: str = "",
               extra_head: str = "") -> str:
    """Wrap body content in a full HTML document."""
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{_esc(title)}</title>
<style>{_BASE_CSS}{extra_css}</style>
{extra_head}
</head>
<body>
<div class="container">
{body}
<div class="footer">TradingAgents {tier_label} v0.2.0</div>
</div>
</body>
</html>"""


def _ticker_display(view) -> str:
    """Return 'TICKER NAME' if name is available, else just 'TICKER'."""
    name = getattr(view, "ticker_name", "")
    if name:
        return f"{view.ticker} {name}"
    return view.ticker


def _status_light(ok: bool, label: str) -> str:
    cls = "light-green" if ok else "light-red"
    return f'<span class="light {cls}"></span>{label}'


def _strip_preamble(text: str) -> str:
    """Remove common LLM self-introduction preambles from excerpt text."""
    from .decision_labels import INTERNAL_TOKEN_PREFIXES
    lines = text.split("\n")
    cleaned = []
    for line in lines:
        stripped = line.strip()
        if any(stripped.startswith(p) for p in INTERNAL_TOKEN_PREFIXES):
            continue
        cleaned.append(line)
    return "\n".join(cleaned).strip()


def _empty_state(icon: str, title: str, hint: str = "") -> str:
    """Render a polished empty-state placeholder."""
    hint_html = f'<div class="empty-state-hint">{_esc(hint)}</div>' if hint else ""
    return (f'<div class="empty-state">'
            f'<div class="empty-state-icon">{icon}</div>'
            f'<div class="empty-state-title">{_esc(title)}</div>'
            f'{hint_html}</div>')


def _format_price_zone(zone: list) -> str:
    """Format price zone safely — handles both float and string values."""
    if len(zone) < 2:
        return "\u2014"
    try:
        return f"{float(zone[0]):.2f} - {float(zone[1]):.2f}"
    except (ValueError, TypeError):
        return f"{_esc(str(zone[0]))} - {_esc(str(zone[1]))}"


def _evidence_strength_label(level: str) -> str:
    return EVIDENCE_STRENGTH_LABELS.get(level, level)


def _degraded_banner(reasons: list, audit_link: str = "") -> str:
    """Render a degraded mode warning banner."""
    items = "".join(f"<li>{_esc(r)}</li>" for r in reasons)
    audit_btn = f'<a href="{audit_link}" style="display:inline-block;margin-top:.75rem;padding:6px 16px;background:var(--yellow);color:var(--bg);border-radius:4px;text-decoration:none;font-weight:600;">查看审计详情</a>' if audit_link else ""
    return f"""
    <div class="card" style="border:2px solid var(--yellow); background:#1c1208;">
      <div style="font-size:1.1rem; font-weight:700; color:var(--yellow); margin-bottom:.5rem;">
        输出质量退化
      </div>
      <div style="color:var(--fg); margin-bottom:.5rem;">
        本次研究输出存在结构化退化，以下内容仅供快速参考，建议优先查看审计页。
      </div>
      <ul style="color:var(--muted); margin-bottom:.5rem;">{items}</ul>
      {audit_btn}
    </div>"""


def _bull_bear_bar(bull: int, bear: int) -> str:
    total = bull + bear
    if total == 0:
        return ""
    bp = int(bull / total * 100)
    return f"""
    <div class="bb-label"><span>看多 ({bull})</span><span>看空 ({bear})</span></div>
    <div class="bb-bar">
      <div class="bb-bull" style="width:{bp}%"></div>
      <div class="bb-bear" style="width:{100-bp}%"></div>
    </div>"""


def _direction_badge(direction: str) -> str:
    """Render a small direction badge for catalysts."""
    cls_map = {"bullish": "buy", "bearish": "sell", "neutral": "hold"}
    labels = {"bullish": "看多", "bearish": "看空", "neutral": "中性"}
    badge_cls = cls_map.get(direction, "hold")
    return f'<span class="badge badge-{badge_cls}">{_esc(labels.get(direction, direction))}</span>'


def _radar_svg(pillars, action_class, size=180):
    """SVG radar chart for 4-pillar scores (0-4 scale)."""
    cx = cy = size / 2
    max_r = size * 0.38
    axes = [(-math.pi / 2 + i * math.pi / 2) for i in range(4)]  # top, right, bottom, left
    labels = ["\u6280\u672f\u9762", "\u57fa\u672c\u9762", "\u65b0\u95fb\u9762", "\u60c5\u7eea\u9762"]
    color_map = {"buy": "#34d399", "hold": "#fbbf24", "sell": "#f87171", "veto": "#f87171"}
    fill_color = color_map.get(action_class, "#60a5fa")

    def polar(angle, r):
        return (cx + r * math.cos(angle), cy + r * math.sin(angle))

    svg = [f'<svg viewBox="0 0 {size} {size}" width="{size}" height="{size}">']
    # Grid polygons at r=max_r/4 (score 1), r=max_r/2 (score 2), r=3*max_r/4 (score 3), r=max_r (score 4)
    for frac in (0.25, 0.5, 0.75, 1.0):
        pts = " ".join(f"{polar(a, max_r * frac)[0]:.1f},{polar(a, max_r * frac)[1]:.1f}" for a in axes)
        svg.append(f'<polygon points="{pts}" fill="none" stroke="rgba(255,255,255,0.08)" stroke-width="1"/>')
    # Axis lines
    for a in axes:
        ex, ey = polar(a, max_r)
        svg.append(f'<line x1="{cx}" y1="{cy}" x2="{ex:.1f}" y2="{ey:.1f}" stroke="rgba(255,255,255,0.06)" stroke-width="1"/>')
    # Data polygon
    scores = []
    for i, p in enumerate(pillars[:4]):
        s = p.get("score", 0)
        scores.append(s)
    if scores:
        data_pts = " ".join(
            f"{polar(axes[i], max_r * s / 4)[0]:.1f},{polar(axes[i], max_r * s / 4)[1]:.1f}"
            for i, s in enumerate(scores)
        )
        svg.append(f'<polygon points="{data_pts}" fill="{fill_color}" fill-opacity="0.18" '
                   f'stroke="{fill_color}" stroke-width="1.5"/>')
        for i, s in enumerate(scores):
            dx, dy = polar(axes[i], max_r * s / 4)
            svg.append(f'<circle cx="{dx:.1f}" cy="{dy:.1f}" r="3" fill="{fill_color}"/>')
    # Labels
    offsets = [(0, -12), (12, 0), (0, 14), (-12, 0)]  # top, right, bottom, left
    anchors = ["middle", "start", "middle", "end"]
    for i, lbl in enumerate(labels[:len(axes)]):
        lx, ly = polar(axes[i], max_r + 16)
        svg.append(f'<text x="{lx + offsets[i][0]:.1f}" y="{ly + offsets[i][1]:.1f}" '
                   f'text-anchor="{anchors[i]}" fill="var(--muted)" '
                   f'font-size="10" font-weight="600">{lbl}</text>')
    svg.append('</svg>')
    return "\n".join(svg)


def _pct_to_hex(pct: float) -> str:
    """Map % change to hex color for treemap.

    A-share convention: red = up, green = down.
    Pastel diverging palette with narrow clamped domain and sqrt compression.

    Design rules:
      - Domain clamped to [-3%, +3%] — beyond that gets the endpoint color
      - Non-linear (sqrt) compression — small moves are visible, large moves
        don't jump to saturated extremes
      - Warm off-white center with wide transition zone
      - Never pure red/green — stays pastel and restrained at all values

    Endpoints:
      rise max  #FDA5B5  (soft salmon pink)
      fall max  #AAD993  (muted mint green)
      neutral   #F0EAE7  (warm off-white)
    """
    CLAMP = 3.0  # narrow domain: [-3%, +3%]
    # Neutral center (warm off-white)
    nr, ng, nb = 0xF0, 0xEA, 0xE7

    # Clamp
    clamped = max(-CLAMP, min(CLAMP, pct))
    # Normalize to [-1, 1]
    t = clamped / CLAMP
    # Sqrt compression: preserves sign, softens extremes, reveals small moves
    compressed = math.copysign(math.sqrt(abs(t)), t)

    if compressed >= 0:
        # Rise: warm off-white → soft salmon pink (#FDA5B5)
        er, eg, eb = 0xFD, 0xA5, 0xB5
    else:
        # Fall: warm off-white → muted mint (#AAD993)
        er, eg, eb = 0xAA, 0xD9, 0x93
        compressed = -compressed  # make positive for interpolation

    r = int(nr + (er - nr) * compressed)
    g = int(ng + (eg - ng) * compressed)
    b = int(nb + (eb - nb) * compressed)
    return f"#{max(0,min(255,r)):02X}{max(0,min(255,g)):02X}{max(0,min(255,b)):02X}"


def _squarify(values, x, y, w, h):
    """Squarified treemap layout algorithm.

    Args:
        values: list of (index, value) sorted desc by value
        x, y, w, h: bounding rectangle

    Returns:
        list of (index, rx, ry, rw, rh) rectangles
    """
    if not values:
        return []

    total = sum(v for _, v in values)
    if total <= 0:
        return [(idx, x, y, w / max(len(values), 1), h) for idx, _ in values]

    rects = []

    def _layout_row(row, rx, ry, rw, rh, horizontal, base_total):
        row_sum = sum(v for _, v in row)
        if row_sum <= 0:
            return
        if horizontal:
            row_h = rh * (row_sum / base_total) if base_total > 0 else rh
            cx = rx
            for idx, val in row:
                cw = rw * (val / row_sum) if row_sum > 0 else rw / max(len(row), 1)
                rects.append((idx, cx, ry, max(cw, 1), max(row_h, 1)))
                cx += cw
        else:
            row_w = rw * (row_sum / base_total) if base_total > 0 else rw
            cy = ry
            for idx, val in row:
                ch = rh * (val / row_sum) if row_sum > 0 else rh / max(len(row), 1)
                rects.append((idx, rx, cy, max(row_w, 1), max(ch, 1)))
                cy += ch

    remaining = list(values)
    cx, cy, cw, ch = x, y, w, h
    remaining_total = total

    while remaining:
        horizontal = cw < ch
        if len(remaining) <= 2:
            _layout_row(remaining, cx, cy, cw, ch, horizontal, remaining_total)
            break

        best_row = [remaining[0]]
        best_ratio = float('inf')

        for i in range(1, len(remaining)):
            test_row = remaining[:i + 1]
            row_sum = sum(v for _, v in test_row)
            if remaining_total <= 0:
                break
            frac = row_sum / remaining_total

            if horizontal:
                row_h = ch * frac
                widths = [(cw * v / row_sum) if row_sum > 0 else 1 for _, v in test_row]
                ratios = [max(ww / row_h, row_h / ww) if min(ww, row_h) > 0 else float('inf') for ww in widths]
            else:
                row_w = cw * frac
                heights = [(ch * v / row_sum) if row_sum > 0 else 1 for _, v in test_row]
                ratios = [max(row_w / hh, hh / row_w) if min(row_w, hh) > 0 else float('inf') for hh in heights]

            worst = max(ratios) if ratios else float('inf')
            if worst <= best_ratio:
                best_ratio = worst
                best_row = test_row
            else:
                break

        row_sum = sum(v for _, v in best_row)
        frac = row_sum / remaining_total if remaining_total > 0 else 1

        if horizontal:
            row_h = ch * frac
            _layout_row(best_row, cx, cy, cw, ch, True, remaining_total)
            cy += row_h
            ch -= row_h
        else:
            row_w = cw * frac
            _layout_row(best_row, cx, cy, cw, ch, False, remaining_total)
            cx += row_w
            cw -= row_w

        remaining = remaining[len(best_row):]
        remaining_total -= row_sum

    return rects

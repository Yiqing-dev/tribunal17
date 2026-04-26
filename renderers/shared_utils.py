"""
Shared utility functions for HTML report renderers.

Extracted from report_renderer.py to allow reuse across
report_renderer, recap_renderer, and other renderer modules
without circular imports.
"""

import math
from typing import Optional

from .decision_labels import EVIDENCE_STRENGTH_LABELS
from .shared_css import _BASE_CSS, _SHARED_SVG_DEFS


def _esc(text: str) -> str:
    """Escape HTML special characters."""
    return (text.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;")
            .replace("'", "&#39;"))


_CONFIDENCE_LABELS = {
    "high": 0.8, "med": 0.5, "medium": 0.5, "low": 0.2,
    "高": 0.8, "中": 0.5, "低": 0.2,
}


def normalize_confidence_value(val) -> float:
    """Canonical confidence normalizer → [0.0, 1.0].

    Handles numeric, percent-strings, and high/med/low labels. Returns -1.0
    when the value is negative, None, unparseable, or explicitly sentinel.
    Numeric scales: >10 → 0-100 (/100), >1 → 1-10 (/10). Matches CLAUDE.md rule #7.
    """
    if val is None:
        return -1.0
    if isinstance(val, bool):
        return -1.0  # avoid treating True/False as 1.0/0.0
    if isinstance(val, (int, float)):
        conf = float(val)
    elif isinstance(val, str):
        mapped = _CONFIDENCE_LABELS.get(val.strip().lower())
        if mapped is not None:
            return mapped
        raw = val.strip().rstrip("%")
        try:
            conf = float(raw)
        except (ValueError, TypeError):
            return -1.0
        if val.strip().endswith("%"):
            conf = conf / 100.0
    else:
        return -1.0

    if conf < 0:
        return -1.0
    # CLAUDE.md rule #7: values ≥10 treated as 0-100 scale (/100);
    # values >1 but <10 treated as 1-10 scale (/10).
    if conf >= 10:
        conf = conf / 100.0
    elif conf > 1.0:
        conf = conf / 10.0
    return max(0.0, min(1.0, conf))


def format_confidence_pct(val) -> str:
    """Format a confidence value as 'NN%', or empty string when missing/unparseable."""
    conf = normalize_confidence_value(val)
    return "" if conf < 0 else f"{conf:.0%}"


def _html_wrap(title: str, body: str, tier_label: str, extra_css: str = "",
               extra_head: str = "", nav_html: str = "") -> str:
    """Wrap body content in a full HTML document.

    Args:
        nav_html: Optional cross-report navigation bar (from _nav_bar()).
    """
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
{_SHARED_SVG_DEFS}
<div class="container">
{nav_html}
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


_SVG_ICONS = {
    "chart": (
        '<svg viewBox="0 0 32 32" fill="none" stroke="currentColor" stroke-width="1.5"'
        ' stroke-linecap="round" stroke-linejoin="round">'
        '<rect x="4" y="18" width="5" height="10" rx="1"/>'
        '<rect x="13.5" y="10" width="5" height="18" rx="1"/>'
        '<rect x="23" y="4" width="5" height="24" rx="1"/></svg>'
    ),
    "lightning": (
        '<svg viewBox="0 0 32 32" fill="none" stroke="currentColor" stroke-width="1.5"'
        ' stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M18 2L6 18h8l-2 12 12-16h-8z"/></svg>'
    ),
    "swords": (
        '<svg viewBox="0 0 32 32" fill="none" stroke="currentColor" stroke-width="1.5"'
        ' stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M6 6l20 20M26 6L6 26"/>'
        '<circle cx="6" cy="6" r="2"/><circle cx="26" cy="6" r="2"/>'
        '<circle cx="6" cy="26" r="2"/><circle cx="26" cy="26" r="2"/></svg>'
    ),
    "magnifier": (
        '<svg viewBox="0 0 32 32" fill="none" stroke="currentColor" stroke-width="1.5"'
        ' stroke-linecap="round" stroke-linejoin="round">'
        '<circle cx="14" cy="14" r="9"/><path d="M21 21l7 7"/></svg>'
    ),
}
_ICON_MAP = {"📊": "chart", "⚡": "lightning", "⚔️": "swords", "🔍": "magnifier"}


def _svg_icon(name: str, size: int = 32) -> str:
    """Return inline SVG icon by name. Returns empty string for unknown names."""
    svg = _SVG_ICONS.get(name, "")
    if not svg:
        return ""
    return svg.replace('viewBox=', f'width="{size}" height="{size}" viewBox=', 1)


def _empty_state(icon: str, title: str, hint: str = "") -> str:
    """Render a polished empty-state placeholder.

    If *icon* matches a known emoji (📊⚡⚔️🔍), renders an SVG icon
    with pulse animation instead. Unknown icons render as-is.
    """
    hint_html = f'<div class="empty-state-hint">{_esc(hint)}</div>' if hint else ""
    svg_name = _ICON_MAP.get(icon)
    if svg_name:
        icon_html = f'<div class="empty-state-icon empty-state-icon--svg" title="{_esc(icon)}">{_svg_icon(svg_name, 48)}</div>'
    else:
        icon_html = f'<div class="empty-state-icon">{icon}</div>'
    return (f'<div class="empty-state">'
            f'{icon_html}'
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


# ── Treemap Subsystem ────────────────────────────────────────────
# Two rendering modes share the same squarify layout:
#   1. render_svg_treemap() — Python SVG, flat single-level (recap, stock heatmap)
#   2. _TREEMAP_ENGINE_JS (market_renderer) — JS drill-down, hierarchical


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


def render_svg_treemap(nodes, width=600, height=340, size_key="value",
                       color_fn=None, label_fn=None, tooltip_fn=None,
                       data_idx=True, node_cls="shm-node",
                       extra_g_attrs_fn=None, extra_rect_attrs_fn=None,
                       svg_attrs="", rect_gap=0):
    """Render a flat single-level SVG treemap from a list of node dicts.

    Args:
        nodes: list of dicts — each must have *size_key* for area sizing.
        width, height: SVG viewBox dimensions.
        size_key: dict key for the sizing value (area ∝ value).
        color_fn: ``(node) -> str`` returning a CSS color for the rect fill.
                  Defaults to ``"#3d5068"`` (neutral slate).
        label_fn: ``(node) -> (name_str, subtitle_str)`` for the two text
                  lines inside each rect.  Defaults to ``("", "")``.
        tooltip_fn: ``(node) -> str`` for the ``<title>`` hover tooltip.
                    Defaults to empty string.
        data_idx: if *True*, each ``<g>`` gets ``data-idx="{i}"`` (needed by
                  drawer click handlers).
        node_cls: CSS class on each ``<g>`` group. Default ``"shm-node"``
                  (recap/sector drawer); market heatmap uses ``"hm-node"``.
        extra_g_attrs_fn: ``(idx, node) -> str`` returning additional
                  attributes for the ``<g>`` element (e.g. ``data-ticker``).
        extra_rect_attrs_fn: ``(idx, node, fill) -> str`` returning
                  additional attributes for the ``<rect>`` element.
        svg_attrs: extra attributes string appended to the ``<svg>`` tag
                   (e.g. ``'preserveAspectRatio="xMidYMid meet"'``).
        rect_gap: pixels to subtract from each rect width/height for gaps.

    Returns:
        Complete ``<svg …>…</svg>`` string.
    """
    if not nodes:
        return ""

    # Defaults
    if color_fn is None:
        color_fn = lambda n: "#3d5068"  # noqa: E731
    if label_fn is None:
        label_fn = lambda n: ("", "")  # noqa: E731
    if tooltip_fn is None:
        tooltip_fn = lambda n: ""  # noqa: E731

    # Build indexed values for squarify
    indexed = []
    for i, n in enumerate(nodes):
        v = max(float(n.get(size_key, 1) or 0), 0.01)
        indexed.append((i, v))
    indexed.sort(key=lambda x: x[1], reverse=True)

    rects = _squarify(indexed, 0, 0, width, height)

    svg_parts = []
    for idx, rx, ry, rw, rh in rects:
        node = nodes[idx]
        fill = color_fn(node)
        name, subtitle = label_fn(node)
        tip = tooltip_fn(node)

        # Apply rect gap
        draw_w = max(rw - rect_gap, 1)
        draw_h = max(rh - rect_gap, 1)

        # Auto-size text based on rect dimensions
        font_size = min(rw / 5, rh / 3, 14)
        font_size = max(font_size, 8)

        text_el = ""
        if rw > 50 and rh > 30:
            name_esc = _esc(name) if name else ""
            sub_esc = _esc(subtitle) if subtitle else ""
            text_el = (
                f'<text x="{rx + rw / 2}" y="{ry + rh / 2 - 4}" '
                f'text-anchor="middle" fill="white" '
                f'font-size="{font_size}px" font-weight="600">'
                f'{name_esc}</text>'
            )
            if sub_esc:
                text_el += (
                    f'<text x="{rx + rw / 2}" y="{ry + rh / 2 + font_size}" '
                    f'text-anchor="middle" fill="rgba(255,255,255,.7)" '
                    f'font-size="{max(font_size - 2, 7)}px" '
                    f'font-family="monospace">'
                    f'{sub_esc}</text>'
                )

        idx_attr = f' data-idx="{idx}"' if data_idx else ""
        g_extra = ""
        if extra_g_attrs_fn is not None:
            g_extra = " " + extra_g_attrs_fn(idx, node)
        tip_el = f"<title>{_esc(tip)}</title>" if tip else ""
        rect_extra = ""
        if extra_rect_attrs_fn is not None:
            rect_extra = " " + extra_rect_attrs_fn(idx, node, fill)

        # When extra_rect_attrs_fn is provided, it supplies its own
        # stroke/stroke-width; otherwise use sensible defaults.
        if extra_rect_attrs_fn is not None:
            stroke_attrs = ""
        else:
            stroke_attrs = ' stroke="var(--bg)" stroke-width="2"'

        svg_parts.append(
            f'<g class="{node_cls}"{idx_attr}{g_extra}>'
            f'{tip_el}'
            f'<rect x="{rx:.1f}" y="{ry:.1f}" width="{draw_w:.1f}" '
            f'height="{draw_h:.1f}" '
            f'fill="{fill}"{stroke_attrs} rx="3"'
            f'{rect_extra}/>'
            f'{text_el}</g>'
        )

    style_attr = f' style="max-height:{height}px"' if not svg_attrs else ""
    extra_svg = f" {svg_attrs}" if svg_attrs else ""
    return (
        f'<svg viewBox="0 0 {width} {height}" '
        f'width="100%" height="auto"{style_attr}{extra_svg} '
        f'xmlns="http://www.w3.org/2000/svg">'
        f'{"".join(svg_parts)}</svg>'
    )


# ── Visual enhancement utilities (added 2026-04-05) ─────────────────────


def _trend_arrow(current: float, previous: float = None,
                 threshold: float = 0.01) -> str:
    """Return a small trend arrow HTML span.

    If *previous* is given, compares current vs previous.
    Otherwise uses sign of *current* (positive=up, negative=down).
    """
    if previous is not None and previous != 0:
        ratio = (current - previous) / abs(previous)
        if ratio > threshold:
            return '<span class="trend-arrow trend-up">↑</span>'
        elif ratio < -threshold:
            return '<span class="trend-arrow trend-down">↓</span>'
        return '<span class="trend-arrow trend-neutral">→</span>'
    # No previous — use sign
    if current > threshold:
        return '<span class="trend-arrow trend-up">↑</span>'
    elif current < -threshold:
        return '<span class="trend-arrow trend-down">↓</span>'
    return '<span class="trend-arrow trend-neutral">→</span>'


def _sparkline_svg(prices: list, width: int = 200, height: int = 60) -> str:
    """Render a mini sparkline SVG from a list of close prices.

    Shows polyline with gradient fill, current price dot + label.
    """
    if not prices or len(prices) < 2:
        return ""
    n = len(prices)
    lo, hi = min(prices), max(prices)
    spread = hi - lo if hi != lo else 1.0
    pad_x, pad_y = 4, 6

    def _x(i):
        return pad_x + i * (width - 2 * pad_x) / (n - 1)

    def _y(v):
        return pad_y + (1 - (v - lo) / spread) * (height - 2 * pad_y)

    pts = " ".join(f"{_x(i):.1f},{_y(v):.1f}" for i, v in enumerate(prices))
    last_x, last_y = _x(n - 1), _y(prices[-1])

    # Trend color
    trend = prices[-1] - prices[0]
    color = "#34d399" if trend > 0 else "#f87171" if trend < 0 else "#60a5fa"
    fill_color = color.replace(")", ",0.15)").replace("#", "rgba(") if "#" in color else color
    # Simple hex to rgba for fill
    r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
    fill_rgba = f"rgba({r},{g},{b},0.12)"

    # Polygon for gradient fill (close the area under the line)
    poly_pts = pts + f" {_x(n-1):.1f},{height - pad_y} {_x(0):.1f},{height - pad_y}"

    # Current price label
    price_label = f"{prices[-1]:.2f}"

    return (
        f'<svg viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
        f'xmlns="http://www.w3.org/2000/svg" style="overflow:visible">'
        f'<polygon points="{poly_pts}" fill="{fill_rgba}" stroke="none"/>'
        f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="1.5" '
        f'stroke-linecap="round" stroke-linejoin="round"/>'
        f'<circle cx="{last_x:.1f}" cy="{last_y:.1f}" r="3" fill="{color}" stroke="#070e1b" stroke-width="1.5"/>'
        f'<text x="{last_x:.1f}" y="{last_y - 6:.1f}" text-anchor="middle" '
        f'font-size="9" font-family="var(--mono)" fill="{color}" font-weight="600">{price_label}</text>'
        f'</svg>'
    )


def _svg_minify(svg: str) -> str:
    """Strip redundant whitespace and newlines from inline SVG strings.

    Intended for programmatically-generated SVG where human readability of the
    source isn't needed. Reduces payload by ~15-20% for chart-heavy reports
    (recap_renderer.py consumes this for K-line / MACD / RSI panels).
    """
    if not svg:
        return ""
    import re
    # Collapse any run of whitespace to a single space
    out = re.sub(r"\s+", " ", svg)
    # Tighten around tag boundaries (safe for attributes because we already collapsed)
    out = re.sub(r"\s*(<)\s*", r"\1", out)
    out = re.sub(r"\s*(/?>)\s*", r"\1", out)
    return out.strip()


# ── V4: Visualization primitives (score_pill, priority_chip, confidence_ring, etc.) ──
# All primitives return inline HTML/SVG strings. No JS deps. A11y via role="img" + aria-label.
# Color-blind-safe: red/green are layered with icons (▲/●/○/◆/—) and patterns (url(#pat-*))
# for deuteranopia/protanopia accessibility.


def _conf_tier(conf: float) -> str:
    """Classify confidence into a tier for CSS class dispatch.

    Returns one of: "hi" (>=0.65), "md" (>=0.50), "lo" (<0.50), "na" (non-finite).
    """
    try:
        c = float(conf)
    except (TypeError, ValueError):
        return "na"
    if not math.isfinite(c):
        return "na"
    if c >= 0.65:
        return "hi"
    if c >= 0.50:
        return "md"
    return "lo"


def _score_pill(score, max_score: int = 4, label: str = "") -> str:
    """Discrete dot-array for pillar scores (default 4 dots for 0-4 scale).

    Colors use --conf-hi/md/lo tier based on fill ratio. Filled dots include
    a `●` Unicode pre-fill + box-shadow for non-color redundancy.

    Example:
        >>> _score_pill(3, 4, "技术")  # ●●●○ 技术
    """
    try:
        s = int(score) if score is not None else 0
    except (TypeError, ValueError):
        s = 0
    s = max(0, min(max_score, s))
    ratio = s / max_score if max_score > 0 else 0
    tier = "hi" if ratio >= 0.75 else "md" if ratio >= 0.5 else "lo" if ratio >= 0.25 else "na"

    dots = "".join(
        f'<span class="sp-dot{" on" if i < s else ""}" aria-hidden="true"></span>'
        for i in range(max_score)
    )
    lab_html = f'<span class="sp-lab">{_esc(label)}</span>' if label else ""
    aria = f"{label}: {s} of {max_score}" if label else f"{s} of {max_score}"
    return (
        f'<span class="score-pill conf-{tier}" role="img" aria-label="{_esc(aria)}">'
        f'{dots}{lab_html}'
        f'</span>'
    )


_PRIO_ICONS = {"hot": "▲", "warm": "◆", "cool": "●", "mute": "—"}


def _priority_chip(level: str, text: str = "") -> str:
    """Severity chip with icon + color + label.

    Args:
        level: one of {"hot", "warm", "cool", "mute"}
        text:  display text (if empty, chip shows only the icon)
    """
    lv = level if level in _PRIO_ICONS else "mute"
    ico = _PRIO_ICONS[lv]
    body_txt = f'<span class="pc-txt">{_esc(text)}</span>' if text else ""
    aria = f"{lv} severity: {text}" if text else f"{lv} severity"
    return (
        f'<span class="prio-chip {lv}" role="img" aria-label="{_esc(aria)}">'
        f'<span class="pc-ico" aria-hidden="true">{ico}</span>{body_txt}'
        f'</span>'
    )


def _confidence_ring_svg(pct, size: int = 72, label: str = "") -> str:
    """Circular progress ring for a single 0..1 confidence value.

    Renders an SVG with stroke-dasharray progress, colored by conf tier,
    center text shows percentage. Safe on NaN / None — renders "—".
    """
    try:
        p = float(pct)
        if not math.isfinite(p):
            raise ValueError
        p = max(0.0, min(1.0, p))
    except (TypeError, ValueError):
        p = None

    stroke_w = max(4, int(size * 0.10))
    r = (size - stroke_w) / 2
    cx = cy = size / 2
    circumference = 2 * math.pi * r

    if p is None:
        pct_txt = "—"
        color = "var(--conf-na)"
        dash = f"0 {circumference:.1f}"
    else:
        tier = _conf_tier(p)
        color = f"var(--conf-{tier})"
        pct_txt = f"{int(round(p * 100))}%"
        dash = f"{circumference * p:.1f} {circumference:.1f}"

    aria = f"confidence {pct_txt}" + (f" ({label})" if label else "")
    lab_html = f'<div class="cr-lab">{_esc(label)}</div>' if label else ""

    svg = (
        f'<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}" '
        f'role="img" aria-label="{_esc(aria)}">'
        f'<circle cx="{cx}" cy="{cy}" r="{r:.1f}" fill="none" '
        f'stroke="rgba(255,255,255,0.08)" stroke-width="{stroke_w}"/>'
        f'<circle cx="{cx}" cy="{cy}" r="{r:.1f}" fill="none" '
        f'stroke="{color}" stroke-width="{stroke_w}" '
        f'stroke-dasharray="{dash}" stroke-linecap="round" '
        f'transform="rotate(-90 {cx} {cy})"/>'
        f'</svg>'
    )
    return (
        f'<div class="conf-ring" style="width:{size}px;height:{size}px">'
        f'{svg}'
        f'<div class="cr-val"><div class="cr-pct">{pct_txt}</div>{lab_html}</div>'
        f'</div>'
    )


def _ridge_bar(values: list, labels: list = None, height: int = 28) -> str:
    """Compact horizontal mini-bar strip; auto-scales to max abs.

    Positive values use --conf-hi gradient, negatives use --conf-lo.
    Labels (optional) render below bars.
    """
    if not values:
        return ""
    try:
        vals = [float(v) if v is not None else 0.0 for v in values]
    except (TypeError, ValueError):
        vals = [0.0] * len(values)
    vals = [v if math.isfinite(v) else 0.0 for v in vals]

    max_abs = max((abs(v) for v in vals), default=1.0) or 1.0
    segs = []
    for v in vals:
        ratio = abs(v) / max_abs
        h_pct = max(4, int(ratio * 100))
        cls = " neg" if v < 0 else ""
        segs.append(
            f'<div class="rb-seg{cls}" style="height:{h_pct}%" '
            f'title="{v:.2f}" aria-hidden="true"></div>'
        )

    labels_html = ""
    if labels and len(labels) == len(vals):
        lab_items = "".join(
            f'<span style="flex:1;text-align:center">{_esc(str(l))}</span>'
            for l in labels
        )
        labels_html = f'<div class="rb-labels">{lab_items}</div>'

    aria = f"distribution of {len(vals)} values, max {max_abs:.2f}"
    return (
        f'<div role="img" aria-label="{_esc(aria)}">'
        f'<div class="ridge-bar" style="height:{height}px">{"".join(segs)}</div>'
        f'{labels_html}'
        f'</div>'
    )


def _delta_arrow(from_v, to_v, unit: str = "", threshold: float = 0.001, decimals: int = 2) -> str:
    """Directional arrow showing magnitude of change.

    Returns '▲+2.3%', '▼-1.1%', or '— flat'. Safe on None.
    """
    try:
        fv = float(from_v) if from_v is not None else None
        tv = float(to_v) if to_v is not None else None
    except (TypeError, ValueError):
        return '<span class="delta-arr flat" role="img" aria-label="no delta available">—</span>'
    if fv is None or tv is None or not math.isfinite(fv) or not math.isfinite(tv):
        return '<span class="delta-arr flat" role="img" aria-label="no delta available">—</span>'

    diff = tv - fv
    if abs(diff) < threshold:
        return f'<span class="delta-arr flat" role="img" aria-label="no change">— {unit}</span>'

    sign = "+" if diff > 0 else ""
    cls = "up" if diff > 0 else "down"
    ico = "▲" if diff > 0 else "▼"
    aria = f"{'increased' if diff > 0 else 'decreased'} by {abs(diff):.{decimals}f}{unit}"
    return (
        f'<span class="delta-arr {cls}" role="img" aria-label="{_esc(aria)}">'
        f'<span aria-hidden="true">{ico}</span>{sign}{diff:.{decimals}f}{_esc(unit)}'
        f'</span>'
    )


def _heat_cell(value, vmin: float = 0.0, vmax: float = 1.0,
               scale: str = "diverging", w: int = 40, h: int = 20,
               label: str = "", pattern: str = "") -> str:
    """Single heat-map cell with optional pattern overlay for CB-safety.

    Args:
        value: numeric value to color-map
        vmin, vmax: domain bounds
        scale: "diverging" (red→neutral→green) or "sequential" (blue-cool→amber-hot)
        w, h: pixel dims
        label: text overlay (typically the value formatted)
        pattern: "" | "diag" | "dot" — adds pattern fill for CB redundancy
    """
    try:
        v = float(value)
        if not math.isfinite(v):
            raise ValueError
    except (TypeError, ValueError):
        return (
            f'<span class="v-heat-cell" style="width:{w}px;height:{h}px;'
            f'background:rgba(255,255,255,0.05)" '
            f'role="img" aria-label="no value"'
            f'{(" data-label=" + chr(34) + _esc(label) + chr(34)) if label else ""}>'
            f'</span>'
        )

    if vmax <= vmin:
        vmax = vmin + 1.0
    t = (v - vmin) / (vmax - vmin)
    t = max(0.0, min(1.0, t))

    if scale == "diverging":
        # 0 -> red, 0.5 -> neutral-ish, 1 -> green
        if t < 0.5:
            # red → neutral
            r, g, b = 248, int(113 + (143 * (t * 2))), int(113 + (160 * (t * 2)))
        else:
            # neutral → green
            k = (t - 0.5) * 2
            r, g, b = int(248 - 196 * k), int(211 + 0 * k), int(153 + 0 * k)
            g, b = 211, 153
            r = int(248 - (248 - 52) * k)
    else:  # sequential cool→hot
        r = int(96 + (245 - 96) * t)
        g = int(165 + (158 - 165) * t)
        b = int(250 + (11 - 250) * t)
    color = f"rgb({r},{g},{b})"
    pat_attr = f' data-pattern="{_esc(pattern)}"' if pattern in ("diag", "dot") else ""
    lab = label or (f"{v:.2f}" if abs(v) < 100 else f"{v:.0f}")
    aria = f"{lab}" + (f" ({label})" if label and label != lab else "")

    return (
        f'<span class="v-heat-cell" style="width:{w}px;height:{h}px;background:{color}" '
        f'data-label="{_esc(lab)}"{pat_attr} '
        f'role="img" aria-label="{_esc(aria)}"></span>'
    )


def _conf_dots(conf, n: int = 5) -> str:
    """Dense 5-dot confidence indicator (denser than _score_pill; for claim cards).

    Dots fill based on round(conf * n), color by conf tier.
    """
    try:
        c = float(conf) if conf is not None else 0.0
        if not math.isfinite(c):
            raise ValueError
    except (TypeError, ValueError):
        c = 0.0
    c = max(0.0, min(1.0, c))
    filled = int(round(c * n))
    tier = _conf_tier(c)
    dots = "".join(
        f'<span class="cd-dot{" on" if i < filled else ""}" aria-hidden="true"></span>'
        for i in range(n)
    )
    aria = f"confidence {int(round(c * 100))}%"
    return (
        f'<span class="conf-dots" data-tier="{tier}" role="img" aria-label="{_esc(aria)}">'
        f'{dots}'
        f'</span>'
    )


def _price_ladder_svg(
    stop_loss: float = 0.0,
    entries: list = None,
    targets: list = None,
    current: float = 0.0,
    width: int = 280,
    height: int = 220,
) -> str:
    """Vertical price ladder — stop (red band, bottom) → current → entries → targets (green bands, top).

    Inputs are plain floats / price tuples. Each entry/target is either a single
    float or a [low, high] tuple (price zone). Draws a labelled vertical axis
    with shaded zones. Gracefully degrades to empty string when there's no data.

    Colour-blind safety: zones are labelled with ✖ / ● / ▲ so redundant with hue.
    """
    entries = [e for e in (entries or []) if e]
    targets = [t for t in (targets or []) if t]
    # Collect all numeric prices to determine range
    prices: list = []

    def _pair(v):
        if isinstance(v, (list, tuple)) and v:
            try:
                return float(v[0]), float(v[-1])
            except (TypeError, ValueError):
                return None
        try:
            f = float(v)
            return f, f
        except (TypeError, ValueError):
            return None

    e_pairs = [p for p in (_pair(e) for e in entries) if p]
    t_pairs = [p for p in (_pair(t) for t in targets) if p]
    if stop_loss and stop_loss > 0:
        prices.append(float(stop_loss))
    prices.extend(lo for lo, _ in e_pairs)
    prices.extend(hi for _, hi in e_pairs)
    prices.extend(lo for lo, _ in t_pairs)
    prices.extend(hi for _, hi in t_pairs)
    if current and current > 0:
        prices.append(float(current))
    prices = [p for p in prices if p and p > 0]
    if len(prices) < 2:
        return ""

    lo, hi = min(prices), max(prices)
    pad = max((hi - lo) * 0.08, 0.01)
    lo, hi = lo - pad, hi + pad
    span = hi - lo or 1.0

    pad_top, pad_bot = 14, 14
    plot_h = height - pad_top - pad_bot
    axis_x = 62

    def _y(price: float) -> float:
        return pad_top + plot_h * (1 - (price - lo) / span)

    parts: list = []
    # Background track
    parts.append(
        f'<rect x="{axis_x - 1}" y="{pad_top}" width="2" height="{plot_h}" '
        f'fill="rgba(255,255,255,0.06)" rx="1"/>'
    )

    # Gridline ticks at 4 evenly spaced prices
    n_ticks = 4
    for i in range(n_ticks + 1):
        p = lo + span * i / n_ticks
        y = _y(p)
        parts.append(
            f'<line x1="{axis_x - 4}" y1="{y:.1f}" x2="{axis_x + 4}" y2="{y:.1f}" '
            f'stroke="rgba(255,255,255,0.15)" stroke-width="1"/>'
        )
        parts.append(
            f'<text x="{axis_x - 8}" y="{y + 3:.1f}" text-anchor="end" '
            f'fill="var(--muted)" font-size="10" font-family="var(--mono)">{p:.2f}</text>'
        )

    def _zone(lo_p: float, hi_p: float, color: str, opacity: str = "0.22"):
        y_top = _y(hi_p)
        y_bot = _y(lo_p)
        h = max(3.0, y_bot - y_top)
        parts.append(
            f'<rect x="{axis_x + 3}" y="{y_top:.1f}" width="{width - axis_x - 8}" height="{h:.1f}" '
            f'fill="{color}" fill-opacity="{opacity}" rx="3"/>'
        )

    def _label(price_y: float, text: str, icon: str, color: str):
        parts.append(
            f'<circle cx="{axis_x}" cy="{price_y:.1f}" r="5" fill="{color}" '
            f'stroke="rgba(9,20,32,0.9)" stroke-width="1.5"/>'
        )
        parts.append(
            f'<text x="{axis_x + 12}" y="{price_y + 3.5:.1f}" fill="{color}" '
            f'font-size="11" font-weight="600">{_esc(icon)} {_esc(text)}</text>'
        )

    # Stop loss: red band from plot_bottom to stop price
    if stop_loss and stop_loss > 0:
        _zone(lo, float(stop_loss), "var(--red)")
        _label(_y(float(stop_loss)), f"止损 {stop_loss:.2f}", "✖", "var(--red)")

    # Entry zones: yellow bands
    for i, (e_lo, e_hi) in enumerate(e_pairs[:3], start=1):
        _zone(e_lo, e_hi, "var(--yellow)", opacity="0.28")
        mid = (e_lo + e_hi) / 2
        lbl = f"{e_lo:.2f}-{e_hi:.2f}" if e_hi != e_lo else f"{e_lo:.2f}"
        _label(_y(mid), f"买点{i} {lbl}", "●", "var(--yellow)")

    # Targets: green bands
    for i, (t_lo, t_hi) in enumerate(t_pairs[:3], start=1):
        _zone(t_lo, t_hi, "var(--green)")
        mid = (t_lo + t_hi) / 2
        lbl = f"{t_lo:.2f}-{t_hi:.2f}" if t_hi != t_lo else f"{t_lo:.2f}"
        _label(_y(mid), f"目标{i} {lbl}", "▲", "var(--green)")

    # Current-price marker (blue, drawn last so it's on top)
    if current and current > 0:
        cy = _y(float(current))
        parts.append(
            f'<line x1="{axis_x + 3}" y1="{cy:.1f}" x2="{width - 6}" y2="{cy:.1f}" '
            f'stroke="var(--blue)" stroke-width="1.5" stroke-dasharray="4 3" opacity="0.85"/>'
        )
        _label(cy, f"现价 {float(current):.2f}", "◆", "var(--blue)")

    aria = (
        f"price ladder: stop {stop_loss or 0:.2f}, "
        f"{len(e_pairs)} entry zones, {len(t_pairs)} targets"
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="{_esc(aria)}" '
        f'class="price-ladder">'
        + "".join(parts)
        + '</svg>'
    )


def _stacked_prob_bar(segments: list, height: int = 22) -> str:
    """Horizontal stacked probability bar. Renders labels below/inside the bar.

    Args:
        segments: list of {"label": str, "value": float (0-1 or 0-100), "color": css_color, "icon": optional}
    Returns HTML string; values auto-normalized to sum 100.
    """
    if not segments:
        return ""
    # Parse values
    parsed = []
    for s in segments:
        try:
            v = float(s.get("value", 0) or 0)
        except (TypeError, ValueError):
            v = 0.0
        if v <= 0:
            continue
        if v <= 1.0:
            v *= 100.0
        parsed.append({
            "label": str(s.get("label", "") or ""),
            "value": v,
            "color": s.get("color") or "var(--blue)",
            "icon": s.get("icon", ""),
        })
    if not parsed:
        return ""
    total = sum(p["value"] for p in parsed) or 1.0
    if total <= 0:
        return ""
    # Normalize
    for p in parsed:
        p["pct"] = round(p["value"] * 100 / total)

    segs_html = "".join(
        f'<div class="spb-seg" style="width:{p["pct"]}%;background:{p["color"]}" '
        f'title="{_esc(p["label"])} {p["pct"]}%">'
        f'<span class="spb-seg-label">{_esc(p["icon"])} {p["pct"]}%</span>'
        f'</div>'
        for p in parsed
    )
    legend_html = "".join(
        f'<span class="spb-legend-item">'
        f'<span class="spb-legend-swatch" style="background:{p["color"]}"></span>'
        f'<span class="spb-legend-label">{_esc(p["label"])}</span>'
        f'<span class="spb-legend-value mono">{p["pct"]}%</span>'
        f'</span>'
        for p in parsed
    )
    aria = "probability breakdown: " + ", ".join(f'{p["label"]} {p["pct"]}%' for p in parsed)
    return (
        f'<div class="stacked-prob" role="img" aria-label="{_esc(aria)}">'
        f'<div class="spb-track" style="height:{height}px">{segs_html}</div>'
        f'<div class="spb-legend">{legend_html}</div>'
        f'</div>'
    )


def _pillar_bar(score, max_score: int = 4, label: str = "") -> str:
    """4-segment progress bar for pillar scores.

    Like _score_pill but drawn as horizontal segments with gap — reads faster
    at a glance than a row of dots when the user is scanning multiple pillars.
    """
    try:
        n = int(float(score))
    except (TypeError, ValueError):
        n = 0
    n = max(0, min(n, max_score))
    tier = _conf_tier(n / max_score if max_score else 0)
    segs = "".join(
        f'<span class="pb-seg{" on" if i < n else ""}" aria-hidden="true"></span>'
        for i in range(max_score)
    )
    aria = f"{label or 'pillar'} score {n} of {max_score}"
    return (
        f'<span class="pillar-bar" data-tier="{tier}" role="img" aria-label="{_esc(aria)}">'
        f'{segs}'
        f'<span class="pb-text mono">{n}/{max_score}</span>'
        f'</span>'
    )


def _history_sparkline(
    points: list,
    width: int = 220,
    height: int = 44,
) -> str:
    """Confidence/price sparkline with color-coded action dots.

    Args:
        points: list of dicts with {"value": 0-1 float, "action": "BUY"/"SELL"/"HOLD"/"VETO",
                                     "date": "YYYY-MM-DD" (optional)}
    Returns SVG string. Empty when fewer than 2 points.
    """
    if not points or len(points) < 2:
        return ""
    vals: list = []
    for p in points:
        try:
            v = float(p.get("value", 0) or 0)
        except (TypeError, ValueError):
            v = 0.0
        vals.append(max(0.0, min(1.0, v)))

    pad = 6
    plot_w = width - pad * 2
    plot_h = height - pad * 2
    n = len(vals)
    step = plot_w / (n - 1) if n > 1 else plot_w

    def _coord(i: int, v: float):
        return pad + i * step, pad + plot_h * (1 - v)

    pts = [_coord(i, v) for i, v in enumerate(vals)]
    path_d = "M " + " L ".join(f"{x:.1f},{y:.1f}" for x, y in pts)

    # Fill under line (area sparkline)
    area_d = path_d + f" L {pts[-1][0]:.1f},{pad + plot_h:.1f} L {pts[0][0]:.1f},{pad + plot_h:.1f} Z"

    _ACTION_COLORS = {
        "BUY": "var(--green)",
        "SELL": "var(--red)",
        "VETO": "var(--red)",
        "HOLD": "var(--yellow)",
        "WAIT": "var(--yellow)",
    }
    dots_html = ""
    for i, (p, (x, y)) in enumerate(zip(points, pts)):
        action = str(p.get("action", "") or "").upper()
        color = _ACTION_COLORS.get(action, "var(--blue)")
        title = f'{p.get("date", "")} {action} {int(vals[i] * 100)}%'
        dots_html += (
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="{color}" '
            f'stroke="rgba(9,20,32,0.9)" stroke-width="1"><title>{_esc(title)}</title></circle>'
        )

    aria = f"signal history sparkline, {n} points, latest {int(vals[-1] * 100)}%"
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="{_esc(aria)}" class="hist-spark">'
        f'<path d="{area_d}" fill="var(--blue)" fill-opacity="0.12"/>'
        f'<path d="{path_d}" stroke="var(--blue)" stroke-width="1.5" fill="none" '
        f'stroke-linejoin="round" stroke-linecap="round"/>'
        f'{dots_html}'
        f'</svg>'
    )


def _section_divider(title: str, icon: str = "", count=None) -> str:
    """Horizontal divider with title + optional icon + optional count chip.

    Use at section boundaries in long reports.
    """
    icon_html = f'<span aria-hidden="true">{icon}</span>' if icon else ""
    count_html = f'<span class="sd-count">{count}</span>' if count is not None else ""
    aria = f"{title} section" + (f", {count} items" if count is not None else "")
    return (
        f'<div class="sec-div" role="separator" aria-label="{_esc(aria)}">'
        f'<div class="sd-line" aria-hidden="true"></div>'
        f'<div class="sd-title">{icon_html}{_esc(title)}{count_html}</div>'
        f'<div class="sd-line" aria-hidden="true"></div>'
        f'</div>'
    )


# ── (Enhanced) _empty_state with variant support ──
def _empty_state_v2(icon: str, title: str, hint: str = "", variant: str = "block") -> str:
    """Empty-state variant-aware dispatcher. Backwards-compat with _empty_state().

    variant: "block" (default) | "inline" | "error"
    """
    aria = f"{title}" + (f": {hint}" if hint else "")
    if variant == "inline":
        return (
            f'<div class="empty-state" role="status" aria-label="{_esc(aria)}" '
            f'style="padding:.5rem 1rem;flex-direction:row;gap:.6rem">'
            f'<span class="empty-state-icon" aria-hidden="true" style="font-size:1rem;margin:0">{_esc(icon)}</span>'
            f'<span class="empty-state-title">{_esc(title)}</span>'
            f'{f"<span class=\"empty-state-hint\" style=\"margin-left:.5rem\">{_esc(hint)}</span>" if hint else ""}'
            f'</div>'
        )
    if variant == "error":
        return (
            f'<div class="empty-state" role="alert" aria-label="{_esc(aria)}" '
            f'style="border:1px solid rgba(248,113,113,0.3);'
            f'background:rgba(248,113,113,0.05);border-radius:14px;color:var(--red)">'
            f'<div class="empty-state-icon" aria-hidden="true" style="color:var(--red)">{_esc(icon)}</div>'
            f'<div class="empty-state-title">{_esc(title)}</div>'
            f'{f"<div class=\"empty-state-hint\">{_esc(hint)}</div>" if hint else ""}'
            f'</div>'
        )
    return _empty_state(icon, title, hint)


def _nav_bar(ticker: str, run_id: str, current_page: str) -> str:
    """Render cross-report navigation bar.

    Links between snapshot/research/audit/committee for the same run.
    """
    if not run_id:
        return ""
    from .report_renderer import _safe_filename
    safe_t = _safe_filename(ticker)
    short_id = run_id.replace("run-", "")[:12]

    pages = [
        ("snapshot", "结论", f"{safe_t}-run-{short_id}-snapshot.html"),
        ("research", "研究", f"{safe_t}-run-{short_id}-research.html"),
        ("audit", "审计", f"{safe_t}-run-{short_id}-audit.html"),
        ("committee", "辩论", f"{safe_t}-{run_id}-committee.html"),
    ]
    links = []
    for key, label, href in pages:
        cls = ' class="active"' if key == current_page else ""
        links.append(f'<a href="{_esc(href)}"{cls}>{label}</a>')
    return f'<nav class="cross-nav">{"".join(links)}</nav>'

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

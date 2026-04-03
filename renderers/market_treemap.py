"""
Market treemap and heatmap rendering utilities.

Contains all heatmap + treemap code extracted from market_renderer.py:
- SVG heatmap with interactive drawer and tooltip
- Inline JS treemap engine (zero external dependencies)
- Plotly-style sector and stock treemaps

All user-facing text is in Chinese (A-share product).
"""

from .shared_utils import _esc, _pct_to_hex, render_svg_treemap


# ── Heatmap Helpers (_squarify and _pct_to_hex moved to shared_utils) ──


def _heatmap_color(pct_change, action=""):
    """Return fill color for a heatmap node."""
    if action == "BUY":
        if pct_change > 0:
            return "#1a7f37"
        return "#2ea043"
    elif action == "SELL":
        if pct_change < 0:
            return "#cf222e"
        return "#da3633"
    elif action == "VETO":
        return "#6e40c9"
    # Neutral / HOLD
    if pct_change > 3:
        return "#1a7f37"
    elif pct_change > 0:
        return "#2ea043"
    elif pct_change > -3:
        return "#da3633"
    return "#cf222e"


def _heatmap_risk_color(confidence):
    """Blue-orange color mapping for risk/confidence view of heatmap."""
    conf = float(confidence) if confidence else 0
    if conf >= 0.8:
        return "#1d4ed8"   # deep blue — high confidence
    elif conf >= 0.6:
        return "#3b82f6"   # blue
    elif conf >= 0.4:
        return "#6b7280"   # grey — neutral
    elif conf >= 0.2:
        return "#ea580c"   # orange
    return "#dc2626"       # red — low confidence


def _render_heatmap_legend():
    """Render heatmap color legend."""
    return (
        '<div class="hm-legend">'
        '<span class="hm-leg-item"><span class="hm-leg-dot" style="background:#1a7f37"></span> BUY/\u2191</span>'
        '<span class="hm-leg-item"><span class="hm-leg-dot" style="background:#2ea043"></span> HOLD/\u2191</span>'
        '<span class="hm-leg-item"><span class="hm-leg-dot" style="background:#da3633"></span> HOLD/\u2193</span>'
        '<span class="hm-leg-item"><span class="hm-leg-dot" style="background:#cf222e"></span> SELL/\u2193</span>'
        '<span class="hm-leg-item"><span class="hm-leg-dot" style="background:#6e40c9"></span> VETO</span>'
        '<span class="hm-leg-note">\u9762\u79ef \u221d \u5e02\u503c</span>'
        '</div>'
    )


def _render_svg_heatmap(heatmap_data, width=960, height=400, max_nodes=0):
    """Render an SVG treemap from heatmap_data dict."""
    if not heatmap_data:
        return ""
    nodes = heatmap_data.get("nodes", [])
    if not nodes:
        return ""
    if max_nodes > 0:
        nodes = nodes[:max_nodes]

    # -- Size key: prefer market_cap, fall back to size_score --
    # render_svg_treemap expects a single size_key string; we normalise here.
    for n in nodes:
        cap = float(n.get("market_cap", 0) or n.get("size_score", 1))
        n.setdefault("_hm_size", cap)

    def _color(n):
        pct = float(n.get("pct_change", 0))
        action = str(n.get("action", "HOLD")).upper()
        return _heatmap_color(pct, action)

    def _label(n):
        name = str(n.get("name", n.get("ticker", "")))
        pct = float(n.get("pct_change", 0))
        sign = "+" if pct > 0 else ""
        return (name, f"{sign}{pct:.1f}%")

    def _g_attrs(idx, n):
        pct = float(n.get("pct_change", 0))
        action = str(n.get("action", "HOLD")).upper()
        name = str(n.get("name", n.get("ticker", "")))
        ticker = str(n.get("ticker", ""))
        conf = float(n.get("confidence", 0))
        conf_str = f"{conf:.0%}" if conf > 0 else ""
        sector = str(n.get("sector", ""))
        return (
            f'data-ticker="{_esc(ticker)}" data-name="{_esc(name)}" '
            f'data-pct="{pct:.2f}" data-action="{_esc(action)}" '
            f'data-conf="{conf_str}" data-sector="{_esc(sector)}"'
        )

    def _rect_attrs(idx, n, fill):
        conf = float(n.get("confidence", 0))
        risk_fill = _heatmap_risk_color(conf)
        return (
            f'stroke="var(--bg, #0d1117)" stroke-width="1.5" '
            f'data-return-fill="{fill}" data-risk-fill="{risk_fill}"'
        )

    svg = render_svg_treemap(
        nodes, width=width, height=height, size_key="_hm_size",
        color_fn=_color, label_fn=_label,
        node_cls="hm-node",
        extra_g_attrs_fn=_g_attrs,
        extra_rect_attrs_fn=_rect_attrs,
        svg_attrs='preserveAspectRatio="xMidYMid meet"',
        rect_gap=1,
    )

    # Mobile fallback list (built separately — not part of SVG)
    mobile_rows = []
    for i, n in enumerate(nodes):
        pct = float(n.get("pct_change", 0))
        action = str(n.get("action", "HOLD")).upper()
        name = str(n.get("name", n.get("ticker", "")))
        ticker = str(n.get("ticker", ""))
        fill = _heatmap_color(pct, action)
        sign = "+" if pct > 0 else ""
        conf = float(n.get("confidence", 0))
        conf_str = f"{conf:.0%}" if conf > 0 else ""
        sector = str(n.get("sector", ""))
        data_attrs = (
            f'data-idx="{i}" data-ticker="{_esc(ticker)}" '
            f'data-name="{_esc(name)}" data-pct="{pct:.2f}" '
            f'data-action="{_esc(action)}" data-conf="{conf_str}" '
            f'data-sector="{_esc(sector)}"'
        )
        pct_cls = "up" if pct > 0 else ("dn" if pct < 0 else "")
        mobile_rows.append(
            f'<div class="hm-list-row" {data_attrs}>'
            f'<span class="hm-list-dot" style="background:{fill}"></span>'
            f'<span class="hm-list-name">{_esc(name)}</span>'
            f'<span class="hm-list-pct {pct_cls}">{sign}{pct:.1f}%</span>'
            f'<span class="hm-list-act">{_esc(action)}</span>'
            f'</div>'
        )

    mobile = f'<div class="hm-mobile-list">{"".join(mobile_rows)}</div>'
    return svg + mobile


def _render_detail_drawer():
    """Render the detail drawer overlay for heatmap clicks."""
    return """
    <div class="drawer-overlay" id="drawerOverlay"></div>
    <div class="detail-drawer" id="detailDrawer">
      <button class="drawer-close" id="drawerClose">&times;</button>
      <div class="drawer-header">
        <h3 id="drawerTitle">--</h3>
      </div>
      <div class="drawer-kpi">
        <div class="kpi"><div class="kpi-val" id="drawerPct">--</div><div class="kpi-lab">\u6da8\u8dcc\u5e45</div></div>
        <div class="kpi"><div class="kpi-val" id="drawerAction">--</div><div class="kpi-lab">\u4fe1\u53f7</div></div>
        <div class="kpi"><div class="kpi-val" id="drawerConf">--</div><div class="kpi-lab">\u7f6e\u4fe1\u5ea6</div></div>
      </div>
      <div class="drawer-section">
        <h4>\u677f\u5757</h4>
        <div id="drawerSector">--</div>
      </div>
    </div>"""


def _render_heatmap_js():
    """Render JavaScript for heatmap interactivity."""
    return """
    <div class="hm-tooltip" id="hmTooltip"></div>
    <script>
    (function(){
      var drawer = document.getElementById('detailDrawer');
      var overlay = document.getElementById('drawerOverlay');
      var tooltip = document.getElementById('hmTooltip');
      if (!drawer) return;

      function openDrawer(el) {
        document.getElementById('drawerTitle').textContent = el.dataset.name || '--';
        var pct = parseFloat(el.dataset.pct || 0);
        var pctEl = document.getElementById('drawerPct');
        pctEl.textContent = (pct > 0 ? '+' : '') + pct.toFixed(2) + '%';
        pctEl.style.color = pct > 0 ? 'var(--green)' : (pct < 0 ? 'var(--red)' : 'var(--muted)');
        document.getElementById('drawerAction').textContent = el.dataset.action || '--';
        document.getElementById('drawerConf').textContent = el.dataset.conf || '--';
        document.getElementById('drawerSector').textContent = el.dataset.sector || '--';
        drawer.classList.add('open');
        overlay.classList.add('open');
      }

      document.querySelectorAll('.hm-node, .hm-list-row').forEach(function(el){
        el.setAttribute('tabindex', '0');
        el.setAttribute('role', 'button');
        el.addEventListener('click', function(){ openDrawer(el); });
        el.addEventListener('keydown', function(evt) {
          if (evt.key === 'Enter' || evt.key === ' ') { evt.preventDefault(); openDrawer(el); }
        });
      });

      function closeDrawer() { drawer.classList.remove('open'); overlay.classList.remove('open'); }
      document.getElementById('drawerClose').addEventListener('click', closeDrawer);
      overlay.addEventListener('click', closeDrawer);

      document.querySelectorAll('.hm-node').forEach(function(el){
        el.addEventListener('mouseenter', function(e){
          var n = el.dataset.name || '';
          var p = parseFloat(el.dataset.pct || 0);
          tooltip.textContent = n + ' ' + (p>0?'+':'') + p.toFixed(2) + '%';
          tooltip.style.display = 'block';
          var tw = tooltip.offsetWidth || 150;
          var th = tooltip.offsetHeight || 30;
          var vw = window.innerWidth;
          var vh = window.innerHeight;
          var tx = e.clientX + 12;
          var ty = e.clientY - 8;
          if (tx + tw > vw - 8) tx = e.clientX - tw - 8;
          if (tx < 8) tx = 8;
          if (ty + th > vh - 8) ty = vh - th - 8;
          if (ty < 8) ty = 8;
          tooltip.style.left = tx + 'px';
          tooltip.style.top = ty + 'px';
        });
        el.addEventListener('mousemove', function(e){
          var tw = tooltip.offsetWidth || 150;
          var th = tooltip.offsetHeight || 30;
          var vw = window.innerWidth;
          var vh = window.innerHeight;
          var tx = e.clientX + 12;
          var ty = e.clientY - 8;
          if (tx + tw > vw - 8) tx = e.clientX - tw - 8;
          if (tx < 8) tx = 8;
          if (ty + th > vh - 8) ty = vh - th - 8;
          if (ty < 8) ty = 8;
          tooltip.style.left = tx + 'px';
          tooltip.style.top = ty + 'px';
        });
        el.addEventListener('mouseleave', function(){ tooltip.style.display = 'none'; });
      });

      /* F3: Color mode toggle (return vs risk/confidence) */
      var btnReturn = document.getElementById('hmModeReturn');
      var btnRisk = document.getElementById('hmModeRisk');
      if (btnReturn && btnRisk) {
        function setMode(mode) {
          var attr = mode === 'risk' ? 'data-risk-fill' : 'data-return-fill';
          document.querySelectorAll('.hm-node rect[data-return-fill]').forEach(function(r) {
            r.setAttribute('fill', r.getAttribute(attr) || r.getAttribute('data-return-fill'));
          });
          btnReturn.classList.toggle('active', mode === 'return');
          btnRisk.classList.toggle('active', mode === 'risk');
        }
        btnReturn.addEventListener('click', function(){ setMode('return'); });
        btnRisk.addEventListener('click', function(){ setMode('risk'); });
      }

      /* F3: Legend hover — highlight matching nodes */
      document.querySelectorAll('.hm-leg-item').forEach(function(leg) {
        leg.addEventListener('mouseenter', function() {
          var dot = leg.querySelector('.hm-leg-dot');
          if (!dot) return;
          var col = dot.style.background || dot.style.backgroundColor;
          document.querySelectorAll('.hm-node rect').forEach(function(r) {
            var fill = r.getAttribute('fill') || '';
            r.style.opacity = fill === col ? '1' : '0.25';
          });
        });
        leg.addEventListener('mouseleave', function() {
          document.querySelectorAll('.hm-node rect').forEach(function(r) {
            r.style.opacity = '1';
          });
        });
      });
    })();
    </script>"""


# ── Inline Treemap Engine (zero external dependencies) ───────────────

# _TREEMAP_ENGINE_JS: Hierarchical drill-down treemap (sector→stock).
# For flat single-level treemaps, use shared_utils.render_svg_treemap().

# Pure-JS squarify treemap renderer, embedded in each HTML page.
# Replaces Plotly CDN which doesn't load from file:// protocol.
_TREEMAP_ENGINE_JS = r"""
(function(cid, D, maxD) {
  var c = document.getElementById(cid);
  if (!c) return;
  c.style.position = 'relative';
  c.style.overflow = 'hidden';
  c.style.cursor = 'default';
  c.style.borderRadius = '12px';
  function escHtml(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');};

  /* Build tree */
  var nodes = {}, rootId = null;
  for (var i = 0; i < D.ids.length; i++) {
    var id = D.ids[i];
    nodes[id] = {id:id, label:D.labels[i], parent:D.parents[i],
      value:D.values[i], color:D.colors[i], text:D.texts[i],
      hover:D.customdata[i], ch:[]};
    if (!D.parents[i]) rootId = id;
  }
  for (var id in nodes) {
    var p = nodes[id].parent;
    if (p && nodes[p]) nodes[p].ch.push(nodes[id]);
  }

  /* Tooltip — frosted glass */
  var tip = document.createElement('div');
  tip.style.cssText = 'position:fixed;display:none;padding:10px 14px;border-radius:8px;font:13px/1.6 "PingFang SC","Microsoft YaHei",sans-serif;pointer-events:none;z-index:9999;max-width:320px;background:rgba(255,255,255,0.95);color:#1a1a1a;box-shadow:0 8px 32px rgba(0,0,0,0.10),0 1px 3px rgba(0,0,0,0.06);backdrop-filter:blur(16px);-webkit-backdrop-filter:blur(16px);border:1px solid rgba(0,0,0,0.06)';
  document.body.appendChild(tip);

  var curParent = rootId;

  /* Squarify */
  function sq(items, x, y, w, h) {
    if (!items.length || w < 1 || h < 1) return;
    var total = 0;
    for (var i = 0; i < items.length; i++) total += items[i]._v;
    if (total <= 0) return;
    var sc = w * h / total;
    /* No sort — respect the interleaved red-green order from Python. */
    _lay(items, 0, x, y, w, h, sc);
  }
  function _lay(a, s, x, y, w, h, sc) {
    if (s >= a.length) return;
    if (s === a.length - 1) { a[s]._r = [x,y,w,h]; return; }
    var sh = Math.min(w, h), rA = 0, best = 1e9, end = s;
    for (var i = s; i < a.length; i++) {
      var tA = rA + a[i]._v * sc, sl = tA / sh, worst = 0;
      for (var j = s; j <= i; j++) {
        var d = a[j]._v * sc / sl;
        var asp = sl > d ? sl/d : d/sl;
        if (asp > worst) worst = asp;
      }
      if (worst <= best || i === s) { best = worst; end = i; rA = tA; }
      else break;
    }
    var sl = rA / sh, p = 0;
    for (var i = s; i <= end; i++) {
      var il = a[i]._v * sc / sl;
      if (w <= h) { a[i]._r = [x+p, y, il, sl]; p += il; }
      else { a[i]._r = [x, y+p, sl, il]; p += il; }
    }
    if (w <= h) _lay(a, end+1, x, y+sl, w, h-sl, sc);
    else _lay(a, end+1, x+sl, y, w-sl, h, sc);
  }

  /* Adaptive font size based on tile area */
  function fontSize(w, h) {
    var area = w * h;
    if (area > 30000) return 15;
    if (area > 15000) return 13;
    if (area > 6000) return 12;
    if (area > 2000) return 11;
    return 10;
  }

  /* Render */
  function render(pid) {
    curParent = pid;
    c.innerHTML = '';
    var par = nodes[pid];
    if (!par || !par.ch.length) return;
    var W = c.clientWidth, H = c.clientHeight;
    if (W < 10 || H < 10) return;
    var items = par.ch.map(function(n){ return {_v: Math.max(n.value, 0.01), node: n}; });
    sq(items, 0, 0, W, H);
    var frag = document.createDocumentFragment();
    for (var i = 0; i < items.length; i++) {
      var it = items[i];
      if (!it._r) continue;
      var r = it._r, n = it.node;
      var rw = Math.round(r[2]), rh = Math.round(r[3]);
      var t = document.createElement('div');
      var fs = fontSize(rw, rh);
      var hasCh = n.ch && n.ch.length && maxD > 1;
      t.style.cssText = 'position:absolute;box-sizing:border-box;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;overflow:hidden;padding:4px;font-family:"PingFang SC","Microsoft YaHei","Helvetica Neue",sans-serif;letter-spacing:0.3px;border:1px solid rgba(0,0,0,0.06);transition:all 0.18s cubic-bezier(0.22,1,0.36,1)';
      t.style.left = Math.round(r[0])+'px';
      t.style.top = Math.round(r[1])+'px';
      t.style.width = rw+'px';
      t.style.height = rh+'px';
      t.style.fontSize = fs+'px';
      t.style.lineHeight = '1.35';
      t.style.color = '#2a2a2a';
      t.style.background = n.color;
      t.style.boxShadow = 'inset 0 1px 0 rgba(255,255,255,0.35), inset 0 -1px 0 rgba(0,0,0,0.03)';
      if (hasCh) t.style.cursor = 'pointer';

      /* Content: name bold, pct below */
      if (rw > 32 && rh > 16) {
        var txt = n.text || n.label;
        var parts = txt.split('<br>');
        var nameStr = escHtml(parts[0] || '');
        var pctStr = escHtml(parts[1] || '');
        var html = '';
        if (rw > 50 && rh > 28) {
          html = '<div style="font-weight:600;pointer-events:none;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:'+(rw-8)+'px">' + nameStr + '</div>';
          if (pctStr && rh > 38) {
            html += '<div style="pointer-events:none;opacity:0.7;font-size:'+(fs-1)+'px;margin-top:1px">' + pctStr + '</div>';
          }
        } else {
          html = '<div style="pointer-events:none;font-weight:500;font-size:'+(fs-1)+'px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:'+(rw-6)+'px">' + nameStr + '</div>';
        }
        t.innerHTML = html;
      }

      (function(n, t) {
        t.addEventListener('mouseenter', function() {
          tip.innerHTML = escHtml(n.hover || n.label).replace('&lt;br&gt;', '<br>');
          tip.style.display = 'block';
          t.style.boxShadow = '0 4px 16px rgba(0,0,0,0.08), inset 0 1px 0 rgba(255,255,255,0.5)';
          t.style.zIndex = '5';
          t.style.transform = 'scale(1.02)';
        });
        t.addEventListener('mousemove', function(e) {
          var tx = e.clientX + 14, ty = e.clientY + 14;
          if (tx + 320 > window.innerWidth) tx = e.clientX - 320;
          if (tx < 8) tx = 8;
          if (ty + 200 > window.innerHeight) ty = e.clientY - 200;
          if (ty < 8) ty = 8;
          tip.style.left = tx+'px';
          tip.style.top = ty+'px';
        });
        t.addEventListener('mouseleave', function() {
          tip.style.display = 'none';
          t.style.boxShadow = 'inset 0 1px 0 rgba(255,255,255,0.25), inset 0 -1px 0 rgba(0,0,0,0.04)';
          t.style.zIndex = '';
          t.style.transform = '';
        });
        if (n.ch && n.ch.length && maxD > 1) {
          t.addEventListener('click', function(){ render(n.id); });
        }
      })(n, t);
      frag.appendChild(t);
    }
    c.appendChild(frag);

    /* Fade-in animation */
    c.style.opacity = '0';
    requestAnimationFrame(function(){ c.style.transition = 'opacity 0.3s ease'; c.style.opacity = '1'; });

    /* Back button — pill style */
    if (pid !== rootId) {
      var parName = nodes[pid] ? nodes[pid].label : '';
      var b = document.createElement('div');
      b.style.cssText = 'position:absolute;top:10px;left:10px;background:rgba(255,255,255,0.88);color:#1a1a1a;padding:5px 14px;border-radius:20px;cursor:pointer;font:500 13px/1.4 "PingFang SC","Microsoft YaHei",sans-serif;z-index:10;backdrop-filter:blur(8px);-webkit-backdrop-filter:blur(8px);box-shadow:0 2px 8px rgba(0,0,0,0.1);border:1px solid rgba(0,0,0,0.06);transition:all 0.15s ease';
      b.textContent = '\u2190 ' + parName;
      b.addEventListener('mouseenter', function(){ b.style.background = 'rgba(255,255,255,0.98)'; b.style.boxShadow = '0 4px 12px rgba(0,0,0,0.15)'; });
      b.addEventListener('mouseleave', function(){ b.style.background = 'rgba(255,255,255,0.88)'; b.style.boxShadow = '0 2px 8px rgba(0,0,0,0.1)'; });
      b.addEventListener('click', function(){ render(rootId); });
      c.appendChild(b);
    }
  }
  render(rootId);
  var _rt;
  window.addEventListener('resize', function(){ clearTimeout(_rt); _rt = setTimeout(function(){ render(curParent); }, 200); });
})
"""


def _render_inline_treemap(div_id: str, data: dict, max_depth: int = 2,
                           height: int = 520) -> str:
    """Render a self-contained treemap using inline JS (no CDN)."""
    import json as _json
    data_json = _json.dumps(data, ensure_ascii=True).replace("</", "<\\/")
    return (
        f'<div id="{div_id}" style="width:100%;height:{height}px;'
        f'border-radius:12px;overflow:hidden;background:linear-gradient(135deg,#f0eded,#e8e6e4)"></div>\n'
        f'<script>\n{_TREEMAP_ENGINE_JS}(\'{div_id}\', {data_json}, {max_depth});\n</script>'
    )


def _render_plotly_sector_treemap(sectors: list, limit_ups: list = None,
                                  sector_stocks: dict = None,
                                  div_id: str = "sectorTreemap") -> str:
    """Build a Plotly treemap for board data.

    Hierarchy: stock → sector → root.  Click a sector to drill in.
    When ``sector_stocks`` is available (from stock_board_industry_cons_em),
    tiles are sized by real market_cap_yi.  Otherwise falls back to
    turnover-based allocation using limit-up stocks and leaders.

    Returns HTML div + JS script (requires plotly.js CDN in <head>).
    """
    if not sectors:
        return ""

    import json as _json

    ids = ["root"]
    labels = ["全市场"]
    parents = [""]
    values = [0]
    colors = ["#E0E0DC"]
    texts = [""]
    customdata = [""]

    # Build limit-up lookup: sector → list of stocks
    lu_by_sector: dict = {}
    for stock in (limit_ups or []):
        sec = str(stock.get("sector", "") or "")
        if sec:
            lu_by_sector.setdefault(sec, []).append(stock)

    # Interleave gainers and losers for visual red-green patchwork effect.
    # Pair by turnover rank: biggest gainer next to biggest loser, etc.
    # This ensures adjacent tiles in the squarify layout have different colors.
    _gainers = sorted(
        [s for s in sectors[:60] if float(s.get("pct_change", 0) or 0) > 0],
        key=lambda s: float(s.get("total_turnover_yi", 0) or 0), reverse=True,
    )
    _losers = sorted(
        [s for s in sectors[:60] if float(s.get("pct_change", 0) or 0) <= 0],
        key=lambda s: float(s.get("total_turnover_yi", 0) or 0), reverse=True,
    )
    _interleaved = []
    gi, li = 0, 0
    while gi < len(_gainers) or li < len(_losers):
        if gi < len(_gainers):
            _interleaved.append(_gainers[gi]); gi += 1
        if li < len(_losers):
            _interleaved.append(_losers[li]); li += 1
    # If one side is much larger, insert neutral-ish items from the dominant
    # side between minority items to keep visual balance.
    # (The squarify JS now respects this order without re-sorting.)

    seen_sectors = set()
    _used_ids = {"root"}
    for s in _interleaved:
        sector_name = str(s.get("sector", ""))
        if not sector_name or sector_name in seen_sectors:
            continue
        seen_sectors.add(sector_name)

        pct = float(s.get("pct_change", 0) or 0)
        turnover = float(s.get("total_turnover_yi", 0) or 0)
        leader = str(s.get("leader", "") or "")
        leader_pct = float(s.get("leader_pct", 0) or 0)
        adv = int(s.get("advance_count", 0) or 0)
        dec = int(s.get("decline_count", 0) or 0)
        net_flow = float(s.get("net_flow_yi", 0) or 0)

        # Sector parent node (id = "sec:{name}")
        sec_id = f"sec:{sector_name}"
        sign = "+" if pct > 0 else ""
        ids.append(sec_id)
        labels.append(sector_name)
        parents.append("root")
        values.append(max(turnover, 0.01))
        colors.append(_pct_to_hex(pct))
        texts.append(f"{sector_name} {sign}{pct:.2f}%")

        hover_parts = [
            f"<b>{_esc(sector_name)}</b>",
            f"板块涨跌: {sign}{pct:.2f}%",
            f"成交额: {turnover:.1f}亿",
        ]
        if adv or dec:
            hover_parts.append(f"涨/跌: {adv}/{dec}")
        if net_flow:
            fsign = "+" if net_flow > 0 else ""
            hover_parts.append(f"净流入: {fsign}{net_flow:.1f}亿")
        customdata.append("<br>".join(hover_parts))

        # Helper to generate unique stock id
        def _stock_id(name, sector):
            base = f"st:{name}@{sector}"
            if base not in _used_ids:
                _used_ids.add(base)
                return base
            i = 2
            while f"{base}#{i}" in _used_ids:
                i += 1
            uid = f"{base}#{i}"
            _used_ids.add(uid)
            return uid

        # --- Child stock nodes ---
        # Priority: sector_stocks (real market cap) > limit-ups > leader only
        real_stocks = (sector_stocks or {}).get(sector_name, [])
        lu_stocks = lu_by_sector.get(sector_name, [])
        sector_val = max(turnover, 0.01)

        if real_stocks:
            # Best case: real constituent data with market_cap_yi
            total_mcap = sum(float(st.get("market_cap_yi", 0) or 0) for st in real_stocks) or 1.0
            child_sum = 0.0
            for st in real_stocks:
                st_name = str(st.get("name", ""))
                st_pct = float(st.get("pct_change", 0) or 0)
                st_mcap = float(st.get("market_cap_yi", 0) or 0)
                st_amount = float(st.get("amount_yi", 0) or 0)
                st_size = max(st_mcap / total_mcap * sector_val, 0.01)
                child_sum += st_size

                st_sign = "+" if st_pct > 0 else ""
                ids.append(_stock_id(st_name, sector_name))
                labels.append(st_name)
                parents.append(sec_id)
                values.append(st_size)
                colors.append(_pct_to_hex(st_pct))
                texts.append(f"{st_name}<br>{st_sign}{st_pct:.1f}%")
                customdata.append(
                    f"<b>{_esc(st_name)}</b> ({_esc(sector_name)})<br>"
                    f"涨跌幅: {st_sign}{st_pct:.2f}%<br>"
                    f"总市值: {st_mcap:.0f}亿"
                    + (f"<br>成交额: {st_amount:.1f}亿" if st_amount else "")
                )

            # Remainder → "其他" bucket
            remainder = max(sector_val - child_sum, 0.01)
            if remainder > 0.02:
                ids.append(f"other:{sector_name}")
                labels.append("其他")
                parents.append(sec_id)
                values.append(remainder)
                colors.append(_pct_to_hex(pct))
                texts.append("")
                customdata.append(f"{_esc(sector_name)} 其他成份股")

        elif lu_stocks:
            # Fallback: limit-up stocks (no real market cap, use amount)
            total_lu_amount = sum(float(st.get("amount_yi", 0) or 0) for st in lu_stocks) or 1.0
            lu_names = {str(st.get("name", "")) for st in lu_stocks}
            has_extra_leader = leader and leader not in lu_names
            lu_share = 0.7 if has_extra_leader else 1.0
            child_sum = 0.0

            for st in lu_stocks:
                st_name = str(st.get("name", ""))
                st_pct = float(st.get("pct_change", 0) or 0)
                st_amount = float(st.get("amount_yi", 0) or 0)
                boards = int(st.get("boards", 1) or 1)
                seal = float(st.get("seal_amount_yi", 0) or 0)
                st_size = max(st_amount / total_lu_amount * sector_val * lu_share, 0.01)
                child_sum += st_size

                st_sign = "+" if st_pct > 0 else ""
                ids.append(_stock_id(st_name, sector_name))
                labels.append(st_name)
                parents.append(sec_id)
                values.append(st_size)
                colors.append(_pct_to_hex(st_pct))
                texts.append(f"{st_name}<br>{st_sign}{st_pct:.1f}%")

                st_hover = [
                    f"<b>{_esc(st_name)}</b> ({_esc(sector_name)})",
                    f"涨跌幅: {st_sign}{st_pct:.2f}%",
                    f"成交额: {st_amount:.2f}亿",
                ]
                if boards > 1:
                    st_hover.append(f"连板: {boards}板")
                if seal > 0:
                    st_hover.append(f"封板资金: {seal:.1f}亿")
                customdata.append("<br>".join(st_hover))

            remainder = max(sector_val - child_sum, 0.01)
            if has_extra_leader:
                lsign = "+" if leader_pct > 0 else ""
                ids.append(_stock_id(leader, sector_name))
                labels.append(leader)
                parents.append(sec_id)
                values.append(remainder)
                colors.append(_pct_to_hex(leader_pct))
                texts.append(f"{leader}<br>{lsign}{leader_pct:.1f}%")
                customdata.append(
                    f"<b>{_esc(leader)}</b> ({_esc(sector_name)})<br>"
                    f"涨跌幅: {lsign}{leader_pct:.2f}%<br>领涨股"
                )
            else:
                ids.append(f"other:{sector_name}")
                labels.append("其他")
                parents.append(sec_id)
                values.append(remainder)
                colors.append(_pct_to_hex(pct))
                texts.append("")
                customdata.append(f"{_esc(sector_name)} 其他成份股")
        else:
            # Minimal fallback: leader as sole child
            if leader:
                lsign = "+" if leader_pct > 0 else ""
                ids.append(_stock_id(leader, sector_name))
                labels.append(leader)
                parents.append(sec_id)
                values.append(sector_val)
                colors.append(_pct_to_hex(leader_pct))
                texts.append(f"{leader}<br>{lsign}{leader_pct:.1f}%")
                customdata.append(
                    f"<b>{_esc(leader)}</b> ({_esc(sector_name)})<br>"
                    f"涨跌幅: {lsign}{leader_pct:.2f}%<br>"
                    f"板块成交额: {turnover:.1f}亿"
                )

    # Root value must equal sum of direct children (branchvalues="total")
    values[0] = sum(values[i] for i, p in enumerate(parents) if p == "root")

    data = {
        "ids": ids, "labels": labels, "parents": parents,
        "values": values, "colors": colors, "texts": texts,
        "customdata": customdata,
    }
    return _render_inline_treemap(div_id, data, max_depth=2, height=520)


def _render_plotly_stock_treemap(heatmap_data: dict, div_id: str = "stockTreemap") -> str:
    """Build a Plotly treemap for stock-level heatmap data.

    Hierarchy: stock → sector → root.
    Size = market_cap, Color = pct_change.
    """
    if not heatmap_data:
        return ""

    nodes = heatmap_data.get("nodes", [])
    if not nodes:
        return ""

    ids = ["root"]
    labels = ["研究池"]
    parents = [""]
    values = [0]
    colors = ["#E0E0DC"]
    texts = [""]
    customdata = [""]
    seen_sectors = set()
    _used_ids = {"root"}

    # First pass: collect unique sectors
    for n in nodes:
        sector = str(n.get("sector", "其他") or "其他")
        if sector not in seen_sectors:
            seen_sectors.add(sector)
            sec_id = f"sec:{sector}"
            ids.append(sec_id)
            labels.append(sector)
            parents.append("root")
            values.append(0)
            colors.append("#BCBCB8")
            texts.append(sector)
            customdata.append(f"<b>{_esc(sector)}</b>")

    # Second pass: add stocks
    for n in nodes:
        name = str(n.get("name", n.get("ticker", "")))
        ticker = str(n.get("ticker", ""))
        sector = str(n.get("sector", "其他") or "其他")
        pct = float(n.get("pct_change", 0) or 0)
        cap = float(n.get("market_cap", 0) or n.get("size_score", 1) or 1)
        action = str(n.get("action", "HOLD")).upper()
        conf = float(n.get("confidence", 0) or 0)

        st_id = f"st:{name}@{sector}"
        if st_id in _used_ids:
            i = 2
            while f"{st_id}#{i}" in _used_ids:
                i += 1
            st_id = f"{st_id}#{i}"
        _used_ids.add(st_id)

        ids.append(st_id)
        labels.append(name)
        parents.append(f"sec:{sector}")
        values.append(max(cap, 0.01))
        colors.append(_pct_to_hex(pct))
        sign = "+" if pct > 0 else ""
        texts.append(f"{name}<br>{sign}{pct:.1f}%")

        action_labels = {"BUY": "建议关注", "SELL": "建议回避", "HOLD": "维持观察", "VETO": "风控否决"}
        hover_parts = [
            f"<b>{_esc(name)}</b> ({_esc(ticker)})",
            f"涨跌幅: {sign}{pct:.2f}%",
            f"信号: {action_labels.get(action, action)}",
        ]
        if conf > 0:
            hover_parts.append(f"置信度: {conf:.0%}")
        hover_parts.append(f"板块: {_esc(sector)}")
        customdata.append("<br>".join(hover_parts))

    # Sector values = sum of children; root = sum of sectors
    for i, pid in enumerate(parents):
        if pid.startswith("sec:"):
            # Find sector index and add to its value
            for j, sid in enumerate(ids):
                if sid == pid:
                    values[j] += values[i]
                    break
    values[0] = sum(values[i] for i, p in enumerate(parents) if p == "root")

    data = {
        "ids": ids, "labels": labels, "parents": parents,
        "values": values, "colors": colors, "texts": texts,
        "customdata": customdata,
    }
    return _render_inline_treemap(div_id, data, max_depth=1, height=480)

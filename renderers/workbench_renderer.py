"""Product workbench renderer.

This is the product entry point: report library, watchlist state, follow-up
triggers, and links into snapshot/research/audit reports.
"""

from __future__ import annotations

import csv
import io
import logging
from pathlib import Path

from ..report_index import build_report_index, save_report_index
from ..replay_service import ReplayService
from ..replay_store import ReplayStore
from ..workbench_state import save_workbench_state
from .decision_labels import AI_DISCLAIMER_BANNER
from .shared_utils import _esc, _html_wrap
from .workbench_view import WorkbenchView, WorkbenchRow

logger = logging.getLogger(__name__)


_WORKBENCH_CSS = """
.container{max-width:1320px}
.workbench-head{display:flex;align-items:flex-end;justify-content:space-between;gap:1rem;margin:.2rem 0 1rem}
.workbench-head h1{margin:0;font-size:1.8rem;letter-spacing:0}
.workbench-sub{color:var(--muted);font-size:.86rem;margin-top:.25rem}
.wb-actions{display:flex;gap:.45rem;flex-wrap:wrap;justify-content:flex-end}
.wb-action-btn,.wb-ctl button,.wb-state button{border:1px solid rgba(255,255,255,.09);background:rgba(255,255,255,.04);color:var(--fg);border-radius:7px;padding:.38rem .58rem;font-size:.76rem;cursor:pointer}
.wb-action-btn:hover,.wb-ctl button:hover,.wb-state button:hover{background:rgba(96,165,250,.11);border-color:rgba(96,165,250,.32)}
.wb-tabs{display:flex;gap:.45rem;flex-wrap:wrap;margin:.75rem 0 1rem}
.wb-tab{border:1px solid rgba(255,255,255,.08);background:rgba(255,255,255,.035);border-radius:999px;padding:.42rem .72rem;color:var(--fg);font-size:.8rem}
.wb-kpis{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:.65rem;margin-bottom:1rem}
.wb-kpi{border:1px solid rgba(255,255,255,.06);background:rgba(255,255,255,.025);border-radius:8px;padding:.75rem .85rem}
.wb-kpi .v{font-size:1.45rem;font-weight:800;line-height:1;color:var(--white)}
.wb-kpi .l{font-size:.72rem;color:var(--muted);margin-top:.22rem}
.wb-controls{display:grid;grid-template-columns:minmax(220px,1.4fr) repeat(5,minmax(115px,.72fr));gap:.5rem;margin:.8rem 0 1rem}
.wb-ctl input,.wb-ctl select{width:100%;height:2.2rem;border:1px solid rgba(255,255,255,.09);background:rgba(255,255,255,.035);color:var(--fg);border-radius:7px;padding:.3rem .55rem;font-size:.82rem}
.wb-ctl select option{background:#0b1423;color:#dde6f0}
.wb-visible{color:var(--muted);font-size:.78rem;margin:-.35rem 0 .7rem}
.wb-board{border:1px solid rgba(255,255,255,.07);border-radius:8px;overflow:hidden;background:rgba(255,255,255,.02)}
.wb-row,.wb-th{display:grid;grid-template-columns:1.18fr .56fr .48fr .62fr .76fr 1.08fr 1.15fr .82fr .84fr;gap:.65rem;align-items:center}
.wb-th{position:sticky;top:0;z-index:2;padding:.7rem .9rem;background:rgba(12,23,35,.98);color:var(--muted);font-size:.72rem;letter-spacing:.04em;text-transform:uppercase}
.wb-th button{all:unset;cursor:pointer;color:inherit}
.wb-th button:hover{color:var(--white)}
.wb-th .sort-ind{display:inline-block;width:1em;margin-left:.18rem;color:var(--blue)}
.wb-row{padding:.8rem .9rem;border-top:1px solid rgba(255,255,255,.055);font-size:.84rem}
.wb-row:hover{background:rgba(96,165,250,.045)}
.wb-row[data-user-state~="ignore"]{opacity:.48}
.wb-row[data-user-state~="favorite"]{background:rgba(251,191,36,.045)}
.wb-row[data-user-state~="review"]{box-shadow:inset 3px 0 0 var(--yellow)}
.wb-name{font-weight:700;color:var(--white)}
.wb-meta{font-size:.72rem;color:var(--muted);margin-top:.15rem}
.wb-small{font-size:.78rem;color:var(--muted);line-height:1.45}
.wb-links{display:flex;gap:.35rem;flex-wrap:wrap}
.wb-links a{color:var(--blue);text-decoration:none;border:1px solid rgba(96,165,250,.22);border-radius:999px;padding:.18rem .45rem;font-size:.72rem}
.wb-links a:hover{background:rgba(96,165,250,.1)}
.wb-links .disabled{color:var(--muted);border:1px solid rgba(255,255,255,.08);border-radius:999px;padding:.18rem .45rem;font-size:.72rem;opacity:.62}
.wb-change{font-size:.72rem;color:var(--muted);margin-top:.18rem}
.wb-delta-up{color:var(--green)}.wb-delta-down{color:var(--red)}.wb-delta-flat{color:var(--muted)}
.wb-diff{font-size:.74rem;line-height:1.45;color:var(--fg);margin-top:.35rem}
.wb-diff.major{color:var(--red)}.wb-diff.moderate{color:var(--yellow)}
.wb-trigger{display:inline-flex;margin:.18rem .2rem .18rem 0;border:1px solid rgba(251,191,36,.26);border-radius:999px;padding:.08rem .35rem;color:var(--yellow);font-size:.68rem}
.wb-state{display:grid;grid-template-columns:repeat(4,1fr);gap:.25rem}
.wb-state button{padding:.22rem .28rem;font-size:.7rem}
.wb-state button.active{background:rgba(96,165,250,.16);border-color:rgba(96,165,250,.45);color:var(--white)}
.wb-note{grid-column:1/-1;width:100%;border:1px solid rgba(255,255,255,.08);background:rgba(255,255,255,.03);color:var(--fg);border-radius:7px;padding:.3rem .4rem;font-size:.72rem;margin-top:.2rem}
.wb-empty{padding:2rem;text-align:center;color:var(--muted)}
.wb-empty[hidden]{display:none}
.wb-footer{margin-top:1rem;color:var(--muted);font-size:.74rem;line-height:1.55}
@media(max-width:1180px){.wb-controls{grid-template-columns:repeat(2,minmax(0,1fr))}.wb-kpis{grid-template-columns:repeat(4,minmax(0,1fr))}}
@media(max-width:980px){.wb-kpis{grid-template-columns:repeat(2,minmax(0,1fr))}.wb-controls{grid-template-columns:1fr}.wb-th{display:none}.wb-row{grid-template-columns:1fr;gap:.45rem}.workbench-head{align-items:flex-start;flex-direction:column}.wb-actions{justify-content:flex-start}.wb-row>div{display:grid;grid-template-columns:7.2rem minmax(0,1fr);gap:.4rem}.wb-row>div::before{content:attr(data-label);color:var(--muted);font-size:.72rem;letter-spacing:.04em}.wb-row>div:first-child{display:block}.wb-row>div:first-child::before{content:""}}
"""


_STATUS_TIPS = {
    "可跟踪": "结论与质量门禁均可接受，进入观察池跟踪触发条件",
    "等待触发": "目前不直接参与，等待价格/事件/行业条件确认",
    "需复核": "存在数据口径、质量或风险缺口，需人工确认后再使用",
    "回避": "当前结论或风控状态偏负面，不作为参与候选",
    "已生成": "报告已生成，缺少足够状态信号",
    "待生成": "今日清单中尚未生成该标的研报",
}

_REL_VAL = {
    "premium": "估值溢价",
    "discount": "估值折价",
    "fair": "估值接近行业",
    "unavailable": "估值不足",
}

_REL_Q = {
    "quality_premium": "质量支撑",
    "weak_quality": "质量偏弱",
    "mixed": "质量分化",
    "unavailable": "质量不足",
}


def _badge(label: str, cls: str = "hold", title: str = "") -> str:
    tip = f' title="{_esc(title)}"' if title else ""
    return f'<span class="badge badge-{_esc(cls or "hold")}"{tip}>{_esc(label or "—")}</span>'


def _delta(row: WorkbenchRow) -> str:
    if row.status == "待生成":
        return '<div class="wb-change">等待生成</div>'
    if not row.previous_run_id:
        return '<div class="wb-change">首次入库</div>'
    action = "动作未变"
    if row.action_changed:
        action = f"{row.previous_action or '—'} → {row.action or '—'}"
    d = row.confidence_delta
    cls = "wb-delta-up" if d > 0.03 else ("wb-delta-down" if d < -0.03 else "wb-delta-flat")
    if row.confidence < 0 or row.previous_confidence < 0:
        return f'<div class="wb-change">{_esc(action)} · <span class="wb-delta-flat">置信度 —</span></div>'
    return (
        f'<div class="wb-change">{_esc(action)} · '
        f'<span class="{cls}">{d:+.0%}</span></div>'
    )


def _diff_summary(row: WorkbenchRow) -> str:
    if not row.diff_summary:
        return ""
    cls = row.diff_severity if row.diff_severity in ("major", "moderate", "minor") else ""
    text = "；".join(str(x) for x in row.diff_summary[:2])
    return f'<div class="wb-diff {cls}">{_esc(text)}</div>'


def _trigger_summary(row: WorkbenchRow) -> str:
    if not row.review_triggers:
        return _esc(row.next_review or row.invalidator or "—")
    bits = []
    for t in row.review_triggers[:2]:
        reason = str(t.get("reason") or "")
        due = str(t.get("due_date") or "")
        label = reason if not due else f"{reason} {due}"
        bits.append(f'<span class="wb-trigger">{_esc(label[:54])}</span>')
    return "".join(bits)


def _links_html(row: WorkbenchRow) -> str:
    links = row.report_links or {}
    labels = [("snapshot", "结论"), ("research", "研究"), ("audit", "审计")]
    parts = []
    for key, label in labels:
        href = links.get(key)
        if href:
            parts.append(f'<a href="{_esc(href)}">{label}</a>')
        else:
            parts.append(f'<span class="disabled">{label}</span>')
    return f'<div class="wb-links">{"".join(parts)}</div>'


def _state_controls(row: WorkbenchRow) -> str:
    return (
        f'<div class="wb-state" data-run-id="{_esc(row.run_id)}">'
        f'<button type="button" data-state="favorite" title="关注">关注</button>'
        f'<button type="button" data-state="read" title="已读">已读</button>'
        f'<button type="button" data-state="review" title="人工复核">复核</button>'
        f'<button type="button" data-state="ignore" title="忽略">忽略</button>'
        f'<input class="wb-note" data-note placeholder="备注" aria-label="备注">'
        f'</div>'
    )


def _row(row: WorkbenchRow) -> str:
    profile = row.profile_label or "—"
    val = _REL_VAL.get(row.relative_valuation_label, row.relative_valuation_label or "—")
    qlt = _REL_Q.get(row.relative_quality_label, row.relative_quality_label or "—")
    quality = row.quality_grade or "—"
    links_html = _links_html(row)
    flags = []
    if row.data_quality_count:
        flags.append(f"口径 {row.data_quality_count}")
    if row.risk_count:
        flags.append(f"风险 {row.risk_count}")
    flags_text = " · ".join(flags) or "—"
    search = " | ".join([
        row.display_name,
        row.trade_date,
        profile,
        row.status,
        row.action_label,
        row.why_now,
        row.next_review,
        row.review_reason,
        " ".join(row.diff_summary),
    ])
    confidence_attr = "" if row.confidence < 0 else f"{row.confidence:.6f}"
    changed = "1" if (row.action_changed or row.diff_score > 0) else "0"
    trigger = "1" if row.review_triggers and row.status != "需复核" else "0"
    return (
        f'<div class="wb-row" data-run-id="{_esc(row.run_id)}" '
        f'data-search="{_esc(search.lower())}" data-status="{_esc(row.status)}" '
        f'data-action="{_esc(row.action)}" data-quality="{_esc(quality)}" '
        f'data-confidence="{confidence_attr}" '
        f'data-date="{_esc(row.trade_date)}" data-changed="{changed}" '
        f'data-trigger="{trigger}" data-diff="{_esc(row.diff_severity)}">'
        f'<div><div class="wb-name">{_esc(row.display_name)}</div>'
        f'<div class="wb-meta">{_esc(row.trade_date)} · {_esc(profile)}</div>{_delta(row)}{_diff_summary(row)}</div>'
        f'<div data-label="状态">{_badge(row.status, row.status_class, _STATUS_TIPS.get(row.status, ""))}</div>'
        f'<div data-label="结论">{_badge(row.action_label, row.action_class)}</div>'
        f'<div data-label="置信/质量"><strong>{_esc(row.confidence_pct)}</strong><div class="wb-meta">质量 {quality}</div></div>'
        f'<div data-label="相对行业" class="wb-small">{_esc(val)}<br>{_esc(qlt)} · {flags_text}</div>'
        f'<div data-label="为什么现在" class="wb-small">{_esc(row.why_now or "—")}</div>'
        f'<div data-label="下一步" class="wb-small">{_trigger_summary(row)}</div>'
        f'<div data-label="报告">{links_html}</div>'
        f'<div data-label="状态标记">{_state_controls(row)}</div>'
        f'</div>'
    )


_WORKBENCH_JS = """
<script>
(function(){
  var rows = Array.prototype.slice.call(document.querySelectorAll('.wb-row'));
  var board = document.querySelector('.wb-board');
  var search = document.getElementById('wb-search');
  var filters = {
    status: document.getElementById('wb-filter-status'),
    action: document.getElementById('wb-filter-action'),
    quality: document.getElementById('wb-filter-quality'),
    change: document.getElementById('wb-filter-change'),
    state: document.getElementById('wb-filter-state')
  };
  var visibleCount = document.getElementById('wb-visible-count');
  var empty = document.getElementById('wb-filter-empty');
  var stateKey = 'tradingagents.workbench.state.v1';
  var state = {};
  try { state = JSON.parse(localStorage.getItem(stateKey) || '{}') || {}; } catch(e) { state = {}; }

  function save(){
    try { localStorage.setItem(stateKey, JSON.stringify(state)); } catch(e) {}
    if(location.protocol.indexOf('http') === 0){
      fetch('/api/workbench/state', {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify(state)
      }).catch(function(){});
    }
  }
  function rowState(row){ return state[row.getAttribute('data-run-id')] || {}; }
  function stateTokens(s){
    var out = [];
    ['favorite','read','review','ignore'].forEach(function(k){ if(s[k]) out.push(k); });
    return out.join(' ');
  }
  function applyState(){
    rows.forEach(function(row){
      var rid = row.getAttribute('data-run-id');
      var s = state[rid] || {};
      row.setAttribute('data-user-state', stateTokens(s));
      row.querySelectorAll('[data-state]').forEach(function(btn){
        var key = btn.getAttribute('data-state');
        btn.classList.toggle('active', !!s[key]);
      });
      var note = row.querySelector('[data-note]');
      if(note && document.activeElement !== note) note.value = s.note || '';
    });
  }
  function matchesState(row, mode){
    if(mode === 'all') return true;
    var s = rowState(row);
    if(mode === 'unread') return !s.read;
    return !!s[mode];
  }
  function filterRows(){
    var q = (search && search.value || '').trim().toLowerCase();
    var vals = {};
    Object.keys(filters).forEach(function(k){ vals[k] = filters[k] ? filters[k].value : 'all'; });
    var n = 0;
    rows.forEach(function(row){
      var ok = true;
      if(q && row.getAttribute('data-search').indexOf(q) < 0) ok = false;
      if(vals.status !== 'all' && row.getAttribute('data-status') !== vals.status) ok = false;
      if(vals.action !== 'all' && row.getAttribute('data-action') !== vals.action) ok = false;
      if(vals.quality !== 'all' && row.getAttribute('data-quality') !== vals.quality) ok = false;
      if(vals.change === 'changed' && row.getAttribute('data-changed') !== '1') ok = false;
      if(vals.change === 'trigger' && row.getAttribute('data-trigger') !== '1') ok = false;
      if(!matchesState(row, vals.state)) ok = false;
      row.hidden = !ok;
      if(ok) n += 1;
    });
    if(visibleCount) visibleCount.textContent = String(n);
    if(empty) empty.hidden = n !== 0;
  }
  function sortRows(key){
    var dir = board.getAttribute('data-sort-key') === key && board.getAttribute('data-sort-dir') !== 'asc' ? 'asc' : 'desc';
    board.setAttribute('data-sort-key', key);
    board.setAttribute('data-sort-dir', dir);
    document.querySelectorAll('[data-sort] .sort-ind').forEach(function(el){ el.textContent = ''; });
    var active = document.querySelector('[data-sort="' + key + '"] .sort-ind');
    if(active) active.textContent = dir === 'asc' ? '↑' : '↓';
    var mult = dir === 'asc' ? 1 : -1;
    var get = function(row){
      if(key === 'name') return row.getAttribute('data-search') || '';
      if(key === 'status') return row.getAttribute('data-status') || '';
      if(key === 'action') return row.getAttribute('data-action') || '';
      if(key === 'quality') return row.getAttribute('data-quality') || '';
      if(key === 'date') return row.getAttribute('data-date') || '';
      if(key === 'changed') return Number(row.getAttribute('data-changed') || 0);
      if(key === 'confidence') {
        var raw = row.getAttribute('data-confidence');
        var parsed = raw === null || raw === '' ? NaN : Number(raw);
        return Number.isFinite(parsed) ? parsed : null;
      }
      return '';
    };
    rows.sort(function(a,b){
      var av = get(a), bv = get(b);
      if(av === null && bv === null) return 0;
      if(av === null) return 1;
      if(bv === null) return -1;
      if(typeof av === 'number' || typeof bv === 'number') return (av - bv) * mult;
      return String(av).localeCompare(String(bv), 'zh-Hans-CN') * mult;
    });
    rows.forEach(function(row){ board.appendChild(row); });
    filterRows();
  }
  document.querySelectorAll('[data-sort]').forEach(function(btn){
    btn.addEventListener('click', function(){ sortRows(btn.getAttribute('data-sort')); });
  });
  if(search) search.addEventListener('input', filterRows);
  Object.keys(filters).forEach(function(k){ if(filters[k]) filters[k].addEventListener('change', filterRows); });
  rows.forEach(function(row){
    row.querySelectorAll('[data-state]').forEach(function(btn){
      btn.addEventListener('click', function(){
        var rid = row.getAttribute('data-run-id');
        state[rid] = state[rid] || {};
        var key = btn.getAttribute('data-state');
        state[rid][key] = !state[rid][key];
        save(); applyState(); filterRows();
      });
    });
    var note = row.querySelector('[data-note]');
    if(note) note.addEventListener('input', function(){
      var rid = row.getAttribute('data-run-id');
      state[rid] = state[rid] || {};
      state[rid].note = note.value;
      save();
    });
  });
  var exportBtn = document.getElementById('wb-export-state');
  if(exportBtn) exportBtn.addEventListener('click', function(){
    var blob = new Blob([JSON.stringify(state, null, 2)], {type:'application/json'});
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url; a.download = 'workbench_state.json'; a.click();
    setTimeout(function(){ URL.revokeObjectURL(url); }, 500);
  });
  var reviewBtn = document.getElementById('wb-run-review');
  if(reviewBtn) reviewBtn.addEventListener('click', function(){
    reviewBtn.textContent = '复核中';
    fetch('/api/workbench/review/run', {method:'POST'}).then(function(r){ return r.json(); }).then(function(data){
      var count = data && data.report ? data.report.alert_count : 0;
      reviewBtn.textContent = '复核 ' + count;
    }).catch(function(){ reviewBtn.textContent = '复核失败'; });
  });
  var calBtn = document.getElementById('wb-run-calibration');
  if(calBtn) calBtn.addEventListener('click', function(){
    calBtn.textContent = '校准中';
    fetch('/api/workbench/calibration/run', {method:'POST'}).then(function(r){ return r.json(); }).then(function(){
      calBtn.textContent = '校准已刷新';
    }).catch(function(){ calBtn.textContent = '校准失败'; });
  });
  fetch('workbench_state.json', {cache:'no-store'}).then(function(r){
    if(!r.ok) throw new Error('no state');
    return r.json();
  }).then(function(remote){
    state = Object.assign({}, remote || {}, state || {});
    applyState(); filterRows();
  }).catch(function(){});
  applyState();
  filterRows();
})();
</script>
"""


def render_workbench(view: WorkbenchView) -> str:
    """Render product workbench HTML."""
    grade_mix = " · ".join(f"{_esc(k)}:{v}" for k, v in sorted(view.grade_mix.items())) or "—"
    rows_html = "".join(_row(r) for r in view.rows)
    if not rows_html:
        rows_html = '<div class="wb-empty">暂无报告。生成单股报告后，这里会自动形成报告库和观察池。</div>'
    scope_tabs = ""
    if view.requested_tickers:
        scope_tabs = (
            f'<span class="wb-tab">今日清单 {len(view.requested_tickers)} 个</span>'
            f'<span class="wb-tab">待生成 {len(view.missing_tickers)} 个</span>'
        )

    body = f"""
    <div class="workbench-head">
      <div>
        <h1>个股研究工作台</h1>
        <div class="workbench-sub">报告库 · 观察池 · 复盘触发 · 历史变化</div>
      </div>
      <div>
        <div class="workbench-sub">生成时间 {_esc(view.generated_at)}</div>
        <div class="wb-actions">
          <a class="wb-action-btn" href="today_changes.html">今日变化</a>
          <a class="wb-action-btn" href="calibration.html">校准</a>
          <a class="wb-action-btn" href="workbench.csv">CSV</a>
          <a class="wb-action-btn" href="workbench.md">Markdown</a>
          <button class="wb-action-btn" type="button" id="wb-export-state">导出状态</button>
          <button class="wb-action-btn" type="button" id="wb-run-review">刷新复核</button>
          <button class="wb-action-btn" type="button" id="wb-run-calibration">刷新校准</button>
        </div>
      </div>
    </div>
    <div class="wb-tabs">
      {scope_tabs}
      <span class="wb-tab">日期 {' / '.join(_esc(d) for d in view.trade_dates) or '—'}</span>
      <span class="wb-tab">质量分布 {grade_mix}</span>
    </div>
    <div class="wb-kpis">
      <div class="wb-kpi"><div class="v">{view.total_tickers}</div><div class="l">覆盖标的</div></div>
      <div class="wb-kpi"><div class="v">{view.total_reports}</div><div class="l">历史报告</div></div>
      <div class="wb-kpi"><div class="v">{view.buy_count}</div><div class="l">BUY 标的</div></div>
      <div class="wb-kpi"><div class="v">{view.wait_count}</div><div class="l">等待触发</div></div>
      <div class="wb-kpi"><div class="v">{view.review_count}</div><div class="l">需复核状态</div></div>
      <div class="wb-kpi"><div class="v">{view.trigger_count}</div><div class="l">触发待看</div></div>
      <div class="wb-kpi"><div class="v">{view.changed_count}</div><div class="l">较上次变化</div></div>
    </div>
    <div class="wb-controls">
      <label class="wb-ctl"><input id="wb-search" type="search" placeholder="搜索代码、名称、触发原因、变化摘要"></label>
      <label class="wb-ctl"><select id="wb-filter-status"><option value="all">全部状态</option><option value="可跟踪">可跟踪</option><option value="等待触发">等待触发</option><option value="需复核">需复核</option><option value="回避">回避</option><option value="已生成">已生成</option><option value="待生成">待生成</option></select></label>
      <label class="wb-ctl"><select id="wb-filter-action"><option value="all">全部结论</option><option value="BUY">BUY</option><option value="HOLD">HOLD</option><option value="SELL">SELL</option><option value="VETO">VETO</option></select></label>
      <label class="wb-ctl"><select id="wb-filter-quality"><option value="all">全部质量</option><option value="A">A</option><option value="B">B</option><option value="C">C</option><option value="D">D</option><option value="—">—</option></select></label>
      <label class="wb-ctl"><select id="wb-filter-change"><option value="all">全部变化</option><option value="changed">较上次变化</option><option value="trigger">触发待看</option></select></label>
      <label class="wb-ctl"><select id="wb-filter-state"><option value="all">全部标记</option><option value="favorite">关注</option><option value="review">人工复核</option><option value="unread">未读</option><option value="ignore">忽略</option></select></label>
    </div>
    <div class="wb-visible">当前显示 <span id="wb-visible-count">{len(view.rows)}</span> / {len(view.rows)} 个标的</div>
    <div class="wb-board">
      <div class="wb-th">
        <div><button data-sort="name">标的<span class="sort-ind"></span></button></div><div><button data-sort="status">状态<span class="sort-ind"></span></button></div>
        <div><button data-sort="action">结论<span class="sort-ind"></span></button></div><div><button data-sort="confidence">置信/质量<span class="sort-ind"></span></button></div>
        <div>相对行业</div><div>为什么现在</div><div>下一步</div><div>报告</div><div>标记</div>
      </div>
      {rows_html}
    </div>
    <div class="wb-empty" id="wb-filter-empty" hidden>没有符合筛选条件的报告。</div>
    <div class="wb-footer">{AI_DISCLAIMER_BANNER}</div>
    {_WORKBENCH_JS}
    """
    return _html_wrap("个股研究工作台", body, "产品工作台", extra_css=_WORKBENCH_CSS)


def render_workbench_csv(view: WorkbenchView) -> str:
    """Render the workbench rows as CSV."""
    buf = io.StringIO()
    buf.write("\ufeff")
    writer = csv.writer(buf)
    writer.writerow([
        "ticker", "name", "trade_date", "status", "action", "confidence",
        "quality", "why_now", "next_review", "review_reason", "changed",
        "diff_severity", "diff_summary", "snapshot", "research", "audit",
    ])
    for row in view.rows:
        writer.writerow([
            row.ticker,
            row.ticker_name,
            row.trade_date,
            row.status,
            row.action,
            "" if row.confidence < 0 else f"{row.confidence:.4f}",
            row.quality_grade,
            row.why_now,
            row.next_review,
            row.review_reason,
            "yes" if row.action_changed or row.diff_score > 0 else "no",
            row.diff_severity,
            "；".join(row.diff_summary),
            row.report_links.get("snapshot", ""),
            row.report_links.get("research", ""),
            row.report_links.get("audit", ""),
        ])
    return buf.getvalue()


def render_workbench_markdown(view: WorkbenchView) -> str:
    """Render a compact markdown export."""
    lines = [
        "# 个股研究工作台",
        "",
        f"> 生成时间 {view.generated_at} | 覆盖 {view.total_tickers} 个标的 | 历史报告 {view.total_reports} 份",
        "",
        "| 标的 | 日期 | 状态 | 结论 | 置信度 | 质量 | 下一步 | 变化 |",
        "|---|---:|---|---|---:|---|---|---|",
    ]
    for row in view.rows:
        changed = "；".join(row.diff_summary[:2]) or ("动作变化" if row.action_changed else "")
        next_review = row.review_reason or row.next_review or row.invalidator or ""
        lines.append(
            "| {ticker} {name} | {date} | {status} | {action} | {conf} | {quality} | {next_review} | {changed} |".format(
                ticker=row.ticker,
                name=row.ticker_name,
                date=row.trade_date,
                status=row.status,
                action=row.action,
                conf=row.confidence_pct,
                quality=row.quality_grade or "—",
                next_review=_md_cell(next_review),
                changed=_md_cell(changed),
            )
        )
    lines.append("")
    lines.append(AI_DISCLAIMER_BANNER)
    return "\n".join(lines) + "\n"


def _md_cell(text: str) -> str:
    return str(text or "—").replace("|", "｜").replace("\n", " ")


def _write_workbench_exports(view: WorkbenchView, output_dir: Path) -> None:
    output_dir.joinpath("workbench.csv").write_text(render_workbench_csv(view), encoding="utf-8")
    output_dir.joinpath("workbench.md").write_text(render_workbench_markdown(view), encoding="utf-8")
    state_path = output_dir / "workbench_state.json"
    if not state_path.exists():
        save_workbench_state({}, output_dir)


def generate_workbench_report(
    output_dir: str = "data/reports",
    storage_dir: str = "data/replays",
    *,
    limit: int = 120,
    latest_per_ticker: bool = True,
    tickers: list[str] | None = None,
    ticker_names: dict[str, str] | None = None,
) -> str:
    """Generate the workbench/report-library page from replay traces."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    store = ReplayStore(storage_dir=storage_dir)
    svc = ReplayService(store=store)
    view = WorkbenchView.build(
        svc,
        limit=limit,
        latest_per_ticker=latest_per_ticker,
        output_dir=str(out),
        tickers=tickers,
        ticker_names=ticker_names,
    )
    index = build_report_index(svc, output_dir=out)
    save_report_index(index, out)
    _write_workbench_exports(view, out)
    try:
        from .today_changes_renderer import generate_today_changes_report

        generate_today_changes_report(view=view, output_dir=str(out))
    except Exception:
        logger.warning("today changes report generation failed", exc_info=True)
    try:
        from .calibration_renderer import generate_calibration_page

        generate_calibration_page(output_dir=str(out), auto_build=True)
    except Exception:
        logger.warning("calibration page generation failed", exc_info=True)
    path = out / "workbench.html"
    path.write_text(render_workbench(view), encoding="utf-8")
    return str(path)

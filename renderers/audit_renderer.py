"""
Tier 3 Trust Audit report renderer.

Evidence chains + replay + parser + compliance -- deep dive.
Consumes AuditView from views.py, never raw traces.
All user-facing text is in Chinese (A-share product).

Extracted from report_renderer.py to reduce file size.
"""

from .views import AuditView
from .decision_labels import (
    get_action_label, get_risk_label, get_node_label,
    NODE_STATUS_LABELS, PARSE_STATUS_LABELS, COMPLIANCE_STATUS_LABELS,
    FRESHNESS_STATUS_LABELS, NO_COMPLIANCE_LABEL,
    safe_badge_class, get_severity_label,
)
from .shared_utils import (
    _esc, _html_wrap, _ticker_display, _status_light,
)


def render_audit(view: AuditView) -> str:
    """Render Tier 3 Trust Audit Report -- trust signals first, details below."""

    # ── Trust signals section (new, top of page) ──
    trust_html = ""
    if view.trust_signals:
        cards = ""
        for ts in view.trust_signals:
            status = ts.get("status", "warn")
            value = ts.get("value", 0)
            cards += f"""
            <div class="trust-card {status}">
              <div class="tv">{value:.0%}</div>
              <div class="tl">{_esc(ts.get("label", ""))}</div>
              <div class="te">{_esc(ts.get("explanation", ""))}</div>
            </div>"""
        trust_html = f'<div class="trust-grid">{cards}</div>'

    # ── Weakest link callout ──
    weakest_html = ""
    if view.weakest_node:
        weakest_html = f'<div class="callout">\u5efa\u8bae\u4eba\u5de5\u590d\u6838\uff1a<strong>{_esc(get_node_label(view.weakest_node))}</strong></div>'

    # ── Manual check items ──
    manual_html = ""
    if view.manual_check_items:
        items = "".join(f"<li>{_esc(m)}</li>" for m in view.manual_check_items)
        manual_html = f'<div class="card"><h3>\u9700\u4eba\u5de5\u786e\u8ba4\u4e8b\u9879</h3><ul>{items}</ul></div>'

    # Metrics dashboard (kept)
    m = view.metrics
    metrics_html = ""
    if m:
        metrics_html = f"""
    <div class="kpi-row">
      <div class="kpi"><span class="kpi-val">{m.strict_parse_rate:.0%}</span><span class="kpi-label">\u4e25\u683c\u89e3\u6790\u7387</span></div>
      <div class="kpi"><span class="kpi-val">{m.fallback_rate:.0%}</span><span class="kpi-label">\u56de\u9000\u89e3\u6790\u7387</span></div>
      <div class="kpi"><span class="kpi-val">{m.narrative_dependency_rate:.0%}</span><span class="kpi-label">\u53d9\u4e8b\u4f9d\u8d56\u7387</span></div>
      <div class="kpi"><span class="kpi-val">{m.claim_to_evidence_binding_rate:.0%}</span><span class="kpi-label">\u8bba\u636e\u7ed1\u5b9a\u7387</span></div>
      <div class="kpi"><span class="kpi-val">{m.replay_completeness_rate:.0%}</span><span class="kpi-label">\u56de\u653e\u5b8c\u6574\u7387</span></div>
    </div>"""

    # Parse quality table
    parse_html = ""
    if view.parse_table:
        rows = ""
        for p in view.parse_table:
            status = p.get("parse_status", "")
            label = PARSE_STATUS_LABELS.get(status, status)
            cls = "badge-ok" if status == "strict_ok" else ("badge-warn" if status == "fallback_used" else "badge-low")
            warnings = ", ".join(p.get("warnings", [])) or "-"
            rows += f"""<tr>
              <td>{_esc(get_node_label(p['node_name']))}</td>
              <td><span class="badge {cls}">{_esc(label)}</span></td>
              <td>{p.get('parse_confidence', -1):.1f}</td>
              <td style="font-size:.8rem;">{_esc(warnings)}</td>
            </tr>"""
        parse_html = f"""
    <div class="card">
      <h3>\u89e3\u6790\u8d28\u91cf</h3>
      <table><thead><tr><th>\u8282\u70b9</th><th>\u72b6\u6001</th><th>\u7f6e\u4fe1\u5ea6</th><th>\u8b66\u544a</th></tr></thead>
      <tbody>{rows}</tbody></table>
    </div>"""

    # Compliance nodes
    compliance_html = ""
    if view.compliance_nodes:
        rows = ""
        for cn in view.compliance_nodes:
            label = COMPLIANCE_STATUS_LABELS.get(cn.compliance_status, cn.compliance_status)
            rules = ", ".join(cn.compliance_rules_fired) or "-"
            rows += f"""<tr>
              <td>{_esc(get_node_label(cn.node_name))}</td>
              <td><span class="badge badge-{'ok' if cn.compliance_status == 'allow' else 'warn'}">{_esc(label)}</span></td>
              <td style="font-size:.8rem;">{_esc(rules)}</td>
            </tr>"""
        compliance_html = f"""
    <div class="card">
      <h3>\u5408\u89c4\u51b3\u7b56</h3>
      <table><thead><tr><th>\u8282\u70b9</th><th>\u72b6\u6001</th><th>\u89e6\u53d1\u89c4\u5219</th></tr></thead>
      <tbody>{rows}</tbody></table>
    </div>"""

    # Freshness
    freshness_html = ""
    if view.vendor_freshness:
        rows = ""
        for vf in view.vendor_freshness:
            status = vf.get("status", "unknown")
            label = FRESHNESS_STATUS_LABELS.get(status, status)
            cls = "badge-ok" if status in ("FRESH", "fresh", "RECOVERED") else "badge-warn"
            rows += f"""<tr>
              <td>{_esc(vf.get('key', ''))}</td>
              <td><span class="badge {cls}">{_esc(label)}</span></td>
              <td>{_esc(str(vf.get('system_lag_min', '\u65e0')))}</td>
              <td>{_esc(str(vf.get('doc_lag_min', '\u65e0')))}</td>
            </tr>"""
        stale_alert = '' if view.freshness_ok else '<div style="color:var(--red); margin-bottom:.5rem;">\u68c0\u6d4b\u5230\u8fc7\u671f\u6570\u636e\u6e90</div>'
        freshness_html = f"""
    <div class="card">
      <h3>\u6570\u636e\u6e90\u65b0\u9c9c\u5ea6</h3>
      {stale_alert}
      <table><thead><tr><th>\u4f9b\u5e94\u5546/\u65b9\u6cd5</th><th>\u72b6\u6001</th><th>\u7cfb\u7edf\u5ef6\u8fdf</th><th>\u6587\u6863\u5ef6\u8fdf</th></tr></thead>
      <tbody>{rows}</tbody></table>
    </div>"""

    # Failures
    _issue_type_labels = {
        "error": "\u5f02\u5e38", "parse_degraded": "\u89e3\u6790\u964d\u7ea7", "vetoed": "\u5426\u51b3",
        "compliance_escalation": "\u5408\u89c4\u5347\u7ea7", "unattributed_claims": "\u65e0\u5f52\u5c5e\u8bba\u636e",
    }
    failures_html = ""
    if view.failures:
        rows = ""
        for f in view.failures:
            issues_str = "; ".join(
                _issue_type_labels.get(i.get("type", ""), i.get("type", ""))
                + (f": {i.get('details', '')}" if i.get('details') else "")
                for i in f.get("issues", [])
            ) or str(f.get("error", ""))
            status_cn = NODE_STATUS_LABELS.get(str(f.get('status', '')), str(f.get('status', '')))
            rows += f"""<tr>
              <td>{_esc(get_node_label(str(f.get('node_name', ''))))}</td>
              <td>{_esc(status_cn)}</td>
              <td style="font-size:.8rem;">{_esc(issues_str[:200])}</td>
            </tr>"""
        failures_html = f"""
    <div class="card">
      <h3>\u6545\u969c\u8bb0\u5f55</h3>
      <table><thead><tr><th>\u8282\u70b9</th><th>\u72b6\u6001</th><th>\u95ee\u9898</th></tr></thead>
      <tbody>{rows}</tbody></table>
    </div>"""

    # Lineage -- Audit tier: structured traceability, counts + coverage, not raw IDs
    lineage_html = ""
    if view.lineage_stages:
        rows = ""
        for s in view.lineage_stages:
            node = get_node_label(s.get('node', ''))
            status = s.get('status', '')
            status_cn = NODE_STATUS_LABELS.get(status, status)
            ev_in = s.get('evidence_consumed', [])
            cl_out = s.get('claims_produced', [])
            cl_in = s.get('claims_consumed', [])
            attr = s.get('attributed', 0)
            unattr = s.get('unattributed', 0)
            decision = s.get('decision', {})
            risk = s.get('risk', {})

            # Evidence: count + coverage indicator
            if ev_in:
                ev_str = f"{len(ev_in)}\u6761"
            else:
                ev_str = '<span style="color:var(--muted)">\u2014</span>'

            # Claims: count + attribution quality
            if cl_out:
                total = len(cl_out)
                if unattr > 0:
                    cl_str = f'{total}\u6761 <span style="color:var(--red)">({unattr}\u6761\u65e0\u636e)</span>'
                else:
                    cl_str = f'{total}\u6761 <span style="color:var(--green)">\u5168\u90e8\u6709\u636e</span>'
            elif cl_in:
                cl_str = f'\u6d88\u8d39{len(cl_in)}\u6761'
            else:
                cl_str = '<span style="color:var(--muted)">\u2014</span>'

            # Decision
            action_raw = decision.get('action', '') if isinstance(decision, dict) else ''
            if action_raw:
                action_cn = get_action_label(action_raw)
                conf = decision.get('confidence', 0)
                decision_str = f'{_esc(action_cn)} ({conf:.0%})'
            else:
                decision_str = '<span style="color:var(--muted)">\u2014</span>'

            # Risk
            if isinstance(risk, dict) and risk.get('flags'):
                cats = risk.get('categories', [])
                cat_str = "\u3001".join(_esc(c) for c in cats[:3])
                _vs2 = risk.get('veto_source', '')
                veto_label2 = "\u98ce\u63a7\u95e8\u7981" if _vs2 == "risk_gate" else ("\u7814\u7a76\u5426\u51b3" if _vs2 == "agent_veto" else "\u5426\u51b3")
                veto = f' <span class="badge badge-veto">{veto_label2}</span>' if risk.get('vetoed') else ""
                risk_str = f'{risk["flags"]}\u9879\uff08{cat_str}\uff09{veto}'
            else:
                risk_str = '<span style="color:var(--muted)">\u2014</span>'

            rows += f"""<tr>
              <td><span class="badge badge-{'ok' if status == 'ok' else 'warn'}">{_esc(status_cn)}</span></td>
              <td>{_esc(node)}</td>
              <td style="font-size:.85rem;">{ev_str}</td>
              <td style="font-size:.85rem;">{cl_str}</td>
              <td style="font-size:.85rem;">{decision_str}</td>
              <td style="font-size:.85rem;">{risk_str}</td>
            </tr>"""
        lineage_html = f"""
    <div class="card">
      <h3>\u8bc1\u636e\u6eaf\u6e90</h3>
      <table><thead><tr><th>\u72b6\u6001</th><th>\u8282\u70b9</th><th>\u8bc1\u636e\u8f93\u5165</th><th>\u8bba\u636e\u6d41\u8f6c</th><th>\u51b3\u7b56</th><th>\u98ce\u63a7\u6807\u8bb0</th></tr></thead>
      <tbody>{rows}</tbody></table>
    </div>"""

    # ── Audit conclusion (top-level, computed from trust signals) ──
    conclusion_html = ""
    if view.audit_conclusion_label:
        level = view.audit_conclusion_level
        level_color = {"high": "green", "medium": "yellow", "low": "red"}.get(level, "yellow")
        conclusion_html = f"""
    <div class="card" style="overflow:hidden;">
      <div style="position:absolute;inset:0 auto auto 0;width:4px;height:100%;background:var(--{level_color});border-radius:20px 0 0 20px;"></div>
      <div style="padding-left:.6rem;">
        <div style="font-size:1.1rem;font-weight:800;color:var(--white);">\u5ba1\u8ba1\u7ed3\u8bba\uff1a{_esc(view.audit_conclusion_label)}</div>
        <div style="margin-top:.3rem;color:var(--muted);font-size:.88rem;line-height:1.6;">
          {_esc(view.audit_conclusion_text)}
        </div>
      </div>
    </div>"""

    body = f"""
    <h1>{_esc(_ticker_display(view))}</h1>
    <p class="subtitle">{_esc(view.trade_date)} &middot; \u4fe1\u4efb\u5ba1\u8ba1\u62a5\u544a</p>
    <div class="banner">\u672c\u62a5\u544a\u5e2e\u52a9\u60a8\u5224\u65ad\uff1a\u8fd9\u6b21\u7ed3\u8bba\u662f\u5426\u503c\u5f97\u4fe1\u4efb\uff1f\u54ea\u4e9b\u73af\u8282\u9700\u8981\u4eba\u5de5\u590d\u6838\uff1f</div>

    <div class="reveal">{conclusion_html}</div>

    <h2>\u4fe1\u4efb\u4fe1\u53f7</h2>
    <div class="reveal reveal-d1">{trust_html}</div>
    <div class="reveal reveal-d1">{weakest_html}</div>
    <div class="reveal reveal-d2">{manual_html}</div>

    <h2>\u63a7\u5236\u9762\u677f</h2>

    <div class="reveal reveal-d2">
      <h3>\u8d28\u91cf\u6307\u6807</h3>
      {metrics_html}
    </div>

    <div class="reveal reveal-d3">
      <h3>\u89e3\u6790\u8d28\u91cf\u4e0e\u7ed3\u6784\u5316\u8f93\u51fa</h3>
      {parse_html}
    </div>

    <div class="reveal reveal-d4">
      <h3>\u5408\u89c4\u5ba1\u67e5</h3>
      {compliance_html or '<div class="card" style="color:var(--muted);">' + _esc(NO_COMPLIANCE_LABEL) + '</div>'}
    </div>

    <div class="reveal reveal-d4">
      <h3>\u6570\u636e\u6e90\u65b0\u9c9c\u5ea6\u4e0e\u5065\u5eb7\u5ea6</h3>
      {freshness_html or '<div class="card">' + _status_light(view.freshness_ok, "\u6240\u6709\u6570\u636e\u6e90\u72b6\u6001\u6b63\u5e38") + '</div>'}
    </div>

    <h2>\u8bc1\u636e\u6eaf\u6e90</h2>
    <div class="reveal reveal-d5">{lineage_html}</div>

    <div class="reveal reveal-d6">
      <h3>\u6545\u969c\u4e0e\u8b66\u544a</h3>
      {failures_html or '<div class="card" style="color:var(--green);">\u65e0\u6545\u969c\u8bb0\u5f55\u3002</div>'}
    </div>"""

    return _html_wrap(f"{_ticker_display(view)} \u4fe1\u4efb\u5ba1\u8ba1\u62a5\u544a \u2014 {view.trade_date}", body, "\u4fe1\u4efb\u5ba1\u8ba1\u62a5\u544a")

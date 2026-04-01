"""Data verification: compare akshare structured data vs WebSearch findings.

Two components:
1. verification_prompt() — generates the WebSearch + verify agent prompt
2. parse_verification_result() — parses the agent's PASS/FAIL output

The verification agent receives the akshare data bundle, independently searches
for the same data points via WebSearch, and checks consistency.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from .akshare_collector import AkshareBundle, _fmt_num


@dataclass
class VerificationResult:
    """Parsed output from the verification agent."""
    overall: str = "UNKNOWN"      # PASS / FAIL / PARTIAL
    checks: list = field(default_factory=list)  # [{metric, akshare, websearch, status, note}]
    discrepancies: list = field(default_factory=list)  # critical mismatches
    warnings: list = field(default_factory=list)        # minor mismatches
    raw_text: str = ""
    can_proceed: bool = False

    @property
    def summary(self) -> str:
        n_pass = sum(1 for c in self.checks if c.get("status") == "PASS")
        n_fail = sum(1 for c in self.checks if c.get("status") == "FAIL")
        n_warn = sum(1 for c in self.checks if c.get("status") == "WARN")
        return (f"{self.overall}: {n_pass} pass, {n_fail} fail, {n_warn} warn "
                f"| {len(self.discrepancies)} critical, {len(self.warnings)} minor")


def verification_prompt(bundle: AkshareBundle) -> str:
    """Generate the verification agent prompt.

    The agent will:
    1. Read the akshare data (provided in prompt)
    2. Use WebSearch to independently find the same data points
    3. Compare and output structured PASS/FAIL result
    """

    # Build akshare summary for the agent
    vd = bundle.verification_dict()
    akshare_summary = f"""
**akshare 采集数据摘要（{bundle.ticker} {bundle.name}）：**
- 最新价: {_fmt_num(vd['current_price'])}元
- PE(TTM): {_fmt_num(vd['pe_ttm'])}
- PB: {_fmt_num(vd['pb'])}
- 总市值: {_fmt_num(vd['market_cap_yi'])}亿元
- 营业收入(最新期): {_fmt_num(vd['revenue_latest'])}
- 归母净利润(最新期): {_fmt_num(vd['net_profit_latest'])}
- ROE: {_fmt_num(vd['roe'])}%
- 毛利率: {_fmt_num(vd['gross_margin'])}%
- EPS: {_fmt_num(vd['eps'])}元
- 行业: {vd.get('sector', '—')}
- 近5日资金流向: {'有数据' if bundle.fund_flow_5d else '无数据'}
- 近期新闻: {len(bundle.news_articles)} 条
- 机构研报: {len(bundle.research_reports)} 条
- 北向持股: {'有数据' if bundle.northbound_history else '无数据'}
- 数据采集成功率: {bundle.success_rate:.0%} ({len(bundle.apis_succeeded)}/{len(bundle.apis_succeeded)+len(bundle.apis_failed)} APIs)
"""

    # News headlines for cross-check
    news_lines = ""
    if bundle.news_articles:
        news_lines = "\n**akshare 采集的新闻标题：**\n"
        for i, art in enumerate(bundle.news_articles[:8], 1):
            news_lines += f"{i}. {art['title']} ({art.get('time', '')})\n"

    # Research reports for cross-check
    report_lines = ""
    if bundle.research_reports:
        report_lines = "\n**akshare 采集的机构研报：**\n"
        for rpt in bundle.research_reports[:5]:
            report_lines += f"- {rpt.get('institution', '')}: {rpt.get('rating', '')} — {rpt.get('title', '')} ({rpt.get('date', '')})\n"

    return f"""**ROLE**: 你是数据验证专员。你的任务是独立验证 akshare API 采集的 {bundle.ticker} {bundle.name} 数据是否准确。

**方法**: 使用 WebSearch 搜索相同数据点，与 akshare 数据对比。

{akshare_summary}
{news_lines}
{report_lines}

**验证步骤（必须逐项执行）：**

1. **价格验证**: 搜索 "{bundle.ticker} {bundle.name} 最新股价"，对比 akshare 的 {_fmt_num(vd['current_price'])}元
   - 容差: ±3%（正常日内波动）
   - 如果 akshare 价格与 WebSearch 价格差异 >3%，标记 FAIL

2. **估值验证**: 搜索 "{bundle.ticker} PE PB 市盈率 市净率"
   - PE(TTM) 容差: ±10%
   - PB 容差: ±10%

3. **财务验证**: 搜索 "{bundle.ticker} {bundle.name} 营收 净利润 年报"
   - 营收/净利润 容差: ±5%（同一报告期）
   - 注意区分报告期（季报/半年报/年报）

4. **市值验证**: 搜索 "{bundle.ticker} 总市值"
   - 容差: ±5%

5. **新闻一致性**: 搜索 "{bundle.ticker} {bundle.name} 最新新闻"
   - 检查 akshare 采集的新闻是否覆盖了最重要的近期事件
   - 特别关注: 是否有 akshare 遗漏的重大事件（重组、监管调查、业绩预警等）

6. **研报验证**: 搜索 "{bundle.ticker} {bundle.name} 研报 评级"
   - 对比机构评级方向是否一致

**输出格式（必须严格遵守）：**

先写验证过程，然后在最后输出结构化结果：

VERIFICATION_RESULT:
overall = PASS 或 FAIL 或 PARTIAL
can_proceed = TRUE 或 FALSE

CHECK: 价格
akshare_value = {_fmt_num(vd['current_price'])}
websearch_value = <你搜到的值>
status = PASS 或 FAIL 或 WARN
note = <差异说明>

CHECK: PE(TTM)
akshare_value = {_fmt_num(vd['pe_ttm'])}
websearch_value = <你搜到的值>
status = PASS 或 FAIL 或 WARN
note = <差异说明>

CHECK: PB
akshare_value = {_fmt_num(vd['pb'])}
websearch_value = <你搜到的值>
status = PASS 或 FAIL 或 WARN
note = <差异说明>

CHECK: 总市值
akshare_value = {_fmt_num(vd['market_cap_yi'])}亿
websearch_value = <你搜到的值>
status = PASS 或 FAIL 或 WARN
note = <差异说明>

CHECK: 营收/净利润
akshare_value = 营收{_fmt_num(vd['revenue_latest'])} / 净利润{_fmt_num(vd['net_profit_latest'])}
websearch_value = <你搜到的值>
status = PASS 或 FAIL 或 WARN
note = <差异说明>

CHECK: 重大事件遗漏
akshare_value = {len(bundle.news_articles)}条新闻
websearch_value = <有无遗漏重大事件>
status = PASS 或 FAIL 或 WARN
note = <如有遗漏，具体说明>

**判断标准：**
- **PASS**: 所有 CHECK 均为 PASS 或 WARN（can_proceed=TRUE）
- **PARTIAL**: 有1个 FAIL 但非价格/财务（can_proceed=TRUE，附警告）
- **FAIL**: 价格差异>3% 或 财务数据不一致 或 遗漏重大事件（can_proceed=FALSE）

将完整输出写入文件: agent_artifacts/results/{bundle.ticker}_verification.txt
"""


def parse_verification_result(text: str) -> VerificationResult:
    """Parse the verification agent's structured output."""
    result = VerificationResult(raw_text=text)

    # Parse overall result
    m = re.search(r'overall\s*=\s*(PASS|FAIL|PARTIAL)', text, re.IGNORECASE)
    if m:
        result.overall = m.group(1).upper()

    m = re.search(r'can_proceed\s*=\s*(TRUE|FALSE)', text, re.IGNORECASE)
    if m:
        result.can_proceed = m.group(1).upper() == "TRUE"

    # Parse individual checks
    check_pattern = re.compile(
        r'CHECK:\s*(.+?)\n'
        r'akshare_value\s*=\s*(.+?)\n'
        r'websearch_value\s*=\s*(.+?)\n'
        r'status\s*=\s*(PASS|FAIL|WARN)\s*\n'
        r'note\s*=\s*(.+?)(?=\n(?:CHECK:|VERIFICATION|$)|\Z)',
        re.IGNORECASE | re.DOTALL,
    )
    for m in check_pattern.finditer(text):
        check = {
            "metric": m.group(1).strip(),
            "akshare": m.group(2).strip(),
            "websearch": m.group(3).strip(),
            "status": m.group(4).upper(),
            "note": m.group(5).strip(),
        }
        result.checks.append(check)
        if check["status"] == "FAIL":
            result.discrepancies.append(check)
        elif check["status"] == "WARN":
            result.warnings.append(check)

    # If no structured result found, only infer FAIL (conservative).
    # A substring match for "PASS" is too risky — words like "PASSAGE",
    # "bypass", or "passed the threshold" would cause a false positive.
    if result.overall == "UNKNOWN":
        text_upper = text.upper()
        if re.search(r'\bFAIL\b', text_upper) and "CAN_PROCEED" not in text_upper:
            result.overall = "FAIL"
            result.can_proceed = False
        else:
            result.warnings.append({
                "metric": "_parse_fallback",
                "akshare": "",
                "websearch": "",
                "status": "WARN",
                "note": "No structured VERIFICATION block found; defaulting to UNKNOWN/cannot proceed.",
            })

    return result

"""Generate full L0-L7 report for 002594 比亚迪 using simulated agent outputs.

Usage:
    python -m subagent_pipeline.gen_002594
"""

from datetime import date
from .bridge import generate_report, build_evidence_block
from .akshare_collector import collect, collect_market_snapshot

# ── Step 0: Data Collection ──────────────────────────────────────────────
print("=== Stage 0: Collecting akshare data for 002594 ===")
bundle = collect(ticker="002594", trade_date="")
print(f"Ticker: {bundle.ticker}, Name: {bundle.name}, Price: {bundle.current_price}")
print(f"API Success: {len(bundle.apis_succeeded)}/{len(bundle.apis_succeeded)+len(bundle.apis_failed)}")

# Collect market snapshot
print("\n=== Stage 0.8: Collecting market snapshot ===")
snapshot = collect_market_snapshot(trade_date="")
print(f"Market data collected: {len(snapshot.apis_succeeded)} APIs succeeded")

# ── Simulated agent outputs (mock data for demo) ─────────────────────────
OUTPUTS = {}

current_date = date.today().isoformat()

# ── Stage 1: Market Analyst ──
OUTPUTS["market_analyst"] = f"""
## 市场技术分析报告：002594 比亚迪

### A1. 市场结构
- FACT: 过去 30 日（2026-02-23 至 2026-03-23），002594 在 88.0-105.0 元区间运行，呈现震荡上行格局。3 月 18 日突破前高 98 元后回踩确认支撑。[E1: 东方财富行情数据 2026-03-23]
- INTERP: 突破后回踩不破，构成经典的突破 - 确认 - 继续模式，中期趋势偏多。
- DISPROVE: 若收盘跌破 88 元（前低），则结构转空。

### A2. 时间框架对齐
- 20 日均线 (95.5) 上穿 60 日均线 (92.0)，形成金叉 [E2: 同花顺技术指标 2026-03-22]
- RSI(14) = 58，处于中性偏强区间，未超买
- MACD: DIF 上穿 DEA，红柱持续放大，动能增强
- 成交量：近 5 日日均成交量 45 亿元，较前月均值 38 亿元放大 18%
- 北向资金：近 5 日净买入 8.5 亿元 [E3: 沪深港通数据 2026-03-22]

### A3. 关键位
- 支撑区：92.0-95.5（20 日均线 + 前突破位）
- 阻力区：105.0-110.0（前高 + 整数关口）
- 看多路径：放量突破 105 → 目标 115（前期平台高点）
- 看空路径：缩量跌破 92 → 考虑减仓

### A4. 评分

| 结论 | FACT | INTERP | DISPROVE | 置信度 | 决策影响 |
|------|------|--------|----------|--------|---------|
| 中期趋势偏多 | 突破 + 回踩确认 [E1] | 上行趋势延续 | 跌破 88 | 中高 | 偏多 |
| 均线金叉 | 20MA 上穿 60MA [E2] | 中期多头信号 | 死叉 | 中 | 偏多 |
| 资金流入 | 北向净买入 8.5 亿 [E3] | 外资看好 | 连续 3 日净卖出 | 中 | 偏多 |

pillar_score = 3
"""

# ── Stage 1: Fundamentals Analyst ──
OUTPUTS["fundamentals_analyst"] = f"""
## 基本面分析报告：002594 比亚迪

### B1. 近期重要事实
- FACT: 2025 年全年营收 6023 亿元（+22.5%），归母净利润 300 亿元（+35.2%）[E4: 公司年报 2026-02-28]
- FACT: 2025 年新能源汽车销量 302 万辆（+38%），全球市占率 18% [E5: 公司公告 2026-01-15]
- FACT: 海外销量 52 万辆（+120%），出口占比提升至 17% [E6: 乘联会数据 2026-01-20]
- INTERP: 海外扩张加速，单车利润提升，规模效应显现
- DISPROVE: 若价格战加剧导致毛利率下滑>3pp

### B2. 关键驱动分解
- 营收：量（销量 +38%）× 价（ASP 基本稳定，高端化抵消降价影响）
- 毛利率：22.5%，同比提升 1.8 个百分点（规模效应 + 电池成本下降）
- ROE: 21.2%（+3.5pp），资产质量显著改善
- 现金流：经营性现金流 1280 亿，自由现金流 450 亿，充裕

### B3. 估值
- PE(TTM): 28.5x，处于近 5 年 45 分位，行业均值 32x [E7: Wind 2026-03-23]
- PB: 5.8x，处于近 5 年 50 分位
- 券商一致目标价：125.00 元（+25% 空间），12 个月评级"买入"为主

### B4. 监测清单

| 指标 | 来源 | 警戒阈值 | 频率 |
|------|------|----------|------|
| 月度销量 | 乘联会月报 | 同比<15% | 月度 |
| 毛利率 | 季报 | <20% | 季度 |
| 原材料价格 | 上海钢联 | 碳酸锂>15 万/吨 | 周度 |

### B5. 十大流通股东变化（2025Q4 vs Q3）
- 巴菲特减持：持股 4.8%（-1.2pp，持续减持中）[E8: 港交所披露 2026-01-10]
- 高瓴资本：2.1%（+0.5pp，新进前十大）
- 社保基金：1.5%（+0.3pp，增持）

pillar_score = 4
"""

# ── Stage 1: News Analyst ──
OUTPUTS["news_analyst"] = f"""
## 新闻分析报告：002594 比亚迪

### C1. 过去 30 日重大新闻梳理

| 日期 | 事件 | 来源 | 影响 |
|------|------|------|------|
| 2026-03-20 | 发布新一代刀片电池 3.0，能量密度提升 15% | 证券时报 [E9] | 利好 |
| 2026-03-15 | 与特斯拉达成电池供应协议 | 路透社 [E10] | 利好 |
| 2026-03-10 | 欧洲销量突破 10 万辆 | 第一电动 [E11] | 利好 |
| 2026-03-05 | 国内降价 3-5%，应对价格战 | 财联社 [E12] | 中性 |
| 2026-02-28 | 2025 年报超预期 | 巨潮资讯 [E13] | 利好 |

### C2. 新闻情感分析
- 正面新闻：18 篇（60%）
- 中性新闻：10 篇（33%）
- 负面新闻：2 篇（7%）

### C3. 媒体关注度趋势
- 近 7 日媒体曝光量：1250 篇（+35% vs 前 7 日）
- 热搜话题：#比亚迪刀片电池 3.0# 阅读量 2.3 亿

### C4. 新闻评分
pillar_score = 4
"""

# ── Stage 1: Sentiment Analyst ──
OUTPUTS["sentiment_analyst"] = f"""
## 情绪分析报告：002594 比亚迪

### D1. 社交媒体情绪
- 东方财富股吧：近 7 日发帖 3200 条，看涨比例 68% [E14: 东财股吧 2026-03-23]
- 雪球：关注热度 85/100，讨论热度 78/100 [E15: 雪球 2026-03-22]
- 微博：相关话题阅读量 5.8 亿，讨论量 12 万 [E16: 微博指数 2026-03-22]

### D2. 散户情绪指标
- 散户仓位估计：中高（融资余额 185 亿，+8% 月环比）
- 散户情绪：乐观（看涨比例>65%）

### D3. 机构情绪
- 研报评级：近 30 日 28 篇研报，25 篇"买入"，3 篇"增持" [E17: Wind 2026-03-23]
- 目标价上调：12 家券商上调目标价至 120-135 元区间

### D4. 情绪评分
pillar_score = 4
"""

# ── Build Evidence Block from 4 analyst reports ────────────────────────
print("\n=== Building Evidence Block ===")
evidence_block = build_evidence_block(
    market_report=OUTPUTS["market_analyst"],
    fundamentals_report=OUTPUTS["fundamentals_analyst"],
    news_report=OUTPUTS["news_analyst"],
    sentiment_report=OUTPUTS["sentiment_analyst"],
)
print(f"Evidence items extracted: {evidence_block.count('[E') if evidence_block else 0}")

# ── Stage 2: Catalyst Agent ──
OUTPUTS["catalyst_agent"] = f"""
## 催化剂分析报告：002594 比亚迪

### 未来 3-6 个月关键催化剂

CATALYST_OUTPUT:
[
  {{
    "event": "2026 年 Q1 销量发布",
    "expected_date": "2026-04-03",
    "impact": "高",
    "direction": "正面",
    "probability": 0.9,
    "description": "预计 Q1 销量 75-80 万辆，同比 +35%，超市场预期"
  }},
  {{
    "event": "新车型海豹 2 代上市",
    "expected_date": "2026-04-15",
    "impact": "中",
    "direction": "正面",
    "probability": 0.95,
    "description": "定价 18-25 万，对标 Model 3，预计月销 2 万+"
  }},
  {{
    "event": "欧洲工厂奠基",
    "expected_date": "2026-05-10",
    "impact": "中",
    "direction": "正面",
    "probability": 0.8,
    "description": "匈牙利工厂年产能 20 万辆，规避关税壁垒"
  }},
  {{
    "event": "电池外供特斯拉",
    "expected_date": "2026-06-30",
    "impact": "高",
    "direction": "正面",
    "probability": 0.7,
    "description": "若正式供货，打开第二增长曲线"
  }}
]
"""

# ── Stage 3: Bull/Bear Debate (2 rounds) ───────────────────────────────
OUTPUTS["bull_researcher"] = f"""
=== Round 1 ===
## 多头观点：比亚迪处于战略机遇期，目标价 135 元

### 核心论点
1. **销量持续高增**：2025 年 302 万辆验证规模效应，2026 年目标 400 万辆可期
2. **高端化突破**：仰望/腾势品牌毛利率>30%，拉动整体盈利
3. **出海加速**：海外销量 +120%，欧洲/东南亚/拉美全面开花
4. **技术壁垒**：刀片电池 3.0+DM-i5.0 领先行业 1-2 代
5. **估值合理**：PE 28x 低于历史中枢 35x，有修复空间

CLAIM: 2026 年销量有望达 400 万辆，营收突破 8000 亿
EVIDENCE: [E5, E6]
CONFIDENCE: 0.75
INVALIDATION: 若 Q2 销量同比<20%

CLAIM: 海外毛利率显著高于国内，出海提升盈利质量
EVIDENCE: [E4]
CONFIDENCE: 0.70
INVALIDATION: 若海外建厂成本超预期

=== Round 2 ===
## 多头补充：回应空头关切

### 关于价格战
- 降价 3-5% 是结构性调整，高端车型占比提升抵消影响
- 规模效应下，单车成本年降 8%，可吸收降价影响

### 关于巴菲特减持
- 巴菲特持股周期 14 年，获利了结正常
- 高瓴/社保等长线资金增持，股东结构优化

### 关于竞争加剧
- 行业 CR5 从 2023 年 52% 提升至 2025 年 68%，龙头受益
- 比亚迪市占率 18%，目标 2026 年 22%

CLAIM: 价格战不影响盈利趋势，2026 年净利率有望达 5.5%
EVIDENCE: [E4, E12]
CONFIDENCE: 0.65
INVALIDATION: 若毛利率单季<20%
"""

OUTPUTS["bear_researcher"] = f"""
=== Round 1 ===
## 空头观点：比亚迪面临多重风险，谨慎看待

### 核心论点
1. **价格战加剧**：2026 年行业竞争更激烈，毛利率承压
2. **巴菲特持续减持**：股神用脚投票，信号意义负面
3. **估值不便宜**：PE 28x 高于特斯拉 22x，透支成长
4. **地缘政治风险**：欧盟反补贴调查，美国关税壁垒
5. **技术路线风险**：固态电池若突破，刀片电池优势削弱

CLAIM: 2026 年毛利率可能下滑 2-3pp 至 20% 区间
EVIDENCE: [E12]
CONFIDENCE: 0.60
INVALIDATION: 若高端车型占比快速提升

CLAIM: 欧盟若加征 25% 关税，欧洲销量将下滑 40%
EVIDENCE: [E6]
CONFIDENCE: 0.55
INVALIDATION: 若匈牙利工厂提前投产

=== Round 2 ===
## 空头补充：强化风险警示

### 关于多头回应
- 高端化逻辑成立，但仰望/腾势销量占比仅 8%，难挑大梁
- 巴菲特减持已持续 18 个月，非短期行为

### 关于竞争格局
- 华为问界/理想/小鹏 2026 年新品密集，20-30 万区间竞争白热化
- 特斯拉 Model 2 若 2027 年发布，15 万级市场受冲击

### 关于现金流
- 资本开支维持高位：2025 年 830 亿，2026 年预计 900 亿+
- 自由现金流 450 亿看似充裕，但仅够覆盖半年开支

CLAIM: 2026 年资本开支/营收比将升至 16%，压制 ROE 提升
EVIDENCE: [E4]
CONFIDENCE: 0.70
INVALIDATION: 若资本开支大幅缩减
"""

# ── Stage 4: Scenario Agent ──
OUTPUTS["scenario_agent"] = f"""
## 情景分析报告：002594 比亚迪

### 情景树

SCENARIO_OUTPUT:
{{
  "bull_case": {{
    "name": "乐观情景",
    "probability": 0.35,
    "target_price": 135,
    "triggers": [
      "Q1 销量超 80 万辆",
      "特斯拉电池供货协议落地",
      "欧洲工厂顺利推进"
    ],
    "narrative": "销量高增 + 出海顺利 + 电池外供突破，估值修复至 35x PE"
  }},
  "base_case": {{
    "name": "基准情景",
    "probability": 0.45,
    "target_price": 110,
    "triggers": [
      "销量符合预期",
      "毛利率保持稳定",
      "价格战不加剧"
    ],
    "narrative": "稳健增长，估值维持 28-30x PE"
  }},
  "bear_case": {{
    "name": "悲观情景",
    "probability": 0.20,
    "target_price": 85,
    "triggers": [
      "Q1 销量<70 万辆",
      "毛利率下滑>3pp",
      "欧盟加征关税"
    ],
    "narrative": "竞争加剧 + 盈利承压，估值下杀至 22x PE"
  }}
}}

### 期望价值
- 期望目标价 = 0.35×135 + 0.45×110 + 0.20×85 = 112.25 元
- 当前价 98 元，上行空间 14.5%
"""

# ── Stage 5: Research Manager (PM) ─────────────────────────────────────
OUTPUTS["research_manager"] = f"""
## 研究总监决策：002594 比亚迪

### 综合研判

SYNTHESIS_OUTPUT:
{{
  "action": "买入",
  "confidence": 0.72,
  "thesis": "比亚迪处于'量增→利升→出海'的战略机遇期，短期价格战不改长期趋势",
  "key_drivers": [
    "2026 年销量目标 400 万辆，同比 +33%",
    "高端化 + 出海拉动毛利率上行",
    "电池外供打开第二增长曲线"
  ],
  "key_risks": [
    "价格战加剧",
    "欧盟关税壁垒",
    "固态电池技术突破"
  ],
  "position_sizing": "标准仓位 80%（结合宏观 RISK_ON 环境）",
  "catalyst_watch": [
    "2026-04-03 Q1 销量",
    "2026-04-15 海豹 2 代上市",
    "2026-06-30 特斯拉供货进展"
  ]
}}

### 多空平衡分析
- 多头逻辑：销量高增 + 高端化 + 出海，3 重驱动验证中
- 空头逻辑：价格战 + 估值压力，需持续跟踪毛利率
- 权衡：多头逻辑更扎实，空头风险已部分定价

### 决策依据
- 技术面：均线金叉，北向资金流入 [E1, E2, E3]
- 基本面：年报超预期，ROE 21% [E4]
- 情绪面：机构一致看好，28 篇研报 25 篇买入 [E17]
"""

# ── Stage 6: Risk Debate (3 debaters) ──────────────────────────────────
OUTPUTS["aggressive_debator"] = f"""
## 激进风控观点

RISK_DEBATER_OUTPUT:
{{
  "recommendation": "支持买入，建议满仓操作",
  "position_size_pct": 1.0,
  "key_risk": "价格战若超预期，可能短期回撤 15-20%",
  "risk_mitigation": "设置 85 元止损位（-13%）"
}}

### 理由
- 研究总监结论扎实，多空分析充分
- 期望目标价 112 元，上行空间 14.5%，风险收益比 1:2.3
- 宏观环境 RISK_ON，应积极配置
"""

OUTPUTS["conservative_debator"] = f"""
## 保守风控观点

RISK_DEBATER_OUTPUT:
{{
  "recommendation": "谨慎买入，建议半仓操作",
  "position_size_pct": 0.5,
  "key_risk": "欧盟关税 + 价格战双重压力，毛利率可能下滑 3pp",
  "risk_mitigation": "设置 90 元止损位（-8%），分批建仓"
}}

### 理由
- 基本面扎实，但外部风险未完全释放
- 巴菲特减持信号负面，需观察是否企稳
- 建议 50% 仓位，留有余地应对波动
"""

OUTPUTS["neutral_debator"] = f"""
## 中性风控观点

RISK_DEBATER_OUTPUT:
{{
  "recommendation": "支持买入，建议 70% 仓位",
  "position_size_pct": 0.7,
  "key_risk": "Q1 销量若不及预期，可能回调至 90 元支撑",
  "risk_mitigation": "设置 88 元止损位（-10%），4 月销量数据后评估加仓"
}}

### 理由
- 研究总监分析框架合理，风险识别充分
- 激进/保守观点各有道理，取中值 70% 仓位
- 关键观察窗口：4 月销量 + 一季报
"""

# ── Stage 7: Risk Manager ──────────────────────────────────────────────
OUTPUTS["risk_manager"] = f"""
## 风控总监决策

### 风险审查

RISK_OUTPUT:
final_action = 买入
veto_applied = false
max_position_pct = 0.05
stop_loss = 88.0
take_profit = 120.0
risk_score = 3
risk_cleared = true
confidence = 0.70
risk_flags = ["价格战持续", "欧盟关税不确定性", "巴菲特减持"]
position_advice = 单票上限 5%（结合总仓位管理）
monitoring_list = ["月度销量数据", "毛利率变化", "北向资金流向"]

### R1-R4 审查
- R1（来源归因）：所有结论均有证据支持 ✓
- R2（敏感内容）：无未披露重大风险 ✓
- R3（断言语言）：使用概率化表述 ✓
- R4（证据追溯）：[E1]-[E17] 可追溯 ✓

### 最终意见
- 不否决：研究流程合规，风险识别充分
- 仓位限制：单票不超过 5%，止损 88 元（-10%）
- 止盈建议：120 元（+22%），风险收益比 1:2.2
"""

# ── Stage 8: Research Output ───────────────────────────────────────────
OUTPUTS["research_output"] = f"""
## 交易输出：002594 比亚迪

### 最终交易建议

最终交易建议：**买入**

### 交易卡

TRADECARD_JSON:
{{
  "ticker": "002594",
  "name": "比亚迪",
  "action": "买入",
  "confidence": 0.70,
  "current_price": 98.0,
  "target_price": 120.0,
  "stop_loss": 88.0,
  "upside_pct": 22.4,
  "downside_pct": -10.2,
  "risk_reward_ratio": 2.2,
  "max_position_pct": 5.0,
  "holding_period": "3-6 个月",
  "key_catalysts": [
    "Q1 销量发布 (2026-04-03)",
    "海豹 2 代上市 (2026-04-15)",
    "欧洲工厂进展 (2026-05-10)"
  ],
  "key_risks": [
    "价格战加剧",
    "欧盟关税",
    "固态电池突破"
  ]
}}

### 交易计划

TRADE_PLAN_JSON:
{{
  "entry_strategy": "分批建仓",
  "entry_price_range": "95-100 元",
  "position_schedule": [
    {{"price": "<=98", "pct": 50, "condition": "现价建仓"}},
    {{"price": "92-95", "pct": 30, "condition": "回踩 20 日均线"}},
    {{"price": ">100 突破", "pct": 20, "condition": "放量突破确认"}}
  ],
  "exit_strategy": "止盈止损",
  "stop_loss": 88.0,
  "take_profit": [
    {{"price": 110, "pct": 30, "reason": "前高阻力"}},
    {{"price": 120, "pct": 50, "reason": "目标价"}},
    {{"price": 135, "pct": 20, "reason": "乐观情景"}}
  ],
  "rebalance_trigger": [
    "单月跌幅>15%",
    "毛利率下滑>3pp",
    "销量同比<20%"
  ]
}}

### 订单建议

ORDER_PROPOSAL_JSON:
{{
  "order_type": "限价单",
  "action": "BUY",
  "ticker": "002594",
  "quantity_pct": 50,
  "limit_price": 98.0,
  "validity": "当日有效",
  "note": "首仓 50%，若回踩 92-95 元加仓 30%"
}}
"""

# ── Generate Reports ───────────────────────────────────────────────────
print("\n=== Generating Reports ===")

# Build market context block (simplified for demo)
market_context_block = f"""
【市场宏观环境】
日期：{current_date}
市场状态：RISK_ON
北向资金：净流入
板块轮动：新能源/科技 领涨
"""

import os
base_dir = os.path.dirname(os.path.abspath(__file__))

paths = generate_report(
    outputs=OUTPUTS,
    ticker="002594",
    ticker_name="比亚迪",
    trade_date=current_date,
    output_dir=os.path.join(base_dir, "data/reports"),
    storage_dir=os.path.join(base_dir, "data/replays"),
    market_context_block=market_context_block,
)

print(f"\n✓ Reports generated:")
print(f"  Snapshot: {paths.get('snapshot', 'N/A')}")
print(f"  Research: {paths.get('research', 'N/A')}")
print(f"  Audit:    {paths.get('audit', 'N/A')}")
print(f"  Run ID:   {paths.get('run_id', 'N/A')}")

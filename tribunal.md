# 论衡十七司 — 自动化编排指令

本文件是 Claude Code 的**可执行编排提示词**。用户在对话中贴出口令，Claude Code 读取本文件后自动执行全流程。

## 口令格式

```
论衡十七司，升堂！{ticker} {ticker_name} {trade_date}
```

示例：
```
论衡十七司，升堂！601985 中国核电 2026-03-19
论衡十七司，升堂！000710 贝瑞基因
```

省略 `trade_date` 时取当天日期。

多股批量：
```
论衡十七司，升堂！601985 中国核电, 000710 贝瑞基因, 688298 东方生物
```

单层口令（只跑某一层）：
```
复盘司，点卯！2026-03-19                          # Layer 0 每日复盘
太史令、户部司、舆图司，会同议事！2026-03-19       # Layer 1 大盘分析
观星度支通政察言，四司齐奏！601985 中国核电        # Layer 2 仅四分析师
```

## 执行流程

收到口令后，Claude Code 严格按以下步骤执行。每完成一步打印对应口令作为状态提示。

### Agent 写文件可靠性规则

每个 Agent 启动时的 prompt 必须包含以下指令（防止 Write 工具因"未 Read"而卡死）：

> **写文件前**：如果目标文件已存在，先用 `Read(file_path, limit=5)` 读取前5行，然后再用 `Write` 写入完整内容。如果目标文件不存在，可以直接 `Write`。

### Orchestration prompt 长度约束的歧义修复（2026-04-14）

**重要教训**：当 orchestration prompt 写 `"Under 40 words"` 时，agent 会误以为**写入文件的内容**也要控制在 40 字，导致它砍掉 CLAIM/EVIDENCE/CONFIDENCE/INVALIDATION 结构化块、证据引用、可证伪条件——analysis_audit 会降到 4/10 以下。

**每次启动 Agent 时 prompt 必须同时说明**（用此模板）：

> Read `/tmp/prompts/{key}.txt` fully. Generate the COMPLETE structured analysis as the prompt instructs — CLAIM blocks, [E#] citations, 5-dimension scores, falsifiability conditions must all be present in the output file. The length limit (Under N words) applies **ONLY to the confirmation message you return to me**, NOT to the file content. Write to `{output_path}`. DO NOT write to subagent_pipeline/ path. Return under 40 words confirming what you wrote.

在启动 Agent 前，主流程应清除上一轮的旧输出文件（防止旧数据残留）：

```python
# 清除旧输出（在每只股票的 L2 Step 0 之前执行）
for suffix in ["_market_report", "_fundamentals_report", "_news_report",
               "_sentiment_report", "_catalyst_report", "_bull_r1", "_bear_r1",
               "_bull_r2", "_bear_r2", "_scenario_report", "_research_manager",
               "_risk_aggressive", "_risk_conservative", "_risk_neutral",
               "_risk_manager", "_research_output"]:
    old = RESULTS / f"{ticker}{suffix}.txt"
    if old.exists():
        old.unlink()
```

### 准备

```python
import json
from pathlib import Path
from subagent_pipeline.config import PIPELINE_CONFIG, _today

# 解析口令参数
ticker = "{ticker}"        # 如 "601985"
ticker_name = "{name}"     # 如 "中国核电"（可留空，Step 0 自动填充）
trade_date = "{date}"      # 如 "2026-03-19"，缺省用 _today()

RESULTS = Path("agent_artifacts/results")
REPORTS = Path("data/reports")
REPLAYS = Path("data/replays")
RESULTS.mkdir(parents=True, exist_ok=True)
REPORTS.mkdir(parents=True, exist_ok=True)
REPLAYS.mkdir(parents=True, exist_ok=True)
```

---

### L0+L1 日期新鲜度检查

在进入 L2 个股分析前，**必须**检查 L0/L1 市场层是否已在当天运行过：

```python
# 检查 market_context + recap + snapshot 三件套是否齐全
from subagent_pipeline.market_layer import MarketLayerData
mld = MarketLayerData.load(trade_date, replays_dir=str(REPLAYS), results_dir=str(RESULTS))
if mld is not None:
    market_context = mld.market_context
    market_context_block = mld.market_context_block
    print(f"[CHECK] 当日 L0+L1 市场上下文已存在，跳过")
else:
    print(f"[CHECK] 未找到 {trade_date} 的市场上下文或复盘数据，需先执行 L0+L1")
    # → 执行下面的 L0 和 L1 步骤
```

若 `market_context_{trade_date}.json` 或 `recap_{trade_date}.json` 不存在，**必须先完成 L0+L1** 再进入 L2。

---

### L0+L1 并行启动

> **编排要点**：L0 和 L1 数据采集相互独立，**必须同时启动**以节省时间。
> L0 耗时约 3-5 分钟（akshare 58+ API），L1 snapshot 约 1-2 分钟。
> L2 仅依赖 L1（market_context），可在 L1 完成后立即开始。
> **L5/L6 同时依赖 L0（board_data）和 L1（market_context）**，必须等 L0+L1 都完成。

```
┌─ L0 复盘采集（~4分钟）──────────────────────────────────┐
│                                                          ├─→ L5/L6 (需要 L0 board_data + L1 context)
├─ L1 Snapshot + 4 Agents + 组装（~2分钟）─→ L2 个股分析 ──┘
└──────────────────────────────────────────────────────────┘
```

**执行步骤**：
1. **同时启动** L0 recap 采集（后台）和 L1 snapshot 采集
2. L1 snapshot 完成后启动 4 个 L1 Agent
3. L1 Agent 完成后组装 market_context，**立即进入 L2**
4. L2-L4 完成后，**必须确认 L0 recap 已完成**，再执行 L5/L6

### L0 — 复盘司，点卯！（每日复盘，无 LLM，后台启动）

```python
from subagent_pipeline.recap_collector import collect_daily_recap
from subagent_pipeline.renderers.recap_renderer import generate_daily_recap_report

# ⚠️ 后台启动 — 耗时 3-5 分钟，与 L1 并行
recap = collect_daily_recap(trade_date=trade_date)
recap_json = recap.to_json()
Path(REPLAYS / f"recap_{trade_date}.json").write_text(recap_json, encoding="utf-8")
generate_daily_recap_report(recap, output_dir=str(REPORTS))
```

打印：`[L0] 复盘司点卯完毕 — {recap.one_line_summary}`

---

### L1 — 太史令、户部司、舆图司，会同议事！（大盘三路并行）

```python
from subagent_pipeline.akshare_collector import collect_market_snapshot
# watchlist 传入本次所有待分析 ticker，获取个股现价
snapshot = collect_market_snapshot(trade_date=trade_date, watchlist=all_tickers_bare)
market_snapshot_md = snapshot.markdown_report  # 属性，非方法
```

**并行** 启动 4 个 Agent（model=sonnet）：

| Agent | prompt 调用 | 输出文件 |
|-------|------------|---------|
| 太史令 | `prompts.macro_analyst(trade_date, market_snapshot_md)` | `macro_analyst_output.txt` |
| 户部司 | `prompts.market_breadth_agent(trade_date, market_snapshot_md)` | `market_breadth_agent_output.txt` |
| 舆图司 | `prompts.sector_rotation_agent(trade_date, market_snapshot_md)` | `sector_rotation_agent_output.txt` |
| 全球宏观情报司 | `web_collector.global_macro_prompt(trade_date, market_snapshot_md)` | `global_macro_output.txt` |

全球宏观情报司 使用 WebSearch/WebFetch 搜索国际宏观情报（隔夜外盘、地缘风险、跨市场催化剂、外资情绪）。
该 Agent 即使失败也不阻塞流程——global_macro 为空时 pipeline 正常继续。

4 个 Agent 全部完成后，组装 market context：

```python
from subagent_pipeline.bridge import (
    parse_macro_output, parse_breadth_output, parse_sector_output,
    assemble_market_context, format_market_context_block,
)
from subagent_pipeline.web_collector import parse_global_macro_output

macro = parse_macro_output(macro_text)
breadth = parse_breadth_output(breadth_text)
sector = parse_sector_output(sector_text)

# Global macro web agent (optional — may be empty if web search failed)
global_macro = parse_global_macro_output(global_macro_text) if global_macro_text else None

market_context = assemble_market_context(macro, breadth, sector, trade_date, global_macro=global_macro)
market_context_block = format_market_context_block(market_context)

# ⚠️ 使用 MarketLayerData 统一持久化三件套（context + block + snapshot）
# 这确保新鲜度检查所需的全部文件一次性写入，不会遗漏
from subagent_pipeline.market_layer import MarketLayerData
mld = MarketLayerData(
    trade_date=trade_date,
    market_context=market_context,
    market_context_block=market_context_block,
    snapshot=snapshot,
    # recap_json 由 L0 单独保存，此处不重复
)
mld.save(replays_dir=str(REPLAYS), results_dir=str(RESULTS))
```

打印：`[L1] 太史令、户部司、舆图司、全球宏观情报司会同议事完毕`

---

### L2 — 以下按个股循环（每只股票）

#### Step 0 — 数据采集（无 LLM）

```python
from subagent_pipeline.akshare_collector import collect
bundle = collect(ticker=ticker, trade_date=trade_date)
# ticker_name 统一从 bundle 获取，后续所有步骤使用此变量
ticker_name = bundle.name or ticker_name or ticker
akshare_md = bundle.markdown_report       # 属性，非方法
```

**重要**: `ticker_name` 从此处开始作为唯一来源，传递给所有后续 Agent（Step 5 `research_manager`、Step 7 `risk_manager`、Step 8 `research_output` 的 `company_name` 参数）。

打印：`[L2.0] {ticker} {ticker_name} 数据采集完毕，{len(bundle.apis_succeeded)}/{len(bundle.apis_succeeded)+len(bundle.apis_failed)} API OK`

#### Step 1 — 观星、度支、通政、察言，四司齐奏！（四分析师并行）

**并行** 启动 4 个 Agent（model=sonnet）：

| Agent | prompt 调用 | 输出文件 |
|-------|------------|---------|
| 观星司 | `prompts.market_analyst(ticker, trade_date, market_context_block=market_context_block, akshare_md=akshare_md)` | `{ticker}_market_report.txt` |
| 度支司 | `prompts.fundamentals_analyst(ticker, trade_date, akshare_md=akshare_md)` | `{ticker}_fundamentals_report.txt` |
| 通政司 | `prompts.news_analyst(ticker, trade_date, akshare_md=akshare_md)` | `{ticker}_news_report.txt` |
| 察言司 | `prompts.sentiment_analyst(ticker, trade_date, akshare_md=akshare_md)` | `{ticker}_sentiment_report.txt` |

打印：`[L2.1] 四司齐奏完毕`

#### Step 1b — 证据封函，编号用印！（证据链，无 LLM）

```python
from subagent_pipeline.bridge import build_evidence_block
evidence_block = build_evidence_block(
    market_report=market_report,
    fundamentals_report=fundamentals_report,
    news_report=news_report,
    sentiment_report=sentiment_report,
)
```

后续 Step 2-7 的所有 Agent 调用都传 `evidence_block=evidence_block`。Step 8 不传。

#### Step 2 — 风信司，探风！（催化剂，串行）

```
prompts.catalyst_agent(ticker, news_report=news_report,
    fundamentals_report=fundamentals_report, market_report=market_report,
    evidence_block=evidence_block, current_date=trade_date)
```
model=sonnet → `{ticker}_catalyst_report.txt`

#### Step 3 — 主战派、主和派，开堂辩论！（多空辩论，2 轮）

**Round 1**（并行，无 debate_history）：
```
prompts.bull_researcher(ticker, market_report, sentiment_report, news_report, fundamentals_report, evidence_block=evidence_block, current_date=trade_date)
prompts.bear_researcher(ticker, market_report, sentiment_report, news_report, fundamentals_report, evidence_block=evidence_block, current_date=trade_date)
```

打印：`[L2.3] 第一轮交锋完毕`

**Round 2 — 二轮交锋，各执其词！**（并行）：
```
debate_history = f"=== Round 1 ===\nBull:\n{bull_r1}\n\nBear:\n{bear_r1}"
prompts.bull_researcher(ticker, ..., debate_history=debate_history, last_bear_argument=bear_r1, evidence_block=evidence_block, current_date=trade_date)
prompts.bear_researcher(ticker, ..., debate_history=debate_history, last_bull_argument=bull_r1, evidence_block=evidence_block, current_date=trade_date)
```

辩论完成后合并：
```python
bull_merged = f"=== Round 1 ===\n{bull_r1}\n\n=== Round 2 ===\n{bull_r2}"
bear_merged = f"=== Round 1 ===\n{bear_r1}\n\n=== Round 2 ===\n{bear_r2}"
```

打印：`[L2.3] 主战派、主和派辩论终结`

#### Step 4 — 推演阁，沙盘列阵！（情景推演，串行）

```
prompts.scenario_agent(ticker, bull_history=bull_merged, bear_history=bear_merged, current_date=trade_date)
```
model=sonnet → `{ticker}_scenario_report.txt`

#### Step 5 — 军机处，定策！（研究总监，串行）

```
prompts.research_manager(ticker, debate_input=combined_debate,
    scenario_block=scenario_output,
    market_context_block=market_context_block,
    current_date=trade_date)
```
model=**opus**。`combined_debate` = bull_merged + bear_merged + catalyst。

#### Step 6 — 锐卫、盾卫、衡卫，三堂会审！（风控三路并行）

**并行** 启动 3 个 Agent（model=sonnet）：

```
prompts.aggressive_debator(research_conclusion=pm_output, market_report=..., sentiment_report=..., news_report=..., fundamentals_report=..., evidence_block=evidence_block, current_date=trade_date)
prompts.conservative_debator(research_conclusion=pm_output, ..., evidence_block=evidence_block, current_date=trade_date)
prompts.neutral_debator(research_conclusion=pm_output, ..., evidence_block=evidence_block, current_date=trade_date)
```

注意：风控辩手**不传** `market_context_block`，但传 `evidence_block` 和 `current_date`。

#### Step 7 — 御史台，判印！（风控总监，串行）

```
prompts.risk_manager(company_name=ticker_name, trader_plan=pm_output,
    risk_debate_history=combined_risk_debate,
    evidence_block=evidence_block,
    market_context_block=market_context_block,
    current_date=trade_date)
```
model=**opus**。

#### Step 8 — 虎符令，落子！（交易输出，串行）

```
prompts.research_output(company_name=ticker_name,
    investment_plan=f"{pm_output}\n\n风控决策:\n{risk_output}",
    ticker=ticker, akshare_md=akshare_md)
```
model=sonnet。注意：**不传** `evidence_block`。

---

### L3 — 封卷成册，呈阅！（报告生成，无 LLM）

```python
from subagent_pipeline.bridge import generate_report

outputs = {
    "market_analyst": market_report,
    "fundamentals_analyst": fundamentals_report,
    "news_analyst": news_report,
    "sentiment_analyst": sentiment_report,
    "catalyst_agent": catalyst_output,
    "bull_researcher": bull_merged,
    "bear_researcher": bear_merged,
    "scenario_agent": scenario_output,
    "research_manager": pm_output,
    "aggressive_debator": aggressive_output,
    "conservative_debator": conservative_output,
    "neutral_debator": neutral_output,
    "risk_manager": risk_output,
    "research_output": research_output,
}

paths = generate_report(
    outputs=outputs, ticker=ticker, ticker_name=ticker_name,
    trade_date=trade_date, output_dir=str(REPORTS),
    storage_dir=str(REPLAYS),
    market_context_block=market_context_block,
    market_context=market_context,
)
run_id = paths["run_id"]
```

打印：`[L3] 封卷成册 — run_id={run_id}`

**⚠️ L3 完成后，必须立即执行 L4 + 信号入账（每只股票都要做）：**

### L4 — 委员会辩论报告（每股必做）

```python
from subagent_pipeline.renderers.debate_renderer import generate_committee_report
from subagent_pipeline.replay_store import ReplayStore
store = ReplayStore(storage_dir=str(REPLAYS))
trace = store.load(run_id)
if trace:
    generate_committee_report(trace, output_dir=str(REPORTS))
    print(f"[L4] 委员会报告生成完毕")
```

### 信号入账（每股必做，L4 之后立即执行）

```python
from subagent_pipeline.signal_ledger import SignalLedger
ledger = SignalLedger()
rec = ledger.append_from_trace(run_id, storage_dir=str(REPLAYS))
if rec:
    print(f"[LEDGER] 信号已入账: {rec.ticker} {rec.action} conf={rec.confidence}")
else:
    print(f"[LEDGER] 信号入账失败（action 无效或 trace 不存在）")
```

---

### L0 完成门控

> **⚠️ 关键检查点**：进入 L5/L6 前，**必须确认 L0 recap 已完成**。
> L0 后台采集通常需要 3-5 分钟。如果 L2-L4 完成时 L0 仍在运行，**等待 L0 完成**。

```python
recap_path = REPLAYS / f"recap_{trade_date}.json"
if not recap_path.exists():
    print("[GATE] ⚠️ L0 复盘尚未完成，等待中...")
    # 如果 L0 是后台运行，此处需要等待其完成
    # 不可跳过 — board_data 为 None 会导致涨跌停数据缺失
    raise RuntimeError(f"L0 recap not found: {recap_path}. Wait for L0 to complete before L5/L6.")
print(f"[GATE] L0 复盘已确认完成: {recap_path}")
```

---

### L5 — 分歧池（多股时）

多股批量模式下，所有个股跑完后：

```python
from subagent_pipeline.renderers.report_renderer import generate_pool_report
from subagent_pipeline.akshare_collector import MarketSnapshot

# ⚠️ 使用 MarketLayerData 统一加载 — 保证 snapshot + board_data 齐全
from subagent_pipeline.market_layer import MarketLayerData
mld = MarketLayerData.load(trade_date, replays_dir=str(REPLAYS), results_dir=str(RESULTS))
if mld is None:
    raise RuntimeError(f"MarketLayerData incomplete for {trade_date}. Run L0+L1 first.")
snapshot = mld.snapshot
board_data = mld.board_data

generate_pool_report(
    run_ids=all_run_ids, output_dir=str(REPORTS),
    storage_dir=str(REPLAYS), trade_date=trade_date,
    market_context=market_context, market_snapshot=snapshot,
)
```

---

### L6 — 大盘指挥台

```python
from subagent_pipeline.renderers.report_renderer import generate_market_report

# snapshot 和 board_data 已在 L5 加载
generate_market_report(
    market_context=market_context, market_snapshot=snapshot,
    output_dir=str(REPORTS), trade_date=trade_date,
    board_data=board_data,
)
```

---

### L7 — 回测验证

```python
from subagent_pipeline.backtest import run_backtest, BacktestConfig, generate_backtest_report
from subagent_pipeline.signal_ledger import SignalLedger

# 信号入账
ledger = SignalLedger()
ledger.append_from_trace(run_id, storage_dir=str(REPLAYS))

# 回测
report = run_backtest(storage_dir=str(REPLAYS), config=BacktestConfig(), fetch_prices=True)
generate_backtest_report(report, output_dir=str(REPORTS))
```

---

### L8 — 观点追踪（跨日漂移分析）

每天跑完后自动生成观点漂移报告，追踪同一股票前后几天的观点演变：

```python
from subagent_pipeline.opinion_tracker import build_watchlist_report

# all_tickers = ["601985.SS", "000710.SZ", ...]  已跑的所有 ticker
tracker_report = build_watchlist_report(
    tickers=all_tickers,
    date_from="",           # 全量历史
    date_to=trade_date,
    storage_dir=str(REPLAYS),
)
print(tracker_report.to_markdown())
tracker_report.save_json(output_dir=str(REPORTS))
```

打印：`[L8] 观点追踪完毕 — {len(tracker_report.action_flips)} 次翻转, {len(tracker_report.biggest_confidence_moves)} 次大幅波动`

如有信号翻转（如 HOLD→BUY），打印详情。

---

### L8.5 — 讨论质量回顾（每股必做）

分析 agent 讨论质量，生成改进建议：

```python
from subagent_pipeline.discussion_tracker import generate_discussion_review
from subagent_pipeline.renderers.review_renderer import generate_review_report

review = generate_discussion_review(run_id, storage_dir=str(REPLAYS))
review_path = generate_review_report(review, output_dir=str(REPORTS))
print(f"[L8.5] 讨论质量: {review.debate_quality.debate_grade}")
print(f"  证据利用率: {review.evidence_utilization.utilization_rate:.0%}")
for s in review.prompt_suggestions:
    print(f"  [{s.severity}] {s.agent}: {s.description[:60]}")
```

打印：`[L8.5] 讨论质量回顾完毕 — Grade {review.debate_quality.debate_grade}, {len(review.prompt_suggestions)} 条改进建议`

### 事后回顾（隔日手动触发）

当实际价格出来后，对比预测：

```
复盘验证！{run_id} {actual_price}
```

```python
from subagent_pipeline.discussion_tracker import review_prediction

pred_review = review_prediction(run_id, actual_price=9.35, storage_dir=str(REPLAYS))
print(f"预测方向: {pred_review.predicted_direction}, 实际: {pred_review.actual_direction}")
print(f"方向正确: {pred_review.direction_correct}")
print(f"命中情景: {pred_review.scenario_hit}")
print(f"教训: {pred_review.lesson}")
```

---

### 散堂

打印：`[完毕] 十七司散堂，论衡已定。报告输出: data/reports/`

列出所有生成的 HTML / JSON 文件路径。

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

### 准备

```python
import json
from pathlib import Path
from subagent_pipeline.config import PIPELINE_CONFIG, _today

# 解析口令参数
ticker = "{ticker}"        # 如 "601985"
ticker_name = "{name}"     # 如 "中国核电"
trade_date = "{date}"      # 如 "2026-03-19"，缺省用 _today()

RESULTS = Path("agent_artifacts/results")
REPORTS = Path("data/reports")
REPLAYS = Path("data/replays")
RESULTS.mkdir(parents=True, exist_ok=True)
REPORTS.mkdir(parents=True, exist_ok=True)
REPLAYS.mkdir(parents=True, exist_ok=True)
```

---

### L0 — 复盘司，点卯！（每日复盘，无 LLM）

```python
from subagent_pipeline.recap_collector import collect_daily_recap
from subagent_pipeline.renderers.recap_renderer import generate_daily_recap_report

recap = collect_daily_recap(trade_date=trade_date)
recap_json = recap.to_json()
Path(REPLAYS / f"recap_{trade_date}.json").write_text(recap_json)
generate_daily_recap_report(recap, output_dir=str(REPORTS))
```

打印：`[L0] 复盘司点卯完毕 — {recap.one_line_summary}`

---

### L1 — 太史令、户部司、舆图司，会同议事！（大盘三路并行）

```python
from subagent_pipeline.akshare_collector import collect_market_snapshot
snapshot = collect_market_snapshot(trade_date=trade_date, watchlist=[f"{ticker}"])
market_snapshot_md = snapshot.markdown_report  # 属性，非方法
```

**并行** 启动 3 个 Agent（model=sonnet）：

| Agent | prompt 调用 | 输出文件 |
|-------|------------|---------|
| 太史令 | `prompts.macro_analyst(trade_date, market_snapshot_md)` | `macro_analyst_output.txt` |
| 户部司 | `prompts.market_breadth_agent(trade_date, market_snapshot_md)` | `market_breadth_agent_output.txt` |
| 舆图司 | `prompts.sector_rotation_agent(trade_date, market_snapshot_md)` | `sector_rotation_agent_output.txt` |

3 个 Agent 全部完成后，组装 market context：

```python
from subagent_pipeline.bridge import (
    parse_macro_output, parse_breadth_output, parse_sector_output,
    assemble_market_context, format_market_context_block,
)
macro = parse_macro_output(macro_text)
breadth = parse_breadth_output(breadth_text)
sector = parse_sector_output(sector_text)
market_context = assemble_market_context(macro, breadth, sector, trade_date)
market_context_block = format_market_context_block(market_context)

Path(RESULTS / "market_context.json").write_text(json.dumps(market_context, ensure_ascii=False, indent=2))
Path(RESULTS / "market_context_block.txt").write_text(market_context_block)
```

打印：`[L1] 太史令、户部司、舆图司会同议事完毕`

---

### L2 — 以下按个股循环（每只股票）

#### Step 0 — 数据采集（无 LLM）

```python
from subagent_pipeline.akshare_collector import collect
bundle = collect(ticker=ticker, trade_date=trade_date)
ticker_name = bundle.name or ticker_name  # akshare 自动填充
akshare_md = bundle.markdown_report       # 属性，非方法
```

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
prompts.bull_researcher(ticker, market_report, sentiment_report, news_report, fundamentals_report, evidence_block=evidence_block)
prompts.bear_researcher(ticker, market_report, sentiment_report, news_report, fundamentals_report, evidence_block=evidence_block)
```

打印：`[L2.3] 第一轮交锋完毕`

**Round 2 — 二轮交锋，各执其词！**（并行）：
```
debate_history = f"=== Round 1 ===\nBull:\n{bull_r1}\n\nBear:\n{bear_r1}"
prompts.bull_researcher(ticker, ..., debate_history=debate_history, last_bear_argument=bear_r1, evidence_block=evidence_block)
prompts.bear_researcher(ticker, ..., debate_history=debate_history, last_bull_argument=bull_r1, evidence_block=evidence_block)
```

辩论完成后合并：
```python
bull_merged = f"=== Round 1 ===\n{bull_r1}\n\n=== Round 2 ===\n{bull_r2}"
bear_merged = f"=== Round 1 ===\n{bear_r1}\n\n=== Round 2 ===\n{bear_r2}"
```

打印：`[L2.3] 主战派、主和派辩论终结`

#### Step 4 — 推演阁，沙盘列阵！（情景推演，串行）

```
prompts.scenario_agent(ticker, bull_history=bull_merged, bear_history=bear_merged)
```
model=sonnet → `{ticker}_scenario_report.txt`

#### Step 5 — 军机处，定策！（研究总监，串行）

```
prompts.research_manager(ticker, debate_input=combined_debate,
    scenario_block=scenario_output,
    market_context_block=market_context_block)
```
model=**opus**。`combined_debate` = bull_merged + bear_merged + catalyst。

#### Step 6 — 锐卫、盾卫、衡卫，三堂会审！（风控三路并行）

**并行** 启动 3 个 Agent（model=sonnet）：

```
prompts.aggressive_debator(research_conclusion=pm_output, market_report=..., sentiment_report=..., news_report=..., fundamentals_report=...)
prompts.conservative_debator(research_conclusion=pm_output, ...)
prompts.neutral_debator(research_conclusion=pm_output, ...)
```

注意：风控辩手**不传** `market_context_block`。

#### Step 7 — 御史台，判印！（风控总监，串行）

```
prompts.risk_manager(company_name=ticker_name, trader_plan=pm_output,
    risk_debate_history=combined_risk_debate,
    evidence_block=evidence_block,
    market_context_block=market_context_block)
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

---

### L4 — 委员会辩论报告

```python
from subagent_pipeline.renderers.debate_renderer import generate_committee_report
from subagent_pipeline.replay_store import ReplayStore
store = ReplayStore(storage_dir=str(REPLAYS))
trace = store.load(run_id)
generate_committee_report(trace, output_dir=str(REPORTS))
```

---

### L5 — 分歧池（多股时）

多股批量模式下，所有个股跑完后：

```python
from subagent_pipeline.renderers.report_renderer import generate_pool_report
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
generate_market_report(
    market_context=market_context, market_snapshot=snapshot,
    output_dir=str(REPORTS), trade_date=trade_date,
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

### 散堂

打印：`[完毕] 十七司散堂，棋局已定。报告输出: data/reports/`

列出所有生成的 HTML / JSON 文件路径。

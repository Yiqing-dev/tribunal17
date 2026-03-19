# 棋局 — A股多智能体研究系统

19 个 LLM 智能体协作完成从数据采集、多维分析、多空辩论到风控决策的完整投研链路，输出 8 层可交互 HTML 研报。

零外部框架依赖 — 数据用 [akshare](https://github.com/akfamily/akshare)，LLM 调用通过 Claude Code Agent 编排，报告渲染纯 Python + 内联 JS。

> 本项目仅供研究学习，不构成任何投资建议。

---

## 系统架构

```
数据层 (akshare)           分析层 (19 LLM agents)            输出层
┌──────────────┐      ┌─────────────────────────────┐    ┌───────────────┐
│ 行情/K线/财务 │      │  4 分析师 (技术/基本面/新闻/情绪)  │    │ 个股研报 HTML  │
│ 板块/涨停/资金 │─────▶│  催化剂 → 多空辩论 (2轮)        │───▶│ 大盘指挥台     │
│ 指数/北向/融资 │      │  情景分析 → 研究总监 (opus)      │    │ 委员会辩论     │
│ 每日复盘数据   │      │  3 风控辩手 → 风控总监 (opus)     │    │ 分歧池 / 回测  │
└──────────────┘      │  交易输出                       │    └───────────────┘
                      └─────────────────────────────┘
```

### 8 层报告体系

| 层 | 名称 | 内容 |
|---|------|------|
| L0 | 每日复盘 | 指数 K线/MACD/RSI、板块热力图、涨停复盘 |
| L1 | 大盘分析 | 宏观 / 市场广度 / 板块轮动，三智能体并行 |
| L2 | 个股分析 | 4 分析师 → 催化剂 → 多空辩论 → 研究总监 → 风控 → 交易输出 |
| L3 | 个股研报 | 快照 / 深度研究 / 审计追踪，三件套 HTML |
| L4 | 委员会辩论 | 多空论点时间线可视化 |
| L5 | 分歧池 | 多只股票横向对比，分歧度排序 |
| L6 | 大盘指挥台 | 矩形树图热力图、板块引擎、涨停生态、情绪仪表盘 |
| L7 | 回测验证 | 历史信号胜率 / 方向准确率 / 收益归因 |

### 智能体一览

| 阶段 | 智能体 | 模型 | 并行 |
|------|--------|------|------|
| L1 | 宏观分析师 / 市场广度 / 板块轮动 | sonnet | 3 路并行 |
| L2 | 技术面 / 基本面 / 新闻 / 情绪分析师 | sonnet | 4 路并行 |
| L2 | 催化剂分析师 | sonnet | 串行 |
| L2 | 多头研究员 / 空头研究员 (×2 轮) | sonnet | 2 路并行 |
| L2 | 情景分析师 | sonnet | 串行 |
| L2 | 研究总监 | **opus** | 串行 |
| L2 | 激进 / 保守 / 中性风控辩手 | sonnet | 3 路并行 |
| L2 | 风控总监 | **opus** | 串行 |
| L2 | 交易输出 | sonnet | 串行 |

---

## 快速开始

### 环境

```bash
pip install akshare>=1.10
```

无其他 Python 依赖 — 所有模块（trace_models、replay_store、renderers）均本地 vendored。

LLM 调用通过 Claude Code 的 `Agent` 工具完成，无需在 Python 代码中配置 API Key。

### Demo（无需 API Key）

```bash
# 从 mock 数据生成示例研报
python -m subagent_pipeline.demo_601985

# 从已有智能体输出批量生成报告
python -m subagent_pipeline.batch_process
```

---

## 项目结构

```
棋局/
│
│── 基础层 ──
├── shared.py              公共 prompt 片段 (规则/证据协议/语言)
├── config.py              流水线 DAG + 模型分配 + 导入时校验
│
│── 数据层 (无 LLM) ──
├── akshare_collector.py   个股数据 → AkshareBundle (12 个 API) + _retry_call()
├── recap_collector.py     每日复盘 → DailyRecapData (指数/板块/涨停)
├── verification.py        交叉验证 prompt + PASS/FAIL 解析
│
│── Prompt 层 ──
├── prompts.py             17 个智能体 prompt 函数
│
│── 变换层 ──
├── bridge.py              文本 → RunTrace: 17 个解析器 + 证据链构建 + 报告生成
├── heatmap.py             HeatmapNode / HeatmapData: 矩形树图数据聚合
├── backtest.py            信号回测: 前向验证、胜率、方向准确率
├── signal_ledger.py       追加式 JSONL 信号流水账
│
│── 编排层 ──
├── batch_process.py       批处理: 读原始输出 → bridge → 写 HTML
├── pipeline.py            参考文档: 子智能体调用模式
├── demo_601985.py         从 mock 数据生成示例报告
│
│── Vendored: 可观测性 ──
├── trace_models.py        NodeStatus, NodeTrace, RunTrace, RunMetrics
├── replay_store.py        ReplayStore: RunTrace 的 JSON 持久化 (原子写入)
├── replay_service.py      ReplayService: 高级回放操作
│
│── Vendored: 渲染器 ──
├── renderers/
│   ├── report_renderer.py   三层 HTML + 分歧池 + 大盘指挥台
│   ├── debate_renderer.py   委员会辩论 HTML
│   ├── recap_renderer.py    每日复盘驾驶舱 HTML
│   ├── views.py             视图模型 (模板数据契约)
│   ├── debate_view.py       辩论专用视图模型
│   └── decision_labels.py   节点名 → 中文标签
│
│── 测试 ──
├── tests/
│   ├── test_market_layer.py   78 tests — 大盘渲染
│   ├── test_daily_recap.py    96 tests — 每日复盘
│   ├── test_debate.py         84 tests — 辩论/委员会
│   ├── test_trade_plan.py     31 tests — 交易计划
│   └── test_dashboard.py     125 tests — 仪表盘
│
└── data/                  运行时生成 (git ignored)
    ├── reports/           HTML 报告
    ├── replays/           RunTrace JSON
    └── signals/           信号流水账 JSONL
```

---

## 测试

```bash
# 全量 (414 tests, ~2min, 无需 API Key)
pytest tests/ -q

# 单模块
pytest tests/test_market_layer.py -v
pytest tests/test_daily_recap.py -v
pytest tests/test_debate.py -v
pytest tests/test_trade_plan.py -v
pytest tests/test_dashboard.py -v
```

---

## 数据可靠性

- **API 重试** — 所有 akshare 调用经 `_retry_call()` 包装，指数退避，仅重试瞬态错误
- **原子写入** — RunTrace 持久化使用 tmpfile → rename，进程崩溃不损坏已有数据
- **证据链** — Agent Evidence Protocol 为每条结论绑定 `[E#]` 编号证据，下游可追溯
- **发布合规** — 5 条确定性规则门控（来源归因 / 敏感内容 / 断言语言 / 证据可追溯 / VETO）

---

## 致谢

- [TradingAgents](https://github.com/TauricResearch/TradingAgents) — Multi-Agents LLM Financial Trading Framework (Xiao et al., 2024)
- [akshare](https://github.com/akfamily/akshare) — 开源 A 股数据接口

```bibtex
@misc{xiao2025tradingagents,
      title={TradingAgents: Multi-Agents LLM Financial Trading Framework},
      author={Yijia Xiao and Edward Sun and Di Luo and Wei Wang},
      year={2025},
      eprint={2412.20138},
      archivePrefix={arXiv},
      primaryClass={q-fin.TR},
      url={https://arxiv.org/abs/2412.20138},
}
```

# Codex Project Notes

When the user asks to start the local workbench, run:

```bash
python start_workbench.py
```

Primary launch phrase:

```text
论衡十七司，升堂！【600519，000858，002594】
```

When the user sends this phrase, extract the bracketed ticker list and start the
daily stock-research workflow for those tickers. The scripts can consume the
same phrase directly:

```bash
python start_workbench.py "论衡十七司，升堂！【600519，000858，002594】"
python -m subagent_pipeline.batch_process "论衡十七司，升堂！【600519，000858，002594】"
python -m subagent_pipeline.lunheng_court "论衡十七司，升堂！【600519，000858，002594】"
```

When this phrase is used, the current Claude Code / Codex language model should
call subagents directly. Run `lunheng_court` first to write
`data/reports/daily_watchlist.json` and `data/reports/lunheng_runbook.md`; then
use subagents for bounded roles per ticker: bull case, bear case, risk/review,
and final synthesis. Python scripts do not call subagents themselves.

If the user provides a daily stock list, scope the workbench to that list:

```bash
python start_workbench.py --tickers 600519,000858,002594
python start_workbench.py --tickers-file watchlist.txt
```

The command regenerates `data/reports/workbench.html`, starts the local server,
and prints the URL:

```text
http://127.0.0.1:8765/workbench.html
```

Use another port if 8765 is already occupied:

```bash
python start_workbench.py --port 8770
```

Use `--no-generate` when the user only wants to serve existing reports.

To build HTML reports from existing agent outputs for the same daily list:

```bash
python -m subagent_pipeline.batch_process --tickers 600519,000858,002594
python -m subagent_pipeline.batch_process --tickers-file watchlist.txt
```

For `论衡十七司，升堂！【...】`, multi-agent/subagent discussion is the default
LLM-runtime behavior. Keep internal review plumbing separate from the
stockholder-facing HTML report unless the user asks to include it.

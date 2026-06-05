# Lunheng Court

Trigger phrase:

```text
论衡十七司，升堂！【600519，000858，002594】
```

Behavior:

1. Treat the bracketed content as the user's daily ticker list.
2. Generate the execution runbook first:

```bash
python -m subagent_pipeline.lunheng_court "论衡十七司，升堂！【600519，000858，002594】"
```

3. For existing agent outputs, build HTML reports with:

```bash
python -m subagent_pipeline.batch_process "论衡十七司，升堂！【600519，000858，002594】"
```

4. Start the local HTML workbench with:

```bash
python start_workbench.py "论衡十七司，升堂！【600519，000858，002594】"
```

5. The current Claude Code language model calls subagents directly. Use bounded
   roles per ticker: bull case, bear case, risk/review, and final synthesis.
   Python scripts do not call subagents themselves.
6. Keep internal review triggers and workflow plumbing out of the
   stockholder-facing HTML report unless requested.

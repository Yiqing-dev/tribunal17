# Discuss Stock

Use this command only when the user explicitly asks for a multi-agent or
subagent discussion of one or more stocks.

Expected input:

```text
/discuss-stock 600519 贵州茅台
/discuss-stock 600519,000858
```

Workflow:

1. Identify the ticker list from the user message. If a name is missing, continue
   with the ticker code.
2. Use subagents for bounded roles: bull case, bear case, risk/review, and final
   synthesis.
3. Keep the output focused on the stockholder-facing research question:
   conclusion, core evidence, disagreement, risk, and what would change the view.
4. Do not expose internal workflow labels, review-trigger plumbing, or system
   implementation details in the final stock report unless the user explicitly
   asks for them.

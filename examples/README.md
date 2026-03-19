# Report Examples

Sample outputs from the 8-layer pipeline (2026-03-19 run, 10 A-share tickers).

| File | Layer | Description |
|------|-------|-------------|
| `L0-recap.html` | L0 Daily Recap | Market cockpit: indices, sector heatmap, limit boards |
| `L3-snapshot.html` | L3 Snapshot | One-page trading card (601985 中国核电) |
| `L3-research.html` | L3 Research | Full research report with all agent outputs |
| `L3-audit.html` | L3 Audit | Evidence trail + node-level trace |
| `L4-committee.html` | L4 Committee | Bull/bear debate + risk committee visualization |
| `L5-pool.html` | L5 Pool | 10-stock divergence pool with heatmap treemap |
| `L6-market.html` | L6 Market | Market overview: regime, breadth, sector engine |
| `L7-backtest.html` | L7 Backtest | Signal accuracy verification report |
| `L7-backtest.json` | L7 Backtest | Machine-readable backtest results |
| `L8-brief.md` | L8 Brief | Push-ready one-line-per-stock summary |

Open any `.html` file in a browser to view. All reports are self-contained (inline CSS/JS, no external dependencies except Plotly CDN for interactive treemaps).

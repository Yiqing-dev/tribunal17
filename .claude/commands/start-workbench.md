# Start Workbench

Start the local stock-research workbench from this repository.

```bash
python start_workbench.py
```

After the server prints the URL, open:

```text
http://127.0.0.1:8765/workbench.html
```

Useful options:

```bash
python start_workbench.py --port 8770
python start_workbench.py --no-generate
python start_workbench.py --tickers 600519,000858,002594
python start_workbench.py --tickers-file watchlist.txt
python start_workbench.py "论衡十七司，升堂！【600519，000858，002594】"
```

For the daily stock-research workflow, use `--tickers` or `--tickers-file` when
the user provides the day's stock codes. The workbench will focus on that list
and mark missing reports as pending.

If the user sends `论衡十七司，升堂！【...】`, use the bracketed codes as the daily
stock list.

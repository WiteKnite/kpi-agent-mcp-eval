# kpi-agent-mcp-eval

A small prototype of a conversational BI agent with an evaluation harness.

- an **MCP server** that exposes read-only analytics tools over a sales-funnel database
- a **tool-using agent** (Anthropic Messages API) that answers KPI questions with those tools
- a **golden question set** whose expected answers are computed from SQL, and a **scoring script**
- optional **Langfuse** tracing and scores

It is a weekend-sized prototype built to show the pattern: tools behind MCP, an agent that must call
them, and an evaluation that does not trust the model to grade itself. The data is synthetic.
It is not a production system.

## Layout

```
data/generate_data.py      synthetic, deterministic SQLite funnel data (24 months of leads, 2025-2026)
src/kpi_agent/tools.py     read-only tools: list_tables, describe_table, run_query, kpi_summary (optional channel and rep filters), kpi_drivers, forecast_kpi
src/kpi_agent/mcp_server.py  MCP server (stdio) exposing the same tools
src/kpi_agent/agent.py     tool-use loop with the Anthropic SDK
src/kpi_agent/tracing.py   optional Langfuse tracing (no-op without keys)
eval/build_golden.py       builds eval/questions.json from SQL
eval/run_eval.py           scores the agent, or validates the golden set with --offline
tests/test_tools.py        pytest checks for the tools and the golden set
```

## Run it

```bash
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

python data/generate_data.py      # creates data/sales.db
python eval/build_golden.py       # regenerates eval/questions.json (already committed)
pytest                            # 35 tests, no API key needed
python eval/run_eval.py --offline # validates the golden set against the tools
```

With an Anthropic key (copy `.env.example`, or set the variables in your shell):

```bash
python -m kpi_agent.agent "Which channel converted best in 2025-12?"
python eval/run_eval.py           # runs the agent on every question and scores it
python -m kpi_agent.mcp_server    # serve the tools to any MCP client
```

Set `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` to send traces and a `correct` score per
question to Langfuse.

## Demo in five minutes

1. `pytest` shows the tools, the read-only guard, a real MCP round trip over stdio, and the agent
   loop (with a stubbed model client) all passing.
2. `python eval/run_eval.py --offline` shows the golden questions and their SQL-derived answers.
3. Open the tools in an MCP client. For example, with the MCP Inspector:

   ```bash
   npx @modelcontextprotocol/inspector python -m kpi_agent.mcp_server
   ```

   Run from the repo root with `PYTHONPATH=src`. Any MCP client works with this server entry:

   ```json
   {
     "mcpServers": {
       "kpi-agent": {
         "command": "python",
         "args": ["-m", "kpi_agent.mcp_server"],
         "env": {"PYTHONPATH": "/absolute/path/to/kpi-agent-mcp-eval/src"}
       }
     }
   }
   ```
4. With `ANTHROPIC_API_KEY` set, `python eval/run_eval.py` runs the real agent on every question and
   prints PASS or FAIL per question. A FAIL is a useful result: it shows what the evaluation catches.

## What the evaluation does

Each question in `eval/questions.json` has an expected answer computed directly from the
database. Numbers must match within a tolerance, and names must appear in the answer. The model
never produces the expected values, so a wrong answer is caught instead of graded by the model.

## Design choices

- **Read-only by construction.** `run_query` accepts a single `SELECT` or `WITH` statement, and the
  database is opened with SQLite `mode=ro`, so a write fails even if the check is bypassed.
- **One set of tools.** The MCP server and the agent call the same functions in `tools.py`.
- **Tracing is optional.** Without Langfuse keys the decorators are no-ops, so the repo runs anywhere.

## Limits

- Synthetic data and nine questions: a demonstration of the method, not a benchmark.
- Channel and rep cells have few conversions each (often under 10 a month), so a single rate
  can swing a lot. Read per-channel and per-rep rates as indicative, not precise.
- The offline tests and the golden-set check run without an API key. The online agent run and the
  Langfuse integration need keys and are not part of the automated tests.
- Live run: the agent passed 9 of 9 questions on 14 November 2026 with `claude-sonnet-5-5`. The
  result is saved in `eval/results/live_20261114_claude-sonnet-5-5.json`. Two earlier runs (6 of 6
  each) were recorded in text only. Langfuse tracing has not been exercised yet. None of the 9
  questions asks about forecasts, so the forecast tool has no live check yet.
- `kpi_drivers` ignores mix effects, so its contributions only approximate the total change.
- `forecast_kpi` uses the mean of the last 3 months, the model the forecast study chose. It is not a
  statistical model. The 2026 months continue the 2025 post-launch pattern, so backtests on them are
  kinder to the model than real data would be.
- The backtest uses 7 development-window origins with a 3-month horizon, on synthetic data. That is
  a small sample. Its MAE and MAPE can disagree, so both are reported.

## Forecast backtest

`forecast_kpi` forecasts the next 3 months with the mean of the last 3 months, and backtests it against
a naive "last value repeats" baseline. The backtest uses the study's protocol: origins 9 to 15,
horizon 3, development window only (through 2026-06), so the holdout is never used to score the tool.
Output from the current data (7 origins):

| Metric | Model MAE | Naive MAE | Model MAPE % | Naive MAPE % | Beats naive on MAE | Beats naive on MAPE |
|---|---|---|---|---|---|---|
| Conversion rate (%) | 1.31 | 1.57 | 17.8 | 22.3 | yes | yes |
| Leads per month | 20.6 | 19.4 | 10.2 | 9.5 | no | no |
| Avg first response (min) | 0.087 | 0.089 | 2.9 | 2.9 | yes, negligibly | yes, negligibly |

Only conversion beats naive clearly, and the study's confidence interval for that gap still touches
zero. Leads lose on this protocol. Response time ties. An earlier version of this table, which
included the holdout and earlier origins, showed leads winning. That result came from the wrong
evaluation window and is withdrawn. The conversion result is also partly in-sample, since the same
development data chose the model. The agent's answers about these forecasts have not yet been
checked with a live model run.

## Forecast study (pre-registered)

`DECISIONS.md` fixes the data split, candidates and choice rule before any results. `eval/forecast_study.py`
runs the development steps (`--step 1` to `3`), and its `--holdout` run refuses to repeat.

Development (2025-01 to 2026-06), horizon 3, 210 backtest points per metric across 10 series:
- Conversion: `ma3` (3-month average) MAE 3.38 vs naive 4.30. Clearly better (CI excludes zero).
- Leads: `ma3` 8.16 vs naive 9.16. Clearly better.
- Response time: `ma3` 0.126 min vs naive 0.140. Better, but the difference is tiny.
- Post-launch training fixed the response-time failure of the trend model (36.5 min error to 0.10).
  A log transform made no difference.

Holdout (2026-07 to 2026-12), run once, horizon 6, pooled over 10 series:
- Conversion: `ma3` 3.35 vs naive 4.08 (CI [-1.33, -0.13]). Holds.
- Leads: `ma3` 8.57 vs naive 9.38 (CI [-1.64, +0.08]). Points the same way, but not clearly.
- Response time: `ma3` 0.146 vs naive 0.173 (CI [-0.052, -0.003]). Holds, but small.

Limits: one holdout forecast, 6 months, on synthetic data; the 10 series overlap, so the points are
not independent. `forecast_kpi` still uses the trend model, which the study did not select.

## Next steps

- Add questions that should be refused or answered "no data", and score those too.
- Compare models and prompts on the same golden set and track the scores in Langfuse.
- Add an MCP client integration test.

MIT licensed.

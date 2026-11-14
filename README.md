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
- Manual live runs: the agent passed 6 of 6 questions in two complete runs with the default model
  (November 2026). Those runs predate the three channel and rep questions, which have not yet been
  run live. Langfuse tracing has not been exercised yet.
- `kpi_drivers` ignores mix effects, so its contributions only approximate the total change.
- `forecast_kpi` is a linear trend over the last 6 months, not a statistical model. The 2026 months
  continue the 2025 post-launch trend, so backtests on them are kinder to the model than real data
  would be.
- The backtest uses 16 forecast origins with a 3-month horizon, all on synthetic data. Its MAE
  and MAPE can disagree, so both are reported.

## Forecast backtest

`forecast_kpi` forecasts the next 3 months and backtests the trend model against a naive "last
value repeats" baseline (rolling origin, 16 origins, horizon 3). Output from the current data:

| Metric | Model MAE | Naive MAE | Model MAPE % | Naive MAPE % | Beats naive on MAE | Beats naive on MAPE |
|---|---|---|---|---|---|---|
| Conversion rate (%) | 1.62 | 1.70 | 23.5 | 23.0 | yes | no |
| Leads per month | 20.4 | 17.6 | 9.9 | 8.6 | no | no |
| Avg first response (min) | 29.5 | 8.9 | 976 | 302 | no | no |

On this data the trend model does not reliably beat the naive baseline. Response time is hard because
the backtest origins include pre-launch months around 140 minutes, and the trend extrapolates that
regime. These numbers are reproducible from `forecast_kpi`, but the agent's answers about them have
not yet been checked with a live model run.

## Next steps

- Add questions that should be refused or answered "no data", and score those too.
- Compare models and prompts on the same golden set and track the scores in Langfuse.
- Add an MCP client integration test.

MIT licensed.

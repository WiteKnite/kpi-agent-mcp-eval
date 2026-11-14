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
data/generate_data.py      synthetic, deterministic SQLite funnel data (12 months of leads)
src/kpi_agent/tools.py     read-only tools: list_tables, describe_table, run_query, kpi_summary, kpi_drivers
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
pytest                            # tools and golden set, no API key needed
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

- Synthetic data and six questions: a demonstration of the method, not a benchmark.
- The offline tests and the golden-set check run without an API key. The online agent run and the
  Langfuse integration need keys and were not exercised in the automated tests.
- `kpi_drivers` ignores mix effects, so its contributions only approximate the total change.

## Next steps

- Add questions that should be refused or answered "no data", and score those too.
- Compare models and prompts on the same golden set and track the scores in Langfuse.
- Add an MCP client integration test.

MIT licensed.

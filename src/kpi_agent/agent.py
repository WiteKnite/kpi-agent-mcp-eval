"""A small tool-using agent that answers KPI questions with the read-only tools.

Needs ANTHROPIC_API_KEY. The model can be changed with ANTHROPIC_MODEL.
"""
import json
import os

import anthropic

from kpi_agent import tools, tracing

MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5")
MAX_STEPS = 8

SYSTEM = (
    "You answer questions about a sales funnel using the provided tools only. "
    "Never guess numbers: call a tool, then answer. Months are formatted YYYY-MM. "
    "Give a short final answer that states the number or name asked for, with units."
)

TOOL_SCHEMAS = [
    {
        "name": "list_tables",
        "description": "List the tables in the analytics database.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "describe_table",
        "description": "Return column names and types for a table.",
        "input_schema": {
            "type": "object",
            "properties": {"table": {"type": "string"}},
            "required": ["table"],
        },
    },
    {
        "name": "run_query",
        "description": "Run one read-only SQLite SELECT and return up to 200 rows.",
        "input_schema": {
            "type": "object",
            "properties": {"sql": {"type": "string"}},
            "required": ["sql"],
        },
    },
    {
        "name": "kpi_summary",
        "description": (
            "Leads, conversions, conversion rate (%) and average first-response minutes for a month, "
            "optionally for one channel and/or one sales rep."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "month": {"type": "string", "description": "YYYY-MM"},
                "channel": {"type": "string", "enum": ["web_form", "whatsapp", "phone", "email"]},
                "rep": {
                    "type": "string",
                    "description": "Sales rep name: Amira, Bruno, Chen, Dana or Eli",
                },
            },
            "required": ["month"],
        },
    },
    {
        "name": "kpi_drivers",
        "description": "Break the change in conversion rate between two months down by channel or rep.",
        "input_schema": {
            "type": "object",
            "properties": {
                "month_from": {"type": "string"},
                "month_to": {"type": "string"},
                "dimension": {"type": "string", "enum": ["channel", "rep"]},
            },
            "required": ["month_from", "month_to"],
        },
    },
    {
        "name": "forecast_kpi",
        "description": (
            "Forecast a monthly KPI for the next 1 to 6 months (linear trend over the last 6 months), "
            "with a rolling backtest that reports the model's error next to a naive 'last value' baseline. "
            "Quote the baseline's error too, and say whether the model beats it on MAE and on MAPE "
            "separately, since the two can disagree."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "metric": {
                    "type": "string",
                    "enum": ["conversion_rate_pct", "leads", "avg_first_response_minutes"],
                },
                "horizon": {"type": "integer", "minimum": 1, "maximum": 6},
            },
            "required": ["metric"],
        },
    },
]


def _call_tool(name: str, args: dict) -> str:
    try:
        return json.dumps(tools.TOOLS[name](**args), default=str)
    except Exception as exc:  # report tool errors back to the model
        return json.dumps({"error": str(exc)})


@tracing.observe(name="kpi-agent-answer")
def answer(question: str, client: anthropic.Anthropic | None = None) -> dict:
    """Run the tool loop and return the final answer plus the tools that were called."""
    client = client or anthropic.Anthropic()
    messages = [{"role": "user", "content": question}]
    calls: list[str] = []
    for _ in range(MAX_STEPS):
        resp = client.messages.create(
            model=MODEL, max_tokens=1024, system=SYSTEM, tools=TOOL_SCHEMAS, messages=messages
        )
        if resp.stop_reason != "tool_use":
            text = "".join(b.text for b in resp.content if b.type == "text")
            return {"answer": text.strip(), "tool_calls": calls}
        messages.append({"role": "assistant", "content": resp.content})
        results = []
        for block in resp.content:
            if block.type == "tool_use":
                calls.append(block.name)
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": _call_tool(block.name, block.input),
                    }
                )
        messages.append({"role": "user", "content": results})
    return {"answer": "", "tool_calls": calls, "error": "step limit reached"}


if __name__ == "__main__":
    import sys

    print(answer(" ".join(sys.argv[1:]) or "What was the conversion rate in 2025-12?"))

"""Agent loop tests with a stubbed Anthropic client (no API key, no network).

These check the loop logic only: that tool calls are executed and fed back, that tool
errors are returned to the model, and that the step limit stops runaway loops. They do not
test the quality of a real model's answers; that is what eval/run_eval.py is for.
"""
import json
import pathlib
import sys
from types import SimpleNamespace as NS

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "data"))

import generate_data  # noqa: E402
from kpi_agent import agent, tools  # noqa: E402


def _tool_use(name, args, id_="t1"):
    return NS(stop_reason="tool_use", content=[NS(type="tool_use", id=id_, name=name, input=args)])


def _text(text):
    return NS(stop_reason="end_turn", content=[NS(type="text", text=text)])


class StubClient:
    def __init__(self, replies):
        self._replies = list(replies)
        self.calls = []
        self.messages = NS(create=self._create)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return self._replies.pop(0)


def _db(tmp_path):
    tools.DB_PATH = generate_data.build(tmp_path / "sales.db")


def test_loop_runs_the_tool_and_returns_the_final_answer(tmp_path):
    _db(tmp_path)
    client = StubClient([_tool_use("kpi_summary", {"month": "2025-12"}), _text("6.09 percent")])
    result = agent.answer("conversion in 2025-12?", client=client)
    assert result["answer"] == "6.09 percent"
    assert result["tool_calls"] == ["kpi_summary"]
    tool_result = client.calls[1]["messages"][-1]["content"][0]
    assert tool_result["type"] == "tool_result"
    assert json.loads(tool_result["content"])["month"] == "2025-12"


def test_tool_errors_are_returned_to_the_model(tmp_path):
    _db(tmp_path)
    client = StubClient([_tool_use("run_query", {"sql": "DROP TABLE leads"}), _text("cannot do that")])
    agent.answer("drop it", client=client)
    tool_result = client.calls[1]["messages"][-1]["content"][0]
    assert "error" in json.loads(tool_result["content"])


def test_step_limit_stops_a_runaway_loop(tmp_path):
    _db(tmp_path)
    replies = [_tool_use("list_tables", {}, id_=f"t{i}") for i in range(agent.MAX_STEPS)]
    result = agent.answer("loop forever", client=StubClient(replies))
    assert result["error"] == "step limit reached"
    assert len(result["tool_calls"]) == agent.MAX_STEPS

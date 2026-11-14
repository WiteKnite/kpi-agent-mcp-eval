"""Score the agent against the golden set.

  python eval/run_eval.py            # needs ANTHROPIC_API_KEY, traces to Langfuse if keys are set
  python eval/run_eval.py --offline  # no API: checks the golden set against the tools

Scoring: numbers match within a tolerance; text must contain the expected name.
"""
import argparse
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from kpi_agent import tools, tracing  # noqa: E402

QUESTIONS = json.loads((ROOT / "eval" / "questions.json").read_text(encoding="utf-8"))
NUMBER = re.compile(r"-?\d[\d,]*\.?\d*")


def score(item: dict, answer: str) -> bool:
    if item["kind"] == "text":
        return item["expected"].lower() in answer.lower()
    numbers = [float(n.replace(",", "")) for n in NUMBER.findall(answer)]
    return any(abs(n - item["expected"]) <= item["tolerance"] for n in numbers)


def offline_answer(item: dict) -> str:
    """Answer the golden questions straight from the tools, to validate the set itself."""
    qid = item["id"]
    if qid == "conv_dec":
        return str(tools.kpi_summary("2025-12")["conversion_rate_pct"])
    if qid == "resp_dec":
        return str(tools.kpi_summary("2025-12")["avg_first_response_minutes"])
    if qid == "resp_jun":
        return str(tools.kpi_summary("2025-06")["avg_first_response_minutes"])
    if qid == "leads_q4":
        sql = "SELECT COUNT(*) AS n FROM leads WHERE month IN ('2025-10','2025-11','2025-12')"
        return str(tools.run_query(sql)[0]["n"])
    if qid == "best_channel_dec":
        sql = (
            "SELECT channel FROM leads WHERE month='2025-12' GROUP BY channel "
            "ORDER BY 1.0*SUM(converted)/COUNT(*) DESC LIMIT 1"
        )
        return tools.run_query(sql)[0]["channel"]
    return tools.kpi_drivers("2025-06", "2025-12", "channel")[0]["channel"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    if not args.offline:
        from kpi_agent import agent

    passed = 0
    for item in QUESTIONS:
        if args.offline:
            ok, text = score(item, offline_answer(item)), "(offline)"
        else:
            result = agent.answer(item["question"])
            text = result["answer"]
            ok = score(item, text)
            tracing.score_current_trace("correct", 1.0 if ok else 0.0, comment=item["id"])
        passed += ok
        print(f"{'PASS' if ok else 'FAIL'}  {item['id']:18} {text[:80]}")
    tracing.flush()
    print(f"\n{passed}/{len(QUESTIONS)} passed")
    return 0 if passed == len(QUESTIONS) else 1


if __name__ == "__main__":
    sys.exit(main())

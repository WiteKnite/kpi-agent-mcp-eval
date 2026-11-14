"""Score the agent against the golden set.

  python eval/run_eval.py            # needs ANTHROPIC_API_KEY, traces to Langfuse if keys are set
  python eval/run_eval.py --offline  # no API: checks the golden set against the tools

Scoring: numbers match within a tolerance; text must contain the expected name.
"""
import argparse
import json
import os
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
    if qid == "conv_whatsapp_dec":
        return str(tools.kpi_summary("2025-12", channel="whatsapp")["conversion_rate_pct"])
    if qid == "conv_amira_dec":
        return str(tools.kpi_summary("2025-12", rep="Amira")["conversion_rate_pct"])
    if qid == "fc_conv_jan27":
        return str(tools.forecast_kpi("conversion_rate_pct", 1)["forecast"][0]["value"])
    if qid == "fc_leads_jan27":
        return str(tools.forecast_kpi("leads", 1)["forecast"][0]["value"])
    if qid == "top_rep_q4":
        sql = (
            "SELECT rep FROM leads WHERE month IN ('2025-10','2025-11','2025-12') GROUP BY rep "
            "ORDER BY 1.0*SUM(converted)/COUNT(*) DESC LIMIT 1"
        )
        return tools.run_query(sql)[0]["rep"]
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
    rows = []
    for item in QUESTIONS:
        tool_calls = []
        if args.offline:
            ok, text = score(item, offline_answer(item)), "(offline)"
        else:
            result = agent.answer(item["question"])
            text = result["answer"]
            tool_calls = result.get("tool_calls", [])
            ok = score(item, text)
            tracing.score_current_trace("correct", 1.0 if ok else 0.0, comment=item["id"])
        passed += ok
        rows.append({"id": item["id"], "pass": ok, "answer": text, "tool_calls": tool_calls})
        print(f"{'PASS' if ok else 'FAIL'}  {item['id']:18} {text[:80]}")
    tracing.flush()
    print(f"\n{passed}/{len(QUESTIONS)} passed")
    if not args.offline:
        # Save every live run so the README can point at the evidence.
        from datetime import date

        model = os.getenv("ANTHROPIC_MODEL", agent.MODEL)
        out_dir = ROOT / "eval" / "results"
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / f"live_{date.today():%Y%m%d}_{model}.json"
        out.write_text(
            json.dumps({"model": model, "date": str(date.today()), "passed": passed,
                        "total": len(QUESTIONS), "results": rows}, indent=2),
            encoding="utf-8",
        )
        print(f"Saved {out}")
    return 0 if passed == len(QUESTIONS) else 1


if __name__ == "__main__":
    sys.exit(main())

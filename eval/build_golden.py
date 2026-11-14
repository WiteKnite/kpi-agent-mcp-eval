"""Build the golden question set. Expected answers come from SQL, never from a model."""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
from kpi_agent import tools  # noqa: E402

OUT = pathlib.Path(__file__).with_name("questions.json")


def build() -> list[dict]:
    dec, jun = tools.kpi_summary("2025-12"), tools.kpi_summary("2025-06")
    q4 = tools.run_query(
        "SELECT COUNT(*) AS n FROM leads WHERE month IN ('2025-10','2025-11','2025-12')"
    )[0]["n"]
    best_channel = tools.run_query(
        "SELECT channel FROM leads WHERE month='2025-12' GROUP BY channel "
        "ORDER BY 1.0*SUM(converted)/COUNT(*) DESC LIMIT 1"
    )[0]["channel"]
    top_driver = tools.kpi_drivers("2025-06", "2025-12", "channel")[0]["channel"]
    whatsapp_dec = tools.kpi_summary("2025-12", channel="whatsapp")
    amira_dec = tools.kpi_summary("2025-12", rep="Amira")
    # Forecast checks: the expected value is the 3-month average computed in SQL, independently of
    # the tool's Python code. It checks that the agent calls forecast_kpi and reports its number.
    last3 = tools.run_query(
        "SELECT month, 100.0*SUM(converted)/COUNT(*) AS rate, COUNT(*) AS n FROM leads "
        "WHERE month IN ('2026-10','2026-11','2026-12') GROUP BY month"
    )
    fc_conv = round(sum(r["rate"] for r in last3) / len(last3), 2)
    fc_leads = round(sum(r["n"] for r in last3) / len(last3), 2)
    top_rep_q4 = tools.run_query(
        "SELECT rep FROM leads WHERE month IN ('2025-10','2025-11','2025-12') GROUP BY rep "
        "ORDER BY 1.0*SUM(converted)/COUNT(*) DESC LIMIT 1"
    )[0]["rep"]
    return [
        {
            "id": "conv_dec",
            "question": "What was the lead-to-contract conversion rate in 2025-12, in percent?",
            "expected": dec["conversion_rate_pct"],
            "kind": "number",
            "tolerance": 0.05,
        },
        {
            "id": "resp_dec",
            "question": "What was the average first-response time in minutes in 2025-12?",
            "expected": dec["avg_first_response_minutes"],
            "kind": "number",
            "tolerance": 0.1,
        },
        {
            "id": "resp_jun",
            "question": "What was the average first-response time in minutes in 2025-06?",
            "expected": jun["avg_first_response_minutes"],
            "kind": "number",
            "tolerance": 0.5,
        },
        {
            "id": "leads_q4",
            "question": "How many leads were created in total in Q4 2025 (October to December)?",
            "expected": q4,
            "kind": "number",
            "tolerance": 0,
        },
        {
            "id": "best_channel_dec",
            "question": "Which channel had the highest conversion rate in 2025-12?",
            "expected": best_channel,
            "kind": "text",
        },
        {
            "id": "top_driver",
            "question": "Which channel contributed most to the change in conversion rate between 2025-06 and 2025-12?",
            "expected": top_driver,
            "kind": "text",
        },
        {
            "id": "conv_whatsapp_dec",
            "question": "What was the conversion rate in percent for WhatsApp leads in 2025-12?",
            "expected": whatsapp_dec["conversion_rate_pct"],
            "kind": "number",
            "tolerance": 0.05,
        },
        {
            "id": "conv_amira_dec",
            "question": "What was the conversion rate in percent for sales rep Amira in 2025-12?",
            "expected": amira_dec["conversion_rate_pct"],
            "kind": "number",
            "tolerance": 0.05,
        },
        {
            "id": "top_rep_q4",
            "question": "Which sales rep had the highest conversion rate in Q4 2025 (October to December)?",
            "expected": top_rep_q4,
            "kind": "text",
        },
        {
            "id": "fc_conv_jan27",
            "question": "Use the forecast tool: what is the forecast conversion rate in percent for 2027-01?",
            "expected": fc_conv,
            "kind": "number",
            "tolerance": 0.05,
        },
        {
            "id": "fc_leads_jan27",
            "question": "Use the forecast tool: how many leads are forecast for 2027-01?",
            "expected": fc_leads,
            "kind": "number",
            "tolerance": 0.5,
        },
    ]


if __name__ == "__main__":
    OUT.write_text(json.dumps(build(), indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {OUT}")

import json
import pathlib
import sqlite3
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "data"))
sys.path.insert(0, str(ROOT / "eval"))

import generate_data  # noqa: E402
from kpi_agent import tools  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def database(tmp_path_factory):
    path = generate_data.build(tmp_path_factory.mktemp("db") / "sales.db")
    tools.DB_PATH = path
    return path


def test_run_query_allows_select():
    assert tools.run_query("SELECT COUNT(*) AS n FROM leads")[0]["n"] > 1000


@pytest.mark.parametrize(
    "sql",
    ["DELETE FROM leads", "DROP TABLE leads", "SELECT 1; DROP TABLE leads", "UPDATE leads SET converted=1"],
)
def test_run_query_blocks_writes(sql):
    with pytest.raises(ValueError):
        tools.run_query(sql)


def test_database_is_read_only(database):
    con = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    with pytest.raises(sqlite3.OperationalError):
        con.execute("DELETE FROM leads")


def test_kpi_summary_matches_sql():
    summary = tools.kpi_summary("2025-12")
    row = tools.run_query(
        "SELECT COUNT(*) AS n, SUM(converted) AS c FROM leads WHERE month='2025-12'"
    )[0]
    assert summary["leads"] == row["n"]
    assert summary["conversion_rate_pct"] == round(100 * row["c"] / row["n"], 2)


def test_story_in_data_response_time_drops_after_launch():
    before = tools.kpi_summary("2025-06")["avg_first_response_minutes"]
    after = tools.kpi_summary("2025-08")["avg_first_response_minutes"]
    assert before > 100 > 10 > after


def test_drivers_contributions_sum_to_total_change():
    drivers = tools.kpi_drivers("2025-06", "2025-12", "channel")
    total = tools.kpi_summary("2025-12")["conversion_rate_pct"] - tools.kpi_summary("2025-06")[
        "conversion_rate_pct"
    ]
    # Mix effects are ignored, so the sum is close to, not equal to, the total change.
    assert abs(sum(d["contribution_pct_points"] for d in drivers) - total) < 1.5


def test_golden_set_is_consistent_with_tools():
    import build_golden
    import run_eval

    for item in build_golden.build():
        assert run_eval.score(item, run_eval.offline_answer(item)), item["id"]


def test_unknown_month_raises():
    with pytest.raises(ValueError):
        tools.kpi_summary("1999-01")

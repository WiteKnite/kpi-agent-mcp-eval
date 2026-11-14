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


def test_kpi_summary_channel_filter_matches_sql():
    summary = tools.kpi_summary("2025-12", channel="whatsapp")
    row = tools.run_query(
        "SELECT COUNT(*) AS n, SUM(converted) AS c FROM leads "
        "WHERE month='2025-12' AND channel='whatsapp'"
    )[0]
    assert summary["channel"] == "whatsapp"
    assert summary["leads"] == row["n"]
    assert summary["conversion_rate_pct"] == round(100 * row["c"] / row["n"], 2)


def test_kpi_summary_rep_filter_matches_sql():
    summary = tools.kpi_summary("2025-12", rep="Amira")
    row = tools.run_query(
        "SELECT COUNT(*) AS n, SUM(converted) AS c FROM leads WHERE month='2025-12' AND rep='Amira'"
    )[0]
    assert summary["rep"] == "Amira"
    assert summary["leads"] == row["n"]
    assert summary["conversion_rate_pct"] == round(100 * row["c"] / row["n"], 2)


def test_filters_without_values_match_the_unfiltered_summary():
    assert tools.kpi_summary("2025-12") == tools.kpi_summary("2025-12", channel=None, rep=None)


@pytest.mark.parametrize(
    "kwargs",
    [{"channel": "fax"}, {"rep": "Nobody"}, {"channel": "email", "rep": "Nobody"}],
)
def test_unknown_filter_value_raises(kwargs):
    with pytest.raises(ValueError, match="unknown"):
        tools.kpi_summary("2025-12", **kwargs)


def test_forecast_months_continue_after_last_actual():
    result = tools.forecast_kpi("leads", 3)
    assert result["last_actual_month"] == "2026-12"
    assert [f["month"] for f in result["forecast"]] == ["2027-01", "2027-02", "2027-03"]


def test_forecast_month_labels_roll_over_the_year():
    assert tools._add_months("2025-11", 2) == "2026-01"
    assert tools._add_months("2025-12", 1) == "2026-01"


def test_forecast_backtest_reports_model_and_baseline_errors():
    bt = tools.forecast_kpi("conversion_rate_pct", 3)["backtest"]
    for key in ("model_mae", "model_mape_pct", "naive_mae", "naive_mape_pct"):
        assert isinstance(bt[key], float), key
    assert bt["origins"] >= 1
    assert bt["beats_naive_mae"] == (bt["model_mae"] < bt["naive_mae"])
    assert bt["beats_naive_mape"] == (bt["model_mape_pct"] < bt["naive_mape_pct"])


def test_trend_forecast_of_constant_series_is_constant():
    assert tools._trend_forecast([5.0] * 8, 3) == pytest.approx([5.0, 5.0, 5.0])


def test_naive_baseline_repeats_last_value():
    assert tools._naive_forecast([1.0, 2.0, 7.5], 2) == [7.5, 7.5]


def test_error_metrics_on_known_values():
    mae, mape = tools._errors([1.0, 2.0], [2.0, 2.0])
    assert mae == 0.5
    assert mape == 50.0  # (|1-2|/1 + |2-2|/2) / 2 = 0.5


@pytest.mark.parametrize("metric", ["revenue", "", "conversion_rate"])
def test_forecast_rejects_unknown_metric(metric):
    with pytest.raises(ValueError, match="metric"):
        tools.forecast_kpi(metric, 3)


@pytest.mark.parametrize("horizon", [0, 7, -1])
def test_forecast_rejects_bad_horizon(horizon):
    with pytest.raises(ValueError, match="horizon"):
        tools.forecast_kpi("leads", horizon)

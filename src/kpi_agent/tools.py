"""Read-only analytics tools shared by the MCP server and the agent loop."""
import os
import pathlib
import re
import sqlite3
from typing import Any

DB_PATH = pathlib.Path(
    os.getenv("KPI_DB_PATH", pathlib.Path(__file__).resolve().parents[2] / "data" / "sales.db")
)
MAX_ROWS = 200
_READ_ONLY = re.compile(r"^\s*(select|with)\b", re.IGNORECASE)


def _connect() -> sqlite3.Connection:
    # mode=ro makes SQLite refuse any write, whatever the query says.
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def list_tables() -> list[str]:
    """List the tables in the analytics database."""
    with _connect() as con:
        rows = con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        return [r["name"] for r in rows]


def describe_table(table: str) -> list[dict[str, str]]:
    """Return column names and types for a table."""
    if table not in list_tables():
        raise ValueError(f"unknown table: {table}")
    with _connect() as con:
        rows = con.execute(f"PRAGMA table_info({table})")
        return [{"name": r["name"], "type": r["type"]} for r in rows]


def run_query(sql: str, limit: int = MAX_ROWS) -> list[dict[str, Any]]:
    """Run one read-only SELECT (or WITH ... SELECT) and return up to `limit` rows."""
    if not _READ_ONLY.match(sql) or ";" in sql.strip().rstrip(";"):
        raise ValueError("only a single SELECT statement is allowed")
    limit = max(1, min(int(limit), MAX_ROWS))
    with _connect() as con:
        cur = con.execute(sql)
        return [dict(r) for r in cur.fetchmany(limit)]


def _known_values(column: str) -> set[str]:
    with _connect() as con:
        return {r[0] for r in con.execute(f"SELECT DISTINCT {column} FROM leads")}


def kpi_summary(month: str, channel: str | None = None, rep: str | None = None) -> dict[str, Any]:
    """Leads, conversions, conversion rate (%) and average first-response time for a month (YYYY-MM).

    Optionally filter to one channel and/or one sales rep.
    """
    where, params = ["month = ?"], [month]
    filters = {}
    for column, value in (("channel", channel), ("rep", rep)):
        if value is None:
            continue
        if value not in _known_values(column):
            raise ValueError(f"unknown {column}: {value}")
        where.append(f"{column} = ?")
        params.append(value)
        filters[column] = value
    with _connect() as con:
        row = con.execute(
            "SELECT COUNT(*) AS leads, SUM(converted) AS conversions, "
            "AVG(first_response_minutes) AS avg_response "
            f"FROM leads WHERE {' AND '.join(where)}",
            params,
        ).fetchone()
    if not row["leads"]:
        raise ValueError(f"no data for month {month} with filters {filters}")
    return {
        "month": month,
        **filters,
        "leads": row["leads"],
        "conversions": row["conversions"],
        "conversion_rate_pct": round(100 * row["conversions"] / row["leads"], 2),
        "avg_first_response_minutes": round(row["avg_response"], 1),
    }


def kpi_drivers(month_from: str, month_to: str, dimension: str = "channel") -> list[dict[str, Any]]:
    """Break the change in conversion rate between two months down by channel or rep.

    contribution_pct_points = (rate_to - rate_from) * share_of_leads_in_month_to.
    Rows are sorted by absolute contribution, largest first.
    """
    if dimension not in {"channel", "rep"}:
        raise ValueError("dimension must be 'channel' or 'rep'")

    def by_dim(month: str) -> dict[str, tuple[int, int]]:
        with _connect() as con:
            rows = con.execute(
                f"SELECT {dimension} AS d, COUNT(*) AS n, SUM(converted) AS c "
                "FROM leads WHERE month = ? GROUP BY d",
                (month,),
            )
            return {r["d"]: (r["n"], r["c"]) for r in rows}

    a, b = by_dim(month_from), by_dim(month_to)
    total_b = sum(n for n, _ in b.values())
    out = []
    for key in sorted(set(a) | set(b)):
        na, ca = a.get(key, (0, 0))
        nb, cb = b.get(key, (0, 0))
        rate_a = 100 * ca / na if na else 0.0
        rate_b = 100 * cb / nb if nb else 0.0
        out.append(
            {
                dimension: key,
                "rate_from_pct": round(rate_a, 2),
                "rate_to_pct": round(rate_b, 2),
                "contribution_pct_points": round((rate_b - rate_a) * (nb / total_b), 3),
            }
        )
    return sorted(out, key=lambda r: abs(r["contribution_pct_points"]), reverse=True)


FORECAST_SQL = {
    "conversion_rate_pct": "100.0 * SUM(converted) / COUNT(*)",
    "leads": "COUNT(*)",
    "avg_first_response_minutes": "AVG(first_response_minutes)",
}
MAX_HORIZON = 6
MIN_TRAIN = 6  # months of history before the first backtest forecast
TREND_WINDOW = 6  # the trend is fitted on the most recent months only


def _monthly_series(metric: str) -> tuple[list[str], list[float]]:
    with _connect() as con:
        rows = con.execute(
            f"SELECT month, {FORECAST_SQL[metric]} AS v FROM leads GROUP BY month ORDER BY month"
        ).fetchall()
    return [r["month"] for r in rows], [float(r["v"]) for r in rows]


def _add_months(month: str, k: int) -> str:
    y, m = (int(p) for p in month.split("-"))
    idx = y * 12 + (m - 1) + k
    return f"{idx // 12:04d}-{idx % 12 + 1:02d}"


def _trend_forecast(history: list[float], horizon: int) -> list[float]:
    """Least-squares line through the last TREND_WINDOW points, extended `horizon` steps."""
    pts = history[-TREND_WINDOW:]
    n = len(pts)
    x_mean, y_mean = (n - 1) / 2, sum(pts) / n
    var = sum((x - x_mean) ** 2 for x in range(n))
    slope = sum((x - x_mean) * (y - y_mean) for x, y in enumerate(pts)) / var if var else 0.0
    return [y_mean + slope * (n - 1 + k - x_mean) for k in range(1, horizon + 1)]


def _naive_forecast(history: list[float], horizon: int) -> list[float]:
    """'Last value repeats' baseline."""
    return [history[-1]] * horizon


def _errors(actual: list[float], predicted: list[float]) -> tuple[float, float | None]:
    """Return (MAE, MAPE %). MAPE skips months whose actual value is zero."""
    abs_err = [abs(a - p) for a, p in zip(actual, predicted)]
    pct = [abs(a - p) / abs(a) for a, p in zip(actual, predicted) if a]
    mae = sum(abs_err) / len(abs_err)
    mape = 100 * sum(pct) / len(pct) if pct else None
    return round(mae, 4), (round(mape, 2) if mape is not None else None)


def _backtest(series: list[float], horizon: int) -> dict[str, Any]:
    """Rolling-origin backtest: at each origin, forecast only from the months before it."""
    origins = range(MIN_TRAIN, len(series) - horizon + 1)
    if not origins:
        raise ValueError("not enough history to backtest this horizon")
    actual, model_pred, naive_pred = [], [], []
    for t in origins:
        history, future = series[:t], series[t : t + horizon]
        actual += future
        model_pred += _trend_forecast(history, horizon)
        naive_pred += _naive_forecast(history, horizon)
    model_mae, model_mape = _errors(actual, model_pred)
    naive_mae, naive_mape = _errors(actual, naive_pred)
    return {
        "origins": len(origins),
        "model_mae": model_mae,
        "model_mape_pct": model_mape,
        "naive_mae": naive_mae,
        "naive_mape_pct": naive_mape,
        # Each measure is reported separately: the two can disagree.
        "beats_naive_mae": model_mae < naive_mae,
        "beats_naive_mape": (
            model_mape < naive_mape if model_mape is not None and naive_mape is not None else None
        ),
    }


def forecast_kpi(metric: str, horizon: int = 3) -> dict[str, Any]:
    """Forecast a monthly KPI for the next 1 to 6 months, with a backtest against a naive baseline.

    metric: conversion_rate_pct, leads or avg_first_response_minutes.
    The forecast is a linear trend over the last 6 months. The backtest reports the trend model's
    error next to the 'last value repeats' baseline, even when the baseline is better.
    """
    if metric not in FORECAST_SQL:
        raise ValueError(f"metric must be one of {sorted(FORECAST_SQL)}")
    horizon = int(horizon)
    if not 1 <= horizon <= MAX_HORIZON:
        raise ValueError(f"horizon must be between 1 and {MAX_HORIZON}")
    months, series = _monthly_series(metric)
    last = months[-1]
    values = _trend_forecast(series, horizon)
    return {
        "metric": metric,
        "horizon": horizon,
        "last_actual_month": last,
        "forecast": [
            {"month": _add_months(last, k), "value": round(v, 2)}
            for k, v in enumerate(values, start=1)
        ],
        "backtest": _backtest(series, horizon),
    }


TOOLS = {
    "list_tables": list_tables,
    "describe_table": describe_table,
    "run_query": run_query,
    "kpi_summary": kpi_summary,
    "kpi_drivers": kpi_drivers,
    "forecast_kpi": forecast_kpi,
}

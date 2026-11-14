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


def kpi_summary(month: str) -> dict[str, Any]:
    """Leads, conversions, conversion rate (%) and average first-response time for a month (YYYY-MM)."""
    with _connect() as con:
        row = con.execute(
            """SELECT COUNT(*) AS leads, SUM(converted) AS conversions,
                      AVG(first_response_minutes) AS avg_response
               FROM leads WHERE month = ?""",
            (month,),
        ).fetchone()
    if not row["leads"]:
        raise ValueError(f"no data for month {month}")
    return {
        "month": month,
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


TOOLS = {
    "list_tables": list_tables,
    "describe_table": describe_table,
    "run_query": run_query,
    "kpi_summary": kpi_summary,
    "kpi_drivers": kpi_drivers,
}

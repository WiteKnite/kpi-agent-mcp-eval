"""End-to-end check of the MCP server over the real stdio protocol."""
import asyncio
import json
import pathlib
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "data"))
import generate_data  # noqa: E402


def _run(tmp_path, calls):
    db = generate_data.build(tmp_path / "sales.db")
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "kpi_agent.mcp_server"],
        env={"PYTHONPATH": str(ROOT / "src"), "KPI_DB_PATH": str(db)},
    )

    async def go():
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await calls(session)

    return asyncio.run(asyncio.wait_for(go(), timeout=60))


def test_server_lists_the_five_tools(tmp_path):
    async def calls(session):
        return [t.name for t in (await session.list_tools()).tools]

    names = _run(tmp_path, calls)
    assert set(names) == {"list_tables", "describe_table", "run_query", "kpi_summary", "kpi_drivers"}


def test_kpi_summary_over_mcp(tmp_path):
    async def calls(session):
        return await session.call_tool("kpi_summary", {"month": "2025-12"})

    result = _run(tmp_path, calls)
    data = json.loads(result.content[0].text)
    assert data["month"] == "2025-12" and data["leads"] > 100


def test_write_query_is_rejected_over_mcp(tmp_path):
    async def calls(session):
        return await session.call_tool("run_query", {"sql": "DELETE FROM leads"})

    result = _run(tmp_path, calls)
    assert result.isError

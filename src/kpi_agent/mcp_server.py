"""MCP server exposing the read-only KPI tools over stdio.

Run:  python -m kpi_agent.mcp_server
Then point any MCP client at that command.
"""
from mcp.server.fastmcp import FastMCP

from kpi_agent import tools

mcp = FastMCP("kpi-agent")

for _fn in (
    tools.list_tables,
    tools.describe_table,
    tools.run_query,
    tools.kpi_summary,
    tools.kpi_drivers,
    tools.forecast_kpi,
):
    mcp.tool()(_fn)

if __name__ == "__main__":
    mcp.run()

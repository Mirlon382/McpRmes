"""Tool registration entrypoint.

The only place that knows about the MCP server. The three RMES tools are registered here, each as
a plain function -- none of them carries a registration wrapper. Each takes its service through
`Depends`, so no tool owns state of its own.
"""

from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from ..settings import Settings
from .rmes.describe_resource_tool import describe_rmes_resource
from .rmes.run_sparql_tool import run_rmes_sparql
from .rmes.search_graphs_tool import search_rmes_graphs

# Les tools sont consultatifs, ne modifient pas leur environnement
READ_ONLY = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    openWorldHint=False,
    idempotentHint=True,
)


def register_tools(mcp: FastMCP, settings: Settings) -> None:
    """Register the tools."""
    mcp.tool(search_rmes_graphs, annotations=READ_ONLY)
    mcp.tool(describe_rmes_resource, annotations=READ_ONLY)
    mcp.tool(run_rmes_sparql, annotations=READ_ONLY)

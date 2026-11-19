"""Tool registration entrypoint.

The only place that knows about the MCP server. Each group -- the three data sources, and the
feedback tool -- is registered only when its flag is on: an unregistered tool is the one kind of
"disabled" the protocol guarantees, unlike tag or visibility filtering, which a later call can undo.

Every tool is a plain function, so none of them carries a registration wrapper. Those that need a
service take it through `Depends`; `send_feedback` needs none.
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

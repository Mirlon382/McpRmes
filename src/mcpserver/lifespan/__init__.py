"""Startup and shutdown: build only what the enabled tool families need.

Each source contributes its own context fragment and closes its own clients. The exit stack
unwinds them in reverse, so a family that was never built is never torn down.

This is the composition root: it is the one place that reads the whole `Settings`, so nothing
below it has to.
"""

from collections.abc import AsyncIterator
from contextlib import AsyncExitStack
from typing import Any

from fastmcp import FastMCP
from fastmcp.server.lifespan import Lifespan, lifespan

from ..settings import Settings
from .rmes import rmes_lifespan


def build_lifespan(settings: Settings) -> Lifespan:
    """Return the lifespan FastMCP runs, wired for the families that are enabled."""

    @lifespan
    async def app_lifespan(_server: FastMCP[Any]) -> AsyncIterator[dict[str, Any]]:
        async with AsyncExitStack() as stack:
            context: dict[str, Any] = {}
            context |= await stack.enter_async_context(
                rmes_lifespan(
                    sparql_endpoint_url=settings.rmes_sparql_endpoint_url,
                    graph_base_uri=settings.rmes_graph_base_uri,
                    graph_listing_timeout_seconds=settings.rmes_graph_listing_timeout_seconds,
                    graph_listing_max_rows=settings.rmes_graph_listing_max_rows,
                    graph_cache_ttl_seconds=settings.rmes_graph_cache_ttl_seconds,
                    resource_query_timeout_seconds=settings.rmes_resource_query_timeout_seconds,
                    resource_query_max_rows=settings.rmes_resource_query_max_rows,
                )
            )

            yield context

    return app_lifespan
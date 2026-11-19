"""What the RMES tools need at runtime."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastmcp import Context
from fastmcp.dependencies import CurrentContext

from httpx import AsyncClient

from ..services.rmes.graph_store_service import RmesGraphStoreService

logger = logging.getLogger(__name__)

# Honest identity -- these APIs need no browser spoofing. Hardcoded: bump with pyproject.toml maybe.
USER_AGENT = "McpDiffusion/0.1.0"


@asynccontextmanager
async def rmes_lifespan(
    sparql_endpoint_url: str,
    graph_base_uri: str,
    graph_listing_timeout_seconds: float,
    graph_listing_max_rows: int,
    graph_cache_ttl_seconds: float,
    resource_query_timeout_seconds: float,
    resource_query_max_rows: int,
) -> AsyncIterator[dict[str, Any]]:
    """Build the RMES service and close its client on shutdown.

    RMES passes its own timeout per query, so this client sets none.
    """
    http_client = AsyncClient(headers={"User-Agent": USER_AGENT})
    logger.info("SPARQL client initialized")
    try:
        yield {
            "rmes_graph_store_service": RmesGraphStoreService(
                http_client=http_client,
                sparql_endpoint_url=sparql_endpoint_url,
                graph_base_uri=graph_base_uri,
                graph_listing_timeout_seconds=graph_listing_timeout_seconds,
                graph_listing_max_rows=graph_listing_max_rows,
                graph_cache_ttl_seconds=graph_cache_ttl_seconds,
                resource_query_timeout_seconds=resource_query_timeout_seconds,
                resource_query_max_rows=resource_query_max_rows,
            ),
        }
    finally:
        await http_client.aclose()

def get_rmes_graph_store_service(ctx: Context = CurrentContext()) -> RmesGraphStoreService:
    """Return the RMES graph store service built at startup."""
    return ctx.lifespan_context["rmes_graph_store_service"]
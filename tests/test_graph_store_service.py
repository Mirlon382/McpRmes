"""The service: one query in, one translated answer out.

The transport is a `httpx.MockTransport`, so every branch above the network is exercised without
calling RMES: the answer shapes, the limits forced on a query, the error codes a caller is told
about, and the graph listing's cache.
"""

from collections.abc import Callable
from urllib.parse import parse_qs

import httpx
import pytest

from mcpserver.errors import AppToolError, ErrorCode
from mcpserver.services.rmes.graph_store_service import (
    GRAPH_LISTING_QUERY,
    RmesGraphStoreService,
)

ENDPOINT = "https://rdf.insee.fr/sparql"
BASE = "http://rdf.insee.fr/graphes/"


def sent_query(request: httpx.Request) -> str:
    """The query as the endpoint receives it: form-encoded under the `query` field."""
    return parse_qs(request.content.decode())["query"][0]


def build_service(handler: Callable[[httpx.Request], httpx.Response], **overrides) -> RmesGraphStoreService:
    """A service wired to a fake endpoint. Defaults mirror the shipped settings."""
    options = {
        "graph_listing_timeout_seconds": 45.0,
        "graph_listing_max_rows": 1000,
        "graph_cache_ttl_seconds": 3600.0,
        "resource_query_timeout_seconds": 20.0,
        "resource_query_max_rows": 2000,
    }
    options.update(overrides)
    return RmesGraphStoreService(
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        sparql_endpoint_url=ENDPOINT,
        graph_base_uri=BASE,
        **options,
    )


def graph_rows_payload(rows: list[tuple[str, int]]) -> dict:
    """The JSON SPARQL answer for the graph listing query."""
    return {
        "head": {"vars": ["g", "nbTriples"]},
        "results": {
            "bindings": [
                {"g": {"type": "uri", "value": graph}, "nbTriples": {"type": "literal", "value": str(count)}}
                for graph, count in rows
            ]
        },
    }


# ----------------------------------------------------------------------------------------------------------------------
# Answers
# ----------------------------------------------------------------------------------------------------------------------


async def test_select_answer_keeps_variables_and_bindings() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "head": {"vars": ["s", "l"]},
                "results": {
                    "bindings": [{"s": {"type": "uri", "value": "http://x"}, "l": {"type": "literal", "value": "L"}}]
                },
            },
        )

    answer = await build_service(handler).execute("SELECT ?s ?l WHERE { ?s ?p ?l } LIMIT 1", 10.0, 200)

    assert answer.variables == ["s", "l"]
    assert answer.bindings is not None
    assert answer.bindings[0]["l"]["value"] == "L"
    assert answer.limit_added is None
    assert answer.hint is None
    assert answer.turtle is None


async def test_answer_without_limit_reports_the_one_that_was_added() -> None:
    sent: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(sent_query(request))
        return httpx.Response(200, json={"head": {"vars": []}, "results": {"bindings": []}})

    answer = await build_service(handler).execute("SELECT ?s WHERE { ?s ?p ?o }", 10.0, 42)

    assert answer.limit_added == 42
    assert answer.hint is not None and "42" in answer.hint
    assert "LIMIT 42" in sent[0]


async def test_ask_answer_is_the_boolean_flag() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"head": {}, "boolean": True})

    answer = await build_service(handler).execute("ASK { GRAPH ?g { ?s ?p ?o } }", 10.0, 10)

    assert answer.boolean is True
    assert answer.bindings is None


async def test_construct_answer_comes_back_as_turtle() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["accept"] == "text/turtle"
        return httpx.Response(200, text="<http://x> <http://p> <http://o> .")

    answer = await build_service(handler).execute("CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }", 10.0, 10)

    assert answer.turtle == "<http://x> <http://p> <http://o> ."
    assert answer.bindings is None


# ----------------------------------------------------------------------------------------------------------------------
# Refusals and failures
# ----------------------------------------------------------------------------------------------------------------------


async def test_refused_queries_never_reach_the_endpoint() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - asserted by the call count
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={})

    service = build_service(handler)
    with pytest.raises(AppToolError) as caught:
        await service.execute("DROP GRAPH <http://rdf.insee.fr/graphes/codes>", 10.0, 10)

    assert caught.value.code is ErrorCode.INVALID_QUERY
    assert calls == 0


async def test_undetectable_query_form_is_refused_without_a_call() -> None:
    with pytest.raises(AppToolError) as caught:
        await build_service(lambda request: httpx.Response(200, json={})).execute('{"graphql": true}', 10.0, 10)

    assert caught.value.code is ErrorCode.INVALID_QUERY


async def test_timeout_is_reported_as_a_retryable_backend_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow", request=request)

    with pytest.raises(AppToolError) as caught:
        await build_service(handler).execute("SELECT ?s WHERE { ?s ?p ?o }", 5.0, 10)

    assert caught.value.code is ErrorCode.BACKEND_UNAVAILABLE
    assert caught.value.retryable is True
    assert "5.0s" in str(caught.value)


async def test_400_is_a_query_error_not_an_outage() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="MALFORMED QUERY: undefined prefix")

    with pytest.raises(AppToolError) as caught:
        await build_service(handler).execute("SELECT ?s WHERE { skos:x ?p ?o }", 10.0, 10)

    assert caught.value.code is ErrorCode.INVALID_QUERY
    assert caught.value.retryable is False
    assert "undefined prefix" in str(caught.value)


async def test_503_is_a_retryable_upstream_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="maintenance")

    with pytest.raises(AppToolError) as caught:
        await build_service(handler).execute("SELECT ?s WHERE { ?s ?p ?o }", 10.0, 10)

    assert caught.value.code is ErrorCode.UPSTREAM_ERROR
    assert caught.value.retryable is True
    assert "503" in str(caught.value)


async def test_connection_failure_is_a_retryable_backend_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    with pytest.raises(AppToolError) as caught:
        await build_service(handler).execute("SELECT ?s WHERE { ?s ?p ?o }", 10.0, 10)

    assert caught.value.code is ErrorCode.BACKEND_UNAVAILABLE
    assert caught.value.retryable is True


async def test_non_json_answer_is_a_parse_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>proxy error</html>")

    with pytest.raises(AppToolError) as caught:
        await build_service(handler).execute("SELECT ?s WHERE { ?s ?p ?o }", 10.0, 10)

    assert caught.value.code is ErrorCode.PARSE_ERROR


# ----------------------------------------------------------------------------------------------------------------------
# Graph listing and its cache
# ----------------------------------------------------------------------------------------------------------------------


async def test_graph_rows_are_read_from_the_endpoint() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert GRAPH_LISTING_QUERY in sent_query(request)
        return httpx.Response(200, json=graph_rows_payload([(f"{BASE}codes", 10), (f"{BASE}geo/x", 3)]))

    rows = await build_service(handler).fetch_graph_rows()

    assert [(row.graph, row.triples) for row in rows] == [(f"{BASE}codes", 10), (f"{BASE}geo/x", 3)]


async def test_the_listing_is_fetched_once_while_the_cache_is_fresh() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=graph_rows_payload([(f"{BASE}codes", 10)]))

    service = build_service(handler)
    await service.fetch_graph_rows()
    again = await service.fetch_graph_rows()

    assert calls == 1
    assert again[0].graph == f"{BASE}codes"


async def test_an_expired_cache_is_refetched() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=graph_rows_payload([(f"{BASE}codes", calls)]))

    service = build_service(handler, graph_cache_ttl_seconds=0.0)
    await service.fetch_graph_rows()
    refreshed = await service.fetch_graph_rows()

    assert calls == 2
    assert refreshed[0].triples == 2


# ----------------------------------------------------------------------------------------------------------------------
# Resource description
# ----------------------------------------------------------------------------------------------------------------------


async def test_describe_resource_parses_both_directions() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "http://id.insee.fr/codes/naf2025/section/A" in sent_query(request)
        return httpx.Response(
            200,
            json={
                "head": {"vars": ["g", "direction", "p", "o"]},
                "results": {
                    "bindings": [
                        {
                            "g": {"type": "uri", "value": f"{BASE}codes/nafr2"},
                            "direction": {"type": "literal", "value": "outgoing"},
                            "p": {"type": "uri", "value": "http://www.w3.org/2004/02/skos/core#prefLabel"},
                            "o": {"type": "literal", "value": "Agriculture", "xml:lang": "fr"},
                        },
                        {
                            "g": {"type": "uri", "value": f"{BASE}codes/nafr2"},
                            "direction": {"type": "literal", "value": "incoming"},
                            "p": {"type": "uri", "value": "http://www.w3.org/2004/02/skos/core#narrower"},
                            "o": {"type": "uri", "value": "http://id.insee.fr/codes/naf2025/division/01"},
                        },
                    ]
                },
            },
        )

    properties = await build_service(handler).describe_resource("http://id.insee.fr/codes/naf2025/section/A", None)

    assert [p.direction for p in properties] == ["outgoing", "incoming"]
    assert properties[0].lang == "fr"
    assert properties[1].value_type == "uri"

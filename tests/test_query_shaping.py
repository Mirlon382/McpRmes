"""Query shaping: what the service decides about a query before it reaches RMES.

Pure functions, no client and no network, so these pin the rules instead of the transport: which
query form a text is, which queries are refused outright, and which limit is forced on the rest.
"""

import pytest

from mcpserver.errors import AppToolError, ErrorCode
from mcpserver.services.rmes.graph_store_service import (
    UNKNOWN_FORM,
    build_accept_header,
    build_limit_hint,
    build_resource_query,
    check_query_is_allowed,
    detect_query_form,
    ensure_row_limit,
    mask_inert_tokens,
    parse_resource_properties,
)

SELECT_ALL_GRAPHS = "SELECT ?s ?p ?o WHERE { GRAPH ?g { ?s ?p ?o } }"


# ----------------------------------------------------------------------------------------------------------------------
# detect_query_form
# ----------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        (SELECT_ALL_GRAPHS, "SELECT"),
        ("ASK { ?s ?p ?o }", "ASK"),
        ("CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }", "CONSTRUCT"),
        ("DESCRIBE <http://id.insee.fr/codes/naf2025/section/A>", "DESCRIBE"),
        ("select ?s where { ?s ?p ?o }", "SELECT"),
        ("  \n\t SELECT ?s WHERE { ?s ?p ?o }", "SELECT"),
    ],
)
def test_detect_query_form_reads_the_keyword(query: str, expected: str) -> None:
    assert detect_query_form(query) == expected


def test_detect_query_form_ignores_prefixes_on_their_own_lines() -> None:
    query = (
        "PREFIX skos: <http://www.w3.org/2004/02/skos/core#>\n"
        "BASE <http://rdf.insee.fr/graphes/>\n"
        "SELECT ?s WHERE { GRAPH <codes/nafr2> { ?s skos:prefLabel ?l } }"
    )

    assert detect_query_form(query) == "SELECT"


def test_detect_query_form_ignores_prefixes_sharing_the_line() -> None:
    """A model often writes the whole query as one line; the SELECT after PREFIX must still be found."""
    query = "PREFIX skos: <http://www.w3.org/2004/02/skos/core#> SELECT ?s WHERE { ?s ?p ?o }"

    assert detect_query_form(query) == "SELECT"


def test_detect_query_form_refuses_to_guess() -> None:
    assert detect_query_form("{ graphs { name } }") == UNKNOWN_FORM
    assert detect_query_form("PREFIX skos: <http://www.w3.org/2004/02/skos/core#>") == UNKNOWN_FORM


# ----------------------------------------------------------------------------------------------------------------------
# check_query_is_allowed
# ----------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("keyword", ["INSERT", "DELETE", "LOAD", "CLEAR", "DROP", "CREATE", "ADD", "MOVE", "COPY"])
def test_update_operations_are_refused(keyword: str) -> None:
    with pytest.raises(AppToolError) as caught:
        check_query_is_allowed(f"{keyword} DATA {{ <http://x> <http://y> <http://z> }}")

    assert caught.value.code is ErrorCode.INVALID_QUERY
    assert keyword in str(caught.value)


def test_service_calls_are_refused() -> None:
    query = "SELECT ?s WHERE { SERVICE <http://elsewhere/sparql> { ?s ?p ?o } }"

    with pytest.raises(AppToolError) as caught:
        check_query_is_allowed(query)

    assert caught.value.code is ErrorCode.INVALID_QUERY
    assert "SERVICE" in str(caught.value)


def test_read_only_queries_pass() -> None:
    check_query_is_allowed(SELECT_ALL_GRAPHS)
    check_query_is_allowed("ASK { GRAPH <http://rdf.insee.fr/graphes/codes> { ?s ?p ?o } }")


@pytest.mark.parametrize(
    "query",
    [
        # An IRI may spell a keyword; it is still an IRI.
        "SELECT ?s WHERE { ?s <http://ex/delete> ?o }",
        # Same for a string literal, a comment, and a prefixed name.
        'SELECT ?s WHERE { ?s ?p "please LOAD this" }',
        "SELECT ?s WHERE { ?s ?p ?o } # drop it later",
        "SELECT ?add ?s WHERE { ?s ?p ?add }",
        "SELECT ?s WHERE { ?s ex:load ?o }",
    ],
)
def test_keywords_inside_inert_tokens_do_not_trip_the_guard(query: str) -> None:
    check_query_is_allowed(query)


def test_mask_inert_tokens_blanks_tokens_but_keeps_structure() -> None:
    masked = mask_inert_tokens('SELECT ?s WHERE { ?s <http://ex/drop> "DELETE" } # clear')

    assert "http://ex/drop" not in masked
    assert "DELETE" not in masked
    assert "clear" not in masked
    assert "SELECT" in masked and "WHERE" in masked


# ----------------------------------------------------------------------------------------------------------------------
# ensure_row_limit
# ----------------------------------------------------------------------------------------------------------------------


def test_limit_is_added_when_absent() -> None:
    query, added = ensure_row_limit(SELECT_ALL_GRAPHS, "SELECT", 50)

    assert added is True
    assert query.endswith("LIMIT 50")


def test_existing_limit_is_left_alone() -> None:
    query = "SELECT ?s WHERE { ?s ?p ?o } LIMIT 7"

    assert ensure_row_limit(query, "SELECT", 50) == (query, False)


def test_limit_followed_by_offset_is_recognised() -> None:
    query = "SELECT ?s WHERE { ?s ?p ?o } LIMIT 7 OFFSET 14"

    assert ensure_row_limit(query, "SELECT", 50) == (query, False)


def test_trailing_semicolon_is_handled() -> None:
    query, added = ensure_row_limit("SELECT ?s WHERE { ?s ?p ?o };", "SELECT", 50)

    assert added is True
    assert query.endswith("LIMIT 50")
    assert ";" not in query


def test_limit_of_a_subquery_does_not_bound_the_outer_query() -> None:
    query = "SELECT ?s WHERE { { SELECT ?s WHERE { ?s ?p ?o } LIMIT 5 } }"

    _, added = ensure_row_limit(query, "SELECT", 50)

    assert added is True


def test_construct_is_bounded_but_ask_and_describe_are_not() -> None:
    assert ensure_row_limit("CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }", "CONSTRUCT", 9)[1] is True
    assert ensure_row_limit("ASK { ?s ?p ?o }", "ASK", 9)[1] is False
    assert ensure_row_limit("DESCRIBE <http://x>", "DESCRIBE", 9)[1] is False
    assert ensure_row_limit(SELECT_ALL_GRAPHS, UNKNOWN_FORM, 9)[1] is False


def test_limit_hint_names_the_parameter_that_raises_it() -> None:
    assert "max_rows" in build_limit_hint(200)
    assert "200" in build_limit_hint(200)


# ----------------------------------------------------------------------------------------------------------------------
# Content negotiation and resource queries
# ----------------------------------------------------------------------------------------------------------------------


def test_accept_header_follows_the_query_form() -> None:
    assert build_accept_header("SELECT") == "application/sparql-results+json"
    assert build_accept_header("ASK") == "application/sparql-results+json"
    assert build_accept_header("CONSTRUCT") == "text/turtle"
    assert build_accept_header("DESCRIBE") == "text/turtle"


def test_resource_query_scans_every_graph_by_default() -> None:
    query = build_resource_query("http://id.insee.fr/x", None, 100)

    assert "GRAPH ?g { <http://id.insee.fr/x> ?p ?o }" in query
    assert "VALUES" not in query
    assert query.rstrip().endswith("LIMIT 100")


def test_resource_query_can_be_pinned_to_one_graph() -> None:
    query = build_resource_query("http://id.insee.fr/x", "http://rdf.insee.fr/graphes/codes/nafr2", 100)

    assert "VALUES ?g { <http://rdf.insee.fr/graphes/codes/nafr2> }" in query
    assert "GRAPH <http://rdf.insee.fr/graphes/codes/nafr2>" in query


def test_resource_query_looks_both_ways() -> None:
    query = build_resource_query("http://id.insee.fr/x", None, 10)

    assert 'BIND("outgoing" AS ?direction)' in query
    assert 'BIND("incoming" AS ?direction)' in query


def test_resource_properties_are_mapped_from_bindings() -> None:
    bindings = [
        {
            "g": {"type": "uri", "value": "http://rdf.insee.fr/graphes/codes/nafr2"},
            "direction": {"type": "literal", "value": "outgoing"},
            "p": {"type": "uri", "value": "http://www.w3.org/2004/02/skos/core#prefLabel"},
            "o": {"type": "literal", "value": "Section NAF", "xml:lang": "fr"},
        },
        {
            "g": {"type": "uri", "value": "http://rdf.insee.fr/graphes/codes/nafr2"},
            "direction": {"type": "literal", "value": "incoming"},
            "p": {"type": "uri", "value": "http://www.w3.org/2004/02/skos/core#broader"},
            "o": {"type": "uri", "value": "http://id.insee.fr/concepts/nafr2/section"},
        },
    ]

    properties = parse_resource_properties(bindings)

    assert properties[0].value == "Section NAF"
    assert properties[0].lang == "fr"
    assert properties[0].value_type == "literal"
    assert properties[1].direction == "incoming"
    assert properties[1].lang is None

"""What the server publishes: the three tools, their read-only annotations, and the guards on their
parameters.

The tool functions are plain Python, so the bounds a client sees are the pydantic annotations carried
by their parameters. These tests read them back through the published schema, which is what a model
actually gets, rather than calling the functions with unvalidated values.
"""

import pytest
from fastmcp import FastMCP
from pydantic import TypeAdapter, ValidationError

from mcpserver.models.rmes import (
    DEFAULT_ROW_LIMIT,
    MAX_ROW_LIMIT,
    GraphCategory,
    GraphCategoryChoice,
    GraphUri,
    MaxRows,
    ResourceUri,
    SparqlQuery,
)
from mcpserver.settings import Settings
from mcpserver.tools import register_tools

EXPECTED_TOOLS = {"search_rmes_graphs", "describe_rmes_resource", "run_rmes_sparql"}


@pytest.fixture
async def tools() -> dict:
    """The tools as registered, exactly as a client would list them."""
    server = FastMCP("test")
    register_tools(server, Settings())
    return {tool.name: tool for tool in await server.list_tools()}


def test_the_three_rmes_tools_are_registered(tools: dict) -> None:
    assert set(tools) == EXPECTED_TOOLS


def test_every_tool_is_declared_read_only(tools: dict) -> None:
    for tool in tools.values():
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.destructive_hint is False


def test_sparql_tool_publishes_the_configured_limits(tools: dict) -> None:
    schema = tools["run_rmes_sparql"].parameters
    max_rows = schema["properties"]["max_rows"]

    assert schema["required"] == ["sparql_query"]
    assert max_rows["default"] == DEFAULT_ROW_LIMIT
    assert max_rows["maximum"] == MAX_ROW_LIMIT
    assert max_rows["minimum"] == 1


def test_graph_search_tool_defaults_to_every_family(tools: dict) -> None:
    schema = tools["search_rmes_graphs"].parameters
    category = schema["properties"]["graph_category"]

    assert category["default"] == GraphCategoryChoice.ALL.value
    assert set(category["enum"]) == {choice.value for choice in GraphCategoryChoice}
    assert "autre" in category["enum"]


def test_graph_category_accepts_a_name_and_refuses_an_unknown_one() -> None:
    adapter = TypeAdapter(GraphCategory)

    assert adapter.validate_python("nomenclatures") is GraphCategoryChoice.NOMENCLATURES
    assert adapter.validate_python(GraphCategoryChoice.ALL) is GraphCategoryChoice.ALL
    with pytest.raises(ValidationError):
        adapter.validate_python("nomenclature")


def test_every_family_in_the_table_is_selectable() -> None:
    """GraphCategoryChoice is derived from the rule table, so the two cannot drift apart."""
    from mcpserver.data.rmes.graph_categories import CATEGORY_DEFINITIONS, FALLBACK_CATEGORY_DEFINITION

    keys = {entry["key"] for entry in [*CATEGORY_DEFINITIONS, FALLBACK_CATEGORY_DEFINITION]}

    assert {choice.value for choice in GraphCategoryChoice} == {"ALL", *keys}


# ----------------------------------------------------------------------------------------------------------------------
# Guards on the parameters that end up inside a SPARQL query
# ----------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "hostile_uri",
    [
        "http://id.insee.fr/x> ?p ?o } UNION { GRAPH <http://evil",
        'http://id.insee.fr/x" }',
        "http://id.insee.fr/x y",
        "<http://id.insee.fr/x>",
    ],
)
def test_uri_parameters_refuse_characters_that_would_close_the_brackets(hostile_uri: str) -> None:
    """Both URIs are interpolated into `<...>`; the pattern is what stops the query being rewritten."""
    for annotation in (ResourceUri, GraphUri):
        with pytest.raises(ValidationError):
            TypeAdapter(annotation).validate_python(hostile_uri)


def test_a_normal_iri_passes_the_guard() -> None:
    assert TypeAdapter(ResourceUri).validate_python("http://id.insee.fr/codes/naf2025/section/A")


def test_query_text_is_trimmed_and_bounded() -> None:
    adapter = TypeAdapter(SparqlQuery)

    assert adapter.validate_python("  SELECT ?s WHERE { ?s ?p ?o }  ").startswith("SELECT")
    with pytest.raises(ValidationError):
        adapter.validate_python("   ")
    with pytest.raises(ValidationError):
        adapter.validate_python("#" + "x" * 20_001)


def test_row_limit_bounds_are_enforced() -> None:
    adapter = TypeAdapter(MaxRows)

    assert adapter.validate_python(1) == 1
    assert adapter.validate_python(MAX_ROW_LIMIT) == MAX_ROW_LIMIT
    for rejected in (0, -1, MAX_ROW_LIMIT + 1):
        with pytest.raises(ValidationError):
            adapter.validate_python(rejected)

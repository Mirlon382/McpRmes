"""Pydantic schemas for RMES (SPARQL) tools."""

from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, Field, StringConstraints

from ..data.rmes.graph_categories import CATEGORY_DEFINITIONS, FALLBACK_CATEGORY_DEFINITION
from ..settings import load_tool_limits
from .common import MAX_SHORT_TEXT_CHARS, ShortText

# ----------------------------------------------------------------------------------------------------------------------
# Schema bounds --------------------------------------------------------------------------------------------------------
# ----------------------------------------------------------------------------------------------------------------------

# Budgets an operator tunes to what the endpoint can bear: the RMES_QUERY_* settings. They are read once,
# here, because the schema is built from them when the tool is registered; a deployment that changes them
# advertises its own limits under the same tool name, which is the point.
_tool_limits = load_tool_limits()
DEFAULT_QUERY_TIMEOUT_SECONDS = _tool_limits.rmes_query_default_timeout_seconds
MAX_QUERY_TIMEOUT_SECONDS = _tool_limits.rmes_query_max_timeout_seconds
DEFAULT_ROW_LIMIT = _tool_limits.rmes_query_default_max_rows
MAX_ROW_LIMIT = _tool_limits.rmes_query_max_rows

MAX_SPARQL_QUERY_CHARS = 20_000
# Far above any real IRI. Both URIs are interpolated into a query, so they are bounded like it.
MAX_IRI_CHARS = 2048

# ----------------------------------------------------------------------------------------------------------------------
# Enumerations ---------------------------------------------------------------------------------------------------------
# ----------------------------------------------------------------------------------------------------------------------


# Derived from the rule table so a new family cannot be added without becoming selectable.
# "ALL" is not a family: it means "do not filter".
GraphCategoryChoice = StrEnum(
    "GraphCategoryChoice",
    {
        "ALL": "ALL",
        **{entry["key"].upper(): entry["key"] for entry in [*CATEGORY_DEFINITIONS, FALLBACK_CATEGORY_DEFINITION]},
    },
)


# ----------------------------------------------------------------------------------------------------------------------
# Tool parameters ------------------------------------------------------------------------------------------------------
# ----------------------------------------------------------------------------------------------------------------------

# --- search_rmes_graphs ---

GraphUriSubstring = Annotated[
    ShortText | None,
    Field(
        description=(
            "Filtre les graphes dont l'URI contient cette sous-chaine (insensible a la "
            "casse), ex. 'naf' ou 'qualite/rapport'. Active automatiquement le detail "
            f"complet (`graphs`) dans les categories retenues. {MAX_SHORT_TEXT_CHARS} caractères maximum."
        ),
        examples=[
            "naf",
            "qualite/rapport",
            "geo",
        ],
    ),
]

# The server validates in strict mode, where an enum field only accepts an enum instance -- never the
# string a client sends. Converting first keeps "ALL" valid and still refuses an unknown name, with
# the published schema unchanged.
GraphCategory = Annotated[
    GraphCategoryChoice,
    BeforeValidator(lambda value: GraphCategoryChoice(value) if isinstance(value, str) else value),
    Field(description="Categorie de graphes a cibler."),
]

ExpandGraphs = Annotated[
    bool,
    Field(
        description=(
            "Si True, inclut la liste complete des graphes (URI + nb de triplets) pour "
            "chaque categorie retenue, au lieu de seulement quelques exemples. Se "
            "declenche automatiquement si `graph_uri_substring` est fourni ou `graph_category != ALL`."
        ),
    ),
]

# --- describe_rmes_resource ---

# Both URIs below are interpolated into `<...>` in a SPARQL query. The SPARQL grammar already
# forbids these characters inside an IRI, so rejecting them costs no legitimate value and stops a
# crafted URI from closing the brackets and continuing the query. The caller gets a schema error
# naming the parameter instead of a syntax error from RMES.
IRI_PATTERN = r'^[^<>"{}|^`\\\x00-\x20]+$'

ResourceUri = Annotated[
    str,
    Field(
        description=f"URI complete de la ressource RDF a decrire. {MAX_IRI_CHARS} caractères maxi.",
        pattern=IRI_PATTERN,
        max_length=MAX_IRI_CHARS,
        examples=[
            "http://id.insee.fr/codes/naf2025/section/A",
        ],
    ),
]

GraphUri = Annotated[
    str | None,
    Field(
        description=(
            "URI d'un graphe nomme pour restreindre la recherche. Sans cette valeur (None par defaut), "
            f"la recherche se fait sur tous les graphes (plus lent). {MAX_IRI_CHARS} caractères maxi."
        ),
        pattern=IRI_PATTERN,
        max_length=MAX_IRI_CHARS,
    ),
]

# --- run_rmes_sparql ---

# Only blank and oversized queries are refused here; the query form is checked by the service.

SparqlQuery = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_SPARQL_QUERY_CHARS),
    Field(
        description=(
            f"Requete SPARQL complete (SELECT / ASK / CONSTRUCT / DESCRIBE).{MAX_SPARQL_QUERY_CHARS} caractères maxi."
        ),
    ),
]

TimeoutSeconds = Annotated[
    float,
    Field(
        description=f"Timeout en secondes (supérieur à 0 et plafonné à {MAX_QUERY_TIMEOUT_SECONDS}s).",
        gt=0,
        le=MAX_QUERY_TIMEOUT_SECONDS,
    ),
]

MaxRows = Annotated[
    int,
    Field(
        description=f"Limite de lignes ajoutee si absente de la requete (de 1 a {MAX_ROW_LIMIT}).",
        ge=1,
        le=MAX_ROW_LIMIT,
    ),
]


# ----------------------------------------------------------------------------------------------------------------------
# Result models --------------------------------------------------------------------------------------------------------
# ----------------------------------------------------------------------------------------------------------------------

# --- search_rmes_graphs ---


class GraphRow(BaseModel):
    graph: str
    triples: int


class CategoryBucket(BaseModel):
    category: str
    label: str
    description: str
    count: int
    total_triples: int
    examples: list[str]
    graphs: list[GraphRow] | None = None


class GraphsOutput(BaseModel):
    total_graphs_matched: int
    categories: list[CategoryBucket]


# --- describe_rmes_resource ---


class ResourceProperty(BaseModel):
    graph: str
    direction: Literal["outgoing", "incoming"]
    predicate: str
    value: str
    value_type: str | None = None
    lang: str | None = None


class ResourceOutput(BaseModel):
    uri: str
    properties: list[ResourceProperty]
    count: int


# --- run_rmes_sparql ---


class SparqlOutput(BaseModel):
    format: Literal["json", "turtle"] = "json"
    limit_added: int | None = None
    hint: str | None = None
    variables: list[str] | None = None
    bindings: list[dict[str, Any]] | None = None
    # ASK only: the endpoint answers true/false instead of rows.
    boolean: bool | None = None
    turtle: str | None = None

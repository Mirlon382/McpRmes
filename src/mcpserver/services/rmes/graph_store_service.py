"""The RMES graph store: sending SPARQL to it and reading the answer.

The endpoint and its budgets are bound once at startup. Everything below the transport is
pure, so query shaping can be checked without reaching the network.
"""

import asyncio
import re
import time
from dataclasses import dataclass
from typing import Any

import httpx

from ...errors import AppToolError, ErrorCode
from ...models.rmes import GraphRow, ResourceProperty

# Ask the store for one row per named graph, with how many triples it holds, biggest first.
# `?s ?p ?o` matches every triple, so COUNT(*) per ?g is that graph's size. It is the only
# query that touches the whole store, which is why it has its own budget and is cached.
GRAPH_LISTING_QUERY = (
    "SELECT ?g (COUNT(*) AS ?nbTriples) WHERE { GRAPH ?g { ?s ?p ?o } } GROUP BY ?g ORDER BY DESC(?nbTriples)"
)

# A PREFIX or BASE declaration, stripped whether or not it sits on its own line. Only the declaration
# is removed: anchoring on the end of the line deleted the rest of it too, so `PREFIX ex: <...> SELECT`
# written as one line lost its SELECT and was reported as an undetectable query form.
STRIP_PREFIX_PATTERN = re.compile(r"(?i)^[ \t]*(?:PREFIX|BASE)\s+(?:[^\s:<>]*:\s*)?<[^<>]*>", re.MULTILINE)
QUERY_FORM_PATTERN = re.compile(r"(?i)\b(SELECT|ASK|CONSTRUCT|DESCRIBE)\b")
# A LIMIT that bounds the whole query is the last thing in it -- OFFSET may follow or precede it,
# but nothing else does. Matching LIMIT anywhere counted one belonging to a subquery, or the word
# sitting in a string literal, and left the outer query unbounded.
TRAILING_LIMIT_PATTERN = re.compile(r"(?i)\bLIMIT\s+\d+\b(?:\s+OFFSET\s+\d+)?\s*;?\s*$")

# What carries no keyword even when it spells one: IRIs, string literals (all four quotings) and comments.
# Masked before the guards below look for keywords, so `<http://x/delete>`, "drop" or `# load` do not
# count, and a `#` inside an IRI does not start a comment. Alternation order is the scan order SPARQL's
# own tokenizer uses: whichever construct opens first wins.
INERT_TOKEN_PATTERN = re.compile(
    r'"""[\s\S]*?"""'
    r"|'''[\s\S]*?'''"
    r'|"(?:[^"\\\n]|\\.)*"'
    r"|'(?:[^'\\\n]|\\.)*'"
    r'|<[^<>"{}|^`\\\x00-\x20]*>'
    r"|#[^\n]*"
)
# A keyword, not part of a variable (`?add`), a prefixed name (`ex:load`, `add:`) or a language tag.
KEYWORD_BOUNDARY_BEFORE = r"(?<![?$:@\w-])"
KEYWORD_BOUNDARY_AFTER = r"(?![\w:-])"
# The SPARQL 1.1 Update operations. RMES is a public read-only endpoint and should refuse them
# anyway; this does not rely on it.
UPDATE_KEYWORD_PATTERN = re.compile(
    KEYWORD_BOUNDARY_BEFORE + r"(INSERT|DELETE|LOAD|CLEAR|DROP|CREATE|ADD|MOVE|COPY)" + KEYWORD_BOUNDARY_AFTER,
    re.IGNORECASE,
)
# Federated query: `SERVICE <url> { ... }` makes the endpoint call that URL on the caller's behalf.
SERVICE_KEYWORD_PATTERN = re.compile(
    KEYWORD_BOUNDARY_BEFORE + r"SERVICE" + KEYWORD_BOUNDARY_AFTER,
    re.IGNORECASE,
)

JSON_RESULT_FORMS = ("SELECT", "ASK")
LIMITABLE_FORMS = ("SELECT", "CONSTRUCT")
UNKNOWN_FORM = "UNKNOWN"


@dataclass(frozen=True)
class SparqlResponse:
    """One answer from the endpoint, already separated into its two possible shapes."""

    limit_added: int | None = None
    hint: str | None = None
    turtle: str | None = None
    variables: list[str] | None = None
    bindings: list[dict[str, Any]] | None = None


# ----------------------------------------------------------------------------------------------------------------------
# Query shaping --------------------------------------------------------------------------------------------------------
# ----------------------------------------------------------------------------------------------------------------------


def detect_query_form(query: str) -> str:
    """Return SELECT / ASK / CONSTRUCT / DESCRIBE, ignoring any PREFIX or BASE preamble."""
    body = STRIP_PREFIX_PATTERN.sub("", query)
    match = QUERY_FORM_PATTERN.search(body)
    return match.group(1).upper() if match else UNKNOWN_FORM


def mask_inert_tokens(query: str) -> str:
    """Blank out IRIs, string literals and comments, keeping the keywords and structure around them."""
    return INERT_TOKEN_PATTERN.sub(" ", query)


def check_query_is_allowed(query: str) -> None:
    """Refuse update operations and federated SERVICE calls, before anything is sent."""
    code = mask_inert_tokens(query)
    update = UPDATE_KEYWORD_PATTERN.search(code)
    if update:
        raise AppToolError(
            ErrorCode.INVALID_QUERY,
            f"Operation de mise a jour SPARQL refusee ({update.group(1).upper()}) : ce serveur est en "
            "lecture seule. Utilise SELECT, ASK, CONSTRUCT ou DESCRIBE.",
        )
    if SERVICE_KEYWORD_PATTERN.search(code):
        raise AppToolError(
            ErrorCode.INVALID_QUERY,
            "Les requetes federees (SERVICE) sont refusees : interroge uniquement les graphes RMES.",
        )


def ensure_row_limit(query: str, query_form: str, max_rows: int) -> tuple[str, bool]:
    """Append a LIMIT when the caller supplied none, so an open query cannot flood the response."""
    if query_form not in LIMITABLE_FORMS:
        return query, False
    if TRAILING_LIMIT_PATTERN.search(query.rstrip()):
        return query, False
    return query.rstrip().rstrip(";") + f"\nLIMIT {max_rows}", True


def build_accept_header(query_form: str) -> str:
    """SELECT and ASK answer in JSON; CONSTRUCT and DESCRIBE answer in Turtle."""
    if query_form in JSON_RESULT_FORMS:
        return "application/sparql-results+json"
    return "text/turtle"


def build_limit_hint(max_rows: int) -> str:
    """Tell the caller a limit was added and how to raise it."""
    return (
        f"Aucune clause LIMIT trouvee : une limite de {max_rows} a ete ajoutee "
        "automatiquement pour eviter une reponse trop volumineuse. "
        "Passe max_rows pour l'augmenter si besoin."
    )


def parse_resource_properties(bindings: list[dict[str, Any]]) -> list[ResourceProperty]:
    """Map the SELECT bindings of a resource description onto the records the tool returns."""
    return [
        ResourceProperty(
            graph=binding["g"]["value"],
            direction=binding["direction"]["value"],
            predicate=binding["p"]["value"],
            value=binding["o"]["value"],
            value_type=binding["o"].get("type"),
            lang=binding["o"].get("xml:lang"),
        )
        for binding in bindings
    ]


def build_resource_query(resource_uri: str, graph_uri: str | None, max_rows: int) -> str:
    """Ask for every triple where the resource appears, in either direction."""
    graph_clause = f"<{graph_uri}>" if graph_uri else "?g"
    graph_values = f"VALUES ?g {{ <{graph_uri}> }}" if graph_uri else ""
    # Interpolated, not parameterised: SPARQL has no bind parameters for IRIs. Safe because both
    # URIs are `pattern`-checked in models/rmes.py against the IRI grammar, so neither can carry
    # the `>` that would close the brackets and let the rest run as query text.
    return f"""
    SELECT ?g ?direction ?p ?o WHERE {{
      {graph_values}
      {{
        GRAPH {graph_clause} {{ <{resource_uri}> ?p ?o }}
        BIND("outgoing" AS ?direction)
      }} UNION {{
        GRAPH {graph_clause} {{ ?o ?p <{resource_uri}> }}
        BIND("incoming" AS ?direction)
      }}
    }} LIMIT {max_rows}
    """


# ----------------------------------------------------------------------------------------------------------------------
# Service --------------------------------------------------------------------------------------------------------------
# ----------------------------------------------------------------------------------------------------------------------


class RmesGraphStoreService:
    """Queries the RDF graph store behind RMES, and caches its expensive graph listing."""

    def __init__(
        self,
        http_client: httpx.AsyncClient,
        sparql_endpoint_url: str,
        graph_base_uri: str,
        graph_listing_timeout_seconds: float,
        graph_listing_max_rows: int,
        graph_cache_ttl_seconds: float,
        resource_query_timeout_seconds: float,
        resource_query_max_rows: int,
    ) -> None:
        self._http_client = http_client
        self._sparql_endpoint_url = sparql_endpoint_url
        # Read by the tool, which passes it to the pure taxonomy functions.
        self.graph_base_uri = graph_base_uri
        self._graph_listing_timeout_seconds = graph_listing_timeout_seconds
        self._graph_listing_max_rows = graph_listing_max_rows
        self._graph_cache_ttl_seconds = graph_cache_ttl_seconds
        # describe_rmes_resource sends a fixed query the model cannot size, so it has its own budget,
        # separate from run_rmes_sparql's schema bounds.
        self._resource_query_timeout_seconds = resource_query_timeout_seconds
        self._resource_query_max_rows = resource_query_max_rows
        self._graph_rows: list[GraphRow] | None = None
        self._graph_rows_fetched_at = 0.0
        # Without this, every request arriving during the long listing runs it again.
        self._graph_rows_lock = asyncio.Lock()

    async def execute(
        self,
        query: str,
        timeout_seconds: float,
        max_rows: int,
    ) -> SparqlResponse:
        """Send one query and return its answer, translating every failure for the caller."""
        check_query_is_allowed(query)
        query_form = detect_query_form(query)
        if query_form == UNKNOWN_FORM:
            raise AppToolError(
                ErrorCode.INVALID_QUERY,
                "Impossible de detecter SELECT / ASK / CONSTRUCT / DESCRIBE dans la requete. "
                "Verifie la syntaxe SPARQL (pas GraphQL).",
            )

        effective_query, limit_added = ensure_row_limit(query, query_form, max_rows)
        accept = build_accept_header(query_form)

        try:
            response = await self._http_client.post(
                self._sparql_endpoint_url,
                data={"query": effective_query},
                headers={"Accept": accept},
                timeout=timeout_seconds,
            )
            response.raise_for_status()
        except httpx.TimeoutException:
            raise AppToolError(
                ErrorCode.BACKEND_UNAVAILABLE,
                f"Le endpoint RMES n'a pas repondu en moins de {timeout_seconds}s. "
                "Restreins la requete (ajoute une clause GRAPH precise, reduis le LIMIT, "
                "evite les scans sans filtre sur tous les graphes).",
                retryable=True,
            )
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            body = exc.response.text[:2000]
            if status == httpx.codes.BAD_REQUEST:
                raise AppToolError(
                    ErrorCode.INVALID_QUERY,
                    f"Le endpoint RMES a rejete la requete (erreur de syntaxe SPARQL probable) : {body}",
                )
            raise AppToolError(
                ErrorCode.UPSTREAM_ERROR,
                f"Le endpoint RMES a repondu {status} : {body}",
                retryable=exc.response.is_server_error,
            )
        except httpx.RequestError as exc:
            raise AppToolError(
                ErrorCode.BACKEND_UNAVAILABLE,
                f"Impossible de contacter l'endpoint RMES ({type(exc).__name__}).",
                retryable=True,
            )

        if accept == "text/turtle":
            return SparqlResponse(
                limit_added=max_rows if limit_added else None,
                turtle=response.text,
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise AppToolError(
                ErrorCode.PARSE_ERROR,
                f"Le endpoint RMES a renvoye une reponse non-JSON : {exc}",
            )

        return SparqlResponse(
            limit_added=max_rows if limit_added else None,
            hint=build_limit_hint(max_rows) if limit_added else None,
            variables=payload.get("head", {}).get("vars"),
            bindings=payload.get("results", {}).get("bindings"),
        )

    async def fetch_graph_rows(self) -> list[GraphRow]:
        """Return every graph with its triple count, cached because the COUNT is expensive."""
        if self._is_graph_cache_fresh():
            return self._graph_rows

        async with self._graph_rows_lock:
            # A waiter that queued behind the fetch finds the answer already there.
            if self._is_graph_cache_fresh():
                return self._graph_rows

            response = await self.execute(
                GRAPH_LISTING_QUERY,
                timeout_seconds=self._graph_listing_timeout_seconds,
                max_rows=self._graph_listing_max_rows,
            )
            self._graph_rows = [
                GraphRow(
                    graph=binding["g"]["value"],
                    triples=int(binding["nbTriples"]["value"]),
                )
                for binding in response.bindings or []
            ]
            self._graph_rows_fetched_at = time.time()
            return self._graph_rows

    def _is_graph_cache_fresh(self) -> bool:
        """True while the cached listing is still within its time to live."""
        if self._graph_rows is None:
            return False
        return (time.time() - self._graph_rows_fetched_at) <= self._graph_cache_ttl_seconds

    async def describe_resource(
        self,
        resource_uri: str,
        graph_uri: str | None,
    ) -> list[ResourceProperty]:
        """Return every triple the endpoint holds about the resource, in either direction."""
        response = await self.execute(
            build_resource_query(resource_uri, graph_uri, self._resource_query_max_rows),
            timeout_seconds=self._resource_query_timeout_seconds,
            max_rows=self._resource_query_max_rows,
        )
        return parse_resource_properties(response.bindings or [])

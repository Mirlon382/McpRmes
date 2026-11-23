"""Sorting RMES graphs into the families advertised by search_rmes_graphs.

The rules come from the static table in `data/rmes/graph_categories.py`; these tests check the
matching semantics around it -- prefix vs exact path, order, fallback -- not the wording of a family.
"""

from mcpserver.data.rmes.graph_categories import CATEGORY_DEFINITIONS, FALLBACK_CATEGORY_DEFINITION
from mcpserver.models.rmes import GraphRow
from mcpserver.services.rmes.graph_taxonomy import (
    MAX_EXAMPLES_PER_CATEGORY,
    build_category_summary,
    build_matcher,
    build_rule,
    categorize_graph,
    filter_graph_rows,
    strip_graph_base_uri,
)

BASE = "http://rdf.insee.fr/graphes/"


def row(path: str, triples: int = 1) -> GraphRow:
    """A graph row as RMES returns it: the listing carries full URIs, not paths."""
    return GraphRow(graph=f"{BASE}{path}", triples=triples)


# ----------------------------------------------------------------------------------------------------------------------
# Matching
# ----------------------------------------------------------------------------------------------------------------------


def test_strip_graph_base_uri_leaves_matching_paths_alone() -> None:
    assert strip_graph_base_uri(f"{BASE}codes/nafr2", BASE) == "codes/nafr2"


def test_strip_graph_base_uri_keeps_a_foreign_uri_whole() -> None:
    foreign = "http://elsewhere.example/graphes/codes/nafr2"

    assert strip_graph_base_uri(foreign, BASE) == foreign


def test_prefix_rule_matches_the_stem_only() -> None:
    matcher = build_matcher({"key": "k", "label": "l", "description": "d", "prefixes": ["qualite/rapport/"]})

    assert matcher("qualite/rapport/2278")
    assert not matcher("qualite/rapport")


def test_path_rule_matches_exactly_and_no_descendant() -> None:
    matcher = build_matcher({"key": "k", "label": "l", "description": "d", "paths": ["codes"]})

    assert matcher("codes")
    assert not matcher("codes/nafr2")


def test_a_rule_without_a_test_matches_everything() -> None:
    assert build_matcher(FALLBACK_CATEGORY_DEFINITION)("anything/at/all")


def test_build_rule_keeps_the_declared_wording() -> None:
    definition = {"key": "k", "label": "Etiquette", "description": "Description", "paths": ["x"]}

    rule = build_rule(definition)

    assert (rule.key, rule.label, rule.description) == ("k", "Etiquette", "Description")


# ----------------------------------------------------------------------------------------------------------------------
# Categorisation
# ----------------------------------------------------------------------------------------------------------------------


def test_first_matching_family_wins() -> None:
    """Both tables would match `codes`; the exact-path family comes first, so it is the one reported."""
    assert categorize_graph(f"{BASE}codes", BASE).key == "codes_concepts_generiques"


def test_prefix_family_catches_the_nomenclatures() -> None:
    assert categorize_graph(f"{BASE}codes/nafr2", BASE).key == "nomenclatures"


def test_unknown_graph_falls_back() -> None:
    assert categorize_graph(f"{BASE}quelque/chose", BASE).key == FALLBACK_CATEGORY_DEFINITION["key"]
    assert categorize_graph("http://elsewhere.example/x", BASE).key == FALLBACK_CATEGORY_DEFINITION["key"]


def test_every_declared_family_is_reachable() -> None:
    """A family that no graph can ever match would be dead configuration."""
    sample = {
        "qualite_rapports": "qualite/rapport/1",
        "qualite_referentiels": "qualite/documents",
        "codes_concepts_generiques": "codes",
        "nomenclatures": "codes/nafr2",
        "operations_statistiques": "operations",
        "demographie": "demo/x",
        "geographie": "geo/x",
        "organisations": "organisations/insee",
        "concepts": "concepts/x",
        "produits": "produits",
        "catalogue": "catalogue",
        "ontologies": "def/base",
    }

    for definition in CATEGORY_DEFINITIONS:
        path = sample.get(definition["key"])
        assert path is not None, f"no sample graph for the family {definition['key']}"
        assert categorize_graph(f"{BASE}{path}", BASE).key == definition["key"]


# ----------------------------------------------------------------------------------------------------------------------
# Filtering and grouping
# ----------------------------------------------------------------------------------------------------------------------


def test_no_filter_keeps_every_row() -> None:
    rows = [row("codes/nafr2"), row("geo/x")]

    assert filter_graph_rows(rows, None, None, BASE) == rows


def test_substring_filter_is_case_insensitive() -> None:
    rows = [row("codes/nafr2"), row("geo/communes")]

    assert [r.graph for r in filter_graph_rows(rows, "NAF", None, BASE)] == [f"{BASE}codes/nafr2"]


def test_category_filter_uses_the_same_rules() -> None:
    rows = [row("codes/nafr2"), row("geo/communes"), row("codes")]

    kept = filter_graph_rows(rows, None, "nomenclatures", BASE)

    assert [r.graph for r in kept] == [f"{BASE}codes/nafr2"]


def test_summary_is_grouped_in_declared_order_and_drops_empty_families() -> None:
    rows = [row("geo/communes", 10), row("codes/nafr2", 30), row("geo/departements", 20)]

    summary = build_category_summary(rows, include_graphs=False, graph_base_uri=BASE)

    assert [bucket.category for bucket in summary] == ["nomenclatures", "geographie"]
    assert [bucket.count for bucket in summary] == [1, 2]
    assert [bucket.total_triples for bucket in summary] == [30, 30]
    assert all(bucket.graphs is None for bucket in summary)


def test_examples_are_capped_but_counts_are_not() -> None:
    rows = [row(f"qualite/rapport/{i}", i) for i in range(MAX_EXAMPLES_PER_CATEGORY + 4)]

    summary = build_category_summary(rows, include_graphs=False, graph_base_uri=BASE)

    assert summary[0].count == MAX_EXAMPLES_PER_CATEGORY + 4
    assert len(summary[0].examples) == MAX_EXAMPLES_PER_CATEGORY


def test_including_graphs_adds_them_biggest_first() -> None:
    rows = [row("geo/a", 1), row("geo/b", 99)]

    summary = build_category_summary(rows, include_graphs=True, graph_base_uri=BASE)

    assert summary[0].graphs is not None
    assert [g.triples for g in summary[0].graphs] == [99, 1]

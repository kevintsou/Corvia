"""Tests for the symbol/call-graph JSON exporter."""

from __future__ import annotations

from corvia.core.call_graph import build_call_graph
from corvia.core.symbol_export import serialize_symbol_graph
from corvia.core.symbol_table import build_symbol_table
from corvia.parser import CParser


def _parse(src: str, name: str):
    parser = CParser()
    ast, _ = parser.parse_string(src, name)
    return ast


def _export(*srcs: tuple[str, str]) -> dict:
    asts = {name: _parse(src, name) for src, name in srcs}
    table = build_symbol_table(asts)
    graph = build_call_graph(asts, table)
    return serialize_symbol_graph(table, graph, asts)


def test_single_file_functions_and_callees():
    src = """
    int helper(int x) { return x + 1; }
    int caller(void) { return helper(2); }
    """
    out = _export((src, "a.c"))
    by_name = {f["name"]: f for f in out["functions"]}

    assert set(by_name) == {"helper", "caller"}
    assert by_name["helper"]["file"] == "a.c"
    assert by_name["helper"]["signature"] == "int helper(int x)"
    assert by_name["caller"]["callees"] == ["helper"]
    assert out["unresolved_callees"] == []
    assert out["file_defines"]["a.c"] == ["helper", "caller"]


def test_cross_file_call_is_captured():
    # free_ctx is defined in free.c but called from use.c — the exact
    # scenario that a naive size-only batch split would blind an agent to.
    header = "typedef struct { int x; } Ctx; void free_ctx(Ctx *c);"
    free_c = f"{header}\nvoid free_ctx(Ctx *c) {{ c->x = 0; }}"
    use_c = f"{header}\nvoid use_ctx(Ctx *c) {{ free_ctx(c); }}"

    out = _export((free_c, "free.c"), (use_c, "use.c"))
    by_name = {f["name"]: f for f in out["functions"]}

    # Each definition is attributed to the .c file it was parsed from.
    assert by_name["free_ctx"]["file"] == "free.c"
    assert by_name["use_ctx"]["file"] == "use.c"
    # The cross-file edge is present and free_ctx is NOT flagged unresolved.
    assert "free_ctx" in by_name["use_ctx"]["callees"]
    assert "free_ctx" not in out["unresolved_callees"]
    assert any(
        e["caller"] == "use_ctx" and e["callee"] == "free_ctx"
        for e in out["call_edges"]
    )


def test_undefined_callee_is_unresolved():
    src = "void run(void) { external_thing(); }"
    out = _export((src, "a.c"))
    assert "external_thing" in out["unresolved_callees"]

"""Tests for the call graph builder."""

from __future__ import annotations

from covia.core.call_graph import build_call_graph
from covia.core.symbol_table import build_symbol_table
from covia.parser import CParser


def _parse(src: str, name: str = "<test>"):
    parser = CParser()
    ast, _ = parser.parse_string(src, name)
    return ast


def _build(*srcs: tuple[str, str]):
    asts = {name: _parse(src, name) for src, name in srcs}
    table = build_symbol_table(asts)
    return build_call_graph(asts, table)


def test_records_direct_call():
    src = """
    int helper(void) { return 1; }
    int caller(void) { return helper(); }
    """
    g = _build((src, "a.c"))
    assert "helper" in g.callees_of("caller")
    assert "caller" in g.callers_of("helper")


def test_records_cross_file_call():
    a = "int helper(void); int caller(void) { return helper(); }"
    b = "int helper(void) { return 1; }"
    g = _build((a, "a.c"), (b, "b.c"))
    assert "helper" in g.callees_of("caller")


def test_detects_direct_recursion():
    src = "int f(int n) { return f(n - 1); }"
    g = _build((src, "a.c"))
    assert g.is_recursive("f")


def test_detects_mutual_recursion():
    src = """
    int g(int n);
    int f(int n) { return g(n - 1); }
    int g(int n) { return f(n - 1); }
    """
    g = _build((src, "a.c"))
    assert g.is_recursive("f")
    assert g.is_recursive("g")


def test_topological_order_callees_before_callers():
    src = """
    int leaf(void) { return 0; }
    int mid(void) { return leaf(); }
    int top(void) { return mid(); }
    """
    g = _build((src, "a.c"))
    order = g.topological_order()
    assert order.index("leaf") < order.index("mid") < order.index("top")

"""Tests for FunctionSummary computation."""

from __future__ import annotations

from corvia.core.call_graph import build_call_graph
from corvia.core.summary import TriState, compute_summaries
from corvia.core.symbol_table import build_symbol_table
from corvia.parser import CParser


def _parse(src: str, name: str = "<test>"):
    parser = CParser()
    ast, _ = parser.parse_string(src, name)
    return ast


def _summaries(src: str, name: str = "a.c"):
    asts = {name: _parse(src, name)}
    table = build_symbol_table(asts)
    graph = build_call_graph(asts, table)
    return compute_summaries(table, graph, asts)


def test_wrapper_alloc_is_detected_as_allocator():
    src = """
    void *malloc(unsigned long);
    void *xalloc(unsigned long n) { return malloc(n); }
    """
    sums = _summaries(src)
    assert sums["xalloc"].allocates is True
    assert sums["xalloc"].transfers_ownership is True


def test_wrapper_free_propagates():
    src = """
    void free(void *p);
    void xfree(void *q) { free(q); }
    """
    sums = _summaries(src)
    assert 0 in sums["xfree"].frees_param


def test_wrapper_open_is_detected():
    src = """
    typedef struct _IO_FILE FILE;
    FILE *fopen(const char *p, const char *m);
    FILE *xopen(const char *p) { return fopen(p, "r"); }
    """
    sums = _summaries(src)
    assert sums["xopen"].opens_resource is True


def test_function_returning_null_constant():
    src = """
    int *maybe(void) { return 0; }
    """
    sums = _summaries(src)
    assert sums["maybe"].returns_null in (TriState.YES, TriState.MAYBE)


def test_recursive_function_marked():
    src = "int f(int n) { return f(n - 1); }"
    sums = _summaries(src)
    assert sums["f"].is_recursive


def test_unconditional_param_deref():
    src = """
    int read(int *p) { return *p; }
    """
    sums = _summaries(src)
    assert 0 in sums["read"].params_must_not_be_null


def test_pure_function_no_side_effects():
    src = "int pure(int x) { return x + 1; }"
    sums = _summaries(src)
    assert sums["pure"].has_side_effects is False

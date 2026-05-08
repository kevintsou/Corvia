"""Tests for the cross-file symbol table."""

from __future__ import annotations

from corvia.core.symbol_table import build_symbol_table
from corvia.parser import CParser


def _parse(src: str, name: str = "<test>"):
    parser = CParser()
    ast, _ = parser.parse_string(src, name)
    return ast


def test_records_function_definitions():
    ast = _parse("int add(int a, int b) { return a + b; }", "a.c")
    table = build_symbol_table({"a.c": ast})
    f = table.lookup_function("add")
    assert f is not None
    assert f.is_definition
    assert f.return_type == "int"
    assert [p.name for p in f.params] == ["a", "b"]


def test_distinguishes_declaration_from_definition():
    ast = _parse("int doit(void); int doit(void) { return 0; }", "a.c")
    table = build_symbol_table({"a.c": ast})
    f = table.lookup_function("doit")
    assert f is not None
    assert f.is_definition


def test_records_static_function_as_file_local():
    ast = _parse("static int helper(void) { return 1; }", "a.c")
    table = build_symbol_table({"a.c": ast})
    f = table.lookup_function("helper")
    assert f is not None
    assert f.is_static
    assert "a.c" in table.file_locals
    assert "helper" in table.file_locals["a.c"]


def test_records_global_variable():
    ast = _parse("int counter = 0;", "a.c")
    table = build_symbol_table({"a.c": ast})
    sym = table.lookup("counter")
    assert sym is not None
    assert sym.kind == "variable"


def test_records_struct_tag():
    ast = _parse("struct point { int x; int y; };", "a.c")
    table = build_symbol_table({"a.c": ast})
    assert "struct point" in table.tags
    tag = table.tags["struct point"]
    assert tag.tag_kind == "struct"
    assert set(tag.members) == {"x", "y"}


def test_records_typedef():
    ast = _parse("typedef int int32_t;", "a.c")
    table = build_symbol_table({"a.c": ast})
    assert "int32_t" in table.typedefs


def test_static_collision_across_files():
    ast_a = _parse("static int helper(void) { return 1; }", "a.c")
    ast_b = _parse("static int helper(void) { return 2; }", "b.c")
    table = build_symbol_table({"a.c": ast_a, "b.c": ast_b})
    files = table.has_static_collision("helper")
    assert set(files) == {"a.c", "b.c"}


def test_variadic_function_flag():
    ast = _parse("int my_printf(const char *fmt, ...);", "a.c")
    table = build_symbol_table({"a.c": ast})
    f = table.lookup_function("my_printf")
    assert f is not None
    assert f.is_variadic

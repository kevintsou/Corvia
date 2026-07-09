"""Tests for the C parser wrapper."""

from corvia.parser import CParser


def test_parse_valid_string():
    parser = CParser()
    ast, errors = parser.parse_string("int main(void) { return 0; }")
    assert ast is not None
    assert errors == []


def test_parse_invalid_string():
    parser = CParser()
    ast, errors = parser.parse_string("int main( { return; }")
    assert ast is None
    assert len(errors) == 1
    assert errors[0].checker_id == "parser"


def test_parse_file(fixtures_dir):
    parser = CParser()
    ast, errors = parser.parse_file(str(fixtures_dir / "clean.c"))
    assert ast is not None
    assert errors == []


def test_parse_missing_file():
    parser = CParser()
    ast, errors = parser.parse_file("/nonexistent/file.c")
    assert ast is None
    assert len(errors) == 1
    assert "not found" in errors[0].message.lower()


def test_code_after_if_else_endif_survives_stripping():
    """Regression: #elif/#else must not increase the conditional nesting
    depth, otherwise everything after the first #if/#else/#endif block is
    blanked out."""
    from pycparser import c_ast

    parser = CParser()
    code = (
        "#if FEATURE\n"
        "int a;\n"
        "#else\n"
        "int b;\n"
        "#endif\n"
        "int after(void) { return 42; }\n"
    )
    ast, errors = parser.parse_string(code)
    assert ast is not None
    assert errors == []
    names = [
        e.decl.name for e in ast.ext
        if isinstance(e, c_ast.FuncDef) and e.decl
    ]
    assert "after" in names


def test_strip_preprocessor_preserves_line_count_with_continuations():
    """Regression: line-continuation stripping must not join lines, so line
    maps built on the stripped text stay accurate."""
    from corvia.parser import _COMMON_TYPE_STUBS, _strip_preprocessor

    code = (
        "#define M(x) \\\n"
        "  ((x) + 1)\n"
        "int x = 1 + \\\n"
        "2;\n"
        "int y;\n"
    )
    out = _strip_preprocessor(code)
    # _strip_preprocessor prepends the stub block plus one joining newline;
    # everything after must keep the original number of lines.
    expected = _COMMON_TYPE_STUBS.count("\n") + 1 + code.count("\n")
    assert out.count("\n") == expected

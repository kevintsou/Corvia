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


def test_cpp_fatal_error_does_not_parse_partial_stdout(tmp_path):
    """A preprocessor fatal error can still produce partial stdout. Treat the
    translation unit as failed instead of parsing that partial text into an
    incomplete AST/symbol graph."""
    src = tmp_path / "partial.c"
    src.write_text('#include "missing_header.h"\nint after(void) { return 1; }\n', encoding="utf-8")

    parser = CParser(use_cpp=True)
    ast, errors = parser.parse_file(str(src))

    assert ast is None
    assert errors
    assert errors[0].checker_id == "parser"
    assert "missing_header.h" in errors[0].message


def test_cpp_uses_bundled_stdlib_stub(tmp_path):
    src = tmp_path / "uses_stdlib.c"
    src.write_text(
        "#include <stdlib.h>\n"
        "int has_symbol(void) { void *p = malloc(4); free(p); return 0; }\n",
        encoding="utf-8",
    )

    parser = CParser(use_cpp=True)
    ast, errors = parser.parse_file(str(src))

    assert ast is not None
    assert errors == []


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


def test_symbol_fallback_mode_keeps_conditional_bodies(tmp_path):
    from pycparser import c_ast

    src = tmp_path / "conditional.c"
    src.write_text(
        "#if FEATURE\n"
        "int conditional_symbol(void) { return 1; }\n"
        "#endif\n",
        encoding="utf-8",
    )

    parser = CParser(keep_conditional_bodies=True)
    ast, errors = parser.parse_file(str(src))

    assert ast is not None
    assert errors == []
    names = [
        e.decl.name for e in ast.ext
        if isinstance(e, c_ast.FuncDef) and e.decl
    ]
    assert "conditional_symbol" in names


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


def test_strip_asm_recovers_output_operand_write():
    """Extended-asm output operands write through their lvalue; stripping the
    asm must leave a synthesized write so dataflow sees the variable as set."""
    from corvia.parser import _strip_gcc_calls

    code = 'void f(void){ unsigned int id; __asm volatile ("mrs %0, X\\n" : "=r" (id)); }'
    out = _strip_gcc_calls(code)
    assert "__asm" not in out
    assert "(id) = 0;" in out


def test_strip_asm_readwrite_operand_recovered():
    """A read-write constraint ('+') is also an output that must be recovered."""
    from corvia.parser import _strip_gcc_calls

    code = 'void f(int *p){ __asm ("op %0" : "+r" (*p)); }'
    out = _strip_gcc_calls(code)
    assert "= 0;" in out


def test_strip_asm_input_only_produces_no_write():
    """An input-only asm has no output operands: nothing should be synthesized."""
    from corvia.parser import _strip_gcc_calls

    code = 'void f(void){ __asm volatile ("msr X, %0" :: "r" ((unsigned long)1)); }'
    out = _strip_gcc_calls(code)
    assert "__asm" not in out
    assert "= 0;" not in out


def test_strip_asm_no_operands_stripped_entirely():
    """A bare asm with no operand sections at all is removed cleanly."""
    from corvia.parser import _strip_gcc_calls

    code = 'void f(void){ __asm volatile ("isb"); int x = 1; }'
    out = _strip_gcc_calls(code)
    assert "__asm" not in out
    assert "= 0;" not in out
    assert "int x = 1;" in out

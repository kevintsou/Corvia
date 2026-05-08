"""Tests for the MISRA expression checker."""

from corvia.checkers.misra_expr import MisraExprChecker


def test_shift_out_of_range(parse_c):
    code = "int f(int x) { return x << 33; }"
    ast, _ = parse_c(code)
    checker = MisraExprChecker()
    checker.set_file("<test>")
    issues = checker.check(ast)
    assert any("Shift amount" in i.message for i in issues)


def test_sizeof_side_effects(parse_c):
    code = "int f(int x) { return sizeof(x++); }"
    ast, _ = parse_c(code)
    checker = MisraExprChecker()
    checker.set_file("<test>")
    issues = checker.check(ast)
    assert any("sizeof" in i.message.lower() and "side effect" in i.message.lower() for i in issues)


def test_comma_operator(parse_c):
    code = "int f(void) { int a; int b; a = (b = 1, b + 2); return a; }"
    ast, _ = parse_c(code)
    checker = MisraExprChecker()
    checker.set_file("<test>")
    issues = checker.check(ast)
    assert any("comma" in i.message.lower() for i in issues)


def test_clean_expr(parse_c):
    code = "int f(int x) { return (x + 1) * 2; }"
    ast, _ = parse_c(code)
    checker = MisraExprChecker()
    checker.set_file("<test>")
    issues = checker.check(ast)
    assert len(issues) == 0

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


def test_func_call_args_not_comma_operator(parse_c):
    """Function-call argument lists are c_ast.ExprList in pycparser but their
    commas are separators, not the comma operator. They must not be reported
    under MISRA 12.3 (regression test for false positive)."""
    code = """
    void g(int a, int b, int c);
    void f(void) {
        g(1, 2, 3);
    }
    """
    ast, _ = parse_c(code)
    checker = MisraExprChecker()
    checker.set_file("<test>")
    issues = checker.check(ast)
    assert not any("comma operator" in i.message.lower() for i in issues)


def test_real_comma_operator_still_detected(parse_c):
    """A genuine comma operator must still be flagged even when the file also
    contains multi-argument function calls."""
    code = """
    void g(int a, int b);
    int f(void) {
        int a; int b;
        g(1, 2);
        a = (b = 1, b + 2);
        return a;
    }
    """
    ast, _ = parse_c(code)
    checker = MisraExprChecker()
    checker.set_file("<test>")
    issues = checker.check(ast)
    comma_issues = [i for i in issues if "comma operator" in i.message.lower()]
    assert len(comma_issues) == 1

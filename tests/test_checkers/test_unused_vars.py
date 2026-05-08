"""Tests for the unused variables checker."""

from corvia.checkers.unused_vars import UnusedVarsChecker


def test_unused_local_var(parse_c):
    code = "int f(void) { int x = 10; int y = 20; return x; }"
    ast, _ = parse_c(code)
    checker = UnusedVarsChecker()
    checker.set_file("<test>")
    issues = checker.check(ast)
    assert any("Unused variable 'y'" in i.message for i in issues)


def test_unused_param(parse_c):
    code = "int f(int a, int b) { return a; }"
    ast, _ = parse_c(code)
    checker = UnusedVarsChecker()
    checker.set_file("<test>")
    issues = checker.check(ast)
    assert any("Unused parameter 'b'" in i.message for i in issues)


def test_underscore_ignored(parse_c):
    code = "int f(int _unused) { return 0; }"
    ast, _ = parse_c(code)
    checker = UnusedVarsChecker()
    checker.set_file("<test>")
    issues = checker.check(ast)
    assert len(issues) == 0


def test_all_used(parse_c):
    code = "int f(int a, int b) { int c = a + b; return c; }"
    ast, _ = parse_c(code)
    checker = UnusedVarsChecker()
    checker.set_file("<test>")
    issues = checker.check(ast)
    assert len(issues) == 0

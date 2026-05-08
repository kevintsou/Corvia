"""Tests for the dead code checker."""

from covia.checkers.dead_code import DeadCodeChecker


def test_dead_after_return(parse_c):
    code = "int f(int x) { return x; x = x + 1; }"
    ast, _ = parse_c(code)
    checker = DeadCodeChecker()
    checker.set_file("<test>")
    issues = checker.check(ast)
    assert any("Unreachable" in i.message for i in issues)


def test_always_true(parse_c):
    code = "int f(void) { if (1) { return 1; } return 0; }"
    ast, _ = parse_c(code)
    checker = DeadCodeChecker()
    checker.set_file("<test>")
    issues = checker.check(ast)
    assert any("always true" in i.message for i in issues)


def test_always_false(parse_c):
    code = "int f(void) { if (0) { return 1; } return 0; }"
    ast, _ = parse_c(code)
    checker = DeadCodeChecker()
    checker.set_file("<test>")
    issues = checker.check(ast)
    assert any("always false" in i.message for i in issues)


def test_no_dead_code(parse_c):
    code = "int f(int x) { if (x > 0) { return 1; } return 0; }"
    ast, _ = parse_c(code)
    checker = DeadCodeChecker()
    checker.set_file("<test>")
    issues = checker.check(ast)
    dead_issues = [i for i in issues if "Unreachable" in i.message or "always" in i.message]
    assert len(dead_issues) == 0

"""Tests for the dead code checker."""

from corvia.checkers.dead_code import DeadCodeChecker


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


def test_do_while_zero_idiom_whitelisted(parse_c):
    # `do { ... } while (0)` is the standard single-iteration macro idiom and
    # must NOT be reported as always-false / unreachable dead code.
    code = "void f(void) { do { int x = 1; (void)x; } while (0); }"
    ast, _ = parse_c(code)
    checker = DeadCodeChecker()
    checker.set_file("<test>")
    issues = checker.check(ast)
    dead_issues = [i for i in issues if "Unreachable" in i.message or "always" in i.message]
    assert len(dead_issues) == 0


def test_while_zero_still_flagged(parse_c):
    # A genuine `while (0) { ... }` loop, whose body never runs, is still a
    # bug and must still be reported.
    code = "void f(void) { while (0) { int x = 1; (void)x; } }"
    ast, _ = parse_c(code)
    checker = DeadCodeChecker()
    checker.set_file("<test>")
    issues = checker.check(ast)
    assert any("always false" in i.message for i in issues)


def test_unreachable_after_return_still_flagged(parse_c):
    # A second, unreachable return (as found in phison_timer.c) is still caught.
    code = "int f(void) { return 0; return 1; }"
    ast, _ = parse_c(code)
    checker = DeadCodeChecker()
    checker.set_file("<test>")
    issues = checker.check(ast)
    assert any("Unreachable" in i.message for i in issues)

"""Tests for the syntax checker."""

from corvia.checkers.syntax import SyntaxChecker


def test_assignment_in_condition(parse_c):
    code = "int f(int x) { if (x = 5) { return 1; } return 0; }"
    ast, _ = parse_c(code)
    checker = SyntaxChecker()
    checker.set_file("<test>")
    issues = checker.check(ast)
    assert any("Assignment in condition" in i.message for i in issues)
    assert any(i.misra_rule and i.misra_rule.rule_id == "13.4" for i in issues)


def test_missing_braces_if(parse_c):
    code = "int f(int x) { if (x > 0) return 1; return 0; }"
    ast, _ = parse_c(code)
    checker = SyntaxChecker()
    checker.set_file("<test>")
    issues = checker.check(ast)
    assert any("missing braces" in i.message.lower() for i in issues)
    assert any(i.misra_rule and i.misra_rule.rule_id == "15.6" for i in issues)


def test_missing_braces_while(parse_c):
    code = "void f(int x) { while (x > 0) x = x - 1; }"
    ast, _ = parse_c(code)
    checker = SyntaxChecker()
    checker.set_file("<test>")
    issues = checker.check(ast)
    assert any("while" in i.message and "missing braces" in i.message.lower() for i in issues)


def test_clean_code(parse_c):
    code = "int f(int x) { if (x > 0) { return 1; } return 0; }"
    ast, _ = parse_c(code)
    checker = SyntaxChecker()
    checker.set_file("<test>")
    issues = checker.check(ast)
    assert len(issues) == 0

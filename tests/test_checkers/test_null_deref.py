"""Tests for the null pointer dereference checker."""

from corvia.checkers.null_deref import NullDerefChecker


def test_null_deref_basic(parse_c):
    code = "int f(void) { int *p = 0; return *p; }"
    ast, _ = parse_c(code)
    checker = NullDerefChecker()
    checker.set_file("<test>")
    issues = checker.check(ast)
    assert any("Dereference of NULL pointer 'p'" in i.message for i in issues)
    assert any(i.misra_rule and i.misra_rule.rule_id == "1.3" for i in issues)


def test_null_arrow_deref(parse_c):
    code = """
    struct node { int val; struct node *next; };
    int f(void) {
        struct node *n = 0;
        return n->val;
    }
    """
    ast, _ = parse_c(code)
    checker = NullDerefChecker()
    checker.set_file("<test>")
    issues = checker.check(ast)
    assert any("'n'" in i.message and "->'" in i.message for i in issues)


def test_null_reassigned(parse_c):
    code = """
    int f(int *q) {
        int *p = 0;
        p = q;
        return *p;
    }
    """
    ast, _ = parse_c(code)
    checker = NullDerefChecker()
    checker.set_file("<test>")
    issues = checker.check(ast)
    null_issues = [i for i in issues if "NULL" in i.message]
    assert len(null_issues) == 0


def test_no_null_issues(parse_c):
    code = "int f(void) { int x = 10; int *p = &x; return *p; }"
    ast, _ = parse_c(code)
    checker = NullDerefChecker()
    checker.set_file("<test>")
    issues = checker.check(ast)
    assert len(issues) == 0

"""Tests for the MISRA control flow checker."""

from covia.checkers.misra_control import MisraControlChecker


def test_goto_detected(parse_c):
    code = "int f(int x) { if (x) goto end; end: return x; }"
    ast, _ = parse_c(code)
    checker = MisraControlChecker()
    checker.set_file("<test>")
    issues = checker.check(ast)
    assert any("goto" in i.message.lower() for i in issues)


def test_elseif_no_else(parse_c):
    code = """
    int f(int x) {
        if (x > 10) { return 2; }
        else if (x > 0) { return 1; }
        return 0;
    }
    """
    ast, _ = parse_c(code)
    checker = MisraControlChecker()
    checker.set_file("<test>")
    issues = checker.check(ast)
    assert any("else" in i.message.lower() and "terminated" in i.message.lower() for i in issues)


def test_multiple_returns(parse_c):
    code = "int f(int x) { if (x > 0) { return 1; } return 0; }"
    ast, _ = parse_c(code)
    checker = MisraControlChecker()
    checker.set_file("<test>")
    issues = checker.check(ast)
    assert any("return statements" in i.message for i in issues)


def test_single_return_ok(parse_c):
    code = "int f(int x) { int r = 0; if (x > 0) { r = 1; } return r; }"
    ast, _ = parse_c(code)
    checker = MisraControlChecker()
    checker.set_file("<test>")
    issues = checker.check(ast)
    return_issues = [i for i in issues if "return statements" in i.message]
    assert len(return_issues) == 0

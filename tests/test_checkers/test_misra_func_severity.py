"""C1 tiering tests for misra-func Rule 17.4 (all-paths-return).

_all_paths_return is an AST-shape heuristic, not real reachability analysis:
it has no notion of noreturn functions. Emitting a build-breaking ERROR on a
heuristic that false-positives on ordinary firmware idioms (a function ending
in panic()/exit()) is exactly what C1 demotes. The genuine finding is still
surfaced, just at WARNING.
"""

from corvia.checkers.misra_func import MisraFuncChecker
from corvia.models import Severity


def _check(parse_c, code):
    ast, _ = parse_c(code)
    checker = MisraFuncChecker()
    checker.set_file("<test>")
    return checker.check(ast)


def test_missing_return_is_warning_not_error(parse_c):
    # non-void function whose last statement is not a return
    code = "int f(int x) { if (x) { return 1; } }"
    issues = _check(parse_c, code)
    r174 = [
        i for i in issues
        if i.misra_rule is not None and i.misra_rule.rule_id == "17.4"
    ]
    assert r174, "expected a 17.4 finding for the missing return path"
    assert all(i.severity == Severity.WARNING for i in r174)
    assert all(i.severity != Severity.ERROR for i in r174)

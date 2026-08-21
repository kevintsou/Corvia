"""Tests for the FP-rate baseline (corvia.baseline).

These pin the deterministic core: how an analysis result reduces to comparable
counts, and how a fresh run is classified against a stored baseline (regression
vs improvement vs new/dropped checker). The classification is what the CI gate
keys on, so it must be exact.
"""

from __future__ import annotations

from types import SimpleNamespace

from corvia.baseline import (
    compare,
    counts_from_result,
    diff_has_regression,
    format_diff_text,
)
from corvia.models import Severity


def _issue(checker_id, severity=Severity.WARNING):
    return SimpleNamespace(checker_id=checker_id, severity=severity)


def _result(issues, files=("a.c",)):
    return SimpleNamespace(issues=list(issues), files_analyzed=list(files))


# ---------------------------------------------------------------------------
# counts_from_result
# ---------------------------------------------------------------------------

def test_counts_group_by_checker_and_severity():
    res = _result([
        _issue("misra-expr", Severity.INFO),
        _issue("misra-expr", Severity.WARNING),
        _issue("null-deref", Severity.ERROR),
    ])
    c = counts_from_result(res)
    assert c["by_checker"] == {"misra-expr": 2, "null-deref": 1}
    assert c["by_severity"] == {"ERROR": 1, "INFO": 1, "WARNING": 1}
    assert c["total_findings"] == 3
    assert c["parse_errors"] == 0


def test_parse_errors_counted_separately_not_as_findings():
    """A parse error (checker_id 'parser') is a coverage gap, never a checker
    finding — it must not inflate a checker count or the finding total."""
    res = _result([
        _issue("parser", Severity.ERROR),
        _issue("parser", Severity.ERROR),
        _issue("misra-expr", Severity.INFO),
    ])
    c = counts_from_result(res)
    assert c["parse_errors"] == 2
    assert "parser" not in c["by_checker"]
    assert c["by_checker"] == {"misra-expr": 1}
    assert c["total_findings"] == 1


# ---------------------------------------------------------------------------
# compare / classification
# ---------------------------------------------------------------------------

def _counts(by_checker, parse_errors=0):
    return {
        "by_checker": dict(by_checker),
        "by_severity": {},
        "parse_errors": parse_errors,
        "total_findings": sum(by_checker.values()),
    }


def test_identical_counts_no_regression():
    base = _counts({"misra-expr": 3, "null-deref": 1})
    cur = _counts({"misra-expr": 3, "null-deref": 1})
    diff = compare(base, cur)
    assert diff["regressions"] == []
    assert diff["new_checkers"] == []
    assert not diff_has_regression(diff)


def test_rise_in_existing_checker_is_regression():
    diff = compare(_counts({"misra-expr": 3}), _counts({"misra-expr": 5}))
    assert diff["regressions"] == [
        {"checker": "misra-expr", "baseline": 3, "current": 5, "delta": 2}
    ]
    assert diff_has_regression(diff)


def test_brand_new_checker_is_regression():
    diff = compare(_counts({"misra-expr": 1}), _counts({"misra-expr": 1, "buffer-overflow": 2}))
    assert diff["regressions"] == []
    assert diff["new_checkers"] == [
        {"checker": "buffer-overflow", "baseline": 0, "current": 2, "delta": 2}
    ]
    assert diff_has_regression(diff)


def test_fall_is_improvement_not_regression():
    diff = compare(_counts({"misra-expr": 5}), _counts({"misra-expr": 2}))
    assert diff["improvements"] == [
        {"checker": "misra-expr", "baseline": 5, "current": 2, "delta": -3}
    ]
    assert not diff_has_regression(diff)


def test_drop_to_zero_is_improvement():
    diff = compare(_counts({"misra-expr": 2, "null-deref": 1}), _counts({"misra-expr": 2}))
    assert diff["dropped_checkers"] == [
        {"checker": "null-deref", "baseline": 1, "current": 0, "delta": -1}
    ]
    assert not diff_has_regression(diff)


def test_parse_error_rise_is_not_a_checker_regression():
    """More parse errors = new coverage gaps; surfaced via delta but must not
    by itself fail the gate (checker counts are unchanged)."""
    diff = compare(_counts({"misra-expr": 1}, parse_errors=0),
                   _counts({"misra-expr": 1}, parse_errors=3))
    assert diff["parse_error_delta"] == 3
    assert not diff_has_regression(diff)


def test_mixed_regression_and_improvement_fails_on_regression():
    diff = compare(_counts({"a": 5, "b": 2}), _counts({"a": 2, "b": 4}))
    # a fell (improvement), b rose (regression) -> overall a regression
    assert any(e["checker"] == "b" for e in diff["regressions"])
    assert any(e["checker"] == "a" for e in diff["improvements"])
    assert diff_has_regression(diff)


def test_format_diff_text_mentions_regressions_and_totals():
    diff = compare(_counts({"misra-expr": 1}), _counts({"misra-expr": 3}))
    text = format_diff_text(diff)
    assert "REGRESSIONS" in text
    assert "misra-expr: 1 -> 3" in text
    assert "totals" in text

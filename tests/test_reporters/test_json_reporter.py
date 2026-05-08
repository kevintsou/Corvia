"""Tests for the JSON reporter."""

import json

from covia.models import AnalysisResult, Issue, MisraCategory, MisraRule, Severity
from covia.reporters.json_reporter import JsonReporter


def _make_result():
    return AnalysisResult(
        files_analyzed=["test.c"],
        issues=[
            Issue(
                checker_id="syntax",
                severity=Severity.WARNING,
                message="Assignment in condition",
                file="test.c",
                line=5,
                column=8,
                misra_rule=MisraRule("13.4", MisraCategory.ADVISORY, "The result of an assignment operator should not be used"),
            ),
            Issue(
                checker_id="null-deref",
                severity=Severity.ERROR,
                message="Dereference of NULL pointer 'p'",
                file="test.c",
                line=10,
                column=5,
                misra_rule=MisraRule("1.3", MisraCategory.REQUIRED, "No undefined behaviour"),
            ),
        ],
    )


def test_json_output():
    result = _make_result()
    reporter = JsonReporter()
    output = reporter.generate(result)
    data = json.loads(output)
    assert data["summary"]["total_files"] == 1
    assert data["summary"]["total_issues"] == 2
    assert len(data["issues"]) == 2
    assert data["issues"][0]["misra_rule"]["rule_id"] == "13.4"


def test_json_misra_summary():
    result = _make_result()
    reporter = JsonReporter()
    output = reporter.generate(result)
    data = json.loads(output)
    assert "13.4" in data["misra_summary"]
    assert data["misra_summary"]["13.4"]["violations"] == 1

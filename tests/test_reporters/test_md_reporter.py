"""Tests for the Markdown reporter."""

from covia.models import AnalysisResult, Issue, MisraCategory, MisraRule, Severity
from covia.reporters.md_reporter import MdReporter


def test_md_output():
    result = AnalysisResult(
        files_analyzed=["test.c"],
        issues=[
            Issue(
                checker_id="dead-code",
                severity=Severity.WARNING,
                message="Unreachable code",
                file="test.c",
                line=5,
                column=1,
                misra_rule=MisraRule("2.1", MisraCategory.REQUIRED, "No unreachable code"),
            ),
        ],
    )
    reporter = MdReporter()
    output = reporter.generate(result)
    assert "# COVIA Analysis Report" in output
    assert "MISRA C:2012 Rule Summary" in output
    assert "Rule 2.1" in output or "2.1" in output
    assert "Unreachable code" in output


def test_md_empty():
    result = AnalysisResult(files_analyzed=["test.c"], issues=[])
    reporter = MdReporter()
    output = reporter.generate(result)
    assert "Total" in output
    assert "0" in output

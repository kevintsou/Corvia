"""Tests for LSP Issue->Diagnostic conversion."""

from __future__ import annotations

from corvia.lsp.converter import (
    LSP_ERROR,
    LSP_INFO,
    LSP_WARNING,
    file_uri_to_path,
    issue_to_diagnostic,
    issues_by_file,
    path_to_file_uri,
)
from corvia.models import Issue, MisraCategory, MisraRule, Severity


def test_basic_conversion():
    issue = Issue(
        checker_id="null-deref",
        severity=Severity.ERROR,
        message="Dereference of NULL pointer 'p'",
        file="/abs/x.c",
        line=12,
        column=5,
    )
    d = issue_to_diagnostic(issue)
    assert d["severity"] == LSP_ERROR
    assert d["range"]["start"]["line"] == 11
    assert d["range"]["start"]["character"] == 4
    assert d["source"] == "corvia"
    assert d["code"] == "null-deref"


def test_severity_mapping():
    base = dict(checker_id="x", message="m", file="/a.c", line=1, column=1)
    assert issue_to_diagnostic(Issue(severity=Severity.ERROR, **base))["severity"] == LSP_ERROR
    assert issue_to_diagnostic(Issue(severity=Severity.WARNING, **base))["severity"] == LSP_WARNING
    assert issue_to_diagnostic(Issue(severity=Severity.INFO, **base))["severity"] == LSP_INFO


def test_misra_code_format():
    rule = MisraRule("11.3", MisraCategory.REQUIRED, "desc")
    issue = Issue(
        checker_id="misra-pointer-conv",
        severity=Severity.WARNING,
        message="m",
        file="/a.c",
        line=1,
        column=1,
        misra_rule=rule,
    )
    d = issue_to_diagnostic(issue)
    assert d["code"] == "misra-pointer-conv:MISRA-11.3"
    assert "codeDescription" in d


def test_grouping_by_file():
    issues = [
        Issue(checker_id="x", severity=Severity.WARNING, message="a", file="/a.c", line=1),
        Issue(checker_id="x", severity=Severity.WARNING, message="b", file="/b.c", line=2),
        Issue(checker_id="x", severity=Severity.WARNING, message="c", file="/a.c", line=3),
    ]
    grouped = issues_by_file(issues)
    assert set(grouped) == {"/a.c", "/b.c"}
    assert len(grouped["/a.c"]) == 2


def test_uri_path_roundtrip():
    assert file_uri_to_path("file:///abs/path.c") == "/abs/path.c"
    assert path_to_file_uri("/abs/path.c") == "file:///abs/path.c"
    assert path_to_file_uri("file:///already.c") == "file:///already.c"


def test_zero_line_clamped():
    issue = Issue(
        checker_id="x",
        severity=Severity.WARNING,
        message="m",
        file="/a.c",
        line=0,
        column=0,
    )
    d = issue_to_diagnostic(issue)
    assert d["range"]["start"]["line"] == 0
    assert d["range"]["start"]["character"] == 0

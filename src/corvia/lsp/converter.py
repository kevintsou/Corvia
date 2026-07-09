"""Conversion helpers between CORVIA Issue and LSP Diagnostic shapes.

Returned values are plain dicts matching the LSP Diagnostic JSON layout
(see https://microsoft.github.io/language-server-protocol/specifications/).
The server module wraps these in lsprotocol types when sending — keeping
this module pygls-free makes it trivial to unit-test.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import url2pathname

from corvia.models import Issue, Severity


# LSP DiagnosticSeverity numeric values
LSP_ERROR = 1
LSP_WARNING = 2
LSP_INFO = 3
LSP_HINT = 4


_SEVERITY_TO_LSP = {
    Severity.ERROR: LSP_ERROR,
    Severity.WARNING: LSP_WARNING,
    Severity.INFO: LSP_INFO,
}


def issue_to_diagnostic(issue: Issue) -> dict[str, Any]:
    """Convert a CORVIA Issue to an LSP Diagnostic dict."""
    line = max(0, issue.line - 1)  # LSP is 0-indexed
    col = max(0, issue.column - 1) if issue.column else 0
    end_line = max(0, (issue.end_line or issue.line) - 1)

    code = issue.checker_id
    if issue.misra_rule:
        code = f"{issue.checker_id}:MISRA-{issue.misra_rule.rule_id}"

    diag: dict[str, Any] = {
        "range": {
            "start": {"line": line, "character": col},
            "end": {"line": end_line, "character": col + 1},
        },
        "severity": _SEVERITY_TO_LSP.get(issue.severity, LSP_INFO),
        "code": code,
        "source": "corvia",
        "message": issue.message,
    }

    if issue.misra_rule:
        diag["codeDescription"] = {
            "href": f"https://www.misra.org.uk/rules/rule_{issue.misra_rule.rule_id.replace('.', '_')}",
        }

    return diag


def issues_by_file(issues: list[Issue]) -> dict[str, list[Issue]]:
    grouped: dict[str, list[Issue]] = {}
    for i in issues:
        grouped.setdefault(i.file, []).append(i)
    return grouped


def file_uri_to_path(uri: str) -> str:
    if uri.startswith("file://"):
        p = urlparse(uri)
        # Preserve the UNC host (file://server/share/x.c -> \\server\share\x.c)
        return url2pathname(f"//{p.netloc}{p.path}" if p.netloc else p.path)
    return uri


def path_to_file_uri(path: str) -> str:
    if path.startswith("file://"):
        return path
    # as_uri() raises ValueError on relative paths, so resolve first.
    return Path(path).resolve().as_uri()

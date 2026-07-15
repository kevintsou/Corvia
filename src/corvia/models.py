"""Core data models for CORVIA analysis results."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import Optional


class Severity(IntEnum):
    INFO = 1
    WARNING = 2
    ERROR = 3


class MisraCategory(Enum):
    MANDATORY = "Mandatory"
    REQUIRED = "Required"
    ADVISORY = "Advisory"


@dataclass(frozen=True)
class MisraRule:
    rule_id: str
    category: MisraCategory
    description: str

    def __str__(self) -> str:
        return f"MISRA C:2012 Rule {self.rule_id} {self.category.value}"


@dataclass
class Issue:
    checker_id: str
    severity: Severity
    message: str
    file: str
    line: int
    column: int = 0
    end_line: Optional[int] = None
    context: Optional[str] = None
    misra_rule: Optional[MisraRule] = None

    @staticmethod
    def _normalize_file(file: str) -> str:
        """Present a clean, forward-slash path in serialized output.

        Preprocessor ``#line`` markers and path joins can leave doubled or
        mixed separators (e.g. ``common\\\\source\\\\x.c``); collapse them so
        consumers of the JSON/HTML/markdown report don't each have to. Purely
        cosmetic — internal path comparisons resolve paths independently.
        """
        if not file or "\\" not in file:
            return file
        # Collapse doubled backslashes, then switch to forward slashes.
        while "\\\\" in file:
            file = file.replace("\\\\", "\\")
        return file.replace("\\", "/")

    def to_dict(self) -> dict:
        d = {
            "checker_id": self.checker_id,
            "severity": self.severity.name,
            "message": self.message,
            "file": self._normalize_file(self.file),
            "line": self.line,
            "column": self.column,
        }
        if self.end_line is not None:
            d["end_line"] = self.end_line
        if self.context is not None:
            d["context"] = self.context
        if self.misra_rule is not None:
            d["misra_rule"] = {
                "rule_id": self.misra_rule.rule_id,
                "category": self.misra_rule.category.value,
                "description": self.misra_rule.description,
            }
        return d

    def format_location(self) -> str:
        return f"{self.file}:{self.line}:{self.column}"

    def format_display(self) -> str:
        parts = [
            self.format_location(),
            f"{self.severity.name.lower()}[{self.checker_id}]",
        ]
        if self.misra_rule:
            parts.append(f"({self.misra_rule})")
        parts.append(self.message)
        return ": ".join(parts)


@dataclass
class AnalysisResult:
    files_analyzed: list[str] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)

    @property
    def summary(self) -> dict:
        counts = {s.name: 0 for s in Severity}
        for issue in self.issues:
            counts[issue.severity.name] += 1
        return {
            "total_files": len(self.files_analyzed),
            "total_issues": len(self.issues),
            **counts,
        }

    @property
    def misra_summary(self) -> dict[str, dict]:
        rules: dict[str, dict] = {}
        for issue in self.issues:
            if issue.misra_rule:
                rid = issue.misra_rule.rule_id
                if rid not in rules:
                    rules[rid] = {
                        "rule_id": rid,
                        "category": issue.misra_rule.category.value,
                        "description": issue.misra_rule.description,
                        "violations": 0,
                    }
                rules[rid]["violations"] += 1
        return dict(sorted(rules.items()))

    def to_dict(self) -> dict:
        return {
            "summary": self.summary,
            "misra_summary": self.misra_summary,
            "files_analyzed": self.files_analyzed,
            "issues": [i.to_dict() for i in self.issues],
        }

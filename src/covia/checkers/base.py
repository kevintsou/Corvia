"""Base checker abstract class for COVIA static analysis."""

from __future__ import annotations

from typing import ClassVar, Optional

from pycparser import c_ast

from covia.models import Issue, MisraRule, Severity


class BaseChecker(c_ast.NodeVisitor):
    """Base class for all COVIA checkers.

    Subclasses implement visit_XXX methods for AST node types they care about.
    pycparser's NodeVisitor dispatches to visit_XXX based on node class name.
    IMPORTANT: visit_XXX methods must call self.generic_visit(node) to continue
    traversal into child nodes.
    """

    checker_id: ClassVar[str]
    description: ClassVar[str]
    default_severity: ClassVar[Severity] = Severity.WARNING
    misra_rules: ClassVar[list[MisraRule]] = []

    def __init__(self) -> None:
        self._issues: list[Issue] = []
        self._current_file: str = ""

    def set_file(self, filename: str) -> None:
        self._current_file = filename

    def report(
        self,
        node: c_ast.Node,
        message: str,
        severity: Optional[Severity] = None,
        misra_rule: Optional[MisraRule] = None,
    ) -> None:
        line = 0
        col = 0
        if node.coord:
            line = node.coord.line
            col = node.coord.column or 0

        self._issues.append(
            Issue(
                checker_id=self.checker_id,
                severity=severity or self.default_severity,
                message=message,
                file=self._current_file,
                line=line,
                column=col,
                misra_rule=misra_rule,
            )
        )

    def check(self, ast: c_ast.FileAST) -> list[Issue]:
        self._issues = []
        self.visit(ast)
        return list(self._issues)

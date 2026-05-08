"""MISRA C:2012 Section 19: Overlapping storage.

Implements Rule 19.2 (the union keyword should not be used) as an
advisory. Rule 19.1 (object shall not be assigned to itself or to an
overlapping object) requires runtime / aliasing analysis beyond the AST
and is not implemented here.
"""

from __future__ import annotations

from pycparser import c_ast

from corvia.checkers.base import BaseChecker
from corvia.models import MisraCategory, MisraRule, Severity
from corvia.registry import CheckerRegistry


RULE_19_2 = MisraRule(
    "19.2", MisraCategory.ADVISORY,
    "The union keyword should not be used",
)


class MisraUnionsChecker(BaseChecker):
    checker_id = "misra-unions"
    description = "MISRA C:2012 Rule 19.2: union usage advisory"
    default_severity = Severity.INFO
    misra_rules = [RULE_19_2]

    def __init__(self) -> None:
        super().__init__()
        self._reported_lines: set[int] = set()

    def check(self, ast: c_ast.FileAST):
        self._issues = []
        self._reported_lines = set()
        self.visit(ast)
        return list(self._issues)

    def visit_Union(self, node: c_ast.Union) -> None:
        line = node.coord.line if node.coord else 0
        if line not in self._reported_lines:
            self._reported_lines.add(line)
            self.report(
                node,
                f"Use of union '{node.name or '<anon>'}' is discouraged",
                Severity.INFO,
                RULE_19_2,
            )
        self.generic_visit(node)


CheckerRegistry.register(MisraUnionsChecker)

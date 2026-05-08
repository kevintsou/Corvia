"""Syntax checker - suspicious patterns that parse but are likely mistakes."""

from __future__ import annotations

from pycparser import c_ast

from corvia.checkers.base import BaseChecker
from corvia.models import MisraCategory, MisraRule, Severity
from corvia.registry import CheckerRegistry

RULE_13_4 = MisraRule("13.4", MisraCategory.ADVISORY, "The result of an assignment operator should not be used")
RULE_15_6 = MisraRule("15.6", MisraCategory.REQUIRED, "The body of an iteration-statement or a selection-statement shall be a compound-statement")


class SyntaxChecker(BaseChecker):
    checker_id = "syntax"
    description = "Detects suspicious syntax patterns (assignment in conditions, missing braces)"
    default_severity = Severity.WARNING
    misra_rules = [RULE_13_4, RULE_15_6]

    def visit_If(self, node: c_ast.If) -> None:
        self._check_assignment_in_condition(node.cond, node)
        self._check_compound_body(node.iftrue, node, "if")
        if node.iffalse and not isinstance(node.iffalse, (c_ast.Compound, c_ast.If)):
            self.report(
                node,
                "else branch is not a compound statement (missing braces)",
                Severity.WARNING,
                RULE_15_6,
            )
        self.generic_visit(node)

    def visit_While(self, node: c_ast.While) -> None:
        self._check_assignment_in_condition(node.cond, node)
        self._check_compound_body(node.stmt, node, "while")
        self.generic_visit(node)

    def visit_DoWhile(self, node: c_ast.DoWhile) -> None:
        self._check_assignment_in_condition(node.cond, node)
        self._check_compound_body(node.stmt, node, "do-while")
        self.generic_visit(node)

    def visit_For(self, node: c_ast.For) -> None:
        self._check_compound_body(node.stmt, node, "for")
        self.generic_visit(node)

    def _check_assignment_in_condition(self, cond: c_ast.Node, parent: c_ast.Node) -> None:
        if cond is None:
            return
        if isinstance(cond, c_ast.Assignment):
            self.report(
                parent,
                f"Assignment in condition (did you mean '==' instead of '{cond.op}'?)",
                Severity.WARNING,
                RULE_13_4,
            )

    def _check_compound_body(self, body: c_ast.Node, parent: c_ast.Node, stmt_type: str) -> None:
        if body is None:
            return
        if not isinstance(body, c_ast.Compound):
            self.report(
                parent,
                f"Body of '{stmt_type}' statement is not a compound statement (missing braces)",
                Severity.WARNING,
                RULE_15_6,
            )


CheckerRegistry.register(SyntaxChecker)

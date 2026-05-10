"""Dead code checker - unreachable statements and always-true/false conditions."""

from __future__ import annotations

from pycparser import c_ast

from corvia.checkers.base import BaseChecker
from corvia.models import MisraCategory, MisraRule, Severity
from corvia.registry import CheckerRegistry

RULE_2_1 = MisraRule("2.1", MisraCategory.REQUIRED, "A project shall not contain unreachable code")
RULE_14_3 = MisraRule("14.3", MisraCategory.REQUIRED, "Controlling expressions shall not be invariant")


class DeadCodeChecker(BaseChecker):
    checker_id = "dead-code"
    description = "Detects unreachable code after return/break/continue/goto and invariant conditions"
    default_severity = Severity.WARNING
    misra_rules = [RULE_2_1, RULE_14_3]

    def visit_Compound(self, node: c_ast.Compound) -> None:
        if node.block_items is None:
            return

        terminator_seen = False
        for item in node.block_items:
            if terminator_seen:
                self.report(
                    item,
                    "Unreachable code after return/break/continue/goto",
                    Severity.WARNING,
                    RULE_2_1,
                )
                break

            if isinstance(item, (c_ast.Return, c_ast.Break, c_ast.Continue, c_ast.Goto)):
                terminator_seen = True

        self.generic_visit(node)

    def visit_Assignment(self, node: c_ast.Assignment) -> None:
        if node.op != "=":
            rhs_val = self._eval_constant_extended(node.rvalue)
            if rhs_val == 0:
                self.report(
                    node,
                    f"Compound assignment '{node.op}' with zero value is a no-op",
                    Severity.WARNING,
                    RULE_2_1,
                )
            elif self._is_all_ones(node.rvalue):
                if node.op in ("|=", "&=", "^="):
                    self.report(
                        node,
                        f"Compound assignment '{node.op}' with bitwise complement of zero is a no-op",
                        Severity.WARNING,
                        RULE_2_1,
                    )
        self.generic_visit(node)

    def visit_If(self, node: c_ast.If) -> None:
        self._check_invariant_condition(node.cond, node, "if")
        self.generic_visit(node)

    def visit_While(self, node: c_ast.While) -> None:
        self._check_invariant_condition(node.cond, node, "while")
        self.generic_visit(node)

    def visit_DoWhile(self, node: c_ast.DoWhile) -> None:
        self._check_invariant_condition(node.cond, node, "do-while")
        self.generic_visit(node)

    def visit_For(self, node: c_ast.For) -> None:
        if node.cond:
            self._check_invariant_condition(node.cond, node, "for")
        self.generic_visit(node)

    def _check_invariant_condition(self, cond: c_ast.Node, parent: c_ast.Node, stmt_type: str) -> None:
        if cond is None:
            return

        val = self._eval_constant(cond)
        if val is None:
            return

        if val:
            self.report(
                parent,
                f"Condition in '{stmt_type}' statement is always true",
                Severity.WARNING,
                RULE_14_3,
            )
        else:
            self.report(
                parent,
                f"Condition in '{stmt_type}' statement is always false",
                Severity.WARNING,
                RULE_14_3,
            )

    def _eval_constant(self, node: c_ast.Node) -> object:
        if isinstance(node, c_ast.Constant):
            if node.type == "int":
                try:
                    return int(node.value, 0)
                except ValueError:
                    return None
        if isinstance(node, c_ast.UnaryOp) and node.op == "!":
            inner = self._eval_constant(node.expr)
            if inner is not None:
                return not inner
        return None

    def _eval_constant_extended(self, node: c_ast.Node) -> object:
        if isinstance(node, c_ast.Constant):
            raw = node.value.rstrip("uUlL")
            try:
                return int(raw, 0)
            except ValueError:
                return None
        if isinstance(node, c_ast.UnaryOp) and node.op == "!":
            inner = self._eval_constant_extended(node.expr)
            if inner is not None:
                return int(not inner)
        return None

    def _is_all_ones(self, node: c_ast.Node) -> bool:
        return (
            isinstance(node, c_ast.UnaryOp)
            and node.op == "~"
            and self._eval_constant_extended(node.expr) == 0
        )


CheckerRegistry.register(DeadCodeChecker)

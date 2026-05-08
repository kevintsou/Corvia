"""MISRA C:2012 expression rules (Rules 12.1-12.5, 13.1-13.6)."""

from __future__ import annotations

from pycparser import c_ast

from covia.checkers.base import BaseChecker
from covia.models import MisraCategory, MisraRule, Severity
from covia.registry import CheckerRegistry

RULE_12_1 = MisraRule("12.1", MisraCategory.ADVISORY, "The precedence of operators within expressions should be made explicit")
RULE_12_2 = MisraRule("12.2", MisraCategory.REQUIRED, "The right hand operand of a shift operator shall lie in the range zero to one less than the width in bits of the essential type of the left hand operand")
RULE_12_3 = MisraRule("12.3", MisraCategory.ADVISORY, "The comma operator should not be used")
RULE_12_4 = MisraRule("12.4", MisraCategory.ADVISORY, "Evaluation of constant expressions should not lead to unsigned integer wrap-around")
RULE_13_1 = MisraRule("13.1", MisraCategory.REQUIRED, "Initializer lists shall not contain persistent side effects")
RULE_13_2 = MisraRule("13.2", MisraCategory.REQUIRED, "The value of an expression and its persistent side effects shall be the same under all permitted evaluation orders")
RULE_13_3 = MisraRule("13.3", MisraCategory.ADVISORY, "A full expression containing an increment or decrement operator should have no other potential side effects")
RULE_13_4 = MisraRule("13.4", MisraCategory.ADVISORY, "The result of an assignment operator should not be used")
RULE_13_5 = MisraRule("13.5", MisraCategory.REQUIRED, "The right hand operand of a logical && or || operator shall not contain persistent side effects")
RULE_13_6 = MisraRule("13.6", MisraCategory.MANDATORY, "The operand of the sizeof operator shall not contain any expression which has potential side effects")

_LOW_PRECEDENCE_OPS = {"+", "-", "*", "/", "%", "<<", ">>", "&", "|", "^"}
_COMPARISON_OPS = {"<", ">", "<=", ">=", "==", "!="}
_LOGICAL_OPS = {"&&", "||"}


class MisraExprChecker(BaseChecker):
    checker_id = "misra-expr"
    description = "MISRA C:2012 Rules 12.1-12.5, 13.1-13.6: expression and side effect rules"
    default_severity = Severity.WARNING
    misra_rules = [RULE_12_1, RULE_12_2, RULE_12_3, RULE_12_4,
                   RULE_13_1, RULE_13_2, RULE_13_3, RULE_13_4, RULE_13_5, RULE_13_6]

    def visit_BinaryOp(self, node: c_ast.BinaryOp) -> None:
        if node.op in _LOW_PRECEDENCE_OPS:
            if isinstance(node.left, c_ast.BinaryOp) and node.left.op in _LOW_PRECEDENCE_OPS:
                if self._needs_parens(node.op, node.left.op):
                    self.report(
                        node,
                        f"Operator precedence may be unclear: '{node.left.op}' within '{node.op}' (consider explicit parentheses)",
                        Severity.INFO,
                        RULE_12_1,
                    )
            if isinstance(node.right, c_ast.BinaryOp) and node.right.op in _LOW_PRECEDENCE_OPS:
                if self._needs_parens(node.op, node.right.op):
                    self.report(
                        node,
                        f"Operator precedence may be unclear: '{node.right.op}' within '{node.op}' (consider explicit parentheses)",
                        Severity.INFO,
                        RULE_12_1,
                    )

        if node.op in ("<<", ">>"):
            if isinstance(node.right, c_ast.Constant) and node.right.type == "int":
                try:
                    shift = int(node.right.value, 0)
                    if shift < 0 or shift >= 32:
                        self.report(
                            node,
                            f"Shift amount {shift} is out of range [0, 31] for typical int type",
                            Severity.WARNING,
                            RULE_12_2,
                        )
                except ValueError:
                    pass

        if node.op in _LOGICAL_OPS:
            if self._has_side_effects(node.right):
                self.report(
                    node,
                    f"Right operand of '{node.op}' contains side effects",
                    Severity.WARNING,
                    RULE_13_5,
                )

        if node.op == ",":
            self.report(node, "Use of comma operator", Severity.INFO, RULE_12_3)

        self.generic_visit(node)

    def visit_ExprList(self, node: c_ast.ExprList) -> None:
        if node.exprs and len(node.exprs) > 1:
            self.report(node, "Use of comma operator", Severity.INFO, RULE_12_3)
        self.generic_visit(node)

    def visit_UnaryOp(self, node: c_ast.UnaryOp) -> None:
        if node.op == "sizeof":
            if self._has_side_effects(node.expr):
                self.report(
                    node,
                    "Operand of sizeof contains side effects",
                    Severity.ERROR,
                    RULE_13_6,
                )

        if node.op in ("++", "--", "p++", "p--"):
            parent_expr = self._find_enclosing_expr(node)
            if parent_expr and self._count_side_effects(parent_expr) > 1:
                self.report(
                    node,
                    f"Expression with '{node.op}' has other potential side effects",
                    Severity.INFO,
                    RULE_13_3,
                )

        self.generic_visit(node)

    def visit_InitList(self, node: c_ast.InitList) -> None:
        if node.exprs:
            for expr in node.exprs:
                if self._has_side_effects(expr):
                    self.report(
                        expr,
                        "Initializer list contains expression with side effects",
                        Severity.WARNING,
                        RULE_13_1,
                    )
        self.generic_visit(node)

    def _has_side_effects(self, node: c_ast.Node) -> bool:
        if node is None:
            return False
        if isinstance(node, c_ast.FuncCall):
            return True
        if isinstance(node, c_ast.UnaryOp) and node.op in ("++", "--", "p++", "p--"):
            return True
        if isinstance(node, c_ast.Assignment):
            return True
        for _, child in node.children():
            if self._has_side_effects(child):
                return True
        return False

    def _count_side_effects(self, node: c_ast.Node) -> int:
        if node is None:
            return 0
        count = 0
        if isinstance(node, c_ast.FuncCall):
            count += 1
        if isinstance(node, c_ast.UnaryOp) and node.op in ("++", "--", "p++", "p--"):
            count += 1
        if isinstance(node, c_ast.Assignment):
            count += 1
        for _, child in node.children():
            count += self._count_side_effects(child)
        return count

    def _needs_parens(self, outer_op: str, inner_op: str) -> bool:
        bitwise = {"&", "|", "^"}
        arithmetic = {"+", "-", "*", "/", "%"}
        shift = {"<<", ">>"}
        if outer_op in bitwise and inner_op in arithmetic:
            return False
        if outer_op in arithmetic and inner_op in bitwise:
            return True
        if (outer_op in bitwise and inner_op in bitwise and outer_op != inner_op):
            return True
        if (outer_op in shift and inner_op in arithmetic) or (outer_op in arithmetic and inner_op in shift):
            return True
        return False

    def _find_enclosing_expr(self, node: c_ast.Node) -> c_ast.Node | None:
        return None


CheckerRegistry.register(MisraExprChecker)

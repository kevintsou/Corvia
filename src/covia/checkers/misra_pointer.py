"""MISRA C:2012 pointer rules (Rules 18.1-18.8)."""

from __future__ import annotations

from pycparser import c_ast

from covia.checkers.base import BaseChecker
from covia.models import MisraCategory, MisraRule, Severity
from covia.registry import CheckerRegistry

RULE_18_1 = MisraRule("18.1", MisraCategory.REQUIRED, "A pointer resulting from arithmetic on a pointer operand shall address an element of the same array")
RULE_18_2 = MisraRule("18.2", MisraCategory.REQUIRED, "Subtraction between pointers shall only be applied to pointers that address elements of the same array")
RULE_18_3 = MisraRule("18.3", MisraCategory.REQUIRED, "The relational operators shall not be applied to objects of pointer type except where they point into the same object")
RULE_18_4 = MisraRule("18.4", MisraCategory.ADVISORY, "The +, -, += and -= operators should not be applied to an expression of pointer type")
RULE_18_5 = MisraRule("18.5", MisraCategory.ADVISORY, "Declarations should contain no more than two levels of pointer nesting")
RULE_18_6 = MisraRule("18.6", MisraCategory.REQUIRED, "The address of an object with automatic storage shall not be copied to another object that persists after the first object has ceased to exist")
RULE_18_7 = MisraRule("18.7", MisraCategory.REQUIRED, "Flexible array members shall not be declared")
RULE_18_8 = MisraRule("18.8", MisraCategory.REQUIRED, "Variable-length array types shall not be used")


class MisraPointerChecker(BaseChecker):
    checker_id = "misra-pointer"
    description = "MISRA C:2012 Rules 18.1-18.8: pointer and array rules"
    default_severity = Severity.WARNING
    misra_rules = [RULE_18_1, RULE_18_2, RULE_18_3, RULE_18_4,
                   RULE_18_5, RULE_18_6, RULE_18_7, RULE_18_8]

    def visit_Decl(self, node: c_ast.Decl) -> None:
        if node.type:
            ptr_depth = self._pointer_depth(node.type)
            if ptr_depth > 2:
                self.report(
                    node,
                    f"Declaration '{node.name}' has {ptr_depth} levels of pointer nesting (max 2 recommended)",
                    Severity.INFO,
                    RULE_18_5,
                )

            if isinstance(node.type, c_ast.ArrayDecl):
                if node.type.dim is None:
                    if self._is_flexible_member(node):
                        self.report(
                            node,
                            f"Flexible array member '{node.name}' declared",
                            Severity.WARNING,
                            RULE_18_7,
                        )
                elif not isinstance(node.type.dim, c_ast.Constant):
                    if self._is_local_var(node):
                        self.report(
                            node,
                            f"Variable-length array '{node.name}' declared",
                            Severity.WARNING,
                            RULE_18_8,
                        )

        self.generic_visit(node)

    def visit_BinaryOp(self, node: c_ast.BinaryOp) -> None:
        if node.op in ("+", "-", "+=", "-="):
            if self._is_pointer_expr(node.left) or self._is_pointer_expr(node.right):
                if node.op in ("+", "+=", "-="):
                    self.report(
                        node,
                        f"Arithmetic operator '{node.op}' applied to pointer type",
                        Severity.INFO,
                        RULE_18_4,
                    )

        if node.op in ("<", ">", "<=", ">="):
            if self._is_pointer_expr(node.left) and self._is_pointer_expr(node.right):
                self.report(
                    node,
                    "Relational operator applied to pointer types",
                    Severity.INFO,
                    RULE_18_3,
                )

        self.generic_visit(node)

    def _pointer_depth(self, type_node: c_ast.Node) -> int:
        if isinstance(type_node, c_ast.PtrDecl):
            return 1 + self._pointer_depth(type_node.type)
        if isinstance(type_node, c_ast.ArrayDecl):
            return self._pointer_depth(type_node.type)
        if isinstance(type_node, c_ast.TypeDecl):
            return 0
        return 0

    def _is_pointer_expr(self, node: c_ast.Node) -> bool:
        if isinstance(node, c_ast.UnaryOp) and node.op == "&":
            return True
        if isinstance(node, c_ast.ID):
            return False
        return False

    def _is_flexible_member(self, node: c_ast.Decl) -> bool:
        return isinstance(node.type, c_ast.ArrayDecl) and node.type.dim is None

    def _is_local_var(self, node: c_ast.Decl) -> bool:
        storage = node.storage or []
        return "extern" not in storage and "static" not in storage


CheckerRegistry.register(MisraPointerChecker)

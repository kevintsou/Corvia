"""MISRA C:2012 declaration and definition rules (Rules 8.1-8.14)."""

from __future__ import annotations

from pycparser import c_ast

from corvia.checkers.base import BaseChecker, parse_int_literal
from corvia.models import MisraCategory, MisraRule, Severity
from corvia.registry import CheckerRegistry

RULE_8_1 = MisraRule("8.1", MisraCategory.REQUIRED, "Types shall be explicitly stated")
RULE_8_2 = MisraRule("8.2", MisraCategory.REQUIRED, "Function types shall be in prototype form with named parameters")
RULE_8_4 = MisraRule("8.4", MisraCategory.REQUIRED, "A compatible declaration shall be visible when an object or function with external linkage is defined")
RULE_8_5 = MisraRule("8.5", MisraCategory.REQUIRED, "An external object or function shall be declared once in one and only one file")
RULE_8_6 = MisraRule("8.6", MisraCategory.REQUIRED, "An identifier with external linkage shall have exactly one external definition")
RULE_8_7 = MisraRule("8.7", MisraCategory.ADVISORY, "Functions and objects should not be defined with external linkage if they are referenced in only one translation unit")
RULE_8_8 = MisraRule("8.8", MisraCategory.REQUIRED, "The static storage class specifier shall be used in all declarations of objects and functions that have internal linkage")
RULE_8_9 = MisraRule("8.9", MisraCategory.ADVISORY, "An object should be defined at block scope if its identifier only appears in a single function")
RULE_8_10 = MisraRule("8.10", MisraCategory.REQUIRED, "An inline function shall be declared with the static storage class")
RULE_8_11 = MisraRule("8.11", MisraCategory.ADVISORY, "When an array with external linkage is declared, its size should be explicitly stated")
RULE_8_12 = MisraRule("8.12", MisraCategory.REQUIRED, "Within an enumerator list, the value of an implicitly-specified enumeration constant shall be unique")
RULE_8_13 = MisraRule("8.13", MisraCategory.ADVISORY, "A pointer should point to a const-qualified type whenever possible")
RULE_8_14 = MisraRule("8.14", MisraCategory.REQUIRED, "The restrict type qualifier shall not be used")


class MisraDeclChecker(BaseChecker):
    checker_id = "misra-decl"
    description = "MISRA C:2012 Rules 8.1-8.14: declaration and definition rules"
    default_severity = Severity.WARNING
    misra_rules = [RULE_8_1, RULE_8_2, RULE_8_4, RULE_8_5, RULE_8_6, RULE_8_7, RULE_8_8,
                   RULE_8_9, RULE_8_10, RULE_8_11, RULE_8_12, RULE_8_13, RULE_8_14]

    def visit_FuncDecl(self, node: c_ast.FuncDecl) -> None:
        if node.args is None:
            self.report(
                node,
                "Function declared without parameter list (not in prototype form)",
                Severity.WARNING,
                RULE_8_2,
            )
        elif node.args.params:
            for param in node.args.params:
                if isinstance(param, c_ast.Decl) and param.name is None:
                    if not (isinstance(param.type, c_ast.IdentifierType) and "void" in param.type.names):
                        self.report(
                            param,
                            "Function parameter does not have a name",
                            Severity.WARNING,
                            RULE_8_2,
                        )
        self.generic_visit(node)

    def visit_FuncDef(self, node: c_ast.FuncDef) -> None:
        if node.decl:
            funcspec = node.decl.funcspec or []
            storage = node.decl.storage or []
            if "inline" in funcspec and "static" not in storage:
                self.report(
                    node.decl,
                    "Inline function is not declared with 'static' storage class",
                    Severity.WARNING,
                    RULE_8_10,
                )
        self.generic_visit(node)

    def visit_Decl(self, node: c_ast.Decl) -> None:
        # Rule 8.14: `restrict` attaches to the PtrDecl in the declarator
        # chain (`int * restrict p`), not to Decl.quals, so walk the chain.
        if self._has_restrict_qualifier(node):
            self.report(
                node,
                "The 'restrict' type qualifier shall not be used",
                Severity.WARNING,
                RULE_8_14,
            )

        if isinstance(node.type, c_ast.ArrayDecl):
            storage = node.storage or []
            if "extern" in storage and node.type.dim is None:
                self.report(
                    node,
                    f"External array '{node.name}' declared without explicit size",
                    Severity.INFO,
                    RULE_8_11,
                )

        self.generic_visit(node)

    def visit_Enum(self, node: c_ast.Enum) -> None:
        if node.values is None:
            return

        seen_values: dict[int, str] = {}
        next_implicit = 0
        counter_unknown = False  # True after a value we could not evaluate

        for enumerator in node.values.enumerators or []:
            if enumerator.value:
                val = self._eval_const_expr(enumerator.value)
                if val is None:
                    # Non-evaluable explicit value (e.g. a macro-expanded
                    # expression): the implicit counter is now desynced.
                    # Suppress duplicate reporting until the next evaluable
                    # explicit constant re-synchronizes it.
                    counter_unknown = True
                    continue
                counter_unknown = False
                next_implicit = val + 1
                if val in seen_values:
                    self.report(
                        enumerator,
                        f"Enum value {val} for '{enumerator.name}' duplicates '{seen_values[val]}'",
                        Severity.WARNING,
                        RULE_8_12,
                    )
                seen_values[val] = enumerator.name
            else:
                if counter_unknown:
                    continue
                val = next_implicit
                next_implicit = val + 1
                if val in seen_values:
                    self.report(
                        enumerator,
                        f"Implicit enum value {val} for '{enumerator.name}' duplicates '{seen_values[val]}'",
                        Severity.WARNING,
                        RULE_8_12,
                    )
                seen_values[val] = enumerator.name

        self.generic_visit(node)

    def _eval_const_expr(self, node: c_ast.Node) -> int | None:
        """Fold simple constant expressions (`1 << 4`, `-1`, `(2 + 3)`)."""
        if isinstance(node, c_ast.Constant):
            return parse_int_literal(node.value)
        if isinstance(node, c_ast.UnaryOp):
            inner = self._eval_const_expr(node.expr)
            if inner is None:
                return None
            if node.op == "-":
                return -inner
            if node.op == "+":
                return inner
            if node.op == "~":
                return ~inner
            return None
        if isinstance(node, c_ast.BinaryOp):
            left = self._eval_const_expr(node.left)
            right = self._eval_const_expr(node.right)
            if left is None or right is None:
                return None
            try:
                if node.op == "+":
                    return left + right
                if node.op == "-":
                    return left - right
                if node.op == "*":
                    return left * right
                if node.op == "<<":
                    return left << right
                if node.op == ">>":
                    return left >> right
                if node.op == "|":
                    return left | right
                if node.op == "&":
                    return left & right
                if node.op == "^":
                    return left ^ right
            except (ValueError, OverflowError):
                return None
        return None

    def _has_restrict_qualifier(self, node: c_ast.Decl) -> bool:
        if "restrict" in (node.quals or []):
            return True
        t = node.type
        while isinstance(t, (c_ast.PtrDecl, c_ast.ArrayDecl, c_ast.FuncDecl, c_ast.TypeDecl)):
            if isinstance(t, c_ast.PtrDecl) and "restrict" in (t.quals or []):
                return True
            if isinstance(t, c_ast.ArrayDecl) and "restrict" in (t.dim_quals or []):
                return True
            t = t.type
        return False


CheckerRegistry.register(MisraDeclChecker)

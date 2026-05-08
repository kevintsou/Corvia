"""MISRA C:2012 type conversion rules (Rules 10.1-10.8)."""

from __future__ import annotations

from pycparser import c_ast

from covia.checkers.base import BaseChecker
from covia.models import MisraCategory, MisraRule, Severity
from covia.registry import CheckerRegistry

RULE_10_1 = MisraRule("10.1", MisraCategory.REQUIRED, "Operands shall not be of an inappropriate essential type")
RULE_10_2 = MisraRule("10.2", MisraCategory.REQUIRED, "Expressions of essentially character type shall not be used inappropriately in addition and subtraction operations")
RULE_10_3 = MisraRule("10.3", MisraCategory.REQUIRED, "The value of an expression shall not be assigned to an object with a narrower essential type or of a different essential type category")
RULE_10_4 = MisraRule("10.4", MisraCategory.REQUIRED, "Both operands of an operator in which the usual arithmetic conversions are performed shall have the same essential type category")
RULE_10_5 = MisraRule("10.5", MisraCategory.ADVISORY, "The value of an expression should not be cast to an inappropriate essential type")
RULE_10_6 = MisraRule("10.6", MisraCategory.REQUIRED, "The value of a composite expression shall not be assigned to an object with wider essential type")
RULE_10_7 = MisraRule("10.7", MisraCategory.REQUIRED, "If a composite expression is used as one operand of an operator in which the usual arithmetic conversions are performed then the other operand shall not have wider essential type")
RULE_10_8 = MisraRule("10.8", MisraCategory.REQUIRED, "The value of a composite expression shall not be cast to a different essential type category or a wider essential type")

_SIGNED_TYPES = {"int", "short", "long", "signed", "signed int", "signed short", "signed long", "signed char", "long long", "signed long long"}
_UNSIGNED_TYPES = {"unsigned", "unsigned int", "unsigned short", "unsigned long", "unsigned char", "unsigned long long"}
_FLOAT_TYPES = {"float", "double", "long double"}
_CHAR_TYPES = {"char"}
_BOOL_TYPES = {"_Bool", "bool"}

_TYPE_WIDTH = {
    "_Bool": 1, "bool": 1,
    "char": 8, "signed char": 8, "unsigned char": 8,
    "short": 16, "signed short": 16, "unsigned short": 16,
    "int": 32, "signed int": 32, "signed": 32, "unsigned int": 32, "unsigned": 32,
    "long": 64, "signed long": 64, "unsigned long": 64,
    "long long": 128, "signed long long": 128, "unsigned long long": 128,
    "float": 32, "double": 64, "long double": 128,
}


def _essential_category(type_names: list[str]) -> str:
    joined = " ".join(type_names)
    if joined in _BOOL_TYPES:
        return "boolean"
    if joined in _CHAR_TYPES:
        return "character"
    if joined in _SIGNED_TYPES:
        return "signed"
    if joined in _UNSIGNED_TYPES:
        return "unsigned"
    if joined in _FLOAT_TYPES:
        return "floating"
    return "unknown"


def _type_width(type_names: list[str]) -> int:
    joined = " ".join(type_names)
    return _TYPE_WIDTH.get(joined, 0)


def _extract_type_names(node: c_ast.Node) -> list[str]:
    if isinstance(node, c_ast.TypeDecl):
        return _extract_type_names(node.type)
    if isinstance(node, c_ast.IdentifierType):
        return node.names
    if isinstance(node, c_ast.Decl) and node.type:
        return _extract_type_names(node.type)
    return []


class MisraTypesChecker(BaseChecker):
    checker_id = "misra-types"
    description = "MISRA C:2012 Rules 10.1-10.8: essential type model and type conversion rules"
    default_severity = Severity.WARNING
    misra_rules = [RULE_10_1, RULE_10_2, RULE_10_3, RULE_10_4, RULE_10_5, RULE_10_6, RULE_10_7, RULE_10_8]

    def visit_Cast(self, node: c_ast.Cast) -> None:
        if node.to_type:
            target_names = _extract_type_names(node.to_type)
            target_cat = _essential_category(target_names)

            if isinstance(node.expr, c_ast.Constant):
                source_cat = self._constant_category(node.expr)
                if source_cat != "unknown" and target_cat != "unknown" and source_cat != target_cat:
                    if target_cat == "boolean" and source_cat not in ("boolean",):
                        self.report(node, f"Cast from {source_cat} to boolean type", Severity.WARNING, RULE_10_5)
                    elif source_cat == "boolean" and target_cat not in ("boolean",):
                        self.report(node, f"Cast from boolean to {target_cat} type", Severity.WARNING, RULE_10_5)

        self.generic_visit(node)

    def visit_Assignment(self, node: c_ast.Assignment) -> None:
        ltype = self._infer_type_names(node.lvalue)
        rtype = self._infer_type_names(node.rvalue)

        if ltype and rtype:
            lcat = _essential_category(ltype)
            rcat = _essential_category(rtype)

            if lcat != "unknown" and rcat != "unknown" and lcat != rcat:
                if not (lcat in ("signed", "unsigned") and rcat in ("signed", "unsigned")):
                    self.report(
                        node,
                        f"Assignment between different essential type categories ({rcat} to {lcat})",
                        Severity.WARNING,
                        RULE_10_3,
                    )

            if lcat == rcat and lcat in ("signed", "unsigned", "floating"):
                lw = _type_width(ltype)
                rw = _type_width(rtype)
                if lw and rw and lw < rw:
                    self.report(
                        node,
                        f"Narrowing assignment from wider type to narrower type",
                        Severity.WARNING,
                        RULE_10_3,
                    )

        self.generic_visit(node)

    def visit_BinaryOp(self, node: c_ast.BinaryOp) -> None:
        if node.op in ("+", "-", "*", "/", "%"):
            ltype = self._infer_type_names(node.left)
            rtype = self._infer_type_names(node.right)

            if ltype and rtype:
                lcat = _essential_category(ltype)
                rcat = _essential_category(rtype)

                if lcat != "unknown" and rcat != "unknown" and lcat != rcat:
                    if node.op in ("+", "-") and (lcat == "character" or rcat == "character"):
                        other = rcat if lcat == "character" else lcat
                        if other not in ("signed", "unsigned", "character"):
                            self.report(
                                node,
                                f"Character type used in arithmetic with {other} type",
                                Severity.WARNING,
                                RULE_10_2,
                            )
                    else:
                        self.report(
                            node,
                            f"Operands of '{node.op}' have different essential type categories ({lcat} and {rcat})",
                            Severity.WARNING,
                            RULE_10_4,
                        )

            if node.op in ("<<", ">>", "&", "|", "^", "~"):
                for operand, side in [(node.left, "left"), (node.right, "right")]:
                    otype = self._infer_type_names(operand)
                    if otype:
                        ocat = _essential_category(otype)
                        if ocat in ("boolean", "character", "floating"):
                            self.report(
                                node,
                                f"Inappropriate essential type ({ocat}) for {side} operand of '{node.op}'",
                                Severity.WARNING,
                                RULE_10_1,
                            )

        self.generic_visit(node)

    def _infer_type_names(self, node: c_ast.Node) -> list[str]:
        if isinstance(node, c_ast.Constant):
            if node.type == "int":
                return ["int"]
            elif node.type == "float" or node.type == "double":
                return [node.type]
            elif node.type == "char":
                return ["char"]
        if isinstance(node, c_ast.Cast) and node.to_type:
            return _extract_type_names(node.to_type)
        return []

    def _constant_category(self, node: c_ast.Constant) -> str:
        if node.type == "int":
            return "signed"
        if node.type in ("float", "double"):
            return "floating"
        if node.type == "char":
            return "character"
        return "unknown"


CheckerRegistry.register(MisraTypesChecker)

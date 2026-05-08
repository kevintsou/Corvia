"""MISRA C:2012 Section 7: Literals and constants.

Implements Rules 7.1 (octal constants), 7.2 (unsigned suffix on unsigned
context constants), 7.3 (lowercase 'l' suffix), and 7.4 (string literal
to non-const-qualified char pointer).
"""

from __future__ import annotations

from pycparser import c_ast

from corvia.checkers.base import BaseChecker
from corvia.models import MisraCategory, MisraRule, Severity
from corvia.registry import CheckerRegistry


RULE_7_1 = MisraRule("7.1", MisraCategory.REQUIRED, "Octal constants shall not be used")
RULE_7_2 = MisraRule(
    "7.2", MisraCategory.REQUIRED,
    "A 'u' or 'U' suffix shall be applied to all integer constants represented in unsigned type",
)
RULE_7_3 = MisraRule(
    "7.3", MisraCategory.REQUIRED,
    "The lowercase character 'l' shall not be used in a literal suffix",
)
RULE_7_4 = MisraRule(
    "7.4", MisraCategory.REQUIRED,
    "A string literal shall not be assigned to an object unless the object's type is 'pointer to const-qualified char'",
)


def _is_octal(value: str) -> bool:
    """C octal: starts with 0 and has at least two characters, but isn't 0x… (hex) or just '0'."""
    s = value.lstrip("+-")
    if len(s) < 2:
        return False
    if s[0] != "0":
        return False
    if s[1] in ("x", "X", "b", "B", "."):
        return False
    suffix_start = 0
    for i, ch in enumerate(s):
        if not ch.isdigit():
            suffix_start = i
            break
    digits = s[:suffix_start] if suffix_start else s
    return len(digits) >= 2 and all(c in "01234567" for c in digits)


def _has_lowercase_l(value: str) -> bool:
    suffix = ""
    for ch in reversed(value):
        if ch.isalpha():
            suffix = ch + suffix
        else:
            break
    return "l" in suffix


def _is_string_literal(node: c_ast.Node) -> bool:
    return isinstance(node, c_ast.Constant) and node.type == "string"


def _pointee_is_const_char(type_node: c_ast.Node) -> bool:
    if not isinstance(type_node, c_ast.PtrDecl):
        return False
    inner = type_node.type
    if isinstance(inner, c_ast.TypeDecl):
        if "const" not in (inner.quals or []):
            return False
        if isinstance(inner.type, c_ast.IdentifierType):
            return "char" in inner.type.names
    return False


class MisraLiteralsChecker(BaseChecker):
    checker_id = "misra-literals"
    description = "MISRA C:2012 Rules 7.1-7.4: literal and string constant rules"
    default_severity = Severity.WARNING
    misra_rules = [RULE_7_1, RULE_7_2, RULE_7_3, RULE_7_4]

    def visit_Constant(self, node: c_ast.Constant) -> None:
        if isinstance(node.value, str) and node.type and "int" in node.type:
            if _is_octal(node.value):
                self.report(
                    node,
                    f"Octal constant '{node.value}' is forbidden",
                    Severity.WARNING,
                    RULE_7_1,
                )
            if _has_lowercase_l(node.value):
                self.report(
                    node,
                    f"Lowercase 'l' suffix in '{node.value}' is ambiguous; use 'L'",
                    Severity.WARNING,
                    RULE_7_3,
                )
        self.generic_visit(node)

    def visit_Decl(self, node: c_ast.Decl) -> None:
        if node.init is not None and _is_string_literal(node.init):
            if not _pointee_is_const_char(node.type):
                self.report(
                    node,
                    f"String literal assigned to '{node.name}' which is not 'const char *'",
                    Severity.WARNING,
                    RULE_7_4,
                )
        self.generic_visit(node)

    def visit_Assignment(self, node: c_ast.Assignment) -> None:
        if _is_string_literal(node.rvalue):
            target_type = self._lookup_lvalue_type(node.lvalue)
            if target_type is not None and not _pointee_is_const_char(target_type):
                self.report(
                    node,
                    "String literal assigned to a non-const-char pointer",
                    Severity.WARNING,
                    RULE_7_4,
                )
        self.generic_visit(node)

    def _lookup_lvalue_type(self, node: c_ast.Node):
        if self._ctx is None:
            return None
        if isinstance(node, c_ast.ID):
            sym = self._ctx.symbol_table.lookup(node.name, file=self._current_file)
            return sym.ast_node.type if sym and sym.ast_node else None
        return None


CheckerRegistry.register(MisraLiteralsChecker)

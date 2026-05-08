"""MISRA C:2012 Section 6: Types (bit-fields).

Implements Rules 6.1 and 6.2 covering the types permitted on bit-fields.
"""

from __future__ import annotations

from pycparser import c_ast

from corvia.checkers.base import BaseChecker
from corvia.models import MisraCategory, MisraRule, Severity
from corvia.registry import CheckerRegistry


RULE_6_1 = MisraRule(
    "6.1", MisraCategory.REQUIRED,
    "Bit-fields shall only be declared with an appropriate type",
)
RULE_6_2 = MisraRule(
    "6.2", MisraCategory.REQUIRED,
    "Single-bit named bit-fields shall not be of a signed type",
)


_ALLOWED_BITFIELD_TYPES = {
    "_Bool", "bool",
    "signed int", "unsigned int", "int", "signed", "unsigned",
}

_SIGNED_INT_TYPES = {"signed int", "int", "signed"}


def _identifier_names(type_node: c_ast.Node) -> list[str] | None:
    cur = type_node
    if isinstance(cur, c_ast.TypeDecl):
        cur = cur.type
    if isinstance(cur, c_ast.IdentifierType):
        return cur.names
    return None


class MisraBitFieldsChecker(BaseChecker):
    checker_id = "misra-bitfields"
    description = "MISRA C:2012 Rules 6.1 / 6.2: bit-field type restrictions"
    default_severity = Severity.WARNING
    misra_rules = [RULE_6_1, RULE_6_2]

    def visit_Struct(self, node: c_ast.Struct) -> None:
        self._check_members(node.decls or [])
        self.generic_visit(node)

    def visit_Union(self, node: c_ast.Union) -> None:
        self._check_members(node.decls or [])
        self.generic_visit(node)

    def _check_members(self, members) -> None:
        for member in members:
            if not isinstance(member, c_ast.Decl):
                continue
            if member.bitsize is None:
                continue

            names = _identifier_names(member.type)
            if names is None:
                continue
            joined = " ".join(names)

            if joined not in _ALLOWED_BITFIELD_TYPES:
                self.report(
                    member,
                    f"Bit-field '{member.name or '<anon>'}' has disallowed type '{joined}'",
                    Severity.WARNING,
                    RULE_6_1,
                )

            if member.name and isinstance(member.bitsize, c_ast.Constant):
                try:
                    width = int(member.bitsize.value, 0)
                except ValueError:
                    width = 0
                if width == 1 and joined in _SIGNED_INT_TYPES:
                    self.report(
                        member,
                        f"Single-bit bit-field '{member.name}' has signed type '{joined}'",
                        Severity.WARNING,
                        RULE_6_2,
                    )


CheckerRegistry.register(MisraBitFieldsChecker)

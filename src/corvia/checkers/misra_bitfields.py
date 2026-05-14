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
        self._check_members(node.decls or [], parent=node)
        self.generic_visit(node)

    def visit_Union(self, node: c_ast.Union) -> None:
        self._check_members(node.decls or [], parent=node)
        self.generic_visit(node)

    def _check_members(self, members, parent: c_ast.Node | None = None) -> None:
        # Build a human-readable parent name for use in messages (e.g. "struct Foo").
        parent_label = ""
        if parent is not None:
            kind = "struct" if isinstance(parent, c_ast.Struct) else "union"
            parent_label = f" in {kind} '{parent.name}'" if parent.name else f" in anonymous {kind}"

        for member in members:
            if not isinstance(member, c_ast.Decl):
                continue
            if member.bitsize is None:
                continue

            names = _identifier_names(member.type)
            if names is None:
                continue
            joined = " ".join(names)

            # Use parent node as coord fallback when member has no usable location.
            coord_node = member
            if parent is not None and (
                member.coord is None
                or not member.coord.line
            ):
                coord_node = parent

            if joined not in _ALLOWED_BITFIELD_TYPES:
                field_label = f"'{member.name}'" if member.name else "<anon>"
                self.report(
                    coord_node,
                    f"Bit-field {field_label}{parent_label} has disallowed type '{joined}'",
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
                        coord_node,
                        f"Single-bit bit-field '{member.name}'{parent_label} has signed type '{joined}'",
                        Severity.WARNING,
                        RULE_6_2,
                    )


CheckerRegistry.register(MisraBitFieldsChecker)

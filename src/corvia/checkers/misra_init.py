"""MISRA C:2012 Section 9: Initialization (Rules 9.2 and 9.3).

Rule 9.1 (use-before-init) is implemented in the existing `uninit-var`
checker. This module covers the structural initializer rules that can be
checked from the AST alone.
"""

from __future__ import annotations

from pycparser import c_ast

from corvia.checkers.base import BaseChecker
from corvia.models import MisraCategory, MisraRule, Severity
from corvia.registry import CheckerRegistry


RULE_9_2 = MisraRule(
    "9.2", MisraCategory.REQUIRED,
    "The initializer for an aggregate or union shall be enclosed in braces",
)
RULE_9_3 = MisraRule(
    "9.3", MisraCategory.REQUIRED,
    "Arrays shall not be partially initialized",
)


def _is_aggregate_type(type_node: c_ast.Node) -> str | None:
    """Return 'array', 'struct', 'union' if the type is an aggregate, else None."""
    if isinstance(type_node, c_ast.ArrayDecl):
        return "array"
    if isinstance(type_node, c_ast.TypeDecl):
        inner = type_node.type
        if isinstance(inner, c_ast.Struct):
            return "struct"
        if isinstance(inner, c_ast.Union):
            return "union"
    return None


def _array_dim(type_node: c_ast.Node) -> int | None:
    if isinstance(type_node, c_ast.ArrayDecl) and isinstance(type_node.dim, c_ast.Constant):
        try:
            return int(type_node.dim.value, 0)
        except ValueError:
            return None
    return None


class MisraInitChecker(BaseChecker):
    checker_id = "misra-init"
    description = "MISRA C:2012 Rules 9.2, 9.3: aggregate / union initializer rules"
    default_severity = Severity.WARNING
    misra_rules = [RULE_9_2, RULE_9_3]

    def visit_Decl(self, node: c_ast.Decl) -> None:
        if node.init is None or node.name is None:
            self.generic_visit(node)
            return

        kind = _is_aggregate_type(node.type)
        if kind is None:
            self.generic_visit(node)
            return

        # 9.2: aggregates / unions need brace-enclosed initializers.
        if kind in ("array", "struct", "union"):
            if not isinstance(node.init, (c_ast.InitList, c_ast.CompoundLiteral)):
                if kind == "array" and isinstance(node.init, c_ast.Constant) and node.init.type == "string":
                    pass  # char arr[] = "..." is allowed
                else:
                    self.report(
                        node,
                        f"Initializer for {kind} '{node.name}' is not enclosed in braces",
                        Severity.WARNING,
                        RULE_9_2,
                    )

        # 9.3: arrays must be fully initialized when an explicit dimension is given.
        if kind == "array" and isinstance(node.init, c_ast.InitList):
            dim = _array_dim(node.type)
            if dim is not None:
                exprs = node.init.exprs or []
                has_designated = any(
                    isinstance(e, (c_ast.NamedInitializer,)) for e in exprs
                )
                if not has_designated and len(exprs) < dim:
                    self.report(
                        node,
                        f"Array '{node.name}' has {dim} elements but only {len(exprs)} initializers",
                        Severity.WARNING,
                        RULE_9_3,
                    )

        self.generic_visit(node)


CheckerRegistry.register(MisraInitChecker)

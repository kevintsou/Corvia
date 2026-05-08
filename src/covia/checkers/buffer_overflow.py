"""Buffer overflow checker - constant index out of bounds on fixed-size arrays."""

from __future__ import annotations

from pycparser import c_ast

from covia.checkers.base import BaseChecker
from covia.models import MisraCategory, MisraRule, Severity
from covia.registry import CheckerRegistry

RULE_1_3 = MisraRule("1.3", MisraCategory.REQUIRED, "There shall be no occurrence of undefined behaviour")
RULE_18_1 = MisraRule("18.1", MisraCategory.REQUIRED, "A pointer resulting from arithmetic on a pointer operand shall address an element of the same array")


class BufferOverflowChecker(BaseChecker):
    checker_id = "buffer-overflow"
    description = "Detects constant-index out-of-bounds access on fixed-size arrays"
    default_severity = Severity.ERROR
    misra_rules = [RULE_1_3, RULE_18_1]

    def __init__(self) -> None:
        super().__init__()
        self._arrays: dict[str, int] = {}

    def visit_FuncDef(self, node: c_ast.FuncDef) -> None:
        self._arrays.clear()
        self.generic_visit(node)

    def visit_Decl(self, node: c_ast.Decl) -> None:
        if node.name and isinstance(node.type, c_ast.ArrayDecl):
            size = self._get_array_size(node.type)
            if size is not None:
                self._arrays[node.name] = size
        self.generic_visit(node)

    def visit_ArrayRef(self, node: c_ast.ArrayRef) -> None:
        if isinstance(node.name, c_ast.ID):
            name = node.name.name
            if name in self._arrays:
                idx = self._get_constant_index(node.subscript)
                if idx is not None:
                    size = self._arrays[name]
                    if idx < 0:
                        self.report(
                            node,
                            f"Negative index {idx} on array '{name}' of size {size}",
                            Severity.ERROR,
                            RULE_1_3,
                        )
                    elif idx >= size:
                        self.report(
                            node,
                            f"Index {idx} out of bounds for array '{name}' of size {size}",
                            Severity.ERROR,
                            RULE_18_1,
                        )
        self.generic_visit(node)

    def _get_array_size(self, type_node: c_ast.ArrayDecl) -> int | None:
        if type_node.dim and isinstance(type_node.dim, c_ast.Constant):
            if type_node.dim.type == "int":
                try:
                    return int(type_node.dim.value, 0)
                except ValueError:
                    return None
        return None

    def _get_constant_index(self, node: c_ast.Node) -> int | None:
        if isinstance(node, c_ast.Constant) and node.type == "int":
            try:
                return int(node.value, 0)
            except ValueError:
                return None
        if isinstance(node, c_ast.UnaryOp) and node.op == "-":
            val = self._get_constant_index(node.expr)
            if val is not None:
                return -val
        return None


CheckerRegistry.register(BufferOverflowChecker)

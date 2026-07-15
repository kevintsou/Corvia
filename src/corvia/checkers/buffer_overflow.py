"""Buffer overflow checker - constant index out of bounds on fixed-size arrays."""

from __future__ import annotations

from pycparser import c_ast

from corvia.checkers.base import BaseChecker, parse_int_literal
from corvia.models import MisraCategory, MisraRule, Severity
from corvia.registry import CheckerRegistry

RULE_1_3 = MisraRule("1.3", MisraCategory.REQUIRED, "There shall be no occurrence of undefined behaviour")
RULE_18_1 = MisraRule("18.1", MisraCategory.REQUIRED, "A pointer resulting from arithmetic on a pointer operand shall address an element of the same array")


class BufferOverflowChecker(BaseChecker):
    checker_id = "buffer-overflow"
    description = "Detects constant-index out-of-bounds access on fixed-size arrays"
    default_severity = Severity.ERROR
    misra_rules = [RULE_1_3, RULE_18_1]

    def __init__(self) -> None:
        super().__init__()
        # Function-local arrays: reset at each function definition.
        self._arrays: dict[str, int] = {}
        # File-scope arrays: persist across all functions in the file, so a
        # global array indexed inside the second function is still checked.
        self._global_arrays: dict[str, int] = {}
        self._in_function = False
        # Names of the current function's parameters. A parameter declared as
        # `U8 *r` or `U8 r[]`/`U8 r[2]` decays to a pointer into a
        # caller-provided buffer: it has NO statically known size, so indexing
        # through it must never be flagged as out-of-bounds.
        self._param_names: set[str] = set()
        # Local non-array declarations (e.g. `U8 *r`) that shadow a same-named
        # file-scope array: the global's size must not apply inside here.
        self._local_shadows: set[str] = set()

    def reset(self) -> None:
        self._arrays = {}
        self._global_arrays = {}
        self._in_function = False
        self._param_names = set()
        self._local_shadows = set()

    def visit_FuncDef(self, node: c_ast.FuncDef) -> None:
        self._arrays.clear()
        self._param_names = self._collect_param_names(node)
        self._local_shadows = set()
        self._in_function = True
        self.generic_visit(node)
        self._in_function = False
        self._param_names = set()
        self._local_shadows = set()

    def _collect_param_names(self, node: c_ast.FuncDef) -> set[str]:
        """Return the names of the function's parameters.

        Parameters decay to pointers regardless of whether they are written
        `U8 *r`, `U8 r[]` or `U8 r[2]` — none of these carry a size the callee
        can rely on, so they are excluded from bounds checking.
        """
        names: set[str] = set()
        func_decl = node.decl.type if node.decl else None
        if isinstance(func_decl, c_ast.FuncDecl) and func_decl.args:
            for param in func_decl.args.params:
                if isinstance(param, c_ast.Decl) and param.name:
                    names.add(param.name)
        return names

    def visit_Decl(self, node: c_ast.Decl) -> None:
        # Never track a parameter as a sized array: an array parameter
        # (`U8 r[2]`) decays to a pointer, so pycparser's `ArrayDecl` dimension
        # does not constrain the accessible range.
        if (
            node.name
            and node.name not in self._param_names
            and isinstance(node.type, c_ast.ArrayDecl)
        ):
            size = self._get_array_size(node.type)
            if size is not None:
                if self._in_function:
                    self._arrays[node.name] = size
                else:
                    self._global_arrays[node.name] = size
        elif self._in_function and node.name and not isinstance(node.type, c_ast.ArrayDecl):
            # A local non-array declaration shadows any same-named file-scope
            # array for the rest of this function.
            self._local_shadows.add(node.name)
        self.generic_visit(node)

    def visit_Assignment(self, node: c_ast.Assignment) -> None:
        # A genuine array is not an lvalue in C, so any assignment (including
        # pointer advancement such as `r += 5U`) to a tracked name means it is
        # really a pointer. Drop it from tracking to avoid phantom bounds
        # checks against a dimension that no longer applies.
        if isinstance(node.lvalue, c_ast.ID):
            self._arrays.pop(node.lvalue.name, None)
            self._global_arrays.pop(node.lvalue.name, None)
        self.generic_visit(node)

    def visit_ArrayRef(self, node: c_ast.ArrayRef) -> None:
        if isinstance(node.name, c_ast.ID):
            name = node.name.name
            # A parameter or local non-array shadows a same-named file-scope
            # array: its size says nothing about what `name` points at here.
            if name in self._param_names or name in self._local_shadows:
                self.generic_visit(node)
                return
            size = self._arrays.get(name)
            if size is None and name not in self._arrays:
                size = self._global_arrays.get(name)
            if size is not None:
                idx = self._get_constant_index(node.subscript)
                if idx is not None:
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
            if "int" in (type_node.dim.type or ""):
                return parse_int_literal(type_node.dim.value)
        return None

    def _get_constant_index(self, node: c_ast.Node) -> int | None:
        if isinstance(node, c_ast.Constant) and "int" in (node.type or ""):
            return parse_int_literal(node.value)
        if isinstance(node, c_ast.UnaryOp) and node.op == "-":
            val = self._get_constant_index(node.expr)
            if val is not None:
                return -val
        return None


CheckerRegistry.register(BufferOverflowChecker)

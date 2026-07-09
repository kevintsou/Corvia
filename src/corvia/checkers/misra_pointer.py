"""MISRA C:2012 pointer rules (Rules 18.1-18.8)."""

from __future__ import annotations

from pycparser import c_ast

from corvia.checkers.base import BaseChecker
from corvia.models import MisraCategory, MisraRule, Severity
from corvia.registry import CheckerRegistry

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

    def __init__(self) -> None:
        super().__init__()
        # Names of variables declared with pointer (or array) type, so
        # pointer arithmetic / comparison rules can recognize `p + 1`.
        self._ptr_vars: set[str] = set()
        # Enumeration constants: an array dimension referencing only these is
        # a constant expression, NOT a variable-length array.
        self._enum_consts: set[str] = set()
        # Struct/union member declarations are field names, not variables;
        # they must not pollute _ptr_vars.
        self._struct_depth = 0

    def reset(self) -> None:
        self._ptr_vars = set()
        self._enum_consts = set()
        self._struct_depth = 0

    def visit_FileAST(self, node: c_ast.FileAST) -> None:
        self._collect_enum_constants(node)
        self.generic_visit(node)

    def _collect_enum_constants(self, node: c_ast.Node) -> None:
        if isinstance(node, c_ast.Enumerator) and node.name:
            self._enum_consts.add(node.name)
        for _, child in node.children():
            self._collect_enum_constants(child)

    def visit_FuncDef(self, node: c_ast.FuncDef) -> None:
        # Pointer variables are scoped per function: snapshot and restore so
        # a pointer `p` in one function does not taint an int `p` elsewhere.
        saved = set(self._ptr_vars)
        self.generic_visit(node)
        self._ptr_vars = saved

    def visit_Struct(self, node: c_ast.Struct) -> None:
        # Rule 18.7: a flexible array member is an incomplete array type as
        # the LAST member of a struct. Checking `dim is None` on any Decl
        # would also flag `char msg[] = "hi";` and array parameters
        # `void g(int a[])`, which are not flexible array members.
        decls = node.decls or []
        if decls:
            last = decls[-1]
            if isinstance(last, c_ast.Decl) and isinstance(last.type, c_ast.ArrayDecl) \
                    and last.type.dim is None:
                self.report(
                    last,
                    f"Flexible array member '{last.name}' declared",
                    Severity.WARNING,
                    RULE_18_7,
                )
        self._struct_depth += 1
        self.generic_visit(node)
        self._struct_depth -= 1

    def visit_Union(self, node: c_ast.Union) -> None:
        self._struct_depth += 1
        self.generic_visit(node)
        self._struct_depth -= 1

    def visit_Decl(self, node: c_ast.Decl) -> None:
        if node.name and self._struct_depth == 0 \
                and isinstance(node.type, (c_ast.PtrDecl, c_ast.ArrayDecl)):
            self._ptr_vars.add(node.name)

        if node.type:
            ptr_depth = self._pointer_depth(node.type)
            if ptr_depth > 2:
                self.report(
                    node,
                    f"Declaration '{node.name}' has {ptr_depth} levels of pointer nesting (max 2 recommended)",
                    Severity.INFO,
                    RULE_18_5,
                )

            if isinstance(node.type, c_ast.ArrayDecl) and node.type.dim is not None:
                if not isinstance(node.type.dim, c_ast.Constant):
                    if self._is_local_var(node) and self._dim_references_variable(node.type.dim):
                        self.report(
                            node,
                            f"Variable-length array '{node.name}' declared",
                            Severity.WARNING,
                            RULE_18_8,
                        )

        self.generic_visit(node)

    def _dim_references_variable(self, dim: c_ast.Node) -> bool:
        """True when the array dimension references an identifier that is not
        an enumeration constant. Dimensions built from constants and enum
        constants (e.g. `int arr[SIZE];` with `enum { SIZE = 8 };` or
        `int arr[SIZE * 2];`) are constant expressions, not VLAs."""
        if dim is None:
            return False
        if isinstance(dim, c_ast.ID):
            return dim.name not in self._enum_consts
        if isinstance(dim, c_ast.UnaryOp) and dim.op == "sizeof":
            return False  # sizeof(...) is a constant expression
        for _, child in dim.children():
            if self._dim_references_variable(child):
                return True
        return False

    def visit_Assignment(self, node: c_ast.Assignment) -> None:
        # Rule 18.4: += / -= on a pointer. These never appear as BinaryOp in
        # pycparser - compound assignments are Assignment nodes.
        if node.op in ("+=", "-=") and self._is_pointer_expr(node.lvalue):
            self.report(
                node,
                f"Arithmetic operator '{node.op}' applied to pointer type",
                Severity.INFO,
                RULE_18_4,
            )
        self.generic_visit(node)

    def visit_BinaryOp(self, node: c_ast.BinaryOp) -> None:
        left_ptr = self._is_pointer_expr(node.left)
        right_ptr = self._is_pointer_expr(node.right)

        if node.op == "-" and left_ptr and right_ptr:
            # Rule 18.2: pointer minus pointer.
            self.report(
                node,
                "Subtraction between two pointers (must address the same array)",
                Severity.WARNING,
                RULE_18_2,
            )
        elif node.op in ("+", "-") and (left_ptr or right_ptr):
            self.report(
                node,
                f"Arithmetic operator '{node.op}' applied to pointer type",
                Severity.INFO,
                RULE_18_4,
            )

        if node.op in ("<", ">", "<=", ">="):
            if left_ptr and right_ptr:
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
            return node.name in self._ptr_vars
        if isinstance(node, c_ast.Cast) and node.to_type is not None:
            t = node.to_type
            if isinstance(t, c_ast.Typename):
                t = t.type
            return isinstance(t, c_ast.PtrDecl)
        return False

    def _is_local_var(self, node: c_ast.Decl) -> bool:
        storage = node.storage or []
        return "extern" not in storage and "static" not in storage


CheckerRegistry.register(MisraPointerChecker)

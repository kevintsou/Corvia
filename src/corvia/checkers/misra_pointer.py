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
        # Scope stack mapping variable name -> is-pointer(bool). A *local*
        # declaration of the same name shadows an outer one, so a `U32 s`
        # inside a function correctly overrides a file-scope `char *s`. Only a
        # variable whose *nearest* declaration is a pointer/array is treated as
        # a pointer operand; integer-typed variables (including typedef'd ones
        # like U32) are recorded as non-pointers so `s += 4U` / `i < m` are not
        # mistaken for pointer arithmetic.
        self._scopes: list[dict[str, bool]] = [{}]
        # Enumeration constants: an array dimension referencing only these is
        # a constant expression, NOT a variable-length array.
        self._enum_consts: set[str] = set()
        # Struct/union member declarations are field names, not variables;
        # they must not pollute the scope map.
        self._struct_depth = 0
        # Typedef name -> True when it ultimately names a pointer type. Lets us
        # see through `U32`-style integer typedefs (which are NOT pointers) as
        # well as `typedef struct x *X_PTR` (which are).
        self._typedef_is_ptr: dict[str, bool] = {}

    def reset(self) -> None:
        self._scopes = [{}]
        self._enum_consts = set()
        self._struct_depth = 0
        self._typedef_is_ptr = {}

    def visit_FileAST(self, node: c_ast.FileAST) -> None:
        self._collect_enum_constants(node)
        self._build_typedef_map(node)
        self._scopes = [{}]
        self.generic_visit(node)

    def _build_typedef_map(self, node: c_ast.FileAST) -> None:
        """Record which typedef names ultimately resolve to a pointer type.

        A typedef of an integer (``typedef unsigned int U32;``) is a
        non-pointer; a typedef of a pointer (``typedef char *STR;``) is a
        pointer. Iterated to a fixpoint so typedef-of-typedef chains resolve
        regardless of declaration order.
        """
        raw: dict[str, c_ast.Node] = {}
        for ext in node.ext or []:
            if isinstance(ext, c_ast.Typedef) and ext.name:
                raw[ext.name] = ext.type

        def resolve(t: c_ast.Node) -> bool | None:
            if isinstance(t, (c_ast.PtrDecl, c_ast.ArrayDecl)):
                return True
            if isinstance(t, c_ast.TypeDecl):
                inner = t.type
                if isinstance(inner, c_ast.IdentifierType) and len(inner.names) == 1 \
                        and inner.names[0] in raw:
                    return self._typedef_is_ptr.get(inner.names[0])
                return False
            return False

        self._typedef_is_ptr = {}
        for _ in range(4):
            for name, t in raw.items():
                r = resolve(t)
                if r is not None:
                    self._typedef_is_ptr[name] = r

    def _collect_enum_constants(self, node: c_ast.Node) -> None:
        if isinstance(node, c_ast.Enumerator) and node.name:
            self._enum_consts.add(node.name)
        for _, child in node.children():
            self._collect_enum_constants(child)

    def visit_FuncDef(self, node: c_ast.FuncDef) -> None:
        # Pointer variables are scoped per function: push a fresh scope so a
        # pointer `p` in one function does not taint an int `p` elsewhere, and
        # a local declaration shadows a same-named file-scope variable.
        scope: dict[str, bool] = {}
        # Register parameters in the function scope.
        t = node.decl.type if node.decl else None
        while isinstance(t, c_ast.PtrDecl):
            t = t.type
        if isinstance(t, c_ast.FuncDecl) and t.args:
            for p in t.args.params or []:
                if isinstance(p, c_ast.Decl) and p.name:
                    scope[p.name] = self._decl_is_pointer(p.type)
        self._scopes.append(scope)
        self.generic_visit(node)
        self._scopes.pop()

    def _decl_is_pointer(self, type_node: c_ast.Node) -> bool:
        """Whether a declaration's type is a pointer/array operand.

        Arrays decay to pointers in arithmetic contexts, so they count. A bare
        identifier naming an integer typedef (U32, ...) is NOT a pointer; one
        naming a pointer typedef is."""
        if isinstance(type_node, (c_ast.PtrDecl, c_ast.ArrayDecl)):
            return True
        if isinstance(type_node, c_ast.TypeDecl):
            inner = type_node.type
            if isinstance(inner, c_ast.IdentifierType) and len(inner.names) == 1:
                return bool(self._typedef_is_ptr.get(inner.names[0], False))
        return False

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
        if node.name and self._struct_depth == 0 and not self._is_typedef(node):
            # Record every variable (pointer or not) in the current scope so a
            # local integer declaration shadows an outer same-named pointer.
            self._scopes[-1][node.name] = self._decl_is_pointer(node.type)

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

    def _is_typedef(self, node: c_ast.Decl) -> bool:
        storage = node.storage or []
        return "typedef" in storage

    def _lookup(self, name: str) -> bool | None:
        for scope in reversed(self._scopes):
            if name in scope:
                return scope[name]
        return None

    def _is_pointer_expr(self, node: c_ast.Node) -> bool:
        if isinstance(node, c_ast.UnaryOp) and node.op == "&":
            return True
        if isinstance(node, c_ast.ID):
            # Only a variable whose nearest declaration is a pointer/array is a
            # pointer operand. Unknown names (never declared here) are treated
            # as non-pointers to avoid false pointer-arithmetic reports on
            # ordinary integer variables.
            return self._lookup(node.name) is True
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

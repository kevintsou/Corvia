"""MISRA C:2012 Section 11: Pointer type conversions.

Implements Rules 11.1-11.9. Most rules involve flagging suspicious explicit
casts; the checker walks every Cast node and inspects source/target types
without attempting full type inference (kept to AST-level heuristics).
"""

from __future__ import annotations

from pycparser import c_ast

from covia.checkers.base import BaseChecker
from covia.models import MisraCategory, MisraRule, Severity
from covia.registry import CheckerRegistry


RULE_11_1 = MisraRule("11.1", MisraCategory.REQUIRED, "Conversions shall not be performed between a pointer to a function and any other type")
RULE_11_2 = MisraRule("11.2", MisraCategory.REQUIRED, "Conversions shall not be performed between a pointer to an incomplete type and any other type")
RULE_11_3 = MisraRule("11.3", MisraCategory.REQUIRED, "A cast shall not be performed between a pointer to object type and a pointer to a different object type")
RULE_11_4 = MisraRule("11.4", MisraCategory.ADVISORY, "A conversion should not be performed between a pointer to object and an integer type")
RULE_11_5 = MisraRule("11.5", MisraCategory.ADVISORY, "A conversion should not be performed from pointer to void into pointer to object")
RULE_11_6 = MisraRule("11.6", MisraCategory.REQUIRED, "A cast shall not be performed between pointer to void and an arithmetic type")
RULE_11_7 = MisraRule("11.7", MisraCategory.REQUIRED, "A cast shall not be performed between pointer to object and a non-integer arithmetic type")
RULE_11_8 = MisraRule("11.8", MisraCategory.REQUIRED, "A cast shall not remove any const or volatile qualification from the type pointed to by a pointer")
RULE_11_9 = MisraRule("11.9", MisraCategory.REQUIRED, "The macro NULL shall be the only permitted form of integer null pointer constant")


def _classify(type_node: c_ast.Node) -> dict:
    """Classify a type node into kind + qualifiers + base type names.

    Returns a dict with:
      kind: "pointer" | "func_pointer" | "void_pointer" | "object_pointer" |
            "int" | "float" | "void" | "other"
      base: list of base IdentifierType names
      ptr_quals: list of qualifiers on the pointee (const/volatile)
      depth: pointer depth (0 = not a pointer)
      to_kind: classification of the pointee
    """
    info: dict = {"kind": "other", "base": [], "ptr_quals": [], "depth": 0, "to_kind": None}

    cur = type_node
    if isinstance(cur, c_ast.Typename):
        cur = cur.type

    depth = 0
    quals: list[str] = []
    while isinstance(cur, c_ast.PtrDecl):
        depth += 1
        cur = cur.type

    info["depth"] = depth

    inner = cur
    if isinstance(inner, c_ast.TypeDecl):
        if inner.quals:
            quals = list(inner.quals)
        inner = inner.type

    info["ptr_quals"] = quals

    if isinstance(inner, c_ast.FuncDecl):
        info["kind"] = "func_pointer" if depth >= 1 else "func"
        return info

    if isinstance(inner, c_ast.IdentifierType):
        names = inner.names
        info["base"] = names
        joined = " ".join(names)
        if depth >= 1:
            if joined == "void":
                info["kind"] = "void_pointer"
            elif joined in ("char", "signed char", "unsigned char"):
                info["kind"] = "char_pointer"
            else:
                info["kind"] = "object_pointer"
            info["to_kind"] = "void" if joined == "void" else "object"
        else:
            if joined in ("float", "double", "long double"):
                info["kind"] = "float"
            elif joined == "void":
                info["kind"] = "void"
            else:
                info["kind"] = "int"
        return info

    if isinstance(inner, (c_ast.Struct, c_ast.Union)):
        if depth >= 1:
            info["kind"] = "object_pointer"
            info["to_kind"] = "object"
            info["base"] = [inner.name or ""]
        return info

    if isinstance(inner, c_ast.Enum):
        if depth >= 1:
            info["kind"] = "object_pointer"
            info["to_kind"] = "object"
        else:
            info["kind"] = "int"
        return info

    return info


def _is_pointer_kind(kind: str) -> bool:
    return kind in ("func_pointer", "void_pointer", "object_pointer", "char_pointer")


def _is_arithmetic_kind(kind: str) -> bool:
    return kind in ("int", "float")


class MisraPointerConvChecker(BaseChecker):
    checker_id = "misra-pointer-conv"
    description = "MISRA C:2012 Rules 11.1-11.9: pointer type conversions"
    default_severity = Severity.WARNING
    misra_rules = [RULE_11_1, RULE_11_2, RULE_11_3, RULE_11_4, RULE_11_5, RULE_11_6, RULE_11_7, RULE_11_8, RULE_11_9]

    def __init__(self) -> None:
        super().__init__()
        self._local_types: list[dict[str, dict]] = []

    def visit_FileAST(self, node: c_ast.FileAST) -> None:
        self._local_types = [{}]
        for ext in node.ext or []:
            if isinstance(ext, c_ast.Decl) and ext.name:
                self._local_types[0][ext.name] = _classify(ext.type)
        self.generic_visit(node)
        self._local_types = []

    def visit_FuncDef(self, node: c_ast.FuncDef) -> None:
        scope: dict[str, dict] = {}
        if node.decl and node.decl.type:
            t = node.decl.type
            while isinstance(t, c_ast.PtrDecl):
                t = t.type
            if isinstance(t, c_ast.FuncDecl) and t.args:
                for p in t.args.params or []:
                    if isinstance(p, c_ast.Decl) and p.name:
                        scope[p.name] = _classify(p.type)
        self._local_types.append(scope)
        if node.body:
            self.generic_visit(node.body)
        self._local_types.pop()

    def visit_Decl(self, node: c_ast.Decl) -> None:
        if node.name and self._local_types:
            self._local_types[-1][node.name] = _classify(node.type)
        if node.init:
            self.visit(node.init)

    def visit_Cast(self, node: c_ast.Cast) -> None:
        if node.to_type is None or node.expr is None:
            self.generic_visit(node)
            return

        target = _classify(node.to_type)
        source = self._classify_expr(node.expr) or {"kind": "other"}

        self._check_cast(node, source, target)
        self.generic_visit(node)

    def _classify_expr(self, node: c_ast.Node) -> dict | None:
        result = _classify_expr(node, self._ctx)
        if result is not None:
            return result
        if isinstance(node, c_ast.ID):
            for scope in reversed(self._local_types):
                if node.name in scope:
                    return scope[node.name]
        return None

    def visit_Assignment(self, node: c_ast.Assignment) -> None:
        # 11.9: assigning integer 0 (not NULL macro) to a pointer.
        if isinstance(node.rvalue, c_ast.Constant) and node.rvalue.value == "0":
            if _expr_looks_like_pointer(node.lvalue, self._ctx):
                self.report(
                    node.rvalue,
                    "Use NULL macro instead of integer constant 0 for null pointer",
                    Severity.INFO,
                    RULE_11_9,
                )
        self.generic_visit(node)

    def _check_cast(self, node: c_ast.Cast, src: dict, dst: dict) -> None:
        sk, dk = src.get("kind", "other"), dst.get("kind", "other")

        # 11.1: function pointer <-> non-function-pointer
        if sk == "func_pointer" and dk != "func_pointer":
            self.report(node, "Cast from function pointer to non-function-pointer type", Severity.WARNING, RULE_11_1)
        elif dk == "func_pointer" and sk != "func_pointer":
            self.report(node, "Cast to function pointer from non-function-pointer type", Severity.WARNING, RULE_11_1)

        # 11.3: object pointer to different object pointer (excluding void/char)
        if sk == "object_pointer" and dk == "object_pointer":
            if src.get("base") and dst.get("base") and src["base"] != dst["base"]:
                self.report(
                    node,
                    f"Cast between pointers to different object types ({' '.join(src['base'])} -> {' '.join(dst['base'])})",
                    Severity.WARNING,
                    RULE_11_3,
                )

        # 11.4: pointer <-> integer
        if (sk in ("object_pointer", "void_pointer", "char_pointer") and dk == "int") or \
           (sk == "int" and dk in ("object_pointer", "void_pointer", "char_pointer")):
            self.report(node, "Conversion between pointer and integer type", Severity.WARNING, RULE_11_4)

        # 11.5: void pointer -> object pointer
        if sk == "void_pointer" and dk in ("object_pointer", "char_pointer"):
            self.report(node, "Conversion from pointer-to-void to pointer-to-object", Severity.INFO, RULE_11_5)

        # 11.6: pointer-to-void <-> arithmetic
        if (sk == "void_pointer" and _is_arithmetic_kind(dk)) or \
           (dk == "void_pointer" and _is_arithmetic_kind(sk)):
            self.report(node, "Cast between pointer-to-void and arithmetic type", Severity.ERROR, RULE_11_6)

        # 11.7: object pointer <-> non-integer arithmetic (float)
        if (sk == "object_pointer" and dk == "float") or \
           (sk == "float" and dk == "object_pointer"):
            self.report(node, "Cast between object pointer and floating-point type", Severity.ERROR, RULE_11_7)

        # 11.8: removing const/volatile from pointee
        src_quals = set(src.get("ptr_quals", []))
        dst_quals = set(dst.get("ptr_quals", []))
        removed = src_quals - dst_quals
        if removed and _is_pointer_kind(sk) and _is_pointer_kind(dk):
            self.report(
                node,
                f"Cast removes qualifier(s) {sorted(removed)} from pointed-to type",
                Severity.WARNING,
                RULE_11_8,
            )


def _classify_expr(node: c_ast.Node, ctx) -> dict | None:
    """Best-effort source-side classification (no full type inference)."""
    if isinstance(node, c_ast.Constant):
        if node.type == "int":
            return {"kind": "int", "base": ["int"], "ptr_quals": [], "depth": 0}
        if node.type == "string":
            return {"kind": "char_pointer", "base": ["char"], "ptr_quals": ["const"], "depth": 1}
        if node.type in ("float", "double"):
            return {"kind": "float", "base": [node.type], "ptr_quals": [], "depth": 0}
    if isinstance(node, c_ast.ID) and node.name == "NULL":
        return {"kind": "void_pointer", "base": ["void"], "ptr_quals": [], "depth": 1}
    if isinstance(node, c_ast.Cast):
        return _classify(node.to_type)
    if isinstance(node, c_ast.UnaryOp) and node.op == "&":
        inner = _classify_expr(node.expr, ctx) or {"kind": "object_pointer"}
        return {"kind": "object_pointer", "base": inner.get("base", []), "ptr_quals": [], "depth": 1}
    return None


def _expr_looks_like_pointer(node: c_ast.Node, ctx) -> bool:
    if ctx is None:
        return False
    if isinstance(node, c_ast.ID):
        sym = ctx.symbol_table.lookup(node.name, file=None)
        if sym and "*" in sym.type_str:
            return True
    return False


CheckerRegistry.register(MisraPointerConvChecker)

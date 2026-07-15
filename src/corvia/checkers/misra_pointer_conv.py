"""MISRA C:2012 Section 11: Pointer type conversions.

Implements Rules 11.1-11.9. Most rules involve flagging suspicious explicit
casts; the checker walks every Cast node and inspects source/target types
without attempting full type inference (kept to AST-level heuristics).
"""

from __future__ import annotations

from pycparser import c_ast

from corvia.checkers.base import BaseChecker
from corvia.models import MisraCategory, MisraRule, Severity
from corvia.registry import CheckerRegistry


RULE_11_1 = MisraRule("11.1", MisraCategory.REQUIRED, "Conversions shall not be performed between a pointer to a function and any other type")
RULE_11_2 = MisraRule("11.2", MisraCategory.REQUIRED, "Conversions shall not be performed between a pointer to an incomplete type and any other type")
RULE_11_3 = MisraRule("11.3", MisraCategory.REQUIRED, "A cast shall not be performed between a pointer to object type and a pointer to a different object type")
RULE_11_4 = MisraRule("11.4", MisraCategory.ADVISORY, "A conversion should not be performed between a pointer to object and an integer type")
RULE_11_5 = MisraRule("11.5", MisraCategory.ADVISORY, "A conversion should not be performed from pointer to void into pointer to object")
RULE_11_6 = MisraRule("11.6", MisraCategory.REQUIRED, "A cast shall not be performed between pointer to void and an arithmetic type")
RULE_11_7 = MisraRule("11.7", MisraCategory.REQUIRED, "A cast shall not be performed between pointer to object and a non-integer arithmetic type")
RULE_11_8 = MisraRule("11.8", MisraCategory.REQUIRED, "A cast shall not remove any const or volatile qualification from the type pointed to by a pointer")
RULE_11_9 = MisraRule("11.9", MisraCategory.REQUIRED, "The macro NULL shall be the only permitted form of integer null pointer constant")


def _classify(type_node: c_ast.Node, typedefs: dict[str, dict] | None = None,
              _depth_guard: int = 0) -> dict:
    """Classify a type node into kind + qualifiers + base type names.

    Returns a dict with:
      kind: "pointer" | "func_pointer" | "void_pointer" | "object_pointer" |
            "int" | "float" | "void" | "other"
      base: list of base IdentifierType names
      ptr_quals: list of qualifiers on the pointee (const/volatile)
      depth: pointer depth (0 = not a pointer)
      to_kind: classification of the pointee

    ``typedefs`` maps a typedef name to the classification of its underlying
    type. Many embedded codebases hide pointers behind typedefs (e.g.
    ``typedef struct x *X_PTR``); without resolving them a cast like
    ``(X_PTR)void_ptr`` is misread as an integer conversion, producing false
    11.4/11.6 violations. When a bare identifier names such a typedef, its
    resolved classification is combined with any additional pointer depth.
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
        joined = " ".join(names)

        # Resolve typedefs whose underlying type is itself a pointer, e.g.
        # ``typedef struct timer *TIMER_PTR``. These are the ones that get
        # misclassified as integers. Typedefs that name a plain object/scalar
        # type (``typedef struct A {..} A``) are deliberately NOT rewritten
        # here: the normal handling below already classifies ``A`` / ``A*``
        # correctly and preserves the base name for Rule 11.3.
        if (typedefs is not None and _depth_guard < 16
                and len(names) == 1 and names[0] in typedefs):
            resolved = dict(typedefs[names[0]])
            resolved_kind = resolved.get("kind")
            resolved_depth = resolved.get("depth", 0)
            if resolved_depth >= 1 and resolved_kind in (
                    "void_pointer", "object_pointer", "char_pointer", "func_pointer"):
                out = dict(resolved)
                out["depth"] = depth + resolved_depth
                out["ptr_quals"] = list(dict.fromkeys(quals + resolved.get("ptr_quals", [])))
                if not out.get("base"):
                    out["base"] = [names[0]]
                return out

        info["base"] = names
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


def _is_integer_constant_zero(node: c_ast.Node) -> bool:
    """True when ``node`` is an integer constant literal with value zero.

    Accepts the usual suffixed forms (``0``, ``0U``, ``0L``, ``0UL``,
    ``0x0``, ``00``) but not floating literals (``0.0``) or non-zero values.
    """
    if not isinstance(node, c_ast.Constant) or node.type not in ("int", "char"):
        return False
    text = node.value.strip()
    # Strip a char-constant's quotes conservatively; a char 0 is not a null
    # pointer constant per the strict wording, so only handle integer text.
    if node.type == "char":
        return False
    # Remove integer suffixes (u/U/l/L combinations).
    core = text.rstrip("uUlL")
    if not core:
        return False
    try:
        # int(...,0) understands 0x / 0b / 0o / decimal / leading-zero octal.
        return int(core, 0) == 0
    except ValueError:
        return False


def _is_null_pointer_constant(node: c_ast.Node) -> bool:
    """True when ``node`` is a MISRA null pointer constant.

    Covers the three forms that appear in this codebase (with or without the
    C preprocessor having expanded ``NULL``):
      * the identifier ``NULL``
      * an integer constant expression with value zero (``0``, ``0U``, ...)
      * a cast of an integer constant zero to a pointer type, e.g. ``(void *)0``
        (the common expansion of the ``NULL`` macro)

    Rule 11.6 (and the integer<->pointer conversions 11.4/11.5) explicitly
    exempt the null pointer constant, so a cast whose operand is one of these
    must not be reported.
    """
    if isinstance(node, c_ast.ID) and node.name == "NULL":
        return True
    if _is_integer_constant_zero(node):
        return True
    # ``(void *)0`` / ``(T *)0`` — a pointer-typed cast of integer zero.
    if isinstance(node, c_ast.Cast) and node.to_type is not None:
        t = node.to_type
        if isinstance(t, c_ast.Typename):
            t = t.type
        if isinstance(t, c_ast.PtrDecl) and _is_integer_constant_zero(node.expr):
            return True
    return False


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
        self._typedefs: dict[str, dict] = {}

    def reset(self) -> None:
        self._local_types = []
        self._typedefs = {}

    def _build_typedef_map(self, node: c_ast.FileAST) -> dict[str, dict]:
        """Resolve every typedef to a classification, following typedef chains.

        Built in two phases so that a typedef referring to an earlier typedef
        (e.g. ``typedef X_PTR Y;``) resolves correctly regardless of order.
        """
        raw: dict[str, c_ast.Node] = {}
        for ext in node.ext or []:
            if isinstance(ext, c_ast.Typedef) and ext.name:
                raw[ext.name] = ext.type

        resolved: dict[str, dict] = {}
        # Iterate to a fixpoint: a typedef that refers to another typedef needs
        # the referent resolved first, and declaration order is not guaranteed.
        for _ in range(3):
            for name in raw:
                resolved[name] = _classify(raw[name], resolved)
        return resolved

    def visit_FileAST(self, node: c_ast.FileAST) -> None:
        self._typedefs = self._build_typedef_map(node)
        self._local_types = [{}]
        for ext in node.ext or []:
            if isinstance(ext, c_ast.Decl) and ext.name:
                self._local_types[0][ext.name] = _classify(ext.type, self._typedefs)
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
                        scope[p.name] = _classify(p.type, self._typedefs)
        self._local_types.append(scope)
        if node.body:
            self.generic_visit(node.body)
        self._local_types.pop()

    def visit_Decl(self, node: c_ast.Decl) -> None:
        if node.name and self._local_types:
            self._local_types[-1][node.name] = _classify(node.type, self._typedefs)
        if node.init:
            self.visit(node.init)

    def visit_Cast(self, node: c_ast.Cast) -> None:
        if node.to_type is None or node.expr is None:
            self.generic_visit(node)
            return

        target = _classify(node.to_type, self._typedefs)
        source = self._classify_expr(node.expr) or {"kind": "other"}

        src_is_null = _is_null_pointer_constant(node.expr)
        self._check_cast(node, source, target, src_is_null)
        self.generic_visit(node)

    def _classify_expr(self, node: c_ast.Node) -> dict | None:
        result = _classify_expr(node, self._ctx, self._typedefs)
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

    def _check_cast(self, node: c_ast.Cast, src: dict, dst: dict,
                    src_is_null: bool = False) -> None:
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

        # 11.4: pointer <-> integer. Exempt the null pointer constant: casting
        # NULL / (void*)0 / integer 0 to or from an integer type is not a real
        # pointer<->integer conversion (MISRA exempts the null pointer constant).
        if not src_is_null and (
                (sk in ("object_pointer", "void_pointer", "char_pointer") and dk == "int") or
                (sk == "int" and dk in ("object_pointer", "void_pointer", "char_pointer"))):
            self.report(node, "Conversion between pointer and integer type", Severity.WARNING, RULE_11_4)

        # 11.5: void pointer -> object pointer. A null pointer constant cast to
        # an object pointer (e.g. (T*)NULL) is exempt.
        if not src_is_null and sk == "void_pointer" and dk in ("object_pointer", "char_pointer"):
            self.report(node, "Conversion from pointer-to-void to pointer-to-object", Severity.INFO, RULE_11_5)

        # 11.6: pointer-to-void <-> arithmetic. MISRA C:2012 11.6 explicitly
        # EXEMPTS the null pointer constant, so casts such as (U32)NULL,
        # (uintptr_t)NULL or (void*)0 must not be reported.
        if not src_is_null and (
                (sk == "void_pointer" and _is_arithmetic_kind(dk)) or
                (dk == "void_pointer" and _is_arithmetic_kind(sk))):
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


def _classify_expr(node: c_ast.Node, ctx, typedefs: dict[str, dict] | None = None) -> dict | None:
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
        return _classify(node.to_type, typedefs)
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

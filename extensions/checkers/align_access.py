"""Unaligned memory access checker (external / opt-in).

Targets ARM aarch32 (ARMv7 Cortex-A15) firmware, where an unaligned access to
device or strongly-ordered memory raises an alignment fault regardless of
``SCTLR.A``. The checker flags only what is *statically decidable* from the
AST - the goal is a low false-positive rate, not exhaustive coverage.

Three patterns are reported:

1. A narrow source pointer (``U8*`` / ``U16*`` / ``void*`` / ``char*``) cast to
   a wider pointer (``U32*`` / ``U64*``) and then dereferenced or indexed.
2. A packed-struct member whose byte offset is not a multiple of the access
   width, taken by address and used through a wider pointer.
3. A register-style access ``*(volatile U32 *)(BASE + N)`` where the constant
   offset ``N`` is not a multiple of the access width.

Deliberately NOT reported (measured false-positive sources on real trees):
  * same-width or narrowing casts (``(U32 *)`` applied to an existing ``U32*``)
  * constant offsets that are already a multiple of the access width
  * byte-wise access (``memcpy``/``memset``, ``U8`` loops)

Type widths are configurable so project-specific typedefs (``U32``, ``UINT32``,
``DWORD``, ...) can be mapped without editing this file - see ``TYPE_WIDTHS``
and the ``CORVIA_ALIGN_TYPE_WIDTHS`` environment override.

Load with:  corvia <target> --external-checkers extensions/checkers
"""

from __future__ import annotations

import json
import os
from typing import Optional

from pycparser import c_ast

from corvia.checkers.base import BaseChecker, parse_int_literal
from corvia.models import MisraCategory, MisraRule, Severity
from corvia.registry import CheckerRegistry


# MISRA C:2012 Rule 1.3 - unaligned access through a converted pointer is
# undefined behaviour on targets that fault on it.
RULE_1_3 = MisraRule(
    "1.3", MisraCategory.REQUIRED,
    "There shall be no occurrence of undefined behaviour",
)

# Default width table. Covers the C99 fixed-width names, the Phison SAL
# typedefs (U8/U16/U32/U64 -> uint*_t) and the plain C types.
_DEFAULT_TYPE_WIDTHS: dict[str, int] = {
    # Phison SAL
    "U8": 1, "U16": 2, "U32": 4, "U64": 8,
    "S8": 1, "S16": 2, "S32": 4, "S64": 8,
    "U8_t": 1, "U16_t": 2, "U32_t": 4, "U64_t": 8,
    # C99
    "uint8_t": 1, "uint16_t": 2, "uint32_t": 4, "uint64_t": 8,
    "int8_t": 1, "int16_t": 2, "int32_t": 4, "int64_t": 8,
    # plain C
    "char": 1, "signed char": 1, "unsigned char": 1,
    "short": 2, "unsigned short": 2,
    "int": 4, "unsigned int": 4, "unsigned": 4, "long": 4, "unsigned long": 4,
    "float": 4, "double": 8,
    "long long": 8, "unsigned long long": 8,
}


def _load_type_widths() -> dict[str, int]:
    """Return the type-width map, allowing a project-level override.

    ``CORVIA_ALIGN_TYPE_WIDTHS`` may hold either a JSON object or a path to a
    JSON file mapping type name -> width in bytes. Entries are merged over the
    defaults, so a project only needs to declare the names it adds or changes.
    """
    widths = dict(_DEFAULT_TYPE_WIDTHS)
    raw = os.environ.get("CORVIA_ALIGN_TYPE_WIDTHS")
    if not raw:
        return widths
    try:
        if raw.lstrip().startswith("{"):
            extra = json.loads(raw)
        else:
            with open(raw, "r", encoding="utf-8") as fh:
                extra = json.load(fh)
        for key, val in extra.items():
            widths[str(key)] = int(val)
    except (OSError, ValueError, TypeError):
        # A malformed override must never crash analysis - fall back silently.
        pass
    return widths


TYPE_WIDTHS = _load_type_widths()

# Source types whose pointee is narrower than the access, or whose size is
# unknown. void*/char* carry no alignment guarantee at all.
_OPAQUE_SOURCE_TYPES = {"void", "char", "signed char", "unsigned char"}

# The access widths this checker cares about. Anything <= 2 bytes is not worth
# reporting on a 4-byte-alignment rule.
_MIN_REPORTED_WIDTH = 4


class AlignAccessChecker(BaseChecker):
    """Detect statically-decidable unaligned wide memory accesses."""

    checker_id = "align-access"
    description = (
        "Detects unaligned (non 4-byte) memory access via pointer casts, "
        "packed struct members, and misaligned constant register offsets"
    )
    # Start at WARNING: promote to ERROR per project via
    # [severity] "align-access" = "error" in corvia.toml once the
    # false-positive rate has been measured on the tree.
    default_severity = Severity.WARNING
    misra_rules = [RULE_1_3]

    def __init__(self) -> None:
        super().__init__()
        # name -> pointee type name, for locally declared pointers
        self._ptr_pointee: dict[str, Optional[str]] = {}
        # name -> declared array element type (arrays decay to pointers)
        self._array_elem: dict[str, str] = {}
        # packed struct name -> {member name: (byte offset, type name)}
        self._packed_structs: dict[str, dict[str, tuple[int, str]]] = {}
        # variable name -> packed struct tag it points at / is
        self._packed_vars: dict[str, str] = {}
        # member name -> pointee/element type, for `U8 *start;` style members.
        # Keyed by member name only: struct-tag resolution through typedefs is
        # unreliable here, and a same-named member of a different type would at
        # worst change the reported type string, not create a finding.
        self._member_elem: dict[str, str] = {}
        # dedup: (line, column, kind)
        self._reported: set[tuple[int, int, str]] = set()

    def reset(self) -> None:
        self._ptr_pointee = {}
        self._array_elem = {}
        self._packed_structs = {}
        self._packed_vars = {}
        self._member_elem = {}
        self._reported = set()

    # ---------- helpers -------------------------------------------------

    @staticmethod
    def _type_name(node: c_ast.Node) -> Optional[str]:
        """Return the base type name of a TypeDecl/IdentifierType chain."""
        cur = node
        seen = 0
        while cur is not None and seen < 12:
            seen += 1
            if isinstance(cur, c_ast.IdentifierType):
                return " ".join(cur.names)
            if isinstance(cur, (c_ast.TypeDecl, c_ast.PtrDecl, c_ast.ArrayDecl)):
                cur = cur.type
                continue
            if isinstance(cur, (c_ast.Struct, c_ast.Union)):
                return cur.name
            return None
        return None

    @classmethod
    def _pointer_target_type(cls, typ: c_ast.Node) -> Optional[str]:
        """For a `T *` type node return T's name; None if not a pointer."""
        if isinstance(typ, c_ast.Typename):
            typ = typ.type
        if not isinstance(typ, c_ast.PtrDecl):
            return None
        return cls._type_name(typ.type)

    @staticmethod
    def _width_of(type_name: Optional[str]) -> Optional[int]:
        if not type_name:
            return None
        return TYPE_WIDTHS.get(type_name)

    def _report_once(
        self,
        node: c_ast.Node,
        kind: str,
        message: str,
        severity: Optional[Severity] = None,
    ) -> None:
        line = node.coord.line if node.coord else 0
        col = (node.coord.column or 0) if node.coord else 0
        key = (line, col, kind)
        if key in self._reported:
            return
        self._reported.add(key)
        self.report(node, message, severity, RULE_1_3)

    # ---------- declaration tracking ------------------------------------

    def visit_Struct(self, node: c_ast.Struct) -> None:
        # Record pointer/array member element types for every struct (not just
        # packed ones), so `&s->buf[i]` can resolve `buf`'s element type.
        for decl in node.decls or []:
            if isinstance(decl, c_ast.Decl) and decl.name:
                if isinstance(decl.type, (c_ast.PtrDecl, c_ast.ArrayDecl)):
                    elem = self._type_name(decl.type.type)
                    if elem:
                        self._member_elem[decl.name] = elem

        # Record packed struct layouts so member offsets can be computed.
        # pycparser drops __attribute__ in most configurations, so a struct is
        # treated as packed only when the parser preserved the marker.
        if node.name and node.decls and self._is_packed(node):
            layout: dict[str, tuple[int, str]] = {}
            offset = 0
            ok = True
            for decl in node.decls:
                if not isinstance(decl, c_ast.Decl) or not decl.name:
                    ok = False
                    break
                tname = self._type_name(decl.type)
                width = self._width_of(tname)
                if isinstance(decl.type, c_ast.PtrDecl):
                    width = 4  # aarch32 pointer
                    tname = tname or "void"
                if width is None:
                    ok = False
                    break
                layout[decl.name] = (offset, tname or "")
                offset += width
            if ok and layout:
                self._packed_structs[node.name] = layout
        self.generic_visit(node)

    @staticmethod
    def _is_packed(node: c_ast.Struct) -> bool:
        """Best-effort detection of a packed struct.

        pycparser only exposes attributes when the source was preprocessed in a
        way that keeps them; when unavailable this returns False and pattern 2
        simply does not fire (a miss, never a false positive).
        """
        for attr in ("attributes", "attrspec", "quals"):
            val = getattr(node, attr, None)
            if val and "packed" in str(val):
                return True
        return False

    def visit_Decl(self, node: c_ast.Decl) -> None:
        if node.name:
            if isinstance(node.type, c_ast.PtrDecl):
                self._ptr_pointee[node.name] = self._type_name(node.type.type)
                inner = node.type.type
                if isinstance(inner, c_ast.TypeDecl) and isinstance(inner.type, c_ast.Struct):
                    if inner.type.name:
                        self._packed_vars[node.name] = inner.type.name
            elif isinstance(node.type, c_ast.ArrayDecl):
                elem = self._type_name(node.type.type)
                if elem:
                    self._array_elem[node.name] = elem
            else:
                tname = self._type_name(node.type)
                if tname and tname in self._packed_structs:
                    self._packed_vars[node.name] = tname
        self.generic_visit(node)

    # ---------- pattern 1 & 3: casts ------------------------------------

    def visit_Cast(self, node: c_ast.Cast) -> None:
        target = self._pointer_target_type(node.to_type)
        tgt_width = self._width_of(target)

        if tgt_width is not None and tgt_width >= _MIN_REPORTED_WIDTH:
            # Pattern 3 - constant address/offset arithmetic.
            const_val = self._const_value(node.expr)
            if const_val is not None:
                if const_val % tgt_width != 0:
                    self._report_once(
                        node, "const-offset",
                        f"Unaligned {tgt_width}-byte access: constant address/offset "
                        f"0x{const_val:X} is not a multiple of {tgt_width} "
                        f"(remainder {const_val % tgt_width})",
                        Severity.ERROR,
                    )
            else:
                # Pattern 1 - narrow/opaque source pointer widened by the cast.
                src, detail = self._source_pointee(node.expr)
                if src is not None:
                    src_width = self._width_of(src)
                    narrower = (
                        src in _OPAQUE_SOURCE_TYPES
                        or (src_width is not None and src_width < tgt_width)
                    )
                    if narrower:
                        self._report_once(
                            node, "widening-cast",
                            f"Possible unaligned {tgt_width}-byte access: "
                            f"'{src} *'{detail} cast to '{target} *' - source carries no "
                            f"{tgt_width}-byte alignment guarantee",
                        )
        self.generic_visit(node)

    def _const_value(self, expr: c_ast.Node) -> Optional[int]:
        """Constant-fold +, -, * over integer literals; None if not constant."""
        if isinstance(expr, c_ast.Constant):
            return parse_int_literal(expr.value)
        if isinstance(expr, c_ast.BinaryOp) and expr.op in ("+", "-", "*"):
            left = self._const_value(expr.left)
            right = self._const_value(expr.right)
            if left is None or right is None:
                return None
            if expr.op == "+":
                return left + right
            if expr.op == "-":
                return left - right
            return left * right
        if isinstance(expr, c_ast.UnaryOp) and expr.op == "-":
            inner = self._const_value(expr.expr)
            return None if inner is None else -inner
        return None

    def _source_pointee(self, expr: c_ast.Node) -> tuple[Optional[str], str]:
        """Infer the pointee type of the expression being cast.

        Returns (type name, human-readable detail). A ``None`` type means the
        source could not be resolved - the checker then stays silent rather
        than guessing.
        """
        # &packed_var->member  /  &packed_var.member
        if isinstance(expr, c_ast.UnaryOp) and expr.op == "&":
            inner = expr.expr
            if isinstance(inner, c_ast.StructRef):
                info = self._packed_member(inner)
                if info is not None:
                    offset, mtype, sname = info
                    return mtype, (
                        f" (packed struct '{sname}' member at byte offset {offset})"
                    )
                return (None, "")
            # &buf[i] / &s->buf[i] — taking the address of a narrow element and
            # widening it. This is the dominant real-world form, e.g.
            # `*(U32 *)&log->start[log->offset]`.
            if isinstance(inner, c_ast.ArrayRef):
                elem = self._array_element_type(inner)
                if elem is not None:
                    idx = self._const_value(inner.subscript)
                    if idx is None:
                        return elem, " (element address at a runtime index)"
                    width = self._width_of(elem) or 1
                    return elem, f" (element address at byte offset {idx * width})"
            return (None, "")

        # plain identifier: U8 *p / U8 buf[]
        if isinstance(expr, c_ast.ID):
            if expr.name in self._ptr_pointee:
                return self._ptr_pointee[expr.name], ""
            if expr.name in self._array_elem:
                return self._array_elem[expr.name], " (array)"
            return (None, "")

        # pointer arithmetic: p + 1, buf + off
        if isinstance(expr, c_ast.BinaryOp) and expr.op in ("+", "-"):
            for side in (expr.left, expr.right):
                src, _ = self._source_pointee(side)
                if src is not None:
                    other = expr.right if side is expr.left else expr.left
                    off = self._const_value(other)
                    width = self._width_of(src) or 1
                    if off is not None:
                        byte_off = off * width
                        return src, f" (offset {byte_off} bytes from base)"
                    return src, " (non-constant pointer arithmetic)"
        return (None, "")

    def _array_element_type(self, ref: c_ast.ArrayRef) -> Optional[str]:
        """Element type of `buf[i]`, `s->buf[i]` or `s.buf[i]`; None if unknown."""
        base = ref.name
        if isinstance(base, c_ast.ID):
            return self._array_elem.get(base.name) or self._ptr_pointee.get(base.name)
        if isinstance(base, c_ast.StructRef) and isinstance(base.field, c_ast.ID):
            return self._member_elem.get(base.field.name)
        return None

    def _packed_member(
        self, ref: c_ast.StructRef
    ) -> Optional[tuple[int, str, str]]:
        """Resolve a StructRef to (byte offset, member type, struct name)."""
        if not isinstance(ref.name, c_ast.ID) or not isinstance(ref.field, c_ast.ID):
            return None
        struct_name = self._packed_vars.get(ref.name.name)
        if struct_name is None:
            return None
        layout = self._packed_structs.get(struct_name)
        if not layout:
            return None
        entry = layout.get(ref.field.name)
        if entry is None:
            return None
        offset, mtype = entry
        return offset, mtype, struct_name

    # ---------- pattern 2: packed member taken by address ---------------

    def visit_UnaryOp(self, node: c_ast.UnaryOp) -> None:
        # &packed->member where the member is itself wide and misaligned,
        # even without an explicit cast (it may be passed to a U32* parameter).
        if node.op == "&" and isinstance(node.expr, c_ast.StructRef):
            info = self._packed_member(node.expr)
            if info is not None:
                offset, mtype, sname = info
                width = self._width_of(mtype)
                if (
                    width is not None
                    and width >= _MIN_REPORTED_WIDTH
                    and offset % width != 0
                ):
                    self._report_once(
                        node, "packed-member",
                        f"Address of packed struct '{sname}' member "
                        f"'{node.expr.field.name}' ({mtype}, byte offset {offset}) "
                        f"is not {width}-byte aligned",
                        Severity.ERROR,
                    )
        self.generic_visit(node)


CheckerRegistry.register(AlignAccessChecker)

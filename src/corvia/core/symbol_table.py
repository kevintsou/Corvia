"""Cross-file symbol table for inter-procedural analysis.

The symbol table is built in a single pass over all parsed ASTs and provides
unified lookup across:
  - Global functions and variables
  - File-local (static) symbols
  - Typedefs and tag names (struct/union/enum)
  - Function-local declarations (parameters + body locals)

Designed to be consumed by checkers via AnalysisContext.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional

from pycparser import c_ast


SymbolKind = str  # "function" | "variable" | "typedef" | "tag" | "param"


@dataclass
class Symbol:
    name: str
    kind: SymbolKind
    type_str: str
    file: str
    line: int
    column: int = 0
    is_static: bool = False
    is_extern: bool = False
    is_const: bool = False
    is_definition: bool = True
    storage_class: str = ""
    scope: str = "global"
    enclosing_func: Optional[str] = None
    ast_node: Optional[c_ast.Node] = None

    @property
    def qualified_name(self) -> str:
        if self.is_static or self.scope != "global":
            return f"{self.file}::{self.name}"
        return self.name


@dataclass
class FunctionSymbol(Symbol):
    return_type: str = ""
    params: list[Symbol] = field(default_factory=list)
    is_variadic: bool = False
    body_node: Optional[c_ast.FuncDef] = None

    def __post_init__(self) -> None:
        if self.kind != "function":
            self.kind = "function"


@dataclass
class TagSymbol(Symbol):
    tag_kind: str = "struct"  # "struct" | "union" | "enum"
    members: list[str] = field(default_factory=list)


def _format_type(node: Optional[c_ast.Node]) -> str:
    if node is None:
        return ""
    if isinstance(node, c_ast.IdentifierType):
        return " ".join(node.names)
    if isinstance(node, c_ast.TypeDecl):
        return _format_type(node.type)
    if isinstance(node, c_ast.PtrDecl):
        return _format_type(node.type) + "*"
    if isinstance(node, c_ast.ArrayDecl):
        return _format_type(node.type) + "[]"
    if isinstance(node, c_ast.FuncDecl):
        ret = _format_type(node.type)
        return f"{ret}(...)"
    if isinstance(node, c_ast.Struct):
        return f"struct {node.name or '<anon>'}"
    if isinstance(node, c_ast.Union):
        return f"union {node.name or '<anon>'}"
    if isinstance(node, c_ast.Enum):
        return f"enum {node.name or '<anon>'}"
    return type(node).__name__


def _coord(node: c_ast.Node) -> tuple[int, int]:
    if node and node.coord:
        return (node.coord.line or 0, node.coord.column or 0)
    return (0, 0)


def _actual_file(filename: str, node: c_ast.Node) -> str:
    """Return the actual source file where a declaration physically lives.

    When --use-cpp is active the AST contains nodes from every #included
    header.  After _remap_ast, coord.file reflects the real origin (e.g.
    ``arm_acle.h``, ``<built-in>``).  We use that instead of the top-level
    .c filename so that cross-file uniqueness rules (5.8, 5.9 …) do not
    confuse header-defined symbols with symbols authored in the .c file.

    Paths starting with ``<`` (e.g. ``<built-in>``, ``<command-line>``) are
    treated as non-user files and are returned as-is so callers can detect
    them cheaply with a ``startswith('<')`` check.
    """
    if node and node.coord and node.coord.file:
        cf = node.coord.file
        # Only override when coord points somewhere other than the analysed file.
        if cf != filename:
            return cf
    return filename


def _has_storage(decl: c_ast.Decl, name: str) -> bool:
    return name in (decl.storage or [])


def _get_underlying_func_decl(node: c_ast.Node) -> Optional[c_ast.FuncDecl]:
    if isinstance(node, c_ast.FuncDecl):
        return node
    if isinstance(node, c_ast.PtrDecl):
        return _get_underlying_func_decl(node.type)
    if isinstance(node, c_ast.TypeDecl):
        return _get_underlying_func_decl(node.type)
    return None


class SymbolTable:
    """Unified symbol table across all analyzed files."""

    def __init__(self) -> None:
        self.globals: dict[str, Symbol] = {}
        self.file_locals: dict[str, dict[str, Symbol]] = {}
        self.functions: dict[str, FunctionSymbol] = {}
        self.typedefs: dict[str, str] = {}
        self.tags: dict[str, TagSymbol] = {}
        self._all_decls: list[Symbol] = []

    def add(self, sym: Symbol) -> None:
        self._all_decls.append(sym)

        if sym.kind == "function" and isinstance(sym, FunctionSymbol):
            existing = self.functions.get(sym.name)
            if existing is None or (sym.is_definition and not existing.is_definition):
                self.functions[sym.name] = sym

        if sym.scope == "global":
            if sym.is_static:
                self.file_locals.setdefault(sym.file, {})[sym.name] = sym
            else:
                if sym.name not in self.globals or sym.is_definition:
                    self.globals[sym.name] = sym

    def add_typedef(self, name: str, underlying: str) -> None:
        self.typedefs[name] = underlying

    def add_tag(self, tag: TagSymbol) -> None:
        self.tags[f"{tag.tag_kind} {tag.name}"] = tag

    def lookup(self, name: str, file: Optional[str] = None) -> Optional[Symbol]:
        if file and file in self.file_locals and name in self.file_locals[file]:
            return self.file_locals[file][name]
        return self.globals.get(name)

    def lookup_function(self, name: str) -> Optional[FunctionSymbol]:
        return self.functions.get(name)

    def all_definitions_of(self, name: str) -> list[Symbol]:
        return [s for s in self._all_decls if s.name == name and s.is_definition]

    def all_declarations_of(self, name: str) -> list[Symbol]:
        return [s for s in self._all_decls if s.name == name]

    def has_static_collision(self, name: str) -> list[str]:
        """Returns files where a static symbol with this name exists."""
        return [f for f, syms in self.file_locals.items() if name in syms]

    def all_functions(self) -> Iterable[FunctionSymbol]:
        return self.functions.values()


class SymbolTableBuilder:
    """Builds a SymbolTable from a collection of (file, AST) pairs."""

    def __init__(self) -> None:
        self.table = SymbolTable()

    def build(self, asts: dict[str, c_ast.FileAST]) -> SymbolTable:
        for filename, ast in asts.items():
            if ast is None:
                continue
            self._visit_file(filename, ast)
        return self.table

    def _visit_file(self, filename: str, ast: c_ast.FileAST) -> None:
        for ext in ast.ext or []:
            if isinstance(ext, c_ast.FuncDef):
                self._handle_funcdef(filename, ext)
            elif isinstance(ext, c_ast.Decl):
                self._handle_top_decl(filename, ext)
            elif isinstance(ext, c_ast.Typedef):
                self._handle_typedef(filename, ext)

    def _handle_funcdef(self, filename: str, node: c_ast.FuncDef) -> None:
        decl = node.decl
        if decl is None or decl.name is None:
            return

        actual_file = _actual_file(filename, decl)
        line, col = _coord(decl)
        func_decl = _get_underlying_func_decl(decl.type)
        ret_type = ""
        params: list[Symbol] = []
        is_variadic = False

        if func_decl is not None:
            ret_type = _format_type(func_decl.type)
            if func_decl.args is not None:
                for p in func_decl.args.params or []:
                    if isinstance(p, c_ast.EllipsisParam):
                        is_variadic = True
                        continue
                    if isinstance(p, c_ast.Decl) and p.name:
                        pline, pcol = _coord(p)
                        params.append(
                            Symbol(
                                name=p.name,
                                kind="param",
                                type_str=_format_type(p.type),
                                file=filename,
                                line=pline,
                                column=pcol,
                                scope="function",
                                enclosing_func=decl.name,
                                ast_node=p,
                            )
                        )

        sym = FunctionSymbol(
            name=decl.name,
            kind="function",
            type_str=ret_type,
            file=actual_file,
            line=line,
            column=col,
            is_static=_has_storage(decl, "static"),
            is_extern=_has_storage(decl, "extern"),
            is_definition=True,
            scope="global",
            ast_node=decl,
            return_type=ret_type,
            params=params,
            is_variadic=is_variadic,
            body_node=node,
        )
        self.table.add(sym)

    def _handle_top_decl(self, filename: str, decl: c_ast.Decl) -> None:
        if decl.name is None:
            self._handle_anonymous_tag(filename, decl)
            return

        func_decl = _get_underlying_func_decl(decl.type)
        if func_decl is not None:
            self._handle_func_declaration(filename, decl, func_decl)
            return

        actual_file = _actual_file(filename, decl)
        line, col = _coord(decl)
        sym = Symbol(
            name=decl.name,
            kind="variable",
            type_str=_format_type(decl.type),
            file=actual_file,
            line=line,
            column=col,
            is_static=_has_storage(decl, "static"),
            is_extern=_has_storage(decl, "extern"),
            is_const="const" in (decl.quals or []),
            is_definition=not _has_storage(decl, "extern"),
            storage_class=" ".join(decl.storage or []),
            scope="global",
            ast_node=decl,
        )
        self.table.add(sym)
        self._maybe_record_tag(filename, decl.type)

    def _handle_func_declaration(
        self, filename: str, decl: c_ast.Decl, func_decl: c_ast.FuncDecl
    ) -> None:
        actual_file = _actual_file(filename, decl)
        line, col = _coord(decl)
        ret_type = _format_type(func_decl.type)
        params: list[Symbol] = []
        is_variadic = False

        if func_decl.args is not None:
            for p in func_decl.args.params or []:
                if isinstance(p, c_ast.EllipsisParam):
                    is_variadic = True
                    continue
                if isinstance(p, c_ast.Decl):
                    pline, pcol = _coord(p)
                    params.append(
                        Symbol(
                            name=p.name or "",
                            kind="param",
                            type_str=_format_type(p.type),
                            file=filename,
                            line=pline,
                            column=pcol,
                            scope="function",
                            enclosing_func=decl.name,
                            ast_node=p,
                        )
                    )

        sym = FunctionSymbol(
            name=decl.name,
            kind="function",
            type_str=ret_type,
            file=actual_file,
            line=line,
            column=col,
            is_static=_has_storage(decl, "static"),
            is_extern=_has_storage(decl, "extern"),
            is_definition=False,
            scope="global",
            ast_node=decl,
            return_type=ret_type,
            params=params,
            is_variadic=is_variadic,
            body_node=None,
        )
        self.table.add(sym)

    def _handle_typedef(self, filename: str, node: c_ast.Typedef) -> None:
        if node.name:
            self.table.add_typedef(node.name, _format_type(node.type))
        self._maybe_record_tag(filename, node.type)

    def _handle_anonymous_tag(self, filename: str, decl: c_ast.Decl) -> None:
        self._maybe_record_tag(filename, decl.type)

    def _maybe_record_tag(self, filename: str, type_node: c_ast.Node) -> None:
        if isinstance(type_node, c_ast.TypeDecl):
            self._maybe_record_tag(filename, type_node.type)
        elif isinstance(type_node, (c_ast.Struct, c_ast.Union, c_ast.Enum)):
            if type_node.name:
                tag_kind = (
                    "struct" if isinstance(type_node, c_ast.Struct)
                    else "union" if isinstance(type_node, c_ast.Union)
                    else "enum"
                )
                line, col = _coord(type_node)
                members: list[str] = []
                if isinstance(type_node, (c_ast.Struct, c_ast.Union)) and type_node.decls:
                    members = [d.name for d in type_node.decls if d.name]
                elif isinstance(type_node, c_ast.Enum) and type_node.values:
                    members = [e.name for e in type_node.values.enumerators or [] if e.name]

                tag = TagSymbol(
                    name=type_node.name,
                    kind="tag",
                    type_str=f"{tag_kind} {type_node.name}",
                    file=filename,
                    line=line,
                    column=col,
                    scope="global",
                    ast_node=type_node,
                    tag_kind=tag_kind,
                    members=members,
                )
                self.table.add_tag(tag)


def build_symbol_table(asts: dict[str, c_ast.FileAST]) -> SymbolTable:
    return SymbolTableBuilder().build(asts)

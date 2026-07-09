"""Serialize the SymbolTable + CallGraph into a JSON-able dict.

This is a thin exporter over structures the engine already builds during
its two-pass analysis. It exists so external tools can consume Corvia's
whole-program view without re-parsing C themselves — in particular the
multi-agent code-review skill uses it for dependency-aware batching and
cross-file context augmentation when a target is too large to review in
one context window.

The exporter adds no analysis of its own; it only reshapes existing data.
"""

from __future__ import annotations

from typing import Optional

from pycparser import c_ast

from corvia.core.call_graph import CallGraph
from corvia.core.symbol_table import FunctionSymbol, SymbolTable

SCHEMA_VERSION = 1


def _end_line(node: Optional[c_ast.Node]) -> Optional[int]:
    """Best-effort last source line of a function body.

    pycparser coords mark node *start* lines only, so we take the maximum
    start line over the whole body subtree. This slightly undershoots the
    closing brace but is a good enough hint for a consumer that wants to
    slice the function's source out of the file.
    """
    max_line = 0

    def walk(n: Optional[c_ast.Node]) -> None:
        nonlocal max_line
        if n is None:
            return
        if n.coord and n.coord.line:
            max_line = max(max_line, n.coord.line)
        for _, child in n.children():
            walk(child)

    walk(node)
    return max_line or None


def _signature(fn: FunctionSymbol) -> str:
    parts: list[str] = []
    for p in fn.params:
        type_str = (p.type_str or "").strip()
        if p.name:
            parts.append(f"{type_str} {p.name}".strip())
        elif type_str:
            parts.append(type_str)
    if fn.is_variadic:
        parts.append("...")
    param_str = ", ".join(parts) if parts else "void"
    prefix = "static " if fn.is_static else ""
    ret = (fn.return_type or "").strip()
    ret = f"{ret} " if ret else ""
    return f"{prefix}{ret}{fn.name}({param_str})"


def serialize_symbol_graph(
    symbol_table: SymbolTable,
    call_graph: CallGraph,
    asts: dict[str, c_ast.FileAST],
) -> dict:
    """Return a JSON-able dict describing every function definition, the
    call edges between them, and which callees have no definition in the
    analyzed set (i.e. cross-translation-unit / external references).

    Definition locations are taken from the *parsed translation unit* (the
    ``asts`` key) rather than from ``Symbol.file``: under --use-cpp the
    symbol table's file/line can be remapped onto an included header (that
    remap serves MISRA cross-TU rules, but here it would mis-attribute a
    body to the header that declared it). The asts key is the authoritative
    ``.c`` file a body was physically parsed from — the same source the call
    graph uses for its edges. Line numbers remain best-effort under cpp; a
    consumer that needs an exact slice should locate the body by signature
    within ``file`` rather than trusting ``line`` blindly.
    """

    files = list(asts.keys())
    functions: list[dict] = []
    defined_names: set[str] = set()
    nonstatic_defined: set[str] = set()
    static_defined: set[tuple[str, str]] = set()

    for filename, ast in asts.items():
        if ast is None:
            continue
        for ext in ast.ext or []:
            if not isinstance(ext, c_ast.FuncDef) or not ext.decl or not ext.decl.name:
                continue
            name = ext.decl.name
            is_static = "static" in (ext.decl.storage or [])
            # Non-static: first translation unit to define a name wins
            # (avoids duplicating header-inlined definitions once per
            # includer). Static definitions are file-scoped, so an
            # identically-named static in a *different* file is a distinct
            # function and gets its own entry — its `file` field carries
            # the qualification while the JSON schema stays unchanged.
            if is_static:
                if (filename, name) in static_defined:
                    continue
                static_defined.add((filename, name))
            else:
                if name in nonstatic_defined:
                    continue
                nonstatic_defined.add(name)
            defined_names.add(name)
            line = ext.decl.coord.line if ext.decl.coord else 0
            fn = symbol_table.lookup_function(name, file=filename)
            functions.append(
                {
                    "name": name,
                    "file": filename,
                    "line": line,
                    "end_line": _end_line(ext),
                    "signature": _signature(fn) if fn else f"{name}(...)",
                    "return_type": (fn.return_type or "") if fn else "",
                    "is_static": fn.is_static if fn else False,
                    "params": (
                        [{"name": p.name, "type": p.type_str} for p in fn.params]
                        if fn
                        else []
                    ),
                    "callees": call_graph.callees_of(name),
                }
            )

    functions.sort(key=lambda e: (e["file"], e["line"], e["name"]))

    call_edges = [
        {
            "caller": site.caller,
            "callee": site.callee,
            "file": site.file,
            "line": site.line,
        }
        for sites in call_graph.edges.values()
        for site in sites
    ]
    call_edges.sort(key=lambda e: (e["file"], e["line"], e["caller"], e["callee"]))

    # Callees that are referenced but never defined in the analyzed set —
    # these are the cross-file/external calls a batched reviewer must be
    # warned about, since their definition lives outside any single batch.
    unresolved = sorted(n for n in call_graph.nodes if n not in defined_names)

    # Convenience index for dependency-aware batching: file -> functions it defines.
    file_defines: dict[str, list[str]] = {}
    for fn_entry in functions:
        file_defines.setdefault(fn_entry["file"], []).append(fn_entry["name"])

    return {
        "schema_version": SCHEMA_VERSION,
        "files": sorted(str(f) for f in files),
        "functions": functions,
        "call_edges": call_edges,
        "unresolved_callees": unresolved,
        "file_defines": file_defines,
    }

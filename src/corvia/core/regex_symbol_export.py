"""Best-effort symbol graph extraction for parser-hostile C files.

This is intentionally narrower than Corvia's AST-based symbol table. It is a
last-resort aid for review/batching workflows when vendor macros, target-only
headers, or conditional compilation prevent pycparser from building an AST.
"""

from __future__ import annotations

import re
from pathlib import Path

from corvia.parser import _strip_comments


_FUNC_DEF_RE = re.compile(
    r"(?ms)^"
    r"[ \t]*(?P<prefix>[A-Za-z_][\w\s\*\(\),\[\]]*?[ \t\*]+)"
    r"(?P<name>[A-Za-z_]\w*)[ \t]*"
    r"\((?P<params>[^;{}]*)\)[ \t\r\n]*"
    r"(?:[A-Za-z_][\w\s\(\),]*[ \t\r\n]*)?"
    r"\{"
)
_CALL_RE = re.compile(r"\b([A-Za-z_]\w*)\s*\(")
_DIRECTIVE_RE = re.compile(r"^[ \t]*#[^\n]*(?:\n|$)", re.MULTILINE)
_WS_RE = re.compile(r"\s+")
_CONTROL_NAMES = {
    "if",
    "for",
    "while",
    "switch",
    "return",
    "sizeof",
    "case",
}


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _find_matching_brace(text: str, open_idx: int) -> int:
    depth = 0
    i = open_idx
    while i < len(text):
        ch = text[i]
        if ch in ("'", '"'):
            quote = ch
            i += 1
            while i < len(text):
                if text[i] == "\\":
                    i += 2
                    continue
                if text[i] == quote:
                    break
                i += 1
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return len(text) - 1


def _clean_type(value: str) -> str:
    value = value.replace("\n", " ")
    value = _WS_RE.sub(" ", value)
    return value.strip()


def _split_params(params: str) -> list[dict]:
    params = _clean_type(params)
    if not params or params == "void":
        return []
    out: list[dict] = []
    for raw in params.split(","):
        part = _clean_type(raw)
        if not part or part == "...":
            continue
        m = re.search(r"([A-Za-z_]\w*)\s*(?:\[[^\]]*\])?$", part)
        if m:
            name = m.group(1)
            typ = part[:m.start(1)].strip()
            out.append({"name": name, "type": typ or part})
        else:
            out.append({"name": "", "type": part})
    return out


def extract_regex_symbol_graph(files: list[str]) -> dict:
    functions: list[dict] = []
    call_edges: list[dict] = []
    defined: set[tuple[str, str]] = set()
    called_names: set[str] = set()

    for filename in files:
        try:
            raw = Path(filename).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        text = _DIRECTIVE_RE.sub("\n", _strip_comments(raw))
        for m in _FUNC_DEF_RE.finditer(text):
            name = m.group("name")
            if name in _CONTROL_NAMES or (filename, name) in defined:
                continue
            prefix = _clean_type(m.group("prefix"))
            if not prefix or "=" in prefix:
                continue

            open_idx = text.find("{", m.end() - 1)
            if open_idx < 0:
                continue
            close_idx = _find_matching_brace(text, open_idx)
            line = _line_of(text, m.start("name"))
            end_line = _line_of(text, close_idx)
            body = text[open_idx + 1:close_idx]

            is_static = bool(re.search(r"\bstatic\b", prefix))
            return_type = _clean_type(re.sub(r"\bstatic\b|\binline\b|\bextern\b", "", prefix))
            params = _split_params(m.group("params"))
            param_sig = ", ".join(
                f"{p['type']} {p['name']}".strip() for p in params
            ) or "void"
            storage = "static " if is_static else ""

            callees: list[str] = []
            for cm in _CALL_RE.finditer(body):
                callee = cm.group(1)
                if callee in _CONTROL_NAMES or callee == name:
                    continue
                if callee not in callees:
                    callees.append(callee)
                called_names.add(callee)
                call_edges.append(
                    {
                        "caller": name,
                        "callee": callee,
                        "file": filename,
                        "line": _line_of(text, open_idx + 1 + cm.start(1)),
                    }
                )

            defined.add((filename, name))
            functions.append(
                {
                    "name": name,
                    "file": filename,
                    "line": line,
                    "end_line": end_line,
                    "signature": f"{storage}{return_type} {name}({param_sig})".strip(),
                    "return_type": return_type,
                    "is_static": is_static,
                    "params": params,
                    "callees": callees,
                }
            )

    defined_names = {name for _, name in defined}
    file_defines: dict[str, list[str]] = {}
    for fn in functions:
        file_defines.setdefault(fn["file"], []).append(fn["name"])

    return {
        "schema_version": 1,
        "files": sorted(files),
        "functions": sorted(functions, key=lambda e: (e["file"], e["line"], e["name"])),
        "call_edges": sorted(call_edges, key=lambda e: (e["file"], e["line"], e["caller"], e["callee"])),
        "unresolved_callees": sorted(called_names - defined_names),
        "file_defines": file_defines,
    }


def merge_symbol_graphs(primary: dict, fallback: dict) -> dict:
    merged = dict(primary)
    merged["files"] = sorted(set(primary.get("files", [])) | set(fallback.get("files", [])))

    seen_functions = {
        (fn.get("file"), fn.get("name")) for fn in primary.get("functions", [])
    }
    functions = list(primary.get("functions", []))
    for fn in fallback.get("functions", []):
        key = (fn.get("file"), fn.get("name"))
        if key not in seen_functions:
            seen_functions.add(key)
            functions.append(fn)
    functions.sort(key=lambda e: (e["file"], e["line"], e["name"]))
    merged["functions"] = functions

    seen_edges = {
        (e.get("caller"), e.get("callee"), e.get("file"), e.get("line"))
        for e in primary.get("call_edges", [])
    }
    call_edges = list(primary.get("call_edges", []))
    for edge in fallback.get("call_edges", []):
        key = (edge.get("caller"), edge.get("callee"), edge.get("file"), edge.get("line"))
        if key not in seen_edges:
            seen_edges.add(key)
            call_edges.append(edge)
    call_edges.sort(key=lambda e: (e["file"], e["line"], e["caller"], e["callee"]))
    merged["call_edges"] = call_edges

    defined = {fn["name"] for fn in functions}
    called = {edge["callee"] for edge in call_edges}
    merged["unresolved_callees"] = sorted(called - defined)

    file_defines: dict[str, list[str]] = {}
    for fn in functions:
        file_defines.setdefault(fn["file"], []).append(fn["name"])
    merged["file_defines"] = file_defines
    return merged

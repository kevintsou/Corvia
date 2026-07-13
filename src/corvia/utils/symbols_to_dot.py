"""Convert a Corvia symbol graph (--emit-symbols JSON) into Graphviz DOT or
Mermaid text for visualization.

Usage:
    corvia-graph symbols.json -o graph.dot
    corvia-graph symbols.json --format mermaid -o graph.mmd
    corvia-graph symbols.json --focus main --depth 2 -o main_graph.dot

DOT output renders with Graphviz (``dot -Tsvg graph.dot -o graph.svg``);
Mermaid output can be pasted directly into GitLab/GitHub markdown.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import deque
from pathlib import Path


def _load(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        raise SystemExit(f"Error: '{path}' not found.")
    except json.JSONDecodeError as e:
        raise SystemExit(f"Error: '{path}' is not valid JSON: {e}")
    for key in ("functions", "call_edges"):
        if key not in data:
            raise SystemExit(
                f"Error: '{path}' does not look like a Corvia symbol graph "
                f"(missing '{key}'). Generate one with: corvia <target> "
                f"--emit-symbols symbols.json -o findings.json"
            )
    return data


def _focus_subset(edges: list[dict], focus: str, depth: int) -> set[str]:
    """BFS outward from `focus` in both call directions up to `depth` hops."""
    fwd: dict[str, set[str]] = {}
    rev: dict[str, set[str]] = {}
    for e in edges:
        fwd.setdefault(e["caller"], set()).add(e["callee"])
        rev.setdefault(e["callee"], set()).add(e["caller"])
    keep = {focus}
    frontier = deque([(focus, 0)])
    while frontier:
        node, d = frontier.popleft()
        if d >= depth:
            continue
        for nxt in fwd.get(node, ()) | rev.get(node, ()):
            if nxt not in keep:
                keep.add(nxt)
                frontier.append((nxt, d + 1))
    return keep


def _sanitize(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", name)


def render_dot(data: dict, keep: set[str] | None) -> str:
    functions = {f["name"]: f for f in data["functions"]}
    unresolved = set(data.get("unresolved_callees", []))
    edges = data["call_edges"]

    by_file: dict[str, list[dict]] = {}
    for fn in data["functions"]:
        if keep is None or fn["name"] in keep:
            by_file.setdefault(fn["file"], []).append(fn)

    lines = [
        "digraph corvia_callgraph {",
        "  rankdir=LR;",
        '  node [shape=box, style="rounded,filled", fillcolor="#e8f0fe", fontname="Consolas"];',
        '  edge [color="#5f6368"];',
    ]
    for idx, (file, fns) in enumerate(sorted(by_file.items())):
        lines.append(f'  subgraph cluster_{idx} {{')
        lines.append(f'    label="{Path(file).name}"; color="#9aa0a6"; fontname="Consolas";')
        for fn in fns:
            style = ', style="rounded,filled,dashed"' if fn.get("is_static") else ""
            lines.append(f'    "{fn["name"]}" [tooltip="{fn.get("signature", "")}"{style}];')
        lines.append("  }")

    drawn_unresolved: set[str] = set()
    drawn_edges: set[tuple[str, str]] = set()
    for e in edges:
        caller, callee = e["caller"], e["callee"]
        if keep is not None and (caller not in keep or callee not in keep):
            continue
        if (caller, callee) in drawn_edges:
            continue  # multiple call sites collapse into one visual edge
        drawn_edges.add((caller, callee))
        if callee in unresolved and callee not in functions:
            if callee not in drawn_unresolved:
                lines.append(
                    f'  "{callee}" [fillcolor="#f1f3f4", style="filled,dashed", color="#9aa0a6"];'
                )
                drawn_unresolved.add(callee)
        lines.append(f'  "{caller}" -> "{callee}";')
    lines.append("}")
    return "\n".join(lines) + "\n"


def render_mermaid(data: dict, keep: set[str] | None) -> str:
    functions = {f["name"]: f for f in data["functions"]}
    unresolved = set(data.get("unresolved_callees", []))
    lines = ["flowchart LR"]
    declared: set[str] = set()

    def declare(name: str) -> str:
        nid = _sanitize(name)
        if name not in declared:
            declared.add(name)
            if name in unresolved and name not in functions:
                lines.append(f'    {nid}["{name} (external)"]:::ext')
            else:
                lines.append(f'    {nid}["{name}"]')
        return nid

    drawn_edges: set[tuple[str, str]] = set()
    for e in data["call_edges"]:
        caller, callee = e["caller"], e["callee"]
        if keep is not None and (caller not in keep or callee not in keep):
            continue
        if (caller, callee) in drawn_edges:
            continue  # multiple call sites collapse into one visual edge
        drawn_edges.add((caller, callee))
        lines.append(f"    {declare(caller)} --> {declare(callee)}")
    lines.append("    classDef ext fill:#f1f3f4,stroke:#9aa0a6,stroke-dasharray:3;")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="corvia-graph",
        description="Render a Corvia --emit-symbols JSON as Graphviz DOT or Mermaid.",
    )
    parser.add_argument("symbols", help="Path to the symbol graph JSON (from --emit-symbols)")
    parser.add_argument("-o", "--output", help="Output file (default: stdout)")
    parser.add_argument(
        "-f", "--format", choices=["dot", "mermaid"], default="dot",
        help="Output format (default: dot)",
    )
    parser.add_argument(
        "--focus", metavar="FUNC",
        help="Only show FUNC and its callers/callees within --depth hops",
    )
    parser.add_argument(
        "--depth", type=int, default=2,
        help="Hop distance for --focus (default: 2)",
    )
    args = parser.parse_args(argv)

    data = _load(args.symbols)

    keep: set[str] | None = None
    if args.focus:
        names = {f["name"] for f in data["functions"]}
        if args.focus not in names:
            candidates = [n for n in sorted(names) if args.focus.lower() in n.lower()]
            hint = f" Did you mean: {', '.join(candidates[:5])}?" if candidates else ""
            raise SystemExit(f"Error: function '{args.focus}' not found in the graph.{hint}")
        keep = _focus_subset(data["call_edges"], args.focus, args.depth)

    text = render_dot(data, keep) if args.format == "dot" else render_mermaid(data, keep)

    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
        edge_count = len({
            (e["caller"], e["callee"]) for e in data["call_edges"]
            if keep is None or (e["caller"] in keep and e["callee"] in keep)
        })
        print(f"{args.format} graph written to {args.output} "
              f"({edge_count} edges)", file=sys.stderr)
        if args.format == "dot":
            print(f"Render with: dot -Tsvg {args.output} -o graph.svg", file=sys.stderr)
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())

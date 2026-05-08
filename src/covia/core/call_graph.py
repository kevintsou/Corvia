"""Call graph construction for inter-procedural analysis.

The call graph records, for every analyzed file, every static call site
(`FuncCall` whose callee is a plain `c_ast.ID`). It exposes traversal
helpers used by the summary computer to schedule analysis bottom-up
and to detect (mutual) recursion.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from pycparser import c_ast

from covia.core.symbol_table import SymbolTable


@dataclass
class CallSite:
    caller: str
    callee: str
    file: str
    line: int
    column: int = 0
    ast_node: Optional[c_ast.FuncCall] = None


@dataclass
class CallGraph:
    nodes: set[str] = field(default_factory=set)
    edges: dict[str, list[CallSite]] = field(default_factory=dict)
    reverse_edges: dict[str, list[CallSite]] = field(default_factory=dict)

    def add_call(self, site: CallSite) -> None:
        self.nodes.add(site.caller)
        self.nodes.add(site.callee)
        self.edges.setdefault(site.caller, []).append(site)
        self.reverse_edges.setdefault(site.callee, []).append(site)

    def callees_of(self, func: str) -> list[str]:
        return sorted({s.callee for s in self.edges.get(func, [])})

    def callers_of(self, func: str) -> list[str]:
        return sorted({s.caller for s in self.reverse_edges.get(func, [])})

    def call_sites_of(self, callee: str) -> list[CallSite]:
        return list(self.reverse_edges.get(callee, []))

    def is_recursive(self, func: str) -> bool:
        if func in self.callees_of(func):
            return True
        for scc in self.strongly_connected_components():
            if func in scc and len(scc) > 1:
                return True
        return False

    def topological_order(self) -> list[str]:
        """Return functions in reverse-postorder over SCCs (callees before callers).

        Mutual recursion forms a cycle which is condensed into a single SCC;
        within the SCC the order is arbitrary.
        """
        order: list[str] = []
        sccs = self.strongly_connected_components()
        for scc in sccs:
            for n in sorted(scc):
                order.append(n)
        return order

    def strongly_connected_components(self) -> list[set[str]]:
        """Tarjan's SCC algorithm. Returns SCCs in reverse topological order
        (callees first, suitable for bottom-up summary computation)."""
        index_counter = [0]
        stack: list[str] = []
        on_stack: set[str] = set()
        index: dict[str, int] = {}
        lowlink: dict[str, int] = {}
        result: list[set[str]] = []

        def strongconnect(v: str) -> None:
            index[v] = index_counter[0]
            lowlink[v] = index_counter[0]
            index_counter[0] += 1
            stack.append(v)
            on_stack.add(v)

            for w in self.callees_of(v):
                if w not in index:
                    strongconnect(w)
                    lowlink[v] = min(lowlink[v], lowlink[w])
                elif w in on_stack:
                    lowlink[v] = min(lowlink[v], index[w])

            if lowlink[v] == index[v]:
                component: set[str] = set()
                while True:
                    w = stack.pop()
                    on_stack.discard(w)
                    component.add(w)
                    if w == v:
                        break
                result.append(component)

        for node in sorted(self.nodes):
            if node not in index:
                strongconnect(node)

        return result


class CallGraphBuilder:
    """Walks each FuncDef body and records every FuncCall whose callee
    is a known function (resolvable via SymbolTable)."""

    def __init__(self, symbol_table: SymbolTable) -> None:
        self.symbol_table = symbol_table
        self.graph = CallGraph()

    def build(self, asts: dict[str, c_ast.FileAST]) -> CallGraph:
        for func in self.symbol_table.all_functions():
            if func.is_definition:
                self.graph.nodes.add(func.name)

        for filename, ast in asts.items():
            if ast is None:
                continue
            for ext in ast.ext or []:
                if isinstance(ext, c_ast.FuncDef) and ext.decl and ext.decl.name:
                    self._scan_body(filename, ext.decl.name, ext.body)
        return self.graph

    def _scan_body(self, filename: str, caller: str, body: Optional[c_ast.Node]) -> None:
        if body is None:
            return
        for call in self._iter_func_calls(body):
            if isinstance(call.name, c_ast.ID):
                callee = call.name.name
                line = call.coord.line if call.coord else 0
                col = call.coord.column or 0 if call.coord else 0
                site = CallSite(
                    caller=caller,
                    callee=callee,
                    file=filename,
                    line=line,
                    column=col,
                    ast_node=call,
                )
                self.graph.add_call(site)

    def _iter_func_calls(self, node: c_ast.Node):
        if isinstance(node, c_ast.FuncCall):
            yield node
        for _, child in node.children():
            yield from self._iter_func_calls(child)


def build_call_graph(
    asts: dict[str, c_ast.FileAST], symbol_table: SymbolTable
) -> CallGraph:
    return CallGraphBuilder(symbol_table).build(asts)

"""Function summaries for inter-procedural analysis.

A FunctionSummary captures the externally observable behaviour of a function
that downstream checkers care about, so a checker analyzing `f` does not need
to re-analyze every callee. Summaries are computed bottom-up over the
call graph's SCC topological order. Recursive cycles are resolved by a small
fixpoint iteration over the SCC.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from pycparser import c_ast

from corvia.core.call_graph import CallGraph
from corvia.core.symbol_table import FunctionSymbol, SymbolTable


class TriState(Enum):
    NO = "no"
    YES = "yes"
    MAYBE = "maybe"


_ALLOC_FUNCS = {"malloc", "calloc", "realloc", "aligned_alloc", "strdup"}
_FREE_FUNCS = {"free"}
_OPEN_FUNCS = {"fopen", "tmpfile", "fdopen", "freopen", "popen"}
_CLOSE_FUNCS = {"fclose", "pclose"}


@dataclass
class FunctionSummary:
    func_name: str

    # Null-deref related
    params_must_not_be_null: set[int] = field(default_factory=set)
    returns_null: TriState = TriState.MAYBE

    # Memory / resource related
    allocates: bool = False
    transfers_ownership: bool = False
    frees_param: set[int] = field(default_factory=set)
    closes_param: set[int] = field(default_factory=set)
    opens_resource: bool = False

    # Side-effects
    has_side_effects: bool = False
    modifies_globals: set[str] = field(default_factory=set)

    # MISRA 17.7
    return_value_used_internally: bool = False

    # Uninitialized output parameters (Rule 9.1)
    output_params_not_initialized: set[int] = field(default_factory=set)

    # Pointer parameters the function writes through (*p = ... / p->f = ...),
    # i.e. out-parameters that initialize the caller's object (Rule 9.1).
    output_params_initialized: set[int] = field(default_factory=set)

    # Bookkeeping
    is_external: bool = False  # True for known stdlib / unresolved
    is_recursive: bool = False


class _SummaryComputer:
    def __init__(
        self,
        symbol_table: SymbolTable,
        call_graph: CallGraph,
        asts: dict[str, c_ast.FileAST],
    ) -> None:
        self.symbol_table = symbol_table
        self.call_graph = call_graph
        self.asts = asts
        self.summaries: dict[str, FunctionSummary] = {}

    def compute_all(self) -> dict[str, FunctionSummary]:
        for name in _ALLOC_FUNCS:
            s = FunctionSummary(func_name=name, is_external=True, allocates=True, transfers_ownership=True)
            s.returns_null = TriState.MAYBE
            self.summaries[name] = s
        for name in _FREE_FUNCS:
            s = FunctionSummary(func_name=name, is_external=True, has_side_effects=True)
            s.frees_param.add(0)
            self.summaries[name] = s
        for name in _OPEN_FUNCS:
            s = FunctionSummary(func_name=name, is_external=True, opens_resource=True, transfers_ownership=True)
            s.returns_null = TriState.MAYBE
            self.summaries[name] = s
        for name in _CLOSE_FUNCS:
            s = FunctionSummary(func_name=name, is_external=True, has_side_effects=True)
            s.closes_param.add(0)
            self.summaries[name] = s

        sccs = self.call_graph.strongly_connected_components()

        for scc in sccs:
            self._compute_scc(scc)

        for func in self.symbol_table.all_functions():
            if func.name not in self.summaries:
                self.summaries[func.name] = self._compute_one(func, recursive=False)

        return self.summaries

    def _compute_scc(self, scc: set[str]) -> None:
        # Known limitation: summaries are keyed by bare function name (the
        # call graph's node naming), so identically-named static functions
        # in different files share one summary — the body found via
        # lookup_function(name) wins. File-aware resolution is available
        # via SymbolTable.lookup_function(name, file=...), but adopting it
        # here would require qualified call-graph nodes, which would break
        # the public schema and checker lookups.
        for name in scc:
            if name in self.summaries and self.summaries[name].is_external:
                continue
            func = self.symbol_table.lookup_function(name)
            if func is None or func.body_node is None:
                if name not in self.summaries:
                    self.summaries[name] = FunctionSummary(func_name=name, is_external=True)
                continue
            self.summaries[name] = FunctionSummary(
                func_name=name,
                is_recursive=(len(scc) > 1 or name in self.call_graph.callees_of(name)),
            )

        for _ in range(3):
            changed = False
            for name in sorted(scc):
                if name in self.summaries and self.summaries[name].is_external:
                    continue
                func = self.symbol_table.lookup_function(name)
                if func is None or func.body_node is None:
                    continue
                new_summary = self._compute_one(
                    func,
                    recursive=(len(scc) > 1 or name in self.call_graph.callees_of(name)),
                )
                if self._summaries_differ(self.summaries[name], new_summary):
                    self.summaries[name] = new_summary
                    changed = True
            if not changed:
                break

    def _summaries_differ(self, a: FunctionSummary, b: FunctionSummary) -> bool:
        return (
            a.allocates != b.allocates
            or a.transfers_ownership != b.transfers_ownership
            or a.opens_resource != b.opens_resource
            or a.returns_null != b.returns_null
            or a.frees_param != b.frees_param
            or a.closes_param != b.closes_param
            or a.has_side_effects != b.has_side_effects
            or a.modifies_globals != b.modifies_globals
            or a.params_must_not_be_null != b.params_must_not_be_null
            or a.output_params_not_initialized != b.output_params_not_initialized
        )

    def _compute_one(self, func: FunctionSymbol, recursive: bool) -> FunctionSummary:
        summary = FunctionSummary(func_name=func.name, is_recursive=recursive)
        body = func.body_node.body if func.body_node else None
        if body is None:
            summary.is_external = True
            return summary

        param_index = {p.name: i for i, p in enumerate(func.params)}

        analyzer = _BodyAnalyzer(
            param_index=param_index,
            param_names=set(param_index),
            summaries=self.summaries,
        )
        analyzer.walk(body)

        summary.allocates = analyzer.returns_allocated
        summary.transfers_ownership = analyzer.returns_allocated
        summary.opens_resource = analyzer.returns_opened
        summary.returns_null = analyzer.returns_null_state
        summary.frees_param = analyzer.frees_param
        summary.closes_param = analyzer.closes_param
        summary.has_side_effects = analyzer.has_side_effects
        summary.modifies_globals = analyzer.modifies_globals
        summary.params_must_not_be_null = analyzer.params_dereffed_unconditionally
        summary.return_value_used_internally = analyzer.return_value_used
        summary.output_params_not_initialized = analyzer.output_params_not_initialized
        summary.output_params_initialized = analyzer.output_params_written

        return summary


class _BodyAnalyzer:
    """Single-function body walker that conservatively extracts summary facts."""

    def __init__(
        self,
        param_index: dict[str, int],
        param_names: set[str],
        summaries: dict[str, FunctionSummary],
    ) -> None:
        self.param_index = param_index
        self.param_names = param_names
        self.summaries = summaries

        self.returns_allocated = False
        self.returns_opened = False
        self.returns_null_state = TriState.NO
        self.has_returns = False
        self.frees_param: set[int] = set()
        self.closes_param: set[int] = set()
        self.has_side_effects = False
        self.modifies_globals: set[str] = set()
        self.params_dereffed_unconditionally: set[int] = set()
        self.return_value_used = False

        self._allocated_locals: set[str] = set()
        self._opened_locals: set[str] = set()
        self.output_params_not_initialized: set[int] = set()
        self.output_params_written: set[int] = set()
        self._param_initialized: dict[int, bool] = {i: False for i in param_index.values()}

    def walk(self, node: c_ast.Node) -> None:
        if isinstance(node, c_ast.Decl) and node.name and node.init:
            self._track_init(node.name, node.init)

        elif isinstance(node, c_ast.Assignment):
            if isinstance(node.lvalue, c_ast.ID):
                name = node.lvalue.name
                if self._is_alloc_call(node.rvalue):
                    self._allocated_locals.add(name)
                if self._is_open_call(node.rvalue):
                    self._opened_locals.add(name)
            if isinstance(node.lvalue, c_ast.UnaryOp) and node.lvalue.op == "*":
                # *p = ...   -> writes through pointer param p
                self._mark_param_initialized(node.lvalue.expr)
            elif isinstance(node.lvalue, c_ast.StructRef) and node.lvalue.type == "->":
                # p->field = ...  -> writes through pointer param p
                self._mark_param_initialized(node.lvalue.name)
            elif isinstance(node.lvalue, c_ast.ArrayRef):
                # p[i] = ...  -> writes through pointer/array param p
                self._mark_param_initialized(node.lvalue.name)
            self.has_side_effects = True

        elif isinstance(node, c_ast.FuncCall):
            self._track_call(node)

        elif isinstance(node, c_ast.Return):
            first_return = not self.has_returns
            self.has_returns = True
            for idx in self._param_initialized:
                if not self._param_initialized[idx]:
                    self.output_params_not_initialized.add(idx)
            if node.expr is None:
                pass
            elif self._is_null(node.expr):
                if self.returns_null_state == TriState.NO and first_return:
                    self.returns_null_state = TriState.YES
                else:
                    self.returns_null_state = TriState.MAYBE
            else:
                if self._is_alloc_call(node.expr):
                    self.returns_allocated = True
                if self._is_open_call(node.expr):
                    self.returns_opened = True
                if isinstance(node.expr, c_ast.ID):
                    if node.expr.name in self._allocated_locals:
                        self.returns_allocated = True
                    if node.expr.name in self._opened_locals:
                        self.returns_opened = True
                if self.returns_null_state == TriState.YES:
                    self.returns_null_state = TriState.MAYBE

        elif isinstance(node, c_ast.UnaryOp) and node.op == "*":
            if isinstance(node.expr, c_ast.ID) and node.expr.name in self.param_index:
                self.params_dereffed_unconditionally.add(self.param_index[node.expr.name])

        elif isinstance(node, c_ast.StructRef) and node.type == "->":
            if isinstance(node.name, c_ast.ID) and node.name.name in self.param_index:
                self.params_dereffed_unconditionally.add(self.param_index[node.name.name])

        for _, child in node.children():
            self.walk(child)

    def _track_init(self, var_name: str, init: c_ast.Node) -> None:
        if self._is_alloc_call(init):
            self._allocated_locals.add(var_name)
        if self._is_open_call(init):
            self._opened_locals.add(var_name)

    def _mark_param_initialized(self, node: c_ast.Node) -> None:
        if isinstance(node, c_ast.ID) and node.name in self.param_index:
            idx = self.param_index[node.name]
            self._param_initialized[idx] = True
            self.output_params_written.add(idx)

    def _track_call(self, call: c_ast.FuncCall) -> None:
        self.has_side_effects = True
        if not isinstance(call.name, c_ast.ID):
            return

        callee = call.name.name
        summary = self.summaries.get(callee)
        if summary is None:
            return

        if call.args and call.args.exprs:
            for idx, arg in enumerate(call.args.exprs):
                if isinstance(arg, c_ast.ID) and arg.name in self.param_index:
                    pidx = self.param_index[arg.name]
                    if idx in summary.frees_param:
                        self.frees_param.add(pidx)
                    if idx in summary.closes_param:
                        self.closes_param.add(pidx)

    def _is_alloc_call(self, node: c_ast.Node) -> bool:
        if isinstance(node, c_ast.FuncCall) and isinstance(node.name, c_ast.ID):
            s = self.summaries.get(node.name.name)
            return bool(s and s.allocates)
        if isinstance(node, c_ast.Cast) and node.expr:
            return self._is_alloc_call(node.expr)
        return False

    def _is_open_call(self, node: c_ast.Node) -> bool:
        if isinstance(node, c_ast.FuncCall) and isinstance(node.name, c_ast.ID):
            s = self.summaries.get(node.name.name)
            return bool(s and s.opens_resource)
        if isinstance(node, c_ast.Cast) and node.expr:
            return self._is_open_call(node.expr)
        return False

    def _is_null(self, node: c_ast.Node) -> bool:
        if isinstance(node, c_ast.Constant):
            return node.value in ("0", "NULL", "((void *)0)")
        if isinstance(node, c_ast.ID):
            return node.name == "NULL"
        if isinstance(node, c_ast.Cast):
            return self._is_null(node.expr)
        return False


def compute_summaries(
    symbol_table: SymbolTable,
    call_graph: CallGraph,
    asts: dict[str, c_ast.FileAST],
) -> dict[str, FunctionSummary]:
    return _SummaryComputer(symbol_table, call_graph, asts).compute_all()

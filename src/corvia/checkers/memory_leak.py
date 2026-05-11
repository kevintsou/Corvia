"""Memory leak checker using CFG-based analysis."""

from __future__ import annotations

from pycparser import c_ast

from corvia.checkers.base import BaseChecker
from corvia.core.cfg import CFG, BasicBlock, build_cfg
from corvia.core.dataflow import ForwardAnalysis
from corvia.models import MisraCategory, MisraRule, Severity
from corvia.registry import CheckerRegistry

RULE_22_1 = MisraRule("22.1", MisraCategory.REQUIRED, "All resources obtained dynamically by means of Standard Library functions shall be explicitly released")
RULE_22_2 = MisraRule("22.2", MisraCategory.MANDATORY, "A block of memory shall only be freed if it was allocated by means of a Standard Library memory allocation function")

_ALLOC_FUNCS = {"malloc", "calloc", "realloc", "aligned_alloc"}
_FREE_FUNCS = {"free"}


def _looks_like_alloc(name: str, ctx) -> bool:
    if name in _ALLOC_FUNCS:
        return True
    if ctx is None:
        return False
    s = ctx.summary_of(name)
    return bool(s and s.allocates)


def _looks_like_free(name: str, ctx) -> bool:
    if name in _FREE_FUNCS:
        return True
    if ctx is None:
        return False
    s = ctx.summary_of(name)
    return bool(s and s.frees_param)


class _AllocState:
    """Tracks which variables hold allocated memory."""

    def __init__(self, allocated: set[str] | None = None, freed: set[str] | None = None) -> None:
        self.allocated: set[str] = set(allocated) if allocated else set()
        self.freed: set[str] = set(freed) if freed else set()

    def copy(self) -> _AllocState:
        return _AllocState(self.allocated, self.freed)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, _AllocState):
            return NotImplemented
        return self.allocated == other.allocated and self.freed == other.freed


class _MemoryLeakAnalysis(ForwardAnalysis[_AllocState]):
    def __init__(self, ctx=None) -> None:
        self.ctx = ctx

    def initial_state(self) -> _AllocState:
        return _AllocState()

    def entry_state(self) -> _AllocState:
        return _AllocState()

    def transfer(self, block: BasicBlock, in_state: _AllocState) -> _AllocState:
        state = in_state.copy()
        for stmt in block.statements:
            self._process_stmt(stmt, state)
        return state

    def merge(self, states: list[_AllocState]) -> _AllocState:
        if not states:
            return _AllocState()
        allocated_union: set[str] = set()
        freed_intersect: set[str] | None = None
        for s in states:
            allocated_union |= s.allocated
            if freed_intersect is None:
                freed_intersect = set(s.freed)
            else:
                freed_intersect &= s.freed
        return _AllocState(allocated_union, freed_intersect or set())

    def equal(self, a: _AllocState, b: _AllocState) -> bool:
        return a == b

    def _process_stmt(self, stmt: c_ast.Node, state: _AllocState) -> None:
        if isinstance(stmt, c_ast.Decl) and stmt.name and stmt.init:
            if self._is_alloc_call(stmt.init):
                state.allocated.add(stmt.name)
                state.freed.discard(stmt.name)

        elif isinstance(stmt, c_ast.Assignment):
            if isinstance(stmt.lvalue, c_ast.ID):
                name = stmt.lvalue.name
                if self._is_alloc_call(stmt.rvalue):
                    state.allocated.add(name)
                    state.freed.discard(name)
                elif name in state.allocated and name not in state.freed:
                    pass

        elif isinstance(stmt, c_ast.FuncCall):
            if self._is_free_call(stmt):
                if stmt.args and stmt.args.exprs:
                    for arg in stmt.args.exprs:
                        if isinstance(arg, c_ast.ID):
                            state.freed.add(arg.name)

    def _is_alloc_call(self, node: c_ast.Node) -> bool:
        if isinstance(node, c_ast.FuncCall):
            if isinstance(node.name, c_ast.ID):
                return _looks_like_alloc(node.name.name, self.ctx)
        if isinstance(node, c_ast.Cast) and node.expr:
            return self._is_alloc_call(node.expr)
        return False

    def _is_free_call(self, node: c_ast.FuncCall) -> bool:
        if isinstance(node.name, c_ast.ID):
            return _looks_like_free(node.name.name, self.ctx)
        return False


class MemoryLeakChecker(BaseChecker):
    checker_id = "memory-leak"
    description = "Detects memory leaks (malloc without free) using CFG analysis"
    default_severity = Severity.WARNING
    misra_rules = [RULE_22_1, RULE_22_2]

    def visit_FuncDef(self, node: c_ast.FuncDef) -> None:
        if node.body is None or node.body.block_items is None:
            return

        has_alloc = self._has_alloc_calls(node.body)
        if not has_alloc:
            return

        cfg = build_cfg(node)
        analysis = _MemoryLeakAnalysis(ctx=self._ctx)
        results = analysis.analyze(cfg)

        exit_state_pair = results.get(cfg.exit.id)
        if exit_state_pair:
            in_state, _ = exit_state_pair
            leaked = in_state.allocated - in_state.freed
            for var_name in sorted(leaked):
                alloc_node = self._find_alloc_node(node.body, var_name)
                report_node = alloc_node or node.decl or node
                self.report(
                    report_node,
                    f"Potential memory leak: '{var_name}' allocated but not freed on all paths",
                    Severity.WARNING,
                    RULE_22_1,
                )

        for block in cfg.blocks:
            state_pair = results.get(block.id)
            if state_pair:
                _, out_state = state_pair
                for var_name in out_state.freed:
                    if var_name not in out_state.allocated:
                        free_node = self._find_free_node(block, var_name)
                        if free_node:
                            self.report(
                                free_node,
                                f"Freeing '{var_name}' which was not dynamically allocated",
                                Severity.ERROR,
                                RULE_22_2,
                            )

    def _has_alloc_calls(self, node: c_ast.Node) -> bool:
        if isinstance(node, c_ast.FuncCall) and isinstance(node.name, c_ast.ID):
            n = node.name.name
            if n in _ALLOC_FUNCS | _FREE_FUNCS:
                return True
            if self._ctx is not None:
                s = self._ctx.summary_of(n)
                if s and (s.allocates or s.frees_param):
                    return True
        for _, child in node.children():
            if self._has_alloc_calls(child):
                return True
        return False

    def _find_alloc_node(self, body: c_ast.Node, var_name: str) -> c_ast.Node | None:
        if isinstance(body, c_ast.Decl) and body.name == var_name and body.init:
            return body
        if isinstance(body, c_ast.Assignment):
            if isinstance(body.lvalue, c_ast.ID) and body.lvalue.name == var_name:
                return body
        for _, child in body.children():
            result = self._find_alloc_node(child, var_name)
            if result:
                return result
        return None

    def _find_free_node(self, block: BasicBlock, var_name: str) -> c_ast.Node | None:
        for stmt in block.statements:
            if isinstance(stmt, c_ast.FuncCall):
                if isinstance(stmt.name, c_ast.ID) and stmt.name.name in _FREE_FUNCS:
                    if stmt.args and stmt.args.exprs:
                        for arg in stmt.args.exprs:
                            if isinstance(arg, c_ast.ID) and arg.name == var_name:
                                return stmt
        return None


CheckerRegistry.register(MemoryLeakChecker)

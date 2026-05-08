"""Resource leak checker using CFG-based analysis (fopen/fclose, etc.)."""

from __future__ import annotations

from pycparser import c_ast

from corvia.checkers.base import BaseChecker
from corvia.core.cfg import build_cfg
from corvia.core.dataflow import ForwardAnalysis
from corvia.core.cfg import BasicBlock
from corvia.models import MisraCategory, MisraRule, Severity
from corvia.registry import CheckerRegistry

RULE_22_1 = MisraRule("22.1", MisraCategory.REQUIRED, "All resources obtained dynamically by means of Standard Library functions shall be explicitly released")
RULE_22_6 = MisraRule("22.6", MisraCategory.MANDATORY, "The value of a pointer to a FILE shall not be used after the associated stream has been closed")

_OPEN_FUNCS = {"fopen", "tmpfile", "fdopen", "freopen", "popen"}
_CLOSE_FUNCS = {"fclose", "pclose"}


def _looks_like_open(name: str, ctx) -> bool:
    if name in _OPEN_FUNCS:
        return True
    if ctx is None:
        return False
    s = ctx.summary_of(name)
    return bool(s and s.opens_resource)


def _looks_like_close(name: str, ctx) -> bool:
    if name in _CLOSE_FUNCS:
        return True
    if ctx is None:
        return False
    s = ctx.summary_of(name)
    return bool(s and s.closes_param)


class _ResourceState:
    def __init__(self, opened: set[str] | None = None, closed: set[str] | None = None) -> None:
        self.opened: set[str] = set(opened) if opened else set()
        self.closed: set[str] = set(closed) if closed else set()

    def copy(self) -> _ResourceState:
        return _ResourceState(self.opened, self.closed)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, _ResourceState):
            return NotImplemented
        return self.opened == other.opened and self.closed == other.closed


class _ResourceAnalysis(ForwardAnalysis[_ResourceState]):
    def __init__(self, ctx=None) -> None:
        self.ctx = ctx

    def initial_state(self) -> _ResourceState:
        return _ResourceState()

    def entry_state(self) -> _ResourceState:
        return _ResourceState()

    def transfer(self, block: BasicBlock, in_state: _ResourceState) -> _ResourceState:
        state = in_state.copy()
        for stmt in block.statements:
            self._process_stmt(stmt, state)
        return state

    def merge(self, states: list[_ResourceState]) -> _ResourceState:
        if not states:
            return _ResourceState()
        opened: set[str] = set()
        closed: set[str] | None = None
        for s in states:
            opened |= s.opened
            if closed is None:
                closed = set(s.closed)
            else:
                closed &= s.closed
        return _ResourceState(opened, closed or set())

    def equal(self, a: _ResourceState, b: _ResourceState) -> bool:
        return a == b

    def _process_stmt(self, stmt: c_ast.Node, state: _ResourceState) -> None:
        if isinstance(stmt, c_ast.Decl) and stmt.name and stmt.init:
            if self._is_open_call(stmt.init):
                state.opened.add(stmt.name)
                state.closed.discard(stmt.name)

        elif isinstance(stmt, c_ast.Assignment):
            if isinstance(stmt.lvalue, c_ast.ID):
                if self._is_open_call(stmt.rvalue):
                    state.opened.add(stmt.lvalue.name)
                    state.closed.discard(stmt.lvalue.name)

        elif isinstance(stmt, c_ast.FuncCall):
            if self._is_close_call(stmt) and stmt.args and stmt.args.exprs:
                for arg in stmt.args.exprs:
                    if isinstance(arg, c_ast.ID):
                        state.closed.add(arg.name)

    def _is_open_call(self, node: c_ast.Node) -> bool:
        if isinstance(node, c_ast.FuncCall) and isinstance(node.name, c_ast.ID):
            return _looks_like_open(node.name.name, self.ctx)
        if isinstance(node, c_ast.Cast) and node.expr:
            return self._is_open_call(node.expr)
        return False

    def _is_close_call(self, node: c_ast.FuncCall) -> bool:
        if isinstance(node.name, c_ast.ID):
            return _looks_like_close(node.name.name, self.ctx)
        return False


class ResourceLeakChecker(BaseChecker):
    checker_id = "resource-leak"
    description = "Detects resource leaks (fopen without fclose) using CFG analysis"
    default_severity = Severity.WARNING
    misra_rules = [RULE_22_1, RULE_22_6]

    def visit_FuncDef(self, node: c_ast.FuncDef) -> None:
        if node.body is None or node.body.block_items is None:
            return

        if not self._has_resource_calls(node.body):
            return

        cfg = build_cfg(node)
        analysis = _ResourceAnalysis(ctx=self._ctx)
        results = analysis.analyze(cfg)

        exit_pair = results.get(cfg.exit.id)
        if exit_pair:
            in_state, _ = exit_pair
            leaked = in_state.opened - in_state.closed
            for var_name in sorted(leaked):
                alloc_node = self._find_open_node(node.body, var_name)
                report_node = alloc_node or node.decl or node
                self.report(
                    report_node,
                    f"Potential resource leak: file handle '{var_name}' opened but not closed on all paths",
                    Severity.WARNING,
                    RULE_22_1,
                )

        self._check_use_after_close(cfg, results, node)

    def _check_use_after_close(self, cfg, results, func_node) -> None:
        for block in cfg.blocks:
            pair = results.get(block.id)
            if not pair:
                continue
            in_state, _ = pair
            closed = set(in_state.closed)
            for stmt in block.statements:
                if isinstance(stmt, c_ast.FuncCall) and stmt.args:
                    if isinstance(stmt.name, c_ast.ID) and _looks_like_close(stmt.name.name, self._ctx):
                        for arg in stmt.args.exprs or []:
                            if isinstance(arg, c_ast.ID):
                                closed.add(arg.name)
                        continue
                    for arg in stmt.args.exprs or []:
                        if isinstance(arg, c_ast.ID) and arg.name in closed:
                            self.report(
                                stmt,
                                f"Use of file handle '{arg.name}' after it has been closed",
                                Severity.ERROR,
                                RULE_22_6,
                            )

    def _has_resource_calls(self, node: c_ast.Node) -> bool:
        if isinstance(node, c_ast.FuncCall) and isinstance(node.name, c_ast.ID):
            n = node.name.name
            if n in _OPEN_FUNCS | _CLOSE_FUNCS:
                return True
            if self._ctx is not None:
                s = self._ctx.summary_of(n)
                if s and (s.opens_resource or s.closes_param):
                    return True
        for _, child in node.children():
            if self._has_resource_calls(child):
                return True
        return False

    def _find_open_node(self, body: c_ast.Node, var_name: str) -> c_ast.Node | None:
        if isinstance(body, c_ast.Decl) and body.name == var_name:
            return body
        if isinstance(body, c_ast.Assignment) and isinstance(body.lvalue, c_ast.ID):
            if body.lvalue.name == var_name:
                return body
        for _, child in body.children():
            result = self._find_open_node(child, var_name)
            if result:
                return result
        return None


CheckerRegistry.register(ResourceLeakChecker)

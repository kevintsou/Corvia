"""Null pointer dereference checker with CFG-based cross-branch analysis."""

from __future__ import annotations

from pycparser import c_ast

from corvia.checkers.base import BaseChecker
from corvia.core.cfg import BasicBlock, build_cfg
from corvia.core.dataflow import ForwardAnalysis
from corvia.models import MisraCategory, MisraRule, Severity
from corvia.registry import CheckerRegistry

RULE_1_3 = MisraRule("1.3", MisraCategory.REQUIRED, "There shall be no occurrence of undefined behaviour")


def _is_null(node: c_ast.Node) -> bool:
    if isinstance(node, c_ast.Constant):
        return node.value in ("0", "NULL", "((void *)0)")
    if isinstance(node, c_ast.ID):
        return node.name == "NULL"
    if isinstance(node, c_ast.Cast):
        return _is_null(node.expr)
    return False


def _callee_returns_null(rvalue: c_ast.Node, ctx) -> bool:
    """If the rvalue is a FuncCall to a function whose summary says it may
    return NULL, treat the assigned variable as definitely-NULL for analysis."""
    if ctx is None:
        return False
    target = rvalue
    if isinstance(target, c_ast.Cast) and target.expr is not None:
        target = target.expr
    if isinstance(target, c_ast.FuncCall) and isinstance(target.name, c_ast.ID):
        return ctx.function_returns_null(target.name.name)
    return False


class _NullState:
    """null_vars: definitely NULL, nonnull_vars: definitely not NULL."""

    def __init__(
        self,
        null_vars: set[str] | None = None,
        nonnull_vars: set[str] | None = None,
    ) -> None:
        self.null_vars: set[str] = set(null_vars) if null_vars else set()
        self.nonnull_vars: set[str] = set(nonnull_vars) if nonnull_vars else set()

    def copy(self) -> _NullState:
        return _NullState(self.null_vars, self.nonnull_vars)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, _NullState):
            return NotImplemented
        return self.null_vars == other.null_vars and self.nonnull_vars == other.nonnull_vars


class _NullAnalysis(ForwardAnalysis[_NullState]):
    def __init__(self, ctx=None) -> None:
        self.deref_issues: list[tuple[c_ast.Node, str]] = []
        self.ctx = ctx

    def initial_state(self) -> _NullState:
        return _NullState()

    def entry_state(self) -> _NullState:
        return _NullState()

    def transfer(self, block: BasicBlock, in_state: _NullState) -> _NullState:
        state = in_state.copy()
        for stmt in block.statements:
            self._process_stmt(stmt, state)
        return state

    def merge(self, states: list[_NullState]) -> _NullState:
        if not states:
            return _NullState()
        null_union: set[str] = set()
        nonnull_intersect: set[str] | None = None
        for s in states:
            null_union |= s.null_vars
            if nonnull_intersect is None:
                nonnull_intersect = set(s.nonnull_vars)
            else:
                nonnull_intersect &= s.nonnull_vars
        result_null = null_union - (nonnull_intersect or set())
        return _NullState(result_null, nonnull_intersect or set())

    def equal(self, a: _NullState, b: _NullState) -> bool:
        return a == b

    def _process_stmt(self, stmt: c_ast.Node, state: _NullState) -> None:
        if isinstance(stmt, c_ast.Decl) and stmt.name:
            if stmt.init and _is_null(stmt.init):
                state.null_vars.add(stmt.name)
                state.nonnull_vars.discard(stmt.name)
            elif stmt.init and _callee_returns_null(stmt.init, self.ctx):
                self._check_deref_expr(stmt.init, state)
                state.null_vars.add(stmt.name)
                state.nonnull_vars.discard(stmt.name)
            elif stmt.init:
                self._check_deref_expr(stmt.init, state)
                state.null_vars.discard(stmt.name)
                state.nonnull_vars.add(stmt.name)

        elif isinstance(stmt, c_ast.Assignment):
            self._check_deref_expr(stmt.rvalue, state)
            if isinstance(stmt.lvalue, c_ast.ID):
                name = stmt.lvalue.name
                if _is_null(stmt.rvalue):
                    state.null_vars.add(name)
                    state.nonnull_vars.discard(name)
                elif _callee_returns_null(stmt.rvalue, self.ctx):
                    state.null_vars.add(name)
                    state.nonnull_vars.discard(name)
                else:
                    state.null_vars.discard(name)
                    state.nonnull_vars.add(name)
            else:
                self._check_deref_expr(stmt.lvalue, state)

        elif isinstance(stmt, c_ast.FuncCall):
            if stmt.args:
                for arg in stmt.args.exprs or []:
                    self._check_deref_expr(arg, state)

        elif isinstance(stmt, c_ast.Return):
            if isinstance(stmt, c_ast.Return) and stmt.expr:
                self._check_deref_expr(stmt.expr, state)

        elif isinstance(stmt, c_ast.BinaryOp):
            # When the CFG condition block contains a null comparison, update
            # state conservatively so downstream blocks don't produce false
            # positives.  We mark the variable as non-null for != NULL (also
            # narrowing through && chains, e.g. `p != NULL && p->x`).
            #
            # NOTE: there is deliberately NO narrowing for `== NULL`.  The
            # transfer function applies to a block whose state flows into
            # BOTH successors; adding the variable to null_vars here would
            # poison the fall-through branch too, so
            # `if (p == NULL) { return -1; } *p = 5;` would falsely report.
            # Implementing `==` narrowing correctly requires per-edge
            # (per-successor) dataflow states, which this framework does not
            # provide yet.
            if stmt.op in ("!=", "&&"):
                self._narrow_nonnull(stmt, state)
            else:
                self._check_deref_expr(stmt, state)

        else:
            self._check_deref_expr(stmt, state)

    def _narrow_nonnull(self, expr: c_ast.Node, state: _NullState) -> None:
        """Apply `!= NULL` narrowing, recursing through `&&` chains.

        In a compound guard like `p != NULL && count > 0`, all conjuncts are
        established on the condition-true path, so each `x != NULL` conjunct
        marks x non-null. This shares the same single-block approximation as
        the plain `!=` case (safe side: it can only suppress warnings, never
        add them).
        """
        if not isinstance(expr, c_ast.BinaryOp):
            return
        if expr.op == "&&":
            self._narrow_nonnull(expr.left, state)
            self._narrow_nonnull(expr.right, state)
            return
        if expr.op == "!=":
            if isinstance(expr.left, c_ast.ID) and _is_null(expr.right):
                state.nonnull_vars.add(expr.left.name)
                state.null_vars.discard(expr.left.name)
            elif isinstance(expr.right, c_ast.ID) and _is_null(expr.left):
                state.nonnull_vars.add(expr.right.name)
                state.null_vars.discard(expr.right.name)

    def _check_deref_expr(self, node: c_ast.Node, state: _NullState) -> None:
        if node is None:
            return

        if isinstance(node, c_ast.UnaryOp) and node.op == "*":
            if isinstance(node.expr, c_ast.ID) and node.expr.name in state.null_vars:
                if node.expr.name not in state.nonnull_vars:
                    self.deref_issues.append((node, node.expr.name))

        if isinstance(node, c_ast.StructRef) and node.type == "->":
            if isinstance(node.name, c_ast.ID) and node.name.name in state.null_vars:
                if node.name.name not in state.nonnull_vars:
                    self.deref_issues.append((node, node.name.name))

        if isinstance(node, c_ast.ArrayRef):
            if isinstance(node.name, c_ast.ID) and node.name.name in state.null_vars:
                if node.name.name not in state.nonnull_vars:
                    self.deref_issues.append((node, node.name.name))

        for _, child in node.children():
            self._check_deref_expr(child, state)


class NullDerefChecker(BaseChecker):
    checker_id = "null-deref"
    description = "Detects dereference of pointers known to be NULL (CFG-based cross-branch analysis)"
    default_severity = Severity.ERROR
    misra_rules = [RULE_1_3]

    def visit_FuncDef(self, node: c_ast.FuncDef) -> None:
        if node.body is None or node.body.block_items is None:
            return

        cfg = build_cfg(node)
        analysis = _NullAnalysis(ctx=self._ctx)
        analysis.analyze(cfg)

        reported: set[tuple[int, str]] = set()
        for issue_node, var_name in analysis.deref_issues:
            line = issue_node.coord.line if issue_node.coord else 0
            key = (line, var_name)
            if key in reported:
                continue
            reported.add(key)

            if isinstance(issue_node, c_ast.StructRef):
                self.report(
                    issue_node,
                    f"Dereference of NULL pointer '{var_name}' via '->'",
                    Severity.ERROR,
                    RULE_1_3,
                )
            elif isinstance(issue_node, c_ast.ArrayRef):
                self.report(
                    issue_node,
                    f"Dereference of NULL pointer '{var_name}' via array subscript",
                    Severity.ERROR,
                    RULE_1_3,
                )
            else:
                self.report(
                    issue_node,
                    f"Dereference of NULL pointer '{var_name}'",
                    Severity.ERROR,
                    RULE_1_3,
                )


CheckerRegistry.register(NullDerefChecker)

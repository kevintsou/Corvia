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


def _null_eq_vars(cond: c_ast.Node) -> set[str]:
    """Variables established non-NULL on the false edge of `cond`.

    Handles `p == NULL`, `NULL == p`, and `||` chains of such tests: when the
    whole condition is false, every `X == NULL` disjunct is false, so every X
    is non-null. `&&` offers no such guarantee and yields nothing.
    """
    if isinstance(cond, c_ast.BinaryOp):
        if cond.op == "||":
            return _null_eq_vars(cond.left) | _null_eq_vars(cond.right)
        if cond.op == "==":
            if isinstance(cond.left, c_ast.ID) and _is_null(cond.right):
                return {cond.left.name}
            if isinstance(cond.right, c_ast.ID) and _is_null(cond.left):
                return {cond.right.name}
    return set()


def _null_ne_vars(cond: c_ast.Node) -> set[str]:
    """Variables established non-NULL on the true edge of `cond`.

    Handles `p != NULL`, `NULL != p`, and `&&` chains of such tests: for the
    whole condition to be true, every `X != NULL` conjunct must be true, so
    each X is non-null. `||` offers no such guarantee and yields nothing.
    """
    if isinstance(cond, c_ast.BinaryOp):
        if cond.op == "&&":
            return _null_ne_vars(cond.left) | _null_ne_vars(cond.right)
        if cond.op == "!=":
            if isinstance(cond.left, c_ast.ID) and _is_null(cond.right):
                return {cond.left.name}
            if isinstance(cond.right, c_ast.ID) and _is_null(cond.left):
                return {cond.right.name}
    return set()


def _branch_terminates(node: c_ast.Node) -> bool:
    """True if the branch unconditionally leaves the enclosing flow."""
    if isinstance(node, c_ast.Compound):
        items = node.block_items or []
        return bool(items) and _branch_terminates(items[-1])
    return isinstance(node, (c_ast.Return, c_ast.Goto, c_ast.Break, c_ast.Continue))


def _derefs_var(node: c_ast.Node, name: str) -> bool:
    if isinstance(node, c_ast.UnaryOp) and node.op == "*":
        if isinstance(node.expr, c_ast.ID) and node.expr.name == name:
            return True
    if isinstance(node, c_ast.StructRef) and node.type == "->":
        if isinstance(node.name, c_ast.ID) and node.name.name == name:
            return True
    if isinstance(node, c_ast.ArrayRef):
        if isinstance(node.name, c_ast.ID) and node.name.name == name:
            return True
    return any(_derefs_var(child, name) for _, child in node.children())


def _is_noop(node: c_ast.Node) -> bool:
    """True for `(void)0`-style no-op expressions (the "true" arm of an
    expanded `assert()` macro)."""
    if isinstance(node, c_ast.Cast):
        return _is_null(node.expr) or (
            isinstance(node.expr, c_ast.Constant) and node.expr.value == "0"
        )
    return False


class _GuardCollector(c_ast.NodeVisitor):
    """Collect the condition nodes of early-exit / assert NULL guards.

    The idiom `if (p == NULL) { ...; return/goto/...; }` guarantees p is
    non-null on the fall-through path. The dataflow framework has no per-edge
    states, so narrowing on `==` is unsound in general (it would poison the
    then-branch too) — but for these specific conditions the then-branch
    terminates and never dereferences p, so block-level narrowing is safe.

    `assert(p != NULL);` is the other common source of this guarantee. When
    ENABLE_ASSERTIONS is defined, the preprocessor expands it to
    `(p != NULL) ? (void)0 : __assert(...);` — a bare ternary used as a
    statement. Its condition establishes the same non-null fact as the
    early-exit idiom (the false arm is a call that aborts), so it narrows on
    the ternary's own condition too. When ENABLE_ASSERTIONS is undefined,
    `assert(e)` expands to `((void)0)` with `e` discarded entirely — the
    condition is unrecoverable at the AST level, so nothing can be narrowed.
    """

    def __init__(self) -> None:
        self.guard_conditions: set[int] = set()

    def visit_If(self, node: c_ast.If) -> None:
        vars_ = _null_eq_vars(node.cond) if node.cond is not None else set()
        if (
            vars_
            and node.iftrue is not None
            and _branch_terminates(node.iftrue)
            and not any(_derefs_var(node.iftrue, v) for v in vars_)
        ):
            self.guard_conditions.add(id(node.cond))
        self.generic_visit(node)

    def visit_TernaryOp(self, node: c_ast.TernaryOp) -> None:
        # assert(cond) expands to `cond ? (void)0 : <abort call>`.
        if (
            _is_noop(node.iftrue)
            and isinstance(node.iffalse, c_ast.FuncCall)
            and _null_ne_vars(node.cond)
        ):
            self.guard_conditions.add(id(node))
        self.generic_visit(node)


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
    def __init__(self, ctx=None, guard_conditions: set[int] | None = None) -> None:
        self.deref_issues: list[tuple[c_ast.Node, str]] = []
        self.ctx = ctx
        # id()s of `if (p == NULL) <terminating branch>` guard conditions
        # (see _GuardCollector) — the only `==` tests safe to narrow on.
        self.guard_conditions = guard_conditions or set()

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
            # General `== NULL` narrowing is unsound here: the transfer
            # function's out-state flows into BOTH successors, so adding the
            # variable to null_vars would poison the fall-through branch.
            # The exception is the pre-collected early-exit guard idiom
            # (`if (p == NULL) { ...; return; }`): its then-branch terminates
            # without dereferencing p, so narrowing p to non-null at the
            # condition is safe for every path that continues.
            if id(stmt) in self.guard_conditions:
                for name in _null_eq_vars(stmt):
                    state.nonnull_vars.add(name)
                    state.null_vars.discard(name)
            elif stmt.op in ("!=", "&&"):
                self._narrow_nonnull(stmt, state)
            else:
                self._check_deref_expr(stmt, state)

        elif isinstance(stmt, c_ast.TernaryOp):
            # assert(p != NULL); expands (with ENABLE_ASSERTIONS defined) to
            # the bare statement `(p != NULL) ? (void)0 : __assert(...);`.
            # Pre-collected by _GuardCollector: the false arm aborts, so on
            # the path that continues past this statement, p is non-null.
            if id(stmt) in self.guard_conditions:
                for name in _null_ne_vars(stmt.cond):
                    state.nonnull_vars.add(name)
                    state.null_vars.discard(name)
            else:
                self._check_deref_expr(stmt.cond, state)

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
        collector = _GuardCollector()
        collector.visit(node)
        analysis = _NullAnalysis(
            ctx=self._ctx, guard_conditions=collector.guard_conditions
        )
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

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

# Functions known not to retain (store) a pointer passed to them. Passing an
# allocated pointer to anything else is conservatively treated as an escape:
# the callee may stash the pointer somewhere and free it later, so we must
# not report a leak for it.
_KNOWN_PURE_FUNCS = {
    "memset", "memcpy", "memmove", "memcmp",
    "strcpy", "strncpy", "strcat", "strncat", "strcmp", "strncmp", "strlen",
    "printf", "fprintf", "sprintf", "snprintf", "puts", "fputs",
    "fread", "fwrite",
}


def _is_null_const(node: c_ast.Node) -> bool:
    if isinstance(node, c_ast.Constant):
        return node.value in ("0", "NULL")
    if isinstance(node, c_ast.ID):
        return node.name == "NULL"
    if isinstance(node, c_ast.Cast) and node.expr is not None:
        return _is_null_const(node.expr)
    return False


def _collect_ids(node: c_ast.Node, out: set[str]) -> None:
    if node is None:
        return
    if isinstance(node, c_ast.ID):
        out.add(node.name)
        return
    for _, child in node.children():
        _collect_ids(child, out)


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
            else:
                # Storing into a struct member / array element / deref target
                # publishes the pointer beyond the local variable: it escapes,
                # so this function is no longer responsible for freeing it.
                escaped: set[str] = set()
                _collect_ids(stmt.rvalue, escaped)
                state.allocated -= escaped

        elif isinstance(stmt, c_ast.Return):
            # `return p;` transfers ownership to the caller - not a leak.
            if stmt.expr is not None:
                escaped = set()
                _collect_ids(stmt.expr, escaped)
                state.allocated -= escaped

        elif isinstance(stmt, c_ast.FuncCall):
            if self._is_free_call(stmt):
                if stmt.args and stmt.args.exprs:
                    for arg in stmt.args.exprs:
                        if isinstance(arg, c_ast.ID):
                            state.freed.add(arg.name)
            else:
                # Passing an allocated pointer to an unknown function is a
                # conservative escape (the callee may store or free it),
                # except for a small list of functions known not to retain
                # their pointer arguments.
                callee = stmt.name.name if isinstance(stmt.name, c_ast.ID) else None
                if callee not in _KNOWN_PURE_FUNCS and stmt.args:
                    escaped = set()
                    for arg in stmt.args.exprs or []:
                        _collect_ids(arg, escaped)
                    state.allocated -= escaped

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
                # `p = malloc(..); if (!p) { return -1; } ... free(p);` -
                # the only path on which p is "not freed" is the one where
                # the allocation failed (p is NULL, nothing to free). If the
                # function both null-guards p with an early return and frees
                # p somewhere, don't report a leak.
                if self._has_null_guard_return(node.body, var_name) and \
                        self._has_free_of(node.body, var_name):
                    continue
                alloc_node = self._find_alloc_node(node.body, var_name)
                report_node = alloc_node or node.decl or node
                self.report(
                    report_node,
                    f"Potential memory leak: '{var_name}' allocated but not freed on all paths",
                    Severity.WARNING,
                    RULE_22_1,
                )

        # Rule 22.2: freeing memory that provably did not come from a Standard
        # Library allocation function. Only report when the pointer verifiably
        # refers to non-heap storage (address of a local, a local array, or a
        # string literal). Untracked pointers - parameters, globals, struct
        # members - must NOT be reported: the caller may well have malloc'd
        # them (e.g. `void destroy(int *o) { free(o); }`).
        self._check_nonheap_free_22_2(node)

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

    def _has_free_of(self, body: c_ast.Node, var_name: str) -> bool:
        if isinstance(body, c_ast.FuncCall):
            if isinstance(body.name, c_ast.ID) and _looks_like_free(body.name.name, self._ctx):
                for arg in (body.args.exprs if body.args else None) or []:
                    if isinstance(arg, c_ast.ID) and arg.name == var_name:
                        return True
        for _, child in body.children():
            if self._has_free_of(child, var_name):
                return True
        return False

    def _has_null_guard_return(self, body: c_ast.Node, var_name: str) -> bool:
        """True if the function contains `if (!var) return ...` or
        `if (var == NULL) return ...` (the allocation-failure guard idiom)."""
        if isinstance(body, c_ast.If) and self._cond_is_null_test(body.cond, var_name):
            if self._branch_returns(body.iftrue):
                return True
        for _, child in body.children():
            if self._has_null_guard_return(child, var_name):
                return True
        return False

    def _cond_is_null_test(self, cond: c_ast.Node, var_name: str) -> bool:
        if isinstance(cond, c_ast.UnaryOp) and cond.op == "!":
            return isinstance(cond.expr, c_ast.ID) and cond.expr.name == var_name
        if isinstance(cond, c_ast.BinaryOp) and cond.op == "==":
            if isinstance(cond.left, c_ast.ID) and cond.left.name == var_name:
                return _is_null_const(cond.right)
            if isinstance(cond.right, c_ast.ID) and cond.right.name == var_name:
                return _is_null_const(cond.left)
        return False

    def _branch_returns(self, node: c_ast.Node) -> bool:
        if isinstance(node, (c_ast.Return, c_ast.Goto)):
            return True
        if isinstance(node, c_ast.Compound):
            items = node.block_items or []
            return bool(items) and self._branch_returns(items[-1])
        return False

    def _check_nonheap_free_22_2(self, func: c_ast.FuncDef) -> None:
        nonheap: set[str] = set()   # vars provably pointing at non-heap storage
        heapish: set[str] = set()   # vars ever assigned an allocation result
        self._classify_pointers(func.body, nonheap, heapish)
        self._scan_frees_22_2(func.body, nonheap - heapish)

    def _classify_pointers(self, node: c_ast.Node, nonheap: set[str], heapish: set[str]) -> None:
        if node is None:
            return
        if isinstance(node, c_ast.Decl) and node.name:
            if isinstance(node.type, c_ast.ArrayDecl):
                nonheap.add(node.name)  # local array
            if node.init is not None:
                if self._is_alloc_expr(node.init):
                    heapish.add(node.name)
                elif self._is_nonheap_expr(node.init):
                    nonheap.add(node.name)
        elif isinstance(node, c_ast.Assignment) and isinstance(node.lvalue, c_ast.ID):
            if self._is_alloc_expr(node.rvalue):
                heapish.add(node.lvalue.name)
            elif self._is_nonheap_expr(node.rvalue):
                nonheap.add(node.lvalue.name)
        for _, child in node.children():
            self._classify_pointers(child, nonheap, heapish)

    def _is_alloc_expr(self, node: c_ast.Node) -> bool:
        if isinstance(node, c_ast.Cast) and node.expr is not None:
            return self._is_alloc_expr(node.expr)
        if isinstance(node, c_ast.FuncCall) and isinstance(node.name, c_ast.ID):
            return _looks_like_alloc(node.name.name, self._ctx)
        return False

    def _is_nonheap_expr(self, node: c_ast.Node) -> bool:
        if isinstance(node, c_ast.Cast) and node.expr is not None:
            return self._is_nonheap_expr(node.expr)
        if isinstance(node, c_ast.UnaryOp) and node.op == "&":
            return True  # address of an object
        if isinstance(node, c_ast.Constant) and node.type == "string":
            return True  # string literal
        return False

    def _scan_frees_22_2(self, node: c_ast.Node, nonheap: set[str]) -> None:
        if node is None:
            return
        if isinstance(node, c_ast.FuncCall) and isinstance(node.name, c_ast.ID) \
                and node.name.name in _FREE_FUNCS:
            for arg in (node.args.exprs if node.args else None) or []:
                target = arg
                if isinstance(target, c_ast.Cast) and target.expr is not None:
                    target = target.expr
                if isinstance(target, c_ast.UnaryOp) and target.op == "&":
                    self.report(node, "Freeing the address of an object (not dynamically allocated)",
                                Severity.ERROR, RULE_22_2)
                elif isinstance(target, c_ast.Constant) and target.type == "string":
                    self.report(node, "Freeing a string literal (not dynamically allocated)",
                                Severity.ERROR, RULE_22_2)
                elif isinstance(target, c_ast.ID) and target.name in nonheap:
                    self.report(node, f"Freeing '{target.name}' which was not dynamically allocated",
                                Severity.ERROR, RULE_22_2)
        for _, child in node.children():
            self._scan_frees_22_2(child, nonheap)


CheckerRegistry.register(MemoryLeakChecker)

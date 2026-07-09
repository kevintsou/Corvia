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
RULE_22_5 = MisraRule(
    "22.5", MisraCategory.MANDATORY,
    "A pointer to a FILE object shall not be dereferenced",
)
RULE_22_6 = MisraRule("22.6", MisraCategory.MANDATORY, "The value of a pointer to a FILE shall not be used after the associated stream has been closed")

_OPEN_FUNCS = {"fopen", "tmpfile", "fdopen", "freopen", "popen"}
_CLOSE_FUNCS = {"fclose", "pclose"}

# Standard I/O functions that USE a FILE* without retaining it. Passing a
# handle to these is normal usage, not an ownership transfer. Passing the
# handle to any other (unknown) function is conservatively treated as an
# escape - the callee may store or close it.
_KNOWN_IO_FUNCS = {
    "fread", "fwrite", "fprintf", "fscanf", "vfprintf", "vfscanf",
    "fgets", "fputs", "fgetc", "fputc", "getc", "putc", "ungetc",
    "fseek", "ftell", "rewind", "fsetpos", "fgetpos",
    "feof", "ferror", "clearerr", "fflush", "fileno",
    "setbuf", "setvbuf", "perror",
}


def _collect_ids(node: c_ast.Node, out: set[str]) -> None:
    if node is None:
        return
    if isinstance(node, c_ast.ID):
        out.add(node.name)
        return
    for _, child in node.children():
        _collect_ids(child, out)


def _is_null_const(node: c_ast.Node) -> bool:
    if isinstance(node, c_ast.Constant):
        return node.value in ("0", "NULL")
    if isinstance(node, c_ast.ID):
        return node.name == "NULL"
    if isinstance(node, c_ast.Cast) and node.expr is not None:
        return _is_null_const(node.expr)
    return False


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
            else:
                # Storing the handle into a struct member / array element /
                # deref target publishes it beyond the local: it escapes and
                # this function is no longer responsible for closing it.
                escaped: set[str] = set()
                _collect_ids(stmt.rvalue, escaped)
                state.opened -= escaped

        elif isinstance(stmt, c_ast.Return):
            # `return f;` transfers ownership of the handle to the caller.
            if stmt.expr is not None:
                escaped = set()
                _collect_ids(stmt.expr, escaped)
                state.opened -= escaped

        elif isinstance(stmt, c_ast.FuncCall):
            if self._is_close_call(stmt) and stmt.args and stmt.args.exprs:
                for arg in stmt.args.exprs:
                    if isinstance(arg, c_ast.ID):
                        state.closed.add(arg.name)
            elif not self._is_close_call(stmt):
                # Passing the handle to an unknown (non-stdio) function is a
                # conservative escape - the callee may store or close it.
                callee = stmt.name.name if isinstance(stmt.name, c_ast.ID) else None
                if callee is not None and callee not in _KNOWN_IO_FUNCS \
                        and callee not in _OPEN_FUNCS and stmt.args:
                    escaped = set()
                    for arg in stmt.args.exprs or []:
                        _collect_ids(arg, escaped)
                    state.opened -= escaped

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
    misra_rules = [RULE_22_1, RULE_22_5, RULE_22_6]

    def visit_FuncDef(self, node: c_ast.FuncDef) -> None:
        if node.body is None or node.body.block_items is None:
            return

        self._check_file_deref_22_5(node)

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
                # `f = fopen(..); if (!f) { return -1; } ... fclose(f);` -
                # the unclosed path is the open-failure path where f is NULL.
                if self._has_null_guard_return(node.body, var_name) and \
                        self._has_close_of(node.body, var_name):
                    continue
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
                # Reopening the handle (`f = fopen(...)`) clears its closed
                # state so later uses are legitimate again.
                if isinstance(stmt, c_ast.Assignment) and isinstance(stmt.lvalue, c_ast.ID):
                    if self._is_open_call(stmt.rvalue):
                        closed.discard(stmt.lvalue.name)
                    continue
                if isinstance(stmt, c_ast.Decl) and stmt.name and stmt.init is not None:
                    if self._is_open_call(stmt.init):
                        closed.discard(stmt.name)
                    continue
                if isinstance(stmt, c_ast.FuncCall) and stmt.args:
                    if isinstance(stmt.name, c_ast.ID) and _looks_like_close(stmt.name.name, self._ctx):
                        for arg in stmt.args.exprs or []:
                            if isinstance(arg, c_ast.ID):
                                if arg.name in closed:
                                    # Closing an already-closed handle is
                                    # itself a use-after-close (double fclose).
                                    self.report(
                                        stmt,
                                        f"File handle '{arg.name}' is closed twice",
                                        Severity.ERROR,
                                        RULE_22_6,
                                    )
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

    def _is_open_call(self, node: c_ast.Node) -> bool:
        if isinstance(node, c_ast.Cast) and node.expr is not None:
            return self._is_open_call(node.expr)
        if isinstance(node, c_ast.FuncCall) and isinstance(node.name, c_ast.ID):
            return _looks_like_open(node.name.name, self._ctx)
        return False

    def _has_close_of(self, body: c_ast.Node, var_name: str) -> bool:
        if isinstance(body, c_ast.FuncCall):
            if isinstance(body.name, c_ast.ID) and _looks_like_close(body.name.name, self._ctx):
                for arg in (body.args.exprs if body.args else None) or []:
                    if isinstance(arg, c_ast.ID) and arg.name == var_name:
                        return True
        for _, child in body.children():
            if self._has_close_of(child, var_name):
                return True
        return False

    def _has_null_guard_return(self, body: c_ast.Node, var_name: str) -> bool:
        """True if the function contains `if (!var) return ...` or
        `if (var == NULL) return ...` (the open-failure guard idiom)."""
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

    def _check_file_deref_22_5(self, func: c_ast.FuncDef) -> None:
        """Find variables of type FILE* and report any *p / p-> dereference."""
        file_vars: set[str] = set()
        self._collect_file_vars(func, file_vars)
        if not file_vars:
            return
        self._scan_for_deref(func.body, file_vars)

    def _collect_file_vars(self, node: c_ast.Node, out: set[str]) -> None:
        if isinstance(node, c_ast.Decl) and node.name and isinstance(node.type, c_ast.PtrDecl):
            inner = node.type.type
            if isinstance(inner, c_ast.TypeDecl) and isinstance(inner.type, c_ast.IdentifierType):
                if "FILE" in inner.type.names:
                    out.add(node.name)
        for _, child in node.children():
            self._collect_file_vars(child, out)

    def _scan_for_deref(self, node: c_ast.Node, file_vars: set[str]) -> None:
        if isinstance(node, c_ast.UnaryOp) and node.op == "*":
            if isinstance(node.expr, c_ast.ID) and node.expr.name in file_vars:
                self.report(
                    node,
                    f"Dereference of FILE pointer '{node.expr.name}'",
                    Severity.ERROR,
                    RULE_22_5,
                )
        elif isinstance(node, c_ast.StructRef) and node.type == "->":
            if isinstance(node.name, c_ast.ID) and node.name.name in file_vars:
                self.report(
                    node,
                    f"Dereference of FILE pointer '{node.name.name}' via '->'",
                    Severity.ERROR,
                    RULE_22_5,
                )
        for _, child in node.children():
            self._scan_for_deref(child, file_vars)

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

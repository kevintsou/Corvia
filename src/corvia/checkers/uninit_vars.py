"""Uninitialized variable checker with partial initialization and cross-function support."""

from __future__ import annotations

from typing import Optional

from pycparser import c_ast

from corvia.checkers.base import BaseChecker
from corvia.core.cfg import BasicBlock, build_cfg
from corvia.core.dataflow import ForwardAnalysis
from corvia.models import MisraCategory, MisraRule, Severity
from corvia.registry import CheckerRegistry

RULE_9_1 = MisraRule("9.1", MisraCategory.MANDATORY, "The value of an object with automatic storage duration shall not be read before it has been set")


class _VarState:
    """Tracks initialization state of a variable."""

    def __init__(self, name: str, node: c_ast.Node, is_array: bool = False, array_size: int = 0,
                 is_struct: bool = False, struct_fields: Optional[list[str]] = None) -> None:
        self.name = name
        self.node = node
        self.is_array = is_array
        self.array_size = array_size
        self.is_struct = is_struct
        self.struct_fields = struct_fields or []
        self.fully_initialized = False
        self.initialized_indices: set[int] = set()
        self.initialized_fields: set[str] = set()


def _collect_id_reads(node: c_ast.Node, exclude_lvalue: bool = True) -> list[c_ast.ID]:
    """Collect all ID nodes in read position within an expression."""
    ids: list[c_ast.ID] = []
    _walk_reads(node, ids, is_lvalue=False)
    return ids


def _walk_reads(node: c_ast.Node, ids: list[c_ast.ID], is_lvalue: bool) -> None:
    if node is None:
        return

    if isinstance(node, c_ast.ID):
        if not is_lvalue:
            ids.append(node)
        return

    if isinstance(node, c_ast.Assignment):
        _walk_reads(node.lvalue, ids, is_lvalue=True)
        _walk_reads(node.rvalue, ids, is_lvalue=False)
        return

    if isinstance(node, c_ast.UnaryOp):
        if node.op in ("p++", "p--", "++", "--"):
            _walk_reads(node.expr, ids, is_lvalue=True)
        else:
            _walk_reads(node.expr, ids, is_lvalue=False)
        return

    if isinstance(node, c_ast.ArrayRef):
        _walk_reads(node.name, ids, is_lvalue=is_lvalue)
        _walk_reads(node.subscript, ids, is_lvalue=False)
        return

    if isinstance(node, c_ast.StructRef):
        _walk_reads(node.name, ids, is_lvalue=is_lvalue)
        return

    if isinstance(node, c_ast.FuncCall):
        if node.args:
            for arg in node.args.exprs or []:
                _walk_reads(arg, ids, is_lvalue=False)
        return

    for child_name, child in node.children():
        _walk_reads(child, ids, is_lvalue=False)


def _get_array_size(type_node: c_ast.Node) -> Optional[int]:
    if isinstance(type_node, c_ast.ArrayDecl) and type_node.dim:
        if isinstance(type_node.dim, c_ast.Constant) and type_node.dim.type == "int":
            try:
                return int(type_node.dim.value)
            except ValueError:
                pass
    return None


def _get_struct_fields(type_node: c_ast.Node) -> Optional[list[str]]:
    if isinstance(type_node, c_ast.Struct) and type_node.decls:
        return [d.name for d in type_node.decls if d.name]
    return None


def _count_init_list_items(init: c_ast.InitList) -> int:
    if init.exprs is None:
        return 0
    return len(init.exprs)


def _get_designated_indices(init: c_ast.InitList) -> set[int]:
    indices: set[int] = set()
    if init.exprs is None:
        return indices
    for i, expr in enumerate(init.exprs):
        if isinstance(expr, c_ast.NamedInitializer):
            for name_part in expr.name or []:
                if isinstance(name_part, c_ast.Constant) and name_part.type == "int":
                    try:
                        indices.add(int(name_part.value))
                    except ValueError:
                        pass
        else:
            indices.add(i)
    return indices


def _get_designated_fields(init: c_ast.InitList) -> set[str]:
    fields: set[str] = set()
    if init.exprs is None:
        return fields
    for expr in init.exprs:
        if isinstance(expr, c_ast.NamedInitializer):
            for name_part in expr.name or []:
                if isinstance(name_part, c_ast.ID):
                    fields.add(name_part.name)
    return fields


class _StructCollector(c_ast.NodeVisitor):
    """Collects struct definitions with their field names."""

    def __init__(self) -> None:
        self.structs: dict[str, list[str]] = {}

    def visit_Struct(self, node: c_ast.Struct) -> None:
        if node.name and node.decls:
            fields = [d.name for d in node.decls if d.name]
            if fields:
                self.structs[node.name] = fields
        self.generic_visit(node)


class UninitVarsChecker(BaseChecker):
    checker_id = "uninit-var"
    description = "Detects use of uninitialized or partially initialized variables (MISRA C:2012 Rule 9.1)"
    default_severity = Severity.ERROR
    misra_rules = [RULE_9_1]

    def __init__(self) -> None:
        super().__init__()
        self._func_return_states: dict[str, str] = {}
        self._struct_defs: dict[str, list[str]] = {}

    def visit_FileAST(self, node: c_ast.FileAST) -> None:
        collector = _StructCollector()
        collector.visit(node)
        self._struct_defs = collector.structs
        self.generic_visit(node)

    def visit_FuncDef(self, node: c_ast.FuncDef) -> None:
        if node.body is None or node.body.block_items is None:
            return

        var_states: dict[str, _VarState] = {}
        self._scan_block(node.body.block_items, var_states)

        self._cfg_pass(node)

    def _scan_block(self, items: list[c_ast.Node], var_states: dict[str, _VarState]) -> None:
        for item in items:
            if isinstance(item, c_ast.Decl) and item.name:
                self._handle_decl(item, var_states)
            elif isinstance(item, c_ast.Assignment):
                self._handle_assignment(item, var_states)
            elif isinstance(item, c_ast.Compound):
                if item.block_items:
                    self._scan_block(item.block_items, dict(var_states))
            elif isinstance(item, c_ast.If):
                self._handle_if(item, var_states)
            elif isinstance(item, (c_ast.While, c_ast.DoWhile)):
                self._check_reads(item.cond, var_states) if item.cond else None
                if item.stmt and isinstance(item.stmt, c_ast.Compound) and item.stmt.block_items:
                    self._scan_block(item.stmt.block_items, dict(var_states))
            elif isinstance(item, c_ast.For):
                if item.init:
                    if isinstance(item.init, c_ast.DeclList):
                        for decl in item.init.decls or []:
                            if isinstance(decl, c_ast.Decl) and decl.name:
                                self._handle_decl(decl, var_states)
                    else:
                        self._check_reads(item.init, var_states)
                if item.cond:
                    self._check_reads(item.cond, var_states)
                if item.next:
                    self._check_reads(item.next, var_states)
                if item.stmt and isinstance(item.stmt, c_ast.Compound) and item.stmt.block_items:
                    self._scan_block(item.stmt.block_items, dict(var_states))
            elif isinstance(item, c_ast.Return):
                if item.expr:
                    self._check_reads(item.expr, var_states)
            elif isinstance(item, c_ast.FuncCall):
                self._handle_func_call(item, var_states)
            else:
                self._check_reads(item, var_states)

    def _handle_decl(self, decl: c_ast.Decl, var_states: dict[str, _VarState]) -> None:
        if decl.name is None:
            return

        arr_size = _get_array_size(decl.type) if decl.type else None
        is_array = arr_size is not None

        struct_fields: Optional[list[str]] = None
        is_struct = False
        struct_node = None
        if isinstance(decl.type, c_ast.Struct):
            struct_node = decl.type
        elif isinstance(decl.type, c_ast.TypeDecl) and isinstance(getattr(decl.type, 'type', None), c_ast.Struct):
            struct_node = decl.type.type

        if struct_node is not None:
            struct_fields = _get_struct_fields(struct_node)
            if struct_fields is None and struct_node.name and struct_node.name in self._struct_defs:
                struct_fields = list(self._struct_defs[struct_node.name])
            is_struct = struct_fields is not None

        state = _VarState(
            name=decl.name,
            node=decl,
            is_array=is_array,
            array_size=arr_size or 0,
            is_struct=is_struct,
            struct_fields=struct_fields or [],
        )

        if decl.init is None:
            var_states[decl.name] = state
            return

        if isinstance(decl.init, c_ast.InitList):
            if is_array and arr_size:
                init_count = _count_init_list_items(decl.init)
                designated = _get_designated_indices(decl.init)
                state.initialized_indices = designated if designated else set(range(init_count))
                state.fully_initialized = len(state.initialized_indices) >= arr_size
            elif is_struct and struct_fields:
                designated = _get_designated_fields(decl.init)
                if designated:
                    state.initialized_fields = designated
                else:
                    init_count = _count_init_list_items(decl.init)
                    state.initialized_fields = set(struct_fields[:init_count])
                state.fully_initialized = state.initialized_fields >= set(struct_fields)
            else:
                state.fully_initialized = True
            var_states[decl.name] = state
        else:
            state.fully_initialized = True
            var_states[decl.name] = state

    def _handle_assignment(self, node: c_ast.Assignment, var_states: dict[str, _VarState]) -> None:
        self._check_reads(node.rvalue, var_states)

        if isinstance(node.lvalue, c_ast.ID):
            name = node.lvalue.name
            if name in var_states:
                var_states[name].fully_initialized = True
        elif isinstance(node.lvalue, c_ast.ArrayRef):
            if isinstance(node.lvalue.name, c_ast.ID):
                name = node.lvalue.name.name
                if name in var_states and var_states[name].is_array:
                    if isinstance(node.lvalue.subscript, c_ast.Constant):
                        try:
                            idx = int(node.lvalue.subscript.value)
                            var_states[name].initialized_indices.add(idx)
                            if len(var_states[name].initialized_indices) >= var_states[name].array_size:
                                var_states[name].fully_initialized = True
                        except ValueError:
                            pass
        elif isinstance(node.lvalue, c_ast.StructRef):
            if isinstance(node.lvalue.name, c_ast.ID):
                name = node.lvalue.name.name
                if name in var_states and var_states[name].is_struct:
                    field = node.lvalue.field.name if node.lvalue.field else None
                    if field:
                        var_states[name].initialized_fields.add(field)
                        if var_states[name].initialized_fields >= set(var_states[name].struct_fields):
                            var_states[name].fully_initialized = True

    def _handle_if(self, node: c_ast.If, var_states: dict[str, _VarState]) -> None:
        if node.cond:
            self._check_reads(node.cond, var_states)

        if node.iftrue:
            true_states = dict(var_states)
            if isinstance(node.iftrue, c_ast.Compound) and node.iftrue.block_items:
                self._scan_block(node.iftrue.block_items, true_states)

        if node.iffalse:
            false_states = dict(var_states)
            if isinstance(node.iffalse, c_ast.Compound) and node.iffalse.block_items:
                self._scan_block(node.iffalse.block_items, false_states)
            elif isinstance(node.iffalse, c_ast.If):
                self._handle_if(node.iffalse, dict(var_states))

    def _handle_func_call(self, node: c_ast.FuncCall, var_states: dict[str, _VarState]) -> None:
        if node.args:
            for arg in node.args.exprs or []:
                if isinstance(arg, c_ast.UnaryOp) and arg.op == "&":
                    if isinstance(arg.expr, c_ast.ID):
                        name = arg.expr.name
                        if name in var_states and not var_states[name].fully_initialized:
                            self.report(
                                node,
                                f"Partially initialized variable '{name}' passed by reference to function",
                                Severity.WARNING,
                                RULE_9_1,
                            )
                self._check_reads(arg, var_states)

    def _check_reads(self, node: c_ast.Node, var_states: dict[str, _VarState]) -> None:
        if node is None:
            return

        if isinstance(node, c_ast.ID):
            name = node.name
            if name in var_states and not var_states[name].fully_initialized:
                state = var_states[name]
                if state.is_struct and state.initialized_fields:
                    uninit = set(state.struct_fields) - state.initialized_fields
                    self.report(
                        node,
                        f"Variable '{name}' is partially initialized (uninitialized fields: {', '.join(sorted(uninit))})",
                        Severity.WARNING,
                        RULE_9_1,
                    )
                elif state.is_array and state.initialized_indices:
                    self.report(
                        node,
                        f"Array '{name}' is partially initialized ({len(state.initialized_indices)}/{state.array_size} elements)",
                        Severity.WARNING,
                        RULE_9_1,
                    )
                else:
                    self.report(
                        node,
                        f"Variable '{name}' may be used before initialization",
                        Severity.ERROR,
                        RULE_9_1,
                    )
            return

        if isinstance(node, c_ast.ArrayRef):
            if isinstance(node.name, c_ast.ID):
                name = node.name.name
                if name in var_states and var_states[name].is_array:
                    state = var_states[name]
                    if not state.fully_initialized and isinstance(node.subscript, c_ast.Constant):
                        try:
                            idx = int(node.subscript.value)
                            if idx not in state.initialized_indices:
                                self.report(
                                    node,
                                    f"Array '{name}' element at index {idx} may not be initialized",
                                    Severity.ERROR,
                                    RULE_9_1,
                                )
                        except ValueError:
                            pass
                    elif not state.fully_initialized:
                        self.report(
                            node,
                            f"Array '{name}' is partially initialized, access with variable index may read uninitialized data",
                            Severity.WARNING,
                            RULE_9_1,
                        )
            self._check_reads(node.subscript, var_states)
            return

        if isinstance(node, c_ast.StructRef):
            if isinstance(node.name, c_ast.ID):
                name = node.name.name
                if name in var_states and var_states[name].is_struct:
                    state = var_states[name]
                    field = node.field.name if node.field else None
                    if field and not state.fully_initialized and field not in state.initialized_fields:
                        self.report(
                            node,
                            f"Field '{name}.{field}' may not be initialized",
                            Severity.ERROR,
                            RULE_9_1,
                        )
            return

        for child_name, child in node.children():
            self._check_reads(child, var_states)


    def _cfg_pass(self, func_node: c_ast.FuncDef) -> None:
        """CFG-based pass to catch branch-dependent uninitialized reads."""
        cfg = build_cfg(func_node)
        analysis = _UninitCFGAnalysis()
        results = analysis.analyze(cfg)

        reported_lines = {i.line for i in self._issues}

        for issue_node, var_name, msg in analysis.found_issues:
            line = issue_node.coord.line if issue_node.coord else 0
            if line not in reported_lines:
                self.report(issue_node, msg, Severity.WARNING, RULE_9_1)
                reported_lines.add(line)


class _UninitCFGState:
    def __init__(
        self,
        uninit: set[str] | None = None,
        init: set[str] | None = None,
    ) -> None:
        self.uninit: set[str] = set(uninit) if uninit else set()
        self.init: set[str] = set(init) if init else set()

    def copy(self) -> _UninitCFGState:
        return _UninitCFGState(self.uninit, self.init)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, _UninitCFGState):
            return NotImplemented
        return self.uninit == other.uninit and self.init == other.init


class _UninitCFGAnalysis(ForwardAnalysis[_UninitCFGState]):
    def __init__(self) -> None:
        self.found_issues: list[tuple[c_ast.Node, str, str]] = []

    def initial_state(self) -> _UninitCFGState:
        return _UninitCFGState()

    def entry_state(self) -> _UninitCFGState:
        return _UninitCFGState()

    def transfer(self, block: BasicBlock, in_state: _UninitCFGState) -> _UninitCFGState:
        state = in_state.copy()
        for stmt in block.statements:
            self._process(stmt, state)
        return state

    def merge(self, states: list[_UninitCFGState]) -> _UninitCFGState:
        if not states:
            return _UninitCFGState()
        uninit_union: set[str] = set()
        init_intersect: set[str] | None = None
        for s in states:
            uninit_union |= s.uninit
            if init_intersect is None:
                init_intersect = set(s.init)
            else:
                init_intersect &= s.init
        safe_init = init_intersect or set()
        return _UninitCFGState(uninit_union - safe_init, safe_init)

    def equal(self, a: _UninitCFGState, b: _UninitCFGState) -> bool:
        return a == b

    def _process(self, stmt: c_ast.Node, state: _UninitCFGState) -> None:
        if isinstance(stmt, c_ast.Decl) and stmt.name:
            if stmt.init is None:
                state.uninit.add(stmt.name)
            else:
                state.init.add(stmt.name)
                state.uninit.discard(stmt.name)
                self._check_use(stmt.init, state)

        elif isinstance(stmt, c_ast.Assignment):
            self._check_use(stmt.rvalue, state)
            if isinstance(stmt.lvalue, c_ast.ID):
                state.init.add(stmt.lvalue.name)
                state.uninit.discard(stmt.lvalue.name)

        elif isinstance(stmt, c_ast.Return):
            if hasattr(stmt, 'expr') and stmt.expr:
                self._check_use(stmt.expr, state)

        elif isinstance(stmt, c_ast.FuncCall):
            if stmt.args:
                for arg in stmt.args.exprs or []:
                    self._check_use(arg, state)
        else:
            self._check_use(stmt, state)

    def _check_use(self, node: c_ast.Node, state: _UninitCFGState) -> None:
        if node is None:
            return
        if isinstance(node, c_ast.ID):
            if node.name in state.uninit and node.name not in state.init:
                self.found_issues.append((
                    node,
                    node.name,
                    f"Variable '{node.name}' may be uninitialized on some execution paths",
                ))
            return
        if isinstance(node, c_ast.Assignment):
            self._check_use(node.rvalue, state)
            return
        for _, child in node.children():
            self._check_use(child, state)


CheckerRegistry.register(UninitVarsChecker)

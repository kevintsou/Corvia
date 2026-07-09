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

    def clone(self) -> "_VarState":
        """Deep copy for branch forking: mutable sets must not be shared."""
        c = _VarState(self.name, self.node, self.is_array, self.array_size,
                      self.is_struct, list(self.struct_fields))
        c.fully_initialized = self.fully_initialized
        c.initialized_indices = set(self.initialized_indices)
        c.initialized_fields = set(self.initialized_fields)
        return c


def _fork_states(var_states: dict[str, _VarState]) -> dict[str, _VarState]:
    """Fork variable states for a conditionally-executed branch.

    A shallow dict() copy would share the mutable _VarState objects, letting
    initialization inside one branch leak into the outer scope and disable
    partial-initialization detection."""
    return {name: st.clone() for name, st in var_states.items()}


def _branch_terminates(node: c_ast.Node) -> bool:
    """True if a branch statement definitely transfers control away
    (so execution never falls through to the code after the if)."""
    if node is None:
        return False
    if isinstance(node, (c_ast.Return, c_ast.Break, c_ast.Continue, c_ast.Goto)):
        return True
    if isinstance(node, c_ast.Compound):
        items = node.block_items or []
        return bool(items) and _branch_terminates(items[-1])
    return False


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
        self._typedef_structs: dict[str, list[str]] = {}

    def reset(self) -> None:
        self._func_return_states = {}
        self._struct_defs = {}
        self._typedef_structs = {}

    def visit_FileAST(self, node: c_ast.FileAST) -> None:
        collector = _StructCollector()
        collector.visit(node)
        self._struct_defs = collector.structs
        self._collect_typedef_structs(node)
        self.generic_visit(node)

    def _collect_typedef_structs(self, node: c_ast.FileAST) -> None:
        """Map typedef names to struct field lists so `S s; s.a = 1;` with
        `typedef struct {...} S;` is tracked as a struct, not a scalar."""
        raw: dict[str, c_ast.Node] = {}
        for ext in node.ext or []:
            if isinstance(ext, c_ast.Typedef) and ext.name:
                raw[ext.name] = ext.type
        # Iterate a few times so typedef-of-typedef chains resolve regardless
        # of declaration order.
        for _ in range(3):
            for name, t in raw.items():
                if name in self._typedef_structs:
                    continue
                inner = t
                if isinstance(inner, c_ast.TypeDecl):
                    inner = inner.type
                if isinstance(inner, c_ast.Struct):
                    fields = _get_struct_fields(inner)
                    if fields is None and inner.name and inner.name in self._struct_defs:
                        fields = list(self._struct_defs[inner.name])
                    if fields:
                        self._typedef_structs[name] = fields
                elif isinstance(inner, c_ast.IdentifierType):
                    names = inner.names
                    if len(names) == 1 and names[0] in self._typedef_structs:
                        self._typedef_structs[name] = list(self._typedef_structs[names[0]])

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
            elif isinstance(item, c_ast.While):
                if item.cond:
                    self._check_reads(item.cond, var_states)
                if item.stmt and isinstance(item.stmt, c_ast.Compound) and item.stmt.block_items:
                    # Body may execute zero times: fork so its inits don't
                    # count as definite for code after the loop.
                    self._scan_block(item.stmt.block_items, _fork_states(var_states))
            elif isinstance(item, c_ast.DoWhile):
                # A do-while executes its body once before evaluating the
                # condition, so scan the body first, then the condition.
                # The body runs unconditionally: share states (dict copy keeps
                # inner declarations from leaking, while writes to outer vars
                # correctly propagate).
                if item.stmt and isinstance(item.stmt, c_ast.Compound) and item.stmt.block_items:
                    self._scan_block(item.stmt.block_items, dict(var_states))
                if item.cond:
                    self._check_reads(item.cond, var_states)
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
                    self._scan_block(item.stmt.block_items, _fork_states(var_states))
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
        elif isinstance(decl.type, c_ast.TypeDecl) and isinstance(decl.type.type, c_ast.IdentifierType):
            # Resolve typedef'd struct types (`typedef struct {...} S; S s;`)
            # so they are tracked per-field instead of as opaque scalars.
            names = decl.type.type.names
            if len(names) == 1 and names[0] in self._typedef_structs:
                struct_fields = list(self._typedef_structs[names[0]])
                is_struct = True

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

        if node.op != "=":
            # Compound assignment (x += 1) reads the lvalue before writing it.
            self._check_reads(node.lvalue, var_states)

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

        # Fork deep copies for each branch so initialization inside one branch
        # cannot leak into the outer scope, then merge explicitly: a variable
        # counts as initialized after the if only when EVERY possible path
        # (including the implicit fall-through when there is no else)
        # initializes it.
        branch_states: list[dict[str, _VarState]] = []

        true_states = _fork_states(var_states)
        if node.iftrue:
            if isinstance(node.iftrue, c_ast.Compound) and node.iftrue.block_items:
                self._scan_block(node.iftrue.block_items, true_states)
            else:
                self._scan_block([node.iftrue], true_states)
        # A branch that definitely terminates (return/break/...) never reaches
        # the code after the if, so it must not weaken the merge.
        if not _branch_terminates(node.iftrue):
            branch_states.append(true_states)

        if node.iffalse:
            false_states = _fork_states(var_states)
            if isinstance(node.iffalse, c_ast.Compound) and node.iffalse.block_items:
                self._scan_block(node.iffalse.block_items, false_states)
            elif isinstance(node.iffalse, c_ast.If):
                self._handle_if(node.iffalse, false_states)
            else:
                self._scan_block([node.iffalse], false_states)
            if not _branch_terminates(node.iffalse):
                branch_states.append(false_states)
        else:
            # No else: the fall-through path keeps the pre-if state.
            branch_states.append(_fork_states(var_states))

        for name, st in var_states.items():
            per_branch = [bs[name] for bs in branch_states if name in bs]
            if not per_branch:
                continue
            st.fully_initialized = all(b.fully_initialized for b in per_branch)
            st.initialized_indices = set.intersection(
                *[b.initialized_indices for b in per_branch]
            ) if per_branch else set()
            st.initialized_fields = set.intersection(
                *[b.initialized_fields for b in per_branch]
            ) if per_branch else set()

    def _handle_func_call(self, node: c_ast.FuncCall, var_states: dict[str, _VarState]) -> None:
        callee_name = node.name.name if isinstance(node.name, c_ast.ID) else None
        if node.args:
            for idx, arg in enumerate(node.args.exprs or []):
                if isinstance(arg, c_ast.UnaryOp) and arg.op == "&":
                    # Passing &var to a function. The overwhelmingly common
                    # reason to take a variable's address is so the callee can
                    # write into it (an out-parameter, e.g. timer_start(&timer)).
                    # Treat this as initializing the variable, unless we have a
                    # function summary that proves the callee does NOT write
                    # through this parameter.
                    if isinstance(arg.expr, c_ast.ID):
                        name = arg.expr.name
                        if name in var_states:
                            writes_through = self._callee_initializes_param(callee_name, idx)
                            if writes_through is False:
                                if not var_states[name].fully_initialized:
                                    self.report(
                                        node,
                                        f"Variable '{name}' passed by reference to '{callee_name}', "
                                        f"which does not initialize it",
                                        Severity.WARNING,
                                        RULE_9_1,
                                    )
                            else:
                                # Unknown callee or a proven out-parameter:
                                # assume the callee initializes the object.
                                var_states[name].fully_initialized = True
                    # Do not fall through to _check_reads for &var: taking an
                    # address is not a read of the value.
                    continue

                self._check_reads(arg, var_states)

    def _callee_initializes_param(self, callee_name: Optional[str], idx: int) -> Optional[bool]:
        """Tri-state answer to 'does callee write through its idx-th param?'

        True  -> summary proves it writes (out-parameter).
        False -> summary proves it does NOT write.
        None  -> unknown; caller should stay optimistic (address-of arguments
                 are out-parameters by convention).

        To avoid false positives we only ever return False when we are highly
        confident: the summary is present, records writes for OTHER parameters
        (so it is genuinely tracking writes) but not for this one. A summary
        that records no writes at all is treated as unknown, since our summary
        analysis may simply have failed to track an indirect write.
        """
        if not callee_name or not self._ctx:
            return None
        summary = getattr(self._ctx, "summaries", {}).get(callee_name)
        if summary is None:
            return None
        written = getattr(summary, "output_params_initialized", set())
        if idx in written:
            return True
        if written:
            return False
        return None

    def _check_reads(self, node: c_ast.Node, var_states: dict[str, _VarState]) -> None:
        if node is None:
            return

        if isinstance(node, c_ast.Assignment):
            # An assignment nested inside an expression context (e.g. the
            # init clause of `for (i = 0; ...)`) WRITES its lvalue - it must
            # not be treated as a read. Delegate to _handle_assignment, which
            # checks the rvalue (and the lvalue for compound ops) and then
            # marks the lvalue as initialized.
            self._handle_assignment(node, var_states)
            return

        if isinstance(node, c_ast.UnaryOp) and node.op == "&":
            # Taking a variable's address is not a read of its value. Treat a
            # bare &var as an out-parameter initialization to stay consistent
            # with _handle_func_call.
            if isinstance(node.expr, c_ast.ID):
                name = node.expr.name
                if name in var_states:
                    var_states[name].fully_initialized = True
            else:
                self._check_reads(node.expr, var_states)
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
            if stmt.op != "=":
                # Compound assignment (x += 1) reads the lvalue first.
                self._check_use(stmt.lvalue, state)
            self._mark_lvalue_initialized(stmt.lvalue, state)

        elif isinstance(stmt, c_ast.Return):
            if hasattr(stmt, 'expr') and stmt.expr:
                self._check_use(stmt.expr, state)

        elif isinstance(stmt, c_ast.FuncCall):
            self._process_call_args(stmt, state)
        else:
            self._check_use(stmt, state)

    def _mark_lvalue_initialized(self, lvalue: c_ast.Node, state: _UninitCFGState) -> None:
        """Mark the root variable of an assignment target as initialized.

        Resolves through StructRef/ArrayRef chains so `s.a = 1` and
        `arr[0] = 1` conservatively initialize `s` / `arr` (a plain
        `lvalue is ID` test would leave them permanently uninitialized).
        """
        node = lvalue
        while isinstance(node, (c_ast.StructRef, c_ast.ArrayRef)):
            if isinstance(node, c_ast.ArrayRef) and node.subscript is not None:
                self._check_use(node.subscript, state)
            node = node.name
        if isinstance(node, c_ast.ID):
            state.init.add(node.name)
            state.uninit.discard(node.name)

    def _process_call_args(self, call: c_ast.FuncCall, state: _UninitCFGState) -> None:
        if not call.args:
            return
        for arg in call.args.exprs or []:
            if isinstance(arg, c_ast.UnaryOp) and arg.op == "&" and isinstance(arg.expr, c_ast.ID):
                # &var passed to a function is treated as an out-parameter
                # write: the callee is assumed to initialize the object.
                name = arg.expr.name
                state.init.add(name)
                state.uninit.discard(name)
                continue
            self._check_use(arg, state)

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
        if isinstance(node, c_ast.UnaryOp) and node.op == "&":
            # Taking an address is not a read of the value; if the operand is a
            # plain variable, treat it as an out-parameter write (initialized).
            if isinstance(node.expr, c_ast.ID):
                state.init.add(node.expr.name)
                state.uninit.discard(node.expr.name)
            else:
                self._check_use(node.expr, state)
            return
        if isinstance(node, c_ast.FuncCall):
            # A nested call (e.g. x = foo(&y)) may itself have &var out-params.
            self._process_call_args(node, state)
            return
        if isinstance(node, c_ast.Assignment):
            # Nested assignment expression: the lvalue is written, not read
            # (except by compound operators), and becomes initialized.
            self._check_use(node.rvalue, state)
            if node.op != "=":
                self._check_use(node.lvalue, state)
            self._mark_lvalue_initialized(node.lvalue, state)
            return
        for _, child in node.children():
            self._check_use(child, state)


CheckerRegistry.register(UninitVarsChecker)

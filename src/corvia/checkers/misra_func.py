"""MISRA C:2012 function rules (Rules 17.1-17.8)."""

from __future__ import annotations

from pycparser import c_ast

from corvia.checkers.base import BaseChecker, parse_int_literal
from corvia.models import MisraCategory, MisraRule, Severity
from corvia.registry import CheckerRegistry

RULE_17_1 = MisraRule("17.1", MisraCategory.REQUIRED, "The features of <stdarg.h> shall not be used")
RULE_17_2 = MisraRule("17.2", MisraCategory.REQUIRED, "Functions shall not call themselves, either directly or indirectly")
RULE_17_3 = MisraRule("17.3", MisraCategory.MANDATORY, "A function shall not be declared implicitly")
RULE_17_4 = MisraRule("17.4", MisraCategory.MANDATORY, "All exit paths from a function with non-void return type shall have an explicit return statement with an expression")
RULE_17_5 = MisraRule("17.5", MisraCategory.ADVISORY, "The function argument corresponding to a parameter declared to have an array type shall have an appropriate number of elements")
RULE_17_6 = MisraRule("17.6", MisraCategory.MANDATORY, "The declaration of an array parameter shall not contain the static keyword between the [ ]")
RULE_17_7 = MisraRule("17.7", MisraCategory.REQUIRED, "The value returned by a function having non-void return type shall be used")
RULE_17_8 = MisraRule("17.8", MisraCategory.ADVISORY, "A function parameter should not be modified")

_STDARG_NAMES = {"va_list", "va_start", "va_end", "va_arg", "va_copy"}


class MisraFuncChecker(BaseChecker):
    checker_id = "misra-func"
    description = "MISRA C:2012 Rules 17.1-17.8: function rules"
    default_severity = Severity.WARNING
    misra_rules = [RULE_17_1, RULE_17_2, RULE_17_3, RULE_17_4,
                   RULE_17_5, RULE_17_6, RULE_17_7, RULE_17_8]

    def __init__(self) -> None:
        super().__init__()
        self._func_names: set[str] = set()

    def reset(self) -> None:
        self._func_names = set()

    def visit_FileAST(self, node: c_ast.FileAST) -> None:
        for ext in node.ext or []:
            if isinstance(ext, c_ast.FuncDef) and ext.decl and ext.decl.name:
                self._func_names.add(ext.decl.name)
        self.generic_visit(node)

    def visit_FuncDef(self, node: c_ast.FuncDef) -> None:
        func_name = node.decl.name if node.decl else None

        if func_name and node.body:
            if self._ctx is not None and self._ctx.call_graph.is_recursive(func_name):
                self.report(
                    node.decl,
                    f"Function '{func_name}' is recursive (direct or indirect)",
                    Severity.WARNING,
                    RULE_17_2,
                )
            else:
                self._check_direct_recursion(func_name, node.body, node)

        if node.decl and node.decl.type:
            ret_type = self._get_return_type(node.decl.type)
            if ret_type and ret_type != "void":
                if node.body:
                    if not self._all_paths_return(node.body):
                        self.report(
                            node.decl,
                            f"Function '{func_name}' with non-void return type may not return a value on all paths",
                            Severity.ERROR,
                            RULE_17_4,
                        )

        if node.body and node.decl and node.decl.type:
            param_names = self._get_param_names(node.decl.type)
            if param_names:
                self._check_param_modification(node.body, param_names, node)

        self.generic_visit(node)

    def visit_FuncCall(self, node: c_ast.FuncCall) -> None:
        if isinstance(node.name, c_ast.ID):
            if node.name.name in _STDARG_NAMES:
                self.report(
                    node,
                    f"Use of stdarg feature '{node.name.name}'",
                    Severity.WARNING,
                    RULE_17_1,
                )
        self.generic_visit(node)

    def visit_Compound(self, node: c_ast.Compound) -> None:
        for stmt in node.block_items or []:
            if isinstance(stmt, c_ast.FuncCall) and isinstance(stmt.name, c_ast.ID):
                self._check_unused_return(stmt)
        self.generic_visit(node)

    def _check_unused_return(self, call: c_ast.FuncCall) -> None:
        if self._ctx is None:
            return
        callee = call.name.name if isinstance(call.name, c_ast.ID) else None
        if callee is None:
            return
        sym = self._ctx.symbol_table.lookup_function(callee)
        if sym is None:
            return
        if sym.return_type and sym.return_type not in ("void", ""):
            self.report(
                call,
                f"Return value of non-void function '{callee}' is discarded",
                Severity.WARNING,
                RULE_17_7,
            )

    def visit_Decl(self, node: c_ast.Decl) -> None:
        # Decl.type is a TypeDecl wrapper; the IdentifierType lives inside it.
        type_node = node.type
        if isinstance(type_node, c_ast.TypeDecl):
            type_node = type_node.type
        if isinstance(type_node, c_ast.IdentifierType):
            if any(n in _STDARG_NAMES for n in type_node.names):
                self.report(
                    node,
                    "Use of stdarg type 'va_list'",
                    Severity.WARNING,
                    RULE_17_1,
                )
        self.generic_visit(node)

    def _check_direct_recursion(self, func_name: str, body: c_ast.Node, func_node: c_ast.Node) -> None:
        if isinstance(body, c_ast.FuncCall):
            if isinstance(body.name, c_ast.ID) and body.name.name == func_name:
                self.report(
                    body,
                    f"Function '{func_name}' calls itself (direct recursion)",
                    Severity.WARNING,
                    RULE_17_2,
                )
                return
        for _, child in body.children():
            self._check_direct_recursion(func_name, child, func_node)

    def _get_return_type(self, type_node: c_ast.Node) -> str | None:
        if isinstance(type_node, c_ast.FuncDecl):
            return self._get_return_type(type_node.type)
        if isinstance(type_node, c_ast.TypeDecl):
            return self._get_return_type(type_node.type)
        if isinstance(type_node, c_ast.IdentifierType):
            return " ".join(type_node.names)
        if isinstance(type_node, c_ast.PtrDecl):
            return "pointer"
        return None

    def _all_paths_return(self, body: c_ast.Compound) -> bool:
        if body.block_items is None:
            return False
        for item in reversed(body.block_items):
            if isinstance(item, c_ast.Return) and item.expr is not None:
                return True
            if isinstance(item, c_ast.If):
                if (item.iftrue and item.iffalse
                    and self._block_returns(item.iftrue)
                    and self._block_returns(item.iffalse)):
                    return True
            if isinstance(item, c_ast.Switch) and self._switch_all_clauses_return(item):
                return True
            if isinstance(item, (c_ast.While, c_ast.DoWhile)) and self._is_infinite_loop(item):
                # `while (1) { ... }` with no break never falls through, so
                # the "missing" return after it is unreachable.
                return True
            if isinstance(item, c_ast.For) and item.cond is None and not self._contains_break(item.stmt):
                return True  # `for (;;)` without break
        return False

    def _block_returns(self, node: c_ast.Node) -> bool:
        if isinstance(node, c_ast.Return) and node.expr is not None:
            return True
        if isinstance(node, c_ast.Compound):
            return self._all_paths_return(node)
        return False

    def _switch_all_clauses_return(self, sw: c_ast.Switch) -> bool:
        """True for a switch with a default clause where every clause returns."""
        body = sw.stmt
        items = body.block_items if isinstance(body, c_ast.Compound) and body.block_items else []
        has_default = False
        clauses: list[list[c_ast.Node]] = []
        for item in items:
            if isinstance(item, (c_ast.Case, c_ast.Default)):
                if isinstance(item, c_ast.Default):
                    has_default = True
                if clauses and not clauses[-1]:
                    # Consecutive label of the same clause.
                    clauses[-1].extend(item.stmts or [])
                else:
                    clauses.append(list(item.stmts or []))
            else:
                if clauses:
                    clauses[-1].append(item)
        if not has_default or not clauses:
            return False
        return all(self._stmts_return(stmts) for stmts in clauses)

    def _stmts_return(self, stmts: list[c_ast.Node]) -> bool:
        for s in reversed(stmts):
            if isinstance(s, c_ast.Return) and s.expr is not None:
                return True
            if isinstance(s, c_ast.Compound):
                return self._stmts_return(s.block_items or [])
            if isinstance(s, c_ast.If):
                return (s.iftrue is not None and s.iffalse is not None
                        and self._block_returns(s.iftrue)
                        and self._block_returns(s.iffalse))
            return False
        return False

    def _is_infinite_loop(self, loop: c_ast.Node) -> bool:
        cond = getattr(loop, "cond", None)
        if not (isinstance(cond, c_ast.Constant) and cond.type == "int"):
            return False
        val = parse_int_literal(cond.value)
        if not val:  # 0 or unparseable: not an infinite loop
            return False
        return not self._contains_break(loop.stmt)

    def _contains_break(self, node: c_ast.Node) -> bool:
        """Does the loop body contain a break at this loop's level?
        (breaks inside nested loops/switches belong to those constructs)."""
        if node is None:
            return False
        if isinstance(node, c_ast.Break):
            return True
        if isinstance(node, (c_ast.For, c_ast.While, c_ast.DoWhile, c_ast.Switch)):
            return False
        for _, child in node.children():
            if self._contains_break(child):
                return True
        return False

    def _get_param_names(self, type_node: c_ast.Node) -> set[str]:
        names: set[str] = set()
        if isinstance(type_node, c_ast.FuncDecl) and type_node.args:
            for param in type_node.args.params or []:
                if isinstance(param, c_ast.Decl) and param.name:
                    names.add(param.name)
        return names

    def _check_param_modification(self, body: c_ast.Node, param_names: set[str], func_node: c_ast.Node) -> None:
        if isinstance(body, c_ast.Assignment):
            if isinstance(body.lvalue, c_ast.ID) and body.lvalue.name in param_names:
                self.report(
                    body,
                    f"Function parameter '{body.lvalue.name}' is modified",
                    Severity.INFO,
                    RULE_17_8,
                )
        if isinstance(body, c_ast.UnaryOp) and body.op in ("++", "--", "p++", "p--"):
            if isinstance(body.expr, c_ast.ID) and body.expr.name in param_names:
                self.report(
                    body,
                    f"Function parameter '{body.expr.name}' is modified via '{body.op}'",
                    Severity.INFO,
                    RULE_17_8,
                )
        for _, child in body.children():
            self._check_param_modification(child, param_names, func_node)


CheckerRegistry.register(MisraFuncChecker)

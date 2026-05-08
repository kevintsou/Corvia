"""MISRA C:2012 control flow rules (Rules 14.1-14.4, 15.1-15.7)."""

from __future__ import annotations

from pycparser import c_ast

from corvia.checkers.base import BaseChecker
from corvia.models import MisraCategory, MisraRule, Severity
from corvia.registry import CheckerRegistry

RULE_14_1 = MisraRule("14.1", MisraCategory.REQUIRED, "A loop counter shall not have essentially floating type")
RULE_14_2 = MisraRule("14.2", MisraCategory.REQUIRED, "A for loop shall be well-formed")
RULE_14_3 = MisraRule("14.3", MisraCategory.REQUIRED, "Controlling expressions shall not be invariant")
RULE_14_4 = MisraRule("14.4", MisraCategory.REQUIRED, "The controlling expression of an if-statement and the controlling expression of an iteration-statement shall have essentially Boolean type")
RULE_15_1 = MisraRule("15.1", MisraCategory.ADVISORY, "The goto statement should not be used")
RULE_15_2 = MisraRule("15.2", MisraCategory.REQUIRED, "The goto statement shall jump to a label declared later in the same function")
RULE_15_3 = MisraRule("15.3", MisraCategory.REQUIRED, "Any label referenced by a goto statement shall be declared in the same block, or in any block enclosing the goto statement")
RULE_15_4 = MisraRule("15.4", MisraCategory.ADVISORY, "There should be no more than one break or goto statement used to terminate any iteration statement")
RULE_15_5 = MisraRule("15.5", MisraCategory.ADVISORY, "A function should have a single point of exit at the end")
RULE_15_6 = MisraRule("15.6", MisraCategory.REQUIRED, "The body of an iteration-statement or a selection-statement shall be a compound-statement")
RULE_15_7 = MisraRule("15.7", MisraCategory.REQUIRED, "All if...else if constructs shall be terminated with an else statement")


class MisraControlChecker(BaseChecker):
    checker_id = "misra-control"
    description = "MISRA C:2012 Rules 14.1-14.4, 15.1-15.7: control flow rules"
    default_severity = Severity.WARNING
    misra_rules = [RULE_14_1, RULE_14_2, RULE_14_3, RULE_14_4,
                   RULE_15_1, RULE_15_2, RULE_15_3, RULE_15_4, RULE_15_5, RULE_15_6, RULE_15_7]

    def visit_Goto(self, node: c_ast.Goto) -> None:
        self.report(node, f"Use of goto statement (target: '{node.name}')", Severity.INFO, RULE_15_1)
        self.generic_visit(node)

    def visit_For(self, node: c_ast.For) -> None:
        if node.init:
            float_names = self._get_float_var_names(node.init)
            if float_names:
                self.report(
                    node,
                    f"Loop counter with floating-point type: {', '.join(float_names)}",
                    Severity.WARNING,
                    RULE_14_1,
                )

        if node.stmt:
            breaks = self._count_breaks(node.stmt)
            gotos = self._count_gotos(node.stmt)
            if breaks + gotos > 1:
                self.report(
                    node,
                    f"Loop has {breaks + gotos} break/goto statements (should be at most 1)",
                    Severity.INFO,
                    RULE_15_4,
                )

        self.generic_visit(node)

    def visit_While(self, node: c_ast.While) -> None:
        if node.stmt:
            breaks = self._count_breaks(node.stmt)
            gotos = self._count_gotos(node.stmt)
            if breaks + gotos > 1:
                self.report(
                    node,
                    f"Loop has {breaks + gotos} break/goto statements (should be at most 1)",
                    Severity.INFO,
                    RULE_15_4,
                )
        self.generic_visit(node)

    def visit_DoWhile(self, node: c_ast.DoWhile) -> None:
        if node.stmt:
            breaks = self._count_breaks(node.stmt)
            gotos = self._count_gotos(node.stmt)
            if breaks + gotos > 1:
                self.report(
                    node,
                    f"Loop has {breaks + gotos} break/goto statements (should be at most 1)",
                    Severity.INFO,
                    RULE_15_4,
                )
        self.generic_visit(node)

    def visit_If(self, node: c_ast.If) -> None:
        if node.iffalse and isinstance(node.iffalse, c_ast.If):
            terminal = self._find_else_if_terminal(node)
            if terminal and terminal.iffalse is None:
                self.report(
                    node,
                    "if...else if chain is not terminated with a final 'else' clause",
                    Severity.WARNING,
                    RULE_15_7,
                )
        self.generic_visit(node)

    def visit_FuncDef(self, node: c_ast.FuncDef) -> None:
        if node.body and node.body.block_items:
            returns = self._count_returns(node.body)
            if returns > 1:
                self.report(
                    node.decl or node,
                    f"Function has {returns} return statements (should have single exit point)",
                    Severity.INFO,
                    RULE_15_5,
                )
        self.generic_visit(node)

    def _find_else_if_terminal(self, node: c_ast.If) -> c_ast.If | None:
        current = node
        while current.iffalse and isinstance(current.iffalse, c_ast.If):
            current = current.iffalse
        return current

    def _count_returns(self, node: c_ast.Node) -> int:
        count = 0
        if isinstance(node, c_ast.Return):
            return 1
        for _, child in node.children():
            count += self._count_returns(child)
        return count

    def _count_breaks(self, node: c_ast.Node) -> int:
        count = 0
        if isinstance(node, c_ast.Break):
            return 1
        if isinstance(node, (c_ast.For, c_ast.While, c_ast.DoWhile, c_ast.Switch)):
            return 0
        for _, child in node.children():
            count += self._count_breaks(child)
        return count

    def _count_gotos(self, node: c_ast.Node) -> int:
        count = 0
        if isinstance(node, c_ast.Goto):
            return 1
        for _, child in node.children():
            count += self._count_gotos(child)
        return count

    def _get_float_var_names(self, init: c_ast.Node) -> list[str]:
        names = []
        if isinstance(init, c_ast.DeclList):
            for decl in init.decls or []:
                if isinstance(decl, c_ast.Decl) and decl.type:
                    if self._is_float_type(decl.type):
                        if decl.name:
                            names.append(decl.name)
        elif isinstance(init, c_ast.Decl) and init.type:
            if self._is_float_type(init.type):
                if init.name:
                    names.append(init.name)
        return names

    def _is_float_type(self, type_node: c_ast.Node) -> bool:
        if isinstance(type_node, c_ast.TypeDecl):
            return self._is_float_type(type_node.type)
        if isinstance(type_node, c_ast.IdentifierType):
            return any(t in ("float", "double") for t in type_node.names)
        return False


CheckerRegistry.register(MisraControlChecker)

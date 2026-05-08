"""Unused variable checker."""

from __future__ import annotations

from pycparser import c_ast

from corvia.checkers.base import BaseChecker
from corvia.models import MisraCategory, MisraRule, Severity
from corvia.registry import CheckerRegistry

RULE_2_2 = MisraRule("2.2", MisraCategory.REQUIRED, "There shall be no dead code")
RULE_2_3 = MisraRule("2.3", MisraCategory.ADVISORY, "A project should not contain unused type declarations")
RULE_2_7 = MisraRule("2.7", MisraCategory.ADVISORY, "There should be no unused parameters in functions")


class _IDCollector(c_ast.NodeVisitor):
    """Collects all ID references in a subtree."""

    def __init__(self) -> None:
        self.names: set[str] = set()

    def visit_ID(self, node: c_ast.ID) -> None:
        self.names.add(node.name)


class UnusedVarsChecker(BaseChecker):
    checker_id = "unused-var"
    description = "Detects unused local variables and function parameters"
    default_severity = Severity.WARNING
    misra_rules = [RULE_2_2, RULE_2_3, RULE_2_7]

    def visit_FuncDef(self, node: c_ast.FuncDef) -> None:
        declared: dict[str, c_ast.Node] = {}

        if node.decl and node.decl.type and isinstance(node.decl.type, c_ast.FuncDecl):
            params = node.decl.type.args
            if params:
                for param in params.params or []:
                    if isinstance(param, c_ast.Decl) and param.name:
                        if param.name != "void":
                            declared[param.name] = param

        if node.body and node.body.block_items:
            for item in node.body.block_items:
                if isinstance(item, c_ast.Decl) and item.name:
                    declared[item.name] = item

        if not declared:
            return

        used = self._collect_used_names(node.body)

        param_names = set()
        if node.decl and node.decl.type and isinstance(node.decl.type, c_ast.FuncDecl):
            params = node.decl.type.args
            if params:
                for param in params.params or []:
                    if isinstance(param, c_ast.Decl) and param.name:
                        param_names.add(param.name)

        for name, decl_node in declared.items():
            if name.startswith("_"):
                continue
            if name not in used:
                if name in param_names:
                    self.report(
                        decl_node,
                        f"Unused parameter '{name}'",
                        Severity.INFO,
                        RULE_2_7,
                    )
                else:
                    self.report(
                        decl_node,
                        f"Unused variable '{name}'",
                        Severity.WARNING,
                        RULE_2_2,
                    )

    def _collect_used_names(self, body: c_ast.Compound) -> set[str]:
        if body is None or body.block_items is None:
            return set()

        collector = _IDCollector()
        for item in body.block_items:
            if isinstance(item, c_ast.Decl):
                if item.init:
                    collector.visit(item.init)
            else:
                collector.visit(item)
        return collector.names


CheckerRegistry.register(UnusedVarsChecker)

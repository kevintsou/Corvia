"""Unused variable checker."""

from __future__ import annotations

from pycparser import c_ast

from corvia.checkers.base import BaseChecker
from corvia.models import MisraCategory, MisraRule, Severity
from corvia.registry import CheckerRegistry

RULE_2_2 = MisraRule("2.2", MisraCategory.REQUIRED, "There shall be no dead code")
RULE_2_3 = MisraRule("2.3", MisraCategory.ADVISORY, "A project should not contain unused type declarations")
RULE_2_4 = MisraRule("2.4", MisraCategory.ADVISORY, "A project should not contain unused tag declarations")
RULE_2_6 = MisraRule("2.6", MisraCategory.ADVISORY, "A function should not contain unused label declarations")
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
    misra_rules = [RULE_2_2, RULE_2_3, RULE_2_4, RULE_2_6, RULE_2_7]

    def visit_FuncDef(self, node: c_ast.FuncDef) -> None:
        self._check_unused_labels_2_6(node)
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


    def _check_unused_labels_2_6(self, func: c_ast.FuncDef) -> None:
        labels: dict[str, c_ast.Label] = {}
        targets: set[str] = set()
        self._collect_labels_and_gotos(func.body, labels, targets)
        for name, lbl in labels.items():
            if name not in targets:
                self.report(
                    lbl,
                    f"Unused label '{name}'",
                    Severity.INFO,
                    RULE_2_6,
                )

    def _collect_labels_and_gotos(
        self, node: c_ast.Node, labels: dict[str, c_ast.Label], targets: set[str]
    ) -> None:
        if node is None:
            return
        if isinstance(node, c_ast.Label):
            labels[node.name] = node
        elif isinstance(node, c_ast.Goto):
            targets.add(node.name)
        for _, child in node.children():
            self._collect_labels_and_gotos(child, labels, targets)

    def visit_FileAST(self, node: c_ast.FileAST) -> None:
        self._check_unused_tags_2_4(node)
        self.generic_visit(node)

    def _check_unused_tags_2_4(self, ast: c_ast.FileAST) -> None:
        if self._ctx is None:
            return
        ctx_tags = self._ctx.symbol_table.tags
        if not ctx_tags:
            return

        used_tags: set[str] = set()
        self._collect_used_tags(ast, used_tags)

        for tag_key, tag in ctx_tags.items():
            if tag.file != self._current_file:
                continue
            if tag.name not in used_tags:
                # If the tag declares members but is never referenced
                # outside its own definition, flag it.
                self.report(
                    tag.ast_node or ast,
                    f"Unused tag '{tag_key}'",
                    Severity.INFO,
                    RULE_2_4,
                )

    def _collect_used_tags(self, node: c_ast.Node, out: set[str]) -> None:
        if node is None:
            return
        if isinstance(node, (c_ast.Struct, c_ast.Union, c_ast.Enum)):
            if node.name and (
                getattr(node, "decls", None) is None
                and (not isinstance(node, c_ast.Enum) or node.values is None)
            ):
                out.add(node.name)
        for _, child in node.children():
            self._collect_used_tags(child, out)


CheckerRegistry.register(UnusedVarsChecker)

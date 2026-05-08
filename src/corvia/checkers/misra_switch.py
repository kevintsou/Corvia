"""MISRA C:2012 Section 16: Switch statements.

Implements Rules 16.1 (well-formedness, restricted heuristic), 16.3
(unconditional break terminates each clause), 16.4 (default required),
16.5 (default first or last), 16.6 (at least two switch-clauses), and
16.7 (switch expression must not be essentially Boolean).

Rule 16.2 (switch labels only at body level) is partially covered by
16.1 and is not always detectable from the AST alone.
"""

from __future__ import annotations

from pycparser import c_ast

from corvia.checkers.base import BaseChecker
from corvia.models import MisraCategory, MisraRule, Severity
from corvia.registry import CheckerRegistry


RULE_16_1 = MisraRule("16.1", MisraCategory.REQUIRED, "All switch statements shall be well-formed")
RULE_16_3 = MisraRule(
    "16.3", MisraCategory.REQUIRED,
    "An unconditional break statement shall terminate every switch-clause",
)
RULE_16_4 = MisraRule("16.4", MisraCategory.REQUIRED, "Every switch statement shall have a default label")
RULE_16_5 = MisraRule(
    "16.5", MisraCategory.REQUIRED,
    "A default label shall appear as either the first or the last switch label of a switch statement",
)
RULE_16_6 = MisraRule("16.6", MisraCategory.REQUIRED, "Every switch statement shall have at least two switch-clauses")
RULE_16_7 = MisraRule(
    "16.7", MisraCategory.REQUIRED,
    "A switch-expression shall not have essentially Boolean type",
)


def _ends_with_break_or_return(stmts: list[c_ast.Node]) -> bool:
    if not stmts:
        return False
    for s in reversed(stmts):
        if isinstance(s, (c_ast.Break, c_ast.Return, c_ast.Continue, c_ast.Goto)):
            return True
        if isinstance(s, c_ast.Compound):
            return _ends_with_break_or_return(s.block_items or [])
        return False
    return False


def _is_boolean_expr(node: c_ast.Node) -> bool:
    if isinstance(node, c_ast.BinaryOp) and node.op in ("==", "!=", "<", ">", "<=", ">=", "&&", "||"):
        return True
    if isinstance(node, c_ast.UnaryOp) and node.op == "!":
        return True
    return False


class MisraSwitchChecker(BaseChecker):
    checker_id = "misra-switch"
    description = "MISRA C:2012 Rules 16.1, 16.3-16.7: switch statement rules"
    default_severity = Severity.WARNING
    misra_rules = [RULE_16_1, RULE_16_3, RULE_16_4, RULE_16_5, RULE_16_6, RULE_16_7]

    def visit_Switch(self, node: c_ast.Switch) -> None:
        # 16.7: condition must not be boolean.
        if node.cond is not None and _is_boolean_expr(node.cond):
            self.report(
                node,
                "Switch expression has essentially Boolean type",
                Severity.WARNING,
                RULE_16_7,
            )

        body = node.stmt
        items: list[c_ast.Node] = []
        if isinstance(body, c_ast.Compound) and body.block_items:
            items = list(body.block_items)
        elif body is not None:
            items = [body]

        cases: list[tuple[c_ast.Node, list[c_ast.Node]]] = []
        has_default = False
        default_position = -1
        case_position = 0

        current_label: c_ast.Node | None = None
        current_stmts: list[c_ast.Node] = []
        for item in items:
            if isinstance(item, (c_ast.Case, c_ast.Default)):
                if current_label is not None:
                    cases.append((current_label, current_stmts))
                current_label = item
                current_stmts = []
                if isinstance(item, c_ast.Default):
                    has_default = True
                    default_position = case_position
                if item.stmts:
                    current_stmts.extend(item.stmts)
                case_position += 1
            else:
                current_stmts.append(item)
        if current_label is not None:
            cases.append((current_label, current_stmts))

        # 16.6: must have at least two clauses.
        if len(cases) < 2:
            self.report(
                node,
                f"Switch statement has only {len(cases)} clause(s); MISRA requires at least 2",
                Severity.WARNING,
                RULE_16_6,
            )

        # 16.4: must have default.
        if not has_default:
            self.report(
                node,
                "Switch statement is missing a default label",
                Severity.WARNING,
                RULE_16_4,
            )

        # 16.5: default first or last.
        if has_default and default_position not in (0, len(cases) - 1):
            self.report(
                node,
                "Default label is neither the first nor the last switch label",
                Severity.WARNING,
                RULE_16_5,
            )

        # 16.3: every clause must be terminated by an unconditional break.
        for label, stmts in cases:
            if not _ends_with_break_or_return(stmts):
                self.report(
                    label,
                    "Switch-clause is not terminated by an unconditional break / return",
                    Severity.WARNING,
                    RULE_16_3,
                )

        self.generic_visit(node)


CheckerRegistry.register(MisraSwitchChecker)

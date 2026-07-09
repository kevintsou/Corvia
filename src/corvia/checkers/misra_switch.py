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
RULE_16_2 = MisraRule(
    "16.2", MisraCategory.REQUIRED,
    "A switch label shall only be used when the most closely-enclosing compound statement is the body of a switch statement",
)
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
        if isinstance(s, (c_ast.Case, c_ast.Default)):
            # Multi-label clause (`case 1: case 2: break;`): the terminating
            # statement lives inside the trailing nested label. Unwrap it.
            return _ends_with_break_or_return(s.stmts or [])
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
    misra_rules = [RULE_16_1, RULE_16_2, RULE_16_3, RULE_16_4, RULE_16_5, RULE_16_6, RULE_16_7]

    def visit_Switch(self, node: c_ast.Switch) -> None:
        body = node.stmt
        if isinstance(body, c_ast.Compound) and body.block_items:
            for item in body.block_items:
                self._check_label_position_16_2(item, switch_body=body)

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

        # Group switch labels into clauses. Consecutive labels with no
        # statements between them (`case 1: case 2: break;`) are multiple
        # labels of the SAME clause, not separate empty clauses.
        groups: list[dict] = []  # {"labels": [Case/Default...], "stmts": [...]}
        for item in items:
            if isinstance(item, (c_ast.Case, c_ast.Default)):
                if groups and not groups[-1]["stmts"]:
                    groups[-1]["labels"].append(item)
                    groups[-1]["stmts"].extend(item.stmts or [])
                else:
                    groups.append({"labels": [item], "stmts": list(item.stmts or [])})
            else:
                if groups:
                    groups[-1]["stmts"].append(item)

        cases: list[tuple[c_ast.Node, list[c_ast.Node]]] = [
            (g["labels"][0], g["stmts"]) for g in groups
        ]
        has_default = False
        default_position = -1
        for pos, g in enumerate(groups):
            if any(isinstance(lbl, c_ast.Default) for lbl in g["labels"]):
                has_default = True
                default_position = pos

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


    def _check_label_position_16_2(self, node: c_ast.Node, switch_body: c_ast.Compound) -> None:
        """Recursively walk into nested compound statements; any Case/Default
        we find in a sub-compound (i.e. not directly in `switch_body`) is a
        16.2 violation."""
        if isinstance(node, c_ast.Switch):
            # A nested switch owns its labels; recursing into it would report
            # perfectly legal inner case labels as 16.2 violations. The inner
            # switch gets its own visit_Switch pass.
            return
        if isinstance(node, c_ast.Compound):
            for item in node.block_items or []:
                if isinstance(item, (c_ast.Case, c_ast.Default)):
                    self.report(
                        item,
                        "Switch label appears inside a nested compound statement",
                        Severity.WARNING,
                        RULE_16_2,
                    )
                self._check_label_position_16_2(item, switch_body)
        else:
            for _, child in node.children():
                self._check_label_position_16_2(child, switch_body)


CheckerRegistry.register(MisraSwitchChecker)

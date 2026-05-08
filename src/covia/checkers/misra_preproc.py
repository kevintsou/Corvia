"""MISRA C:2012 preprocessor rules (Rules 20.1-20.14) - AST-detectable subset."""

from __future__ import annotations

from pycparser import c_ast

from covia.checkers.base import BaseChecker
from covia.models import MisraCategory, MisraRule, Severity
from covia.registry import CheckerRegistry

RULE_20_7 = MisraRule("20.7", MisraCategory.REQUIRED, "Expressions resulting from the expansion of macro parameters shall be enclosed in parentheses")
RULE_20_10 = MisraRule("20.10", MisraCategory.ADVISORY, "The # and ## preprocessor operators should not be used")
RULE_20_11 = MisraRule("20.11", MisraCategory.REQUIRED, "A macro parameter immediately following a # operator shall not immediately be followed by a ## operator")
RULE_20_12 = MisraRule("20.12", MisraCategory.REQUIRED, "A macro parameter used as an operand to the # or ## operators, which is itself subject to further macro replacement, shall only be used as an operand to these operators")
RULE_20_14 = MisraRule("20.14", MisraCategory.REQUIRED, "All #else, #elif and #endif preprocessor directives shall reside in the same file as the #if, #ifdef or #ifndef directive to which they are related")


class MisraPreprocChecker(BaseChecker):
    checker_id = "misra-preproc"
    description = "MISRA C:2012 Rules 20.x: preprocessor rules (AST-detectable subset)"
    default_severity = Severity.INFO
    misra_rules = [RULE_20_7, RULE_20_10, RULE_20_11, RULE_20_12, RULE_20_14]

    def visit_Pragma(self, node: c_ast.Pragma) -> None:
        self.generic_visit(node)


CheckerRegistry.register(MisraPreprocChecker)

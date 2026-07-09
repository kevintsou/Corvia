"""MISRA C:2012 expression rules (Rules 12.1-12.5, 13.1-13.6)."""

from __future__ import annotations

from pycparser import c_ast

from corvia.checkers.base import BaseChecker, int_literal_suffix, parse_int_literal
from corvia.models import MisraCategory, MisraRule, Severity
from corvia.registry import CheckerRegistry

RULE_12_1 = MisraRule("12.1", MisraCategory.ADVISORY, "The precedence of operators within expressions should be made explicit")
RULE_12_2 = MisraRule("12.2", MisraCategory.REQUIRED, "The right hand operand of a shift operator shall lie in the range zero to one less than the width in bits of the essential type of the left hand operand")
RULE_12_3 = MisraRule("12.3", MisraCategory.ADVISORY, "The comma operator should not be used")
RULE_12_4 = MisraRule("12.4", MisraCategory.ADVISORY, "Evaluation of constant expressions should not lead to unsigned integer wrap-around")
RULE_13_1 = MisraRule("13.1", MisraCategory.REQUIRED, "Initializer lists shall not contain persistent side effects")
RULE_13_2 = MisraRule("13.2", MisraCategory.REQUIRED, "The value of an expression and its persistent side effects shall be the same under all permitted evaluation orders")
RULE_13_3 = MisraRule("13.3", MisraCategory.ADVISORY, "A full expression containing an increment or decrement operator should have no other potential side effects")
# NOTE: Rule 13.4 (result of assignment operator used) is implemented by the
# `syntax` checker; it is deliberately NOT declared here (single ownership).
RULE_13_5 = MisraRule("13.5", MisraCategory.REQUIRED, "The right hand operand of a logical && or || operator shall not contain persistent side effects")
RULE_13_6 = MisraRule("13.6", MisraCategory.MANDATORY, "The operand of the sizeof operator shall not contain any expression which has potential side effects")

_LOW_PRECEDENCE_OPS = {"+", "-", "*", "/", "%", "<<", ">>", "&", "|", "^"}
_COMPARISON_OPS = {"<", ">", "<=", ">=", "==", "!="}
_LOGICAL_OPS = {"&&", "||"}

# Bit widths for types we can name with confidence. Plain `long` is
# deliberately absent (32-bit on Windows/ILP32, 64-bit on LP64): when the
# width is not reliably known, Rule 12.2 stays silent.
_TYPE_WIDTHS = {
    "char": 8, "signed char": 8, "unsigned char": 8, "int8_t": 8, "uint8_t": 8,
    "short": 16, "short int": 16, "signed short": 16, "unsigned short": 16,
    "int16_t": 16, "uint16_t": 16,
    "int": 32, "signed": 32, "signed int": 32, "unsigned": 32, "unsigned int": 32,
    "int32_t": 32, "uint32_t": 32,
    "long long": 64, "signed long long": 64, "unsigned long long": 64,
    "long long int": 64, "unsigned long long int": 64,
    "int64_t": 64, "uint64_t": 64,
}


class MisraExprChecker(BaseChecker):
    checker_id = "misra-expr"
    description = "MISRA C:2012 Rules 12.1-12.5, 13.1-13.6: expression and side effect rules"
    default_severity = Severity.WARNING
    misra_rules = [RULE_12_1, RULE_12_2, RULE_12_3, RULE_12_4,
                   RULE_13_1, RULE_13_2, RULE_13_3, RULE_13_5, RULE_13_6]

    def __init__(self) -> None:
        super().__init__()
        # ExprList nodes that are function-call argument lists, not comma
        # operators. pycparser represents both as c_ast.ExprList, so we record
        # the argument lists while visiting FuncCall and skip them in
        # visit_ExprList (tracked by object id).
        self._funccall_arg_lists: set[int] = set()
        # Declared integer variable widths (for Rule 12.2 shift-range checks).
        self._var_widths: dict[str, int] = {}

    def reset(self) -> None:
        self._funccall_arg_lists = set()
        self._var_widths = {}

    def visit_FuncCall(self, node: c_ast.FuncCall) -> None:
        if isinstance(node.args, c_ast.ExprList):
            self._funccall_arg_lists.add(id(node.args))
        self.generic_visit(node)

    def visit_BinaryOp(self, node: c_ast.BinaryOp) -> None:
        if node.op in _LOW_PRECEDENCE_OPS:
            if isinstance(node.left, c_ast.BinaryOp) and node.left.op in _LOW_PRECEDENCE_OPS:
                if self._needs_parens(node.op, node.left.op):
                    self.report(
                        node,
                        f"Operator precedence may be unclear: '{node.left.op}' within '{node.op}' (consider explicit parentheses)",
                        Severity.INFO,
                        RULE_12_1,
                    )
            if isinstance(node.right, c_ast.BinaryOp) and node.right.op in _LOW_PRECEDENCE_OPS:
                if self._needs_parens(node.op, node.right.op):
                    self.report(
                        node,
                        f"Operator precedence may be unclear: '{node.right.op}' within '{node.op}' (consider explicit parentheses)",
                        Severity.INFO,
                        RULE_12_1,
                    )

        if node.op in ("<<", ">>"):
            if isinstance(node.right, c_ast.Constant) and "int" in (node.right.type or ""):
                shift = parse_int_literal(node.right.value)
                width = self._infer_operand_width(node.left)
                # Only report when the left operand's width is actually
                # known: assuming 32 bits would falsely flag `1ULL << 40`.
                if shift is not None and width is not None and (shift < 0 or shift >= width):
                    self.report(
                        node,
                        f"Shift amount {shift} is out of range [0, {width - 1}] "
                        f"for a {width}-bit left operand",
                        Severity.WARNING,
                        RULE_12_2,
                    )

        if node.op in _LOGICAL_OPS:
            if self._has_side_effects(node.right):
                self.report(
                    node,
                    f"Right operand of '{node.op}' contains side effects",
                    Severity.WARNING,
                    RULE_13_5,
                )

        if node.op == ",":
            self.report(node, "Use of comma operator", Severity.INFO, RULE_12_3)

        self.generic_visit(node)

    def visit_ExprList(self, node: c_ast.ExprList) -> None:
        # A function-call argument list is also a c_ast.ExprList in pycparser,
        # but its commas are argument separators, not the comma operator. Only
        # report ExprLists that are genuine comma-operator expressions.
        if id(node) not in self._funccall_arg_lists:
            if node.exprs and len(node.exprs) > 1:
                self.report(node, "Use of comma operator", Severity.INFO, RULE_12_3)
        self.generic_visit(node)

    def visit_UnaryOp(self, node: c_ast.UnaryOp) -> None:
        if node.op == "sizeof":
            if self._has_side_effects(node.expr):
                self.report(
                    node,
                    "Operand of sizeof contains side effects",
                    Severity.ERROR,
                    RULE_13_6,
                )

        self.generic_visit(node)

    def visit_Decl(self, node: c_ast.Decl) -> None:
        # Record declared integer widths for Rule 12.2.
        if node.name and isinstance(node.type, c_ast.TypeDecl) \
                and isinstance(node.type.type, c_ast.IdentifierType):
            joined = " ".join(node.type.type.names)
            width = _TYPE_WIDTHS.get(joined)
            if width is not None:
                self._var_widths[node.name] = width
        self.generic_visit(node)

    def visit_Compound(self, node: c_ast.Compound) -> None:
        # Rule 13.3: a full expression (statement-level expression) containing
        # ++/-- should have no other potential side effects. Checked here at
        # the statement level, where the enclosing full expression is known.
        for stmt in node.block_items or []:
            self._check_13_3(stmt)
        self.generic_visit(node)

    def _check_13_3(self, stmt: c_ast.Node) -> None:
        if stmt is None or isinstance(stmt, (
            c_ast.Compound, c_ast.If, c_ast.While, c_ast.DoWhile, c_ast.For,
            c_ast.Switch, c_ast.Label, c_ast.Case, c_ast.Default,
            c_ast.Return, c_ast.Decl, c_ast.DeclList, c_ast.Goto,
            c_ast.Break, c_ast.Continue,
        )):
            return
        incdecs = self._find_incdec(stmt)
        if incdecs and self._count_side_effects(stmt) > 1:
            for op_node in incdecs:
                self.report(
                    op_node,
                    f"Expression with '{op_node.op}' has other potential side effects",
                    Severity.INFO,
                    RULE_13_3,
                )

    def _find_incdec(self, node: c_ast.Node) -> list[c_ast.UnaryOp]:
        found: list[c_ast.UnaryOp] = []
        if node is None:
            return found
        if isinstance(node, c_ast.UnaryOp) and node.op in ("++", "--", "p++", "p--"):
            found.append(node)
        for _, child in node.children():
            found.extend(self._find_incdec(child))
        return found

    def _infer_operand_width(self, node: c_ast.Node) -> int | None:
        """Best-effort bit width of a shift's left operand; None if unknown."""
        if isinstance(node, c_ast.Constant) and "int" in (node.type or ""):
            suffix = int_literal_suffix(node.value).lower()
            if "ll" in suffix:
                return 64
            if "l" in suffix:
                return None  # plain long: width is platform-dependent
            return 32
        if isinstance(node, c_ast.Cast) and node.to_type is not None:
            t = node.to_type
            if isinstance(t, c_ast.Typename):
                t = t.type
            if isinstance(t, c_ast.TypeDecl) and isinstance(t.type, c_ast.IdentifierType):
                return _TYPE_WIDTHS.get(" ".join(t.type.names))
            return None
        if isinstance(node, c_ast.ID):
            return self._var_widths.get(node.name)
        return None

    def visit_InitList(self, node: c_ast.InitList) -> None:
        if node.exprs:
            for expr in node.exprs:
                if self._has_side_effects(expr):
                    self.report(
                        expr,
                        "Initializer list contains expression with side effects",
                        Severity.WARNING,
                        RULE_13_1,
                    )
        self.generic_visit(node)

    def _has_side_effects(self, node: c_ast.Node) -> bool:
        if node is None:
            return False
        if isinstance(node, c_ast.FuncCall):
            return True
        if isinstance(node, c_ast.UnaryOp) and node.op in ("++", "--", "p++", "p--"):
            return True
        if isinstance(node, c_ast.Assignment):
            return True
        for _, child in node.children():
            if self._has_side_effects(child):
                return True
        return False

    def _count_side_effects(self, node: c_ast.Node) -> int:
        if node is None:
            return 0
        count = 0
        if isinstance(node, c_ast.FuncCall):
            count += 1
        if isinstance(node, c_ast.UnaryOp) and node.op in ("++", "--", "p++", "p--"):
            count += 1
        if isinstance(node, c_ast.Assignment):
            count += 1
        for _, child in node.children():
            count += self._count_side_effects(child)
        return count

    def _needs_parens(self, outer_op: str, inner_op: str) -> bool:
        bitwise = {"&", "|", "^"}
        arithmetic = {"+", "-", "*", "/", "%"}
        shift = {"<<", ">>"}
        # pycparser's AST records no parentheses: an arithmetic expression
        # nested under a bitwise operator (e.g. `a & b + c` parsing as
        # `a & (b + c)`) can arise WITHOUT parentheses because arithmetic
        # binds tighter - that is the unclear case to flag. The converse
        # (bitwise nested under arithmetic, e.g. `a + (b & c)`) can only be
        # written with explicit parentheses, so it is already clear.
        if outer_op in bitwise and inner_op in arithmetic:
            return True
        if outer_op in arithmetic and inner_op in bitwise:
            return False
        if (outer_op in bitwise and inner_op in bitwise and outer_op != inner_op):
            return True
        if (outer_op in shift and inner_op in arithmetic) or (outer_op in arithmetic and inner_op in shift):
            return True
        return False


CheckerRegistry.register(MisraExprChecker)

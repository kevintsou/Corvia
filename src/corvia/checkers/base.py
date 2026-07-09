"""Base checker abstract class for CORVIA static analysis."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Optional

from pycparser import c_ast

from corvia.models import Issue, MisraRule, Severity

if TYPE_CHECKING:
    from corvia.core.context import AnalysisContext


def parse_int_literal(value: str) -> Optional[int]:
    """Parse a C integer literal into a Python int.

    Handles the ``u``/``U``/``l``/``L`` suffixes and the ``0x``/``0X``,
    ``0b``/``0B`` and C-style leading-zero octal prefixes. Returns None when
    the literal cannot be parsed (e.g. floating constants, char constants).

    Shared by every checker that needs constant folding so that suffix
    handling does not drift between checkers.
    """
    if not isinstance(value, str) or not value:
        return None
    s = value.strip()
    neg = False
    if s and s[0] in "+-":
        neg = s[0] == "-"
        s = s[1:]
    core = s.rstrip("uUlL")
    if not core:
        return None
    try:
        lowered = core.lower()
        if lowered.startswith("0x"):
            val = int(core, 16)
        elif lowered.startswith("0b"):
            val = int(core, 2)
        elif len(core) > 1 and core[0] == "0":
            val = int(core, 8)
        else:
            val = int(core, 10)
    except ValueError:
        return None
    return -val if neg else val


def int_literal_suffix(value: str) -> str:
    """Return the integer-suffix characters (uUlL) at the end of a literal."""
    suffix = ""
    for ch in reversed(value):
        if ch in "uUlL":
            suffix = ch + suffix
        else:
            break
    return suffix


def is_reserved_identifier(name: str) -> bool:
    """Return True for identifiers reserved by the C implementation.

    C standard (7.1.3) reserves:
    * Names starting with ``__`` (double underscore)
    * Names starting with ``_`` followed by an uppercase letter

    GCC/Clang ARM intrinsics, MSVC extensions, and built-in helpers all fall
    into one of these categories. Reporting MISRA violations on them is
    noise - the programmer cannot rename them.
    """
    if name.startswith("__"):
        return True
    return len(name) >= 2 and name[0] == "_" and name[1].isupper()


class BaseChecker(c_ast.NodeVisitor):
    """Base class for all CORVIA checkers.

    Subclasses implement visit_XXX methods for AST node types they care about.
    pycparser's NodeVisitor dispatches to visit_XXX based on node class name.
    IMPORTANT: visit_XXX methods must call self.generic_visit(node) to continue
    traversal into child nodes.
    """

    checker_id: ClassVar[str]
    description: ClassVar[str]
    default_severity: ClassVar[Severity] = Severity.WARNING
    misra_rules: ClassVar[list[MisraRule]] = []

    def __init__(self) -> None:
        self._issues: list[Issue] = []
        self._current_file: str = ""
        self._ctx: Optional["AnalysisContext"] = None

    def set_file(self, filename: str) -> None:
        self._current_file = filename

    def set_context(self, ctx: "AnalysisContext") -> None:
        """Inject inter-procedural context. Optional — checkers may ignore it."""
        self._ctx = ctx

    @property
    def ctx(self) -> Optional["AnalysisContext"]:
        return self._ctx

    def report(
        self,
        node: c_ast.Node,
        message: str,
        severity: Optional[Severity] = None,
        misra_rule: Optional[MisraRule] = None,
    ) -> None:
        line = 0
        col = 0
        file = self._current_file
        if node.coord:
            line = node.coord.line
            col = node.coord.column or 0
            if node.coord.file and node.coord.file != self._current_file:
                file = node.coord.file

        self._issues.append(
            Issue(
                checker_id=self.checker_id,
                severity=severity or self.default_severity,
                message=message,
                file=file,
                line=line,
                column=col,
                misra_rule=misra_rule,
            )
        )

    def reset(self) -> None:
        """Clear per-run mutable state.

        Called by check() before each analysis run. Checkers that accumulate
        state across visit_XXX calls (caches, symbol maps, dedup sets) must
        override this to clear that state, so a checker instance reused across
        multiple files does not leak results from one file into the next.
        """

    def check(self, ast: c_ast.FileAST) -> list[Issue]:
        self._issues = []
        self.reset()
        self.visit(ast)
        return list(self._issues)

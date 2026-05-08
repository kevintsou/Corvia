"""MISRA C:2012 Section 21: Standard libraries.

Implements Rules 21.3, 21.4, 21.5, 21.6, 21.7, 21.8, 21.9, 21.10, 21.12 and
the function-detectable subset of 21.1 / 21.2 (calls to reserved
identifiers). Detection works at the FuncCall and Decl level — anything
that requires preprocessor knowledge (e.g. macro redefinition) is out of
scope without `--use-cpp`.
"""

from __future__ import annotations

from pycparser import c_ast

from corvia.checkers.base import BaseChecker
from corvia.models import MisraCategory, MisraRule, Severity
from corvia.registry import CheckerRegistry


RULE_21_1 = MisraRule("21.1", MisraCategory.REQUIRED, "#define and #undef shall not be used on a reserved identifier")
RULE_21_2 = MisraRule("21.2", MisraCategory.REQUIRED, "A reserved identifier or macro name shall not be declared")
RULE_21_3 = MisraRule("21.3", MisraCategory.REQUIRED, "The memory allocation and deallocation functions of <stdlib.h> shall not be used")
RULE_21_4 = MisraRule("21.4", MisraCategory.REQUIRED, "The standard header file <setjmp.h> shall not be used")
RULE_21_5 = MisraRule("21.5", MisraCategory.REQUIRED, "The standard header file <signal.h> shall not be used")
RULE_21_6 = MisraRule("21.6", MisraCategory.REQUIRED, "The Standard Library input/output routines shall not be used")
RULE_21_7 = MisraRule("21.7", MisraCategory.REQUIRED, "The Standard Library functions atof, atoi, atol and atoll of <stdlib.h> shall not be used")
RULE_21_8 = MisraRule("21.8", MisraCategory.REQUIRED, "The library functions abort, exit and system of <stdlib.h> shall not be used")
RULE_21_9 = MisraRule("21.9", MisraCategory.REQUIRED, "The library functions bsearch and qsort of <stdlib.h> shall not be used")
RULE_21_10 = MisraRule("21.10", MisraCategory.REQUIRED, "The Standard Library time and date functions shall not be used")
RULE_21_12 = MisraRule("21.12", MisraCategory.ADVISORY, "The exception handling features of <fenv.h> should not be used")
RULE_1_4 = MisraRule(
    "1.4", MisraCategory.REQUIRED,
    "Emergent language features shall not be used",
)


# C11 emergent features (atomics, generic selection, threads, alignment).
_EMERGENT_TYPES = {
    "atomic_bool", "atomic_int", "atomic_uint", "atomic_long", "atomic_ulong",
    "atomic_flag", "thrd_t", "mtx_t", "cnd_t", "tss_t", "once_flag",
    "max_align_t",
}
_EMERGENT_FUNCS = {
    "thrd_create", "thrd_join", "thrd_detach", "thrd_yield", "thrd_sleep",
    "mtx_init", "mtx_lock", "mtx_unlock", "mtx_destroy",
    "cnd_init", "cnd_signal", "cnd_wait", "cnd_destroy",
    "atomic_load", "atomic_store", "atomic_exchange", "atomic_compare_exchange_strong",
    "atomic_fetch_add", "atomic_fetch_sub",
    "_Generic", "_Static_assert", "_Alignas", "_Alignof", "_Noreturn", "_Atomic",
}

_DYNAMIC_MEM = {"malloc", "calloc", "realloc", "free", "aligned_alloc"}
_SETJMP = {"setjmp", "longjmp", "jmp_buf"}
_SIGNAL = {"signal", "raise", "sig_atomic_t"}
_STDIO = {
    "printf", "fprintf", "sprintf", "snprintf", "vprintf", "vfprintf", "vsprintf",
    "scanf", "fscanf", "sscanf", "vscanf", "vfscanf", "vsscanf",
    "fopen", "freopen", "fclose", "fflush", "fread", "fwrite",
    "fgetc", "fputc", "fgets", "fputs", "getc", "putc", "getchar", "putchar",
    "puts", "perror", "remove", "rename", "tmpfile", "tmpnam",
    "fseek", "ftell", "fsetpos", "fgetpos", "rewind", "feof", "ferror", "clearerr",
    "setbuf", "setvbuf", "ungetc",
}
_ATOX = {"atof", "atoi", "atol", "atoll"}
_TERMINATION = {"abort", "exit", "_Exit", "quick_exit", "system", "getenv", "atexit", "at_quick_exit"}
_BSEARCH_QSORT = {"bsearch", "qsort"}
_TIME = {
    "clock", "time", "difftime", "mktime", "asctime", "ctime", "gmtime",
    "localtime", "strftime", "timespec_get", "clock_t", "time_t", "tm",
}
_FENV = {"feclearexcept", "fegetexceptflag", "feraiseexcept", "fesetexceptflag", "fetestexcept"}

_RESERVED_PREFIXES = ("__", "_")  # _ + uppercase or _ at file scope
_RESERVED_NAMES = {"errno"}


class MisraStandardLibChecker(BaseChecker):
    checker_id = "misra-stdlib"
    description = "MISRA C:2012 Rules 21.x: forbidden Standard Library usage and reserved identifiers"
    default_severity = Severity.WARNING
    misra_rules = [
        RULE_1_4, RULE_21_1, RULE_21_2, RULE_21_3, RULE_21_4, RULE_21_5,
        RULE_21_6, RULE_21_7, RULE_21_8, RULE_21_9, RULE_21_10, RULE_21_12,
    ]

    def visit_FuncCall(self, node: c_ast.FuncCall) -> None:
        if isinstance(node.name, c_ast.ID):
            self._check_call(node, node.name.name)
        self.generic_visit(node)

    def visit_Decl(self, node: c_ast.Decl) -> None:
        if node.name and self._is_reserved(node.name):
            self.report(
                node,
                f"Declaration of reserved identifier '{node.name}'",
                Severity.WARNING,
                RULE_21_2,
            )
        type_node = node.type
        if isinstance(type_node, c_ast.TypeDecl) and isinstance(type_node.type, c_ast.IdentifierType):
            for typ in type_node.type.names:
                if typ in _SETJMP - {"setjmp", "longjmp"}:
                    self.report(node, f"Use of <setjmp.h> type '{typ}'", Severity.WARNING, RULE_21_4)
                if typ in _SIGNAL - {"signal", "raise"}:
                    self.report(node, f"Use of <signal.h> type '{typ}'", Severity.WARNING, RULE_21_5)
                if typ in _TIME and typ.endswith(("_t",)) or typ == "tm":
                    self.report(node, f"Use of <time.h> type '{typ}'", Severity.WARNING, RULE_21_10)
                if typ in _EMERGENT_TYPES:
                    self.report(node, f"Use of emergent language type '{typ}'", Severity.WARNING, RULE_1_4)
        self.generic_visit(node)

    def _check_call(self, node: c_ast.FuncCall, name: str) -> None:
        if name in _DYNAMIC_MEM:
            self.report(node, f"Use of dynamic memory function '{name}'", Severity.WARNING, RULE_21_3)
        if name in _SETJMP:
            self.report(node, f"Use of <setjmp.h> facility '{name}'", Severity.WARNING, RULE_21_4)
        if name in _SIGNAL:
            self.report(node, f"Use of <signal.h> facility '{name}'", Severity.WARNING, RULE_21_5)
        if name in _STDIO:
            self.report(node, f"Use of Standard Library I/O function '{name}'", Severity.WARNING, RULE_21_6)
        if name in _ATOX:
            self.report(node, f"Use of '{name}' is forbidden (no error reporting)", Severity.WARNING, RULE_21_7)
        if name in _TERMINATION:
            self.report(node, f"Use of program termination / environment function '{name}'", Severity.WARNING, RULE_21_8)
        if name in _BSEARCH_QSORT:
            self.report(node, f"Use of '{name}' is forbidden", Severity.WARNING, RULE_21_9)
        if name in _TIME and name not in {"clock_t", "time_t", "tm"}:
            self.report(node, f"Use of <time.h> function '{name}'", Severity.WARNING, RULE_21_10)
        if name in _FENV:
            self.report(node, f"Use of <fenv.h> exception facility '{name}'", Severity.INFO, RULE_21_12)
        if name in _EMERGENT_FUNCS:
            self.report(node, f"Use of emergent language feature '{name}'", Severity.WARNING, RULE_1_4)

    def _is_reserved(self, name: str) -> bool:
        if name in _RESERVED_NAMES:
            return True
        if name.startswith("__"):
            return True
        if name.startswith("_") and len(name) >= 2 and name[1].isupper():
            return True
        return False


CheckerRegistry.register(MisraStandardLibChecker)

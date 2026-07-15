"""Regression tests for two false-positive fixes:

* misra-pointer-conv (Section 11): Rule 11.6 (and the 11.4/11.5 integer
  <-> pointer family) must EXEMPT the null pointer constant.
* misra-pointer (Section 18): the pointer-arithmetic / relational rules must
  not fire on pure integer variables (U32, ...), only on real pointers.

Each corresponds to a verified code-review finding on a real firmware scan.
"""

from __future__ import annotations

from corvia.checkers.misra_pointer import MisraPointerChecker
from corvia.checkers.misra_pointer_conv import MisraPointerConvChecker


def _check(checker_cls, parse_c, code):
    ast, _ = parse_c(code)
    checker = checker_cls()
    checker.set_file("<test>")
    return checker.check(ast)


def _rules(issues):
    return {i.misra_rule.rule_id for i in issues if i.misra_rule}


# --------------------------------------------------------------------------
# FIX 1: Rule 11.6 exempts the null pointer constant.
# --------------------------------------------------------------------------

def test_11_6_cast_null_to_arithmetic_not_reported(parse_c):
    # (U32)NULL / (U64)NULL / (uintptr_t)NULL are conversions of the null
    # pointer constant and are exempt under MISRA 11.6.
    code = (
        "typedef unsigned int U32;\n"
        "typedef unsigned long U64;\n"
        "typedef unsigned long uintptr_t;\n"
        "void f(void) {\n"
        "    U32 a = (U32)NULL;\n"
        "    U64 b = (U64)NULL;\n"
        "    uintptr_t c = (uintptr_t)NULL;\n"
        "    (void)a; (void)b; (void)c;\n"
        "}\n"
    )
    issues = _check(MisraPointerConvChecker, parse_c, code)
    assert "11.6" not in _rules(issues), [i.message for i in issues]
    assert "11.4" not in _rules(issues), [i.message for i in issues]


def test_11_6_cast_zero_to_void_pointer_not_reported(parse_c):
    # (void *)0 is the classic NULL expansion: a null pointer constant.
    code = "void f(void) { void *p = (void *)0; (void)p; }"
    issues = _check(MisraPointerConvChecker, parse_c, code)
    assert "11.6" not in _rules(issues), [i.message for i in issues]
    assert "11.4" not in _rules(issues), [i.message for i in issues]
    assert "11.5" not in _rules(issues), [i.message for i in issues]


def test_11_6_cast_null_to_object_pointer_not_reported(parse_c):
    # (T *)NULL / (T *)0 assigning a null pointer constant to an object
    # pointer is exempt (must not fire 11.4/11.5/11.6).
    code = (
        "struct T { int x; };\n"
        "void f(void) {\n"
        "    struct T *p = (struct T *)NULL;\n"
        "    struct T *q = (struct T *)0;\n"
        "    (void)p; (void)q;\n"
        "}\n"
    )
    issues = _check(MisraPointerConvChecker, parse_c, code)
    assert "11.6" not in _rules(issues), [i.message for i in issues]
    assert "11.4" not in _rules(issues), [i.message for i in issues]
    assert "11.5" not in _rules(issues), [i.message for i in issues]


def test_11_genuine_pointer_integer_cast_still_reported(parse_c):
    # (U32)ptr and (void*)int_var are real non-null pointer<->integer
    # conversions and must STILL be reported.
    code = (
        "typedef unsigned int U32;\n"
        "void f(U32 tar_addr) {\n"
        "    int obj;\n"
        "    int *ptr = &obj;\n"
        "    U32 a = (U32)ptr;\n"        # object pointer -> integer: 11.4
        "    void *p = (void *)tar_addr;\n"  # integer -> void*: 11.6
        "    (void)a; (void)p;\n"
        "}\n"
    )
    issues = _check(MisraPointerConvChecker, parse_c, code)
    rules = _rules(issues)
    assert "11.4" in rules, [i.message for i in issues]
    assert "11.6" in rules, [i.message for i in issues]


# --------------------------------------------------------------------------
# FIX 2: Rule 18.x must not fire on pure integer arithmetic.
# --------------------------------------------------------------------------

def test_18_int_compound_assign_not_pointer(parse_c):
    # U32 s; s += 4U; is integer arithmetic, not pointer arithmetic.
    code = (
        "typedef unsigned int U32;\n"
        "void f(void) { U32 s = 0U; s += 4U; (void)s; }\n"
    )
    issues = _check(MisraPointerChecker, parse_c, code)
    assert "18.4" not in _rules(issues), [i.message for i in issues]


def test_18_int_relational_not_pointer(parse_c):
    # U32 i, m; if (i < m) is an integer comparison, not a pointer one.
    code = (
        "typedef unsigned int U32;\n"
        "void f(void) { U32 i = 0U; U32 m = 3U; if (i < m) { (void)i; } }\n"
    )
    issues = _check(MisraPointerChecker, parse_c, code)
    assert "18.3" not in _rules(issues), [i.message for i in issues]


def test_18_local_int_shadows_global_pointer(parse_c):
    # A file-scope pointer `s` must not taint a local `U32 s` that shadows it.
    code = (
        "typedef unsigned int U32;\n"
        "char *s;\n"
        "void f(void) { U32 s = 0U; s += 4U; (void)s; }\n"
    )
    issues = _check(MisraPointerChecker, parse_c, code)
    assert "18.4" not in _rules(issues), [i.message for i in issues]


def test_18_pointer_arith_still_reported(parse_c):
    # char *v; v = v + 12U; is genuine pointer arithmetic (18.4).
    code = "void f(void) { char buf[16]; char *v = buf; v = v + 12U; (void)v; }"
    issues = _check(MisraPointerChecker, parse_c, code)
    assert "18.4" in _rules(issues), [i.message for i in issues]


def test_18_pointer_compound_assign_still_reported(parse_c):
    # char *v; v += 12U; is genuine pointer arithmetic (18.4).
    code = "void f(void) { char buf[16]; char *v = buf; v += 12U; (void)v; }"
    issues = _check(MisraPointerChecker, parse_c, code)
    assert "18.4" in _rules(issues), [i.message for i in issues]

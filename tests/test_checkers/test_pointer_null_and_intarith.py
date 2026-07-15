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


# ---------------------------------------------------------------------------
# Round 2: FPs exposed by the v0.5.3 rescan of secure_boot
# ---------------------------------------------------------------------------


def _run_checker(checker_id: str, tmp_path, code: str):
    from corvia.engine import AnalysisEngine

    src = tmp_path / "case.c"
    src.write_text(code)
    return AnalysisEngine(checker_ids=[checker_id]).analyze([str(src)]).issues


def test_param_shadows_global_array_no_bounds_check(tmp_path):
    """cpp-inlined headers can declare a global `r[2]`; a parameter named r
    inside a function must shadow it (poly_compress FP)."""
    issues = _run_checker("buffer-overflow", tmp_path, """
        typedef unsigned char U8;
        U8 r[2];
        void poly_compress(U8 *r, const U8 *t)
        {
            r[0] = t[0];
            r[4] = t[6];
        }
    """)
    assert not [i for i in issues if "out of bounds" in i.message]


def test_local_pointer_shadows_global_array(tmp_path):
    issues = _run_checker("buffer-overflow", tmp_path, """
        typedef unsigned char U8;
        U8 r[2];
        U8 *get_buf(void);
        void f(void)
        {
            U8 *r = get_buf();
            r[5] = 1U;
        }
    """)
    assert not [i for i in issues if "out of bounds" in i.message]


def test_global_array_oob_still_reported_without_shadow(tmp_path):
    issues = _run_checker("buffer-overflow", tmp_path, """
        typedef unsigned char U8;
        U8 g_buf[2];
        void f(void)
        {
            g_buf[2] = 1U;
        }
    """)
    assert [i for i in issues if "out of bounds" in i.message]


def test_else_if_chain_all_paths_return_no_17_4(tmp_path):
    """if / else if / else where every branch returns (dal_flow_i2c FP)."""
    issues = _run_checker("misra-func", tmp_path, """
        typedef unsigned short U16;
        typedef unsigned char U8;
        U16 get_ht(U8 pd)
        {
            if (pd == 0U)
            {
                return 1U;
            }
            else if (pd == 1U)
            {
                return 2U;
            }
            else
            {
                return 0U;
            }
        }
    """)
    assert not [i for i in issues if i.misra_rule and i.misra_rule.rule_id == "17.4"]


def test_else_if_chain_missing_else_still_17_4(tmp_path):
    issues = _run_checker("misra-func", tmp_path, """
        typedef unsigned short U16;
        typedef unsigned char U8;
        U16 get_ht(U8 pd)
        {
            if (pd == 0U)
            {
                return 1U;
            }
            else if (pd == 1U)
            {
                return 2U;
            }
        }
    """)
    assert [i for i in issues if i.misra_rule and i.misra_rule.rule_id == "17.4"]


def test_stub_symbols_not_attributed_to_user_file(tmp_path):
    """Type-stub scaffolding (NULL_SIM, TRUE_SIM enums, L4KTableBitMap union)
    must not produce issues attributed to the user's file — previously they
    landed on lines beyond end-of-file in short files."""
    from corvia.engine import AnalysisEngine

    src = tmp_path / "tiny.c"
    src.write_text("int conf_get(void)\n{\n    return 1;\n}\n")
    n_lines = 4

    result = AnalysisEngine(
        checker_ids=["misra-decl", "misra-identifiers", "misra-unions"]
    ).analyze([str(src)])
    offenders = [i for i in result.issues if i.line > n_lines]
    assert not offenders, [(i.checker_id, i.line, i.message[:50]) for i in offenders]


def test_macro_expansion_121_artifacts_dropped():
    from corvia.engine import AnalysisEngine
    from corvia.models import Issue, MisraCategory, MisraRule, Severity

    rule = MisraRule("12.1", MisraCategory.ADVISORY, "precedence")
    artifact = Issue(
        checker_id="misra-expr", severity=Severity.INFO,
        message="Operator precedence may be unclear: '>>' within '+'",
        file="a.c", line=39, context="w_spi_CMD_OD_2(0x0DU);", misra_rule=rule,
    )
    genuine = Issue(
        checker_id="misra-expr", severity=Severity.INFO,
        message="Operator precedence may be unclear: '>>' within '+'",
        file="a.c", line=40, context="x = a >> 2 + b;", misra_rule=rule,
    )
    no_ctx = Issue(
        checker_id="misra-expr", severity=Severity.INFO,
        message="Operator precedence may be unclear: '>>' within '+'",
        file="a.c", line=41, context=None, misra_rule=rule,
    )
    kept = AnalysisEngine._drop_macro_expansion_artifacts([artifact, genuine, no_ctx])
    assert genuine in kept and no_ctx in kept and artifact not in kept


# ---------------------------------------------------------------------------
# Round 3: early-exit NULL guard idiom (TF-A bl1_fwu.c pattern)
# ---------------------------------------------------------------------------

_MAYBE_NULL_HELPER = """
    typedef struct desc { int state; } desc_t;
    desc_t *get_desc(int id)
    {
        static desc_t d;
        if (id < 0) {
            return (desc_t *)0;
        }
        return &d;
    }
"""


def test_early_exit_null_guard_suppresses_deref(tmp_path):
    issues = _run_checker("null-deref", tmp_path, _MAYBE_NULL_HELPER + """
    int use(int id)
    {
        desc_t *d = get_desc(id);
        if (d == (desc_t *)0) {
            return -1;
        }
        d->state = 1;
        return 0;
    }
    """)
    assert not [i for i in issues if "Dereference" in i.message]


def test_early_exit_or_guard_narrows_all_disjuncts(tmp_path):
    issues = _run_checker("null-deref", tmp_path, _MAYBE_NULL_HELPER + """
    int use2(int id)
    {
        desc_t *a = get_desc(id);
        desc_t *b = get_desc(id + 1);
        if ((a == (desc_t *)0) || (b == (desc_t *)0)) {
            return -1;
        }
        a->state = 1;
        b->state = 2;
        return 0;
    }
    """)
    assert not [i for i in issues if "Dereference" in i.message]


def test_non_terminating_null_guard_still_reports(tmp_path):
    issues = _run_checker("null-deref", tmp_path, _MAYBE_NULL_HELPER + """
    void log_msg(void);
    int use3(int id)
    {
        desc_t *d = get_desc(id);
        if (d == (desc_t *)0) {
            log_msg();
        }
        d->state = 1;
        return 0;
    }
    """)
    assert [i for i in issues if "Dereference of NULL pointer 'd'" in i.message]


def test_deref_inside_null_branch_still_reports(tmp_path):
    issues = _run_checker("null-deref", tmp_path, _MAYBE_NULL_HELPER + """
    int use4(int id)
    {
        desc_t *d = get_desc(id);
        if (d == (desc_t *)0) {
            d->state = 9;
            return -1;
        }
        return 0;
    }
    """)
    assert [i for i in issues if "Dereference of NULL pointer 'd'" in i.message]

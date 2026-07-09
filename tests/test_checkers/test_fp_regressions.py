"""Regression tests for false-positive fixes across the checkers.

Each test corresponds to a verified code-review finding: either a false
positive that must no longer be reported, or a true positive that must
still fire after the fix.
"""

from __future__ import annotations

from corvia.checkers.dead_code import DeadCodeChecker
from corvia.checkers.memory_leak import MemoryLeakChecker
from corvia.checkers.misra_bitfields import MisraBitFieldsChecker
from corvia.checkers.misra_control import MisraControlChecker
from corvia.checkers.misra_expr import MisraExprChecker
from corvia.checkers.misra_func import MisraFuncChecker
from corvia.checkers.misra_init import MisraInitChecker
from corvia.checkers.misra_literals import MisraLiteralsChecker
from corvia.checkers.misra_pointer import MisraPointerChecker
from corvia.checkers.misra_switch import MisraSwitchChecker
from corvia.checkers.misra_types import MisraTypesChecker
from corvia.checkers.null_deref import NullDerefChecker
from corvia.checkers.resource_leak import ResourceLeakChecker
from corvia.checkers.uninit_vars import UninitVarsChecker
from corvia.checkers.unused_vars import UnusedVarsChecker


def _check(checker_cls, parse_c, code):
    ast, _ = parse_c(code)
    checker = checker_cls()
    checker.set_file("<test>")
    return checker.check(ast)


def _rules(issues):
    return {i.misra_rule.rule_id for i in issues if i.misra_rule}


# --------------------------------------------------------------------------
# B1: for-loop init assignment must not count the lvalue as a read.
# --------------------------------------------------------------------------

def test_b1_for_init_assignment_not_a_read(parse_c):
    code = """
    int f(void) {
        int i;
        int t = 0;
        for (i = 0; i < 3; i++) { t += 1; }
        return t;
    }
    """
    issues = _check(UninitVarsChecker, parse_c, code)
    assert not any("'i'" in i.message for i in issues), [i.message for i in issues]


# --------------------------------------------------------------------------
# B2: struct-member / array-element assignment initializes the base (CFG pass).
# --------------------------------------------------------------------------

def test_b2_structref_assignment_initializes_base(parse_c):
    code = """
    struct s { int a; };
    int f(void) {
        struct s v;
        v.a = 1;
        return v.a;
    }
    """
    issues = _check(UninitVarsChecker, parse_c, code)
    assert not any("'v'" in i.message for i in issues), [i.message for i in issues]


def test_b2_arrayref_assignment_initializes_base(parse_c):
    code = """
    int f(void) {
        int arr[2];
        arr[0] = 1;
        return arr[0];
    }
    """
    issues = _check(UninitVarsChecker, parse_c, code)
    assert not any("'arr'" in i.message for i in issues), [i.message for i in issues]


# --------------------------------------------------------------------------
# B3: `== NULL` guard with early return must not poison the fall-through path.
# --------------------------------------------------------------------------

def test_b3_null_check_early_return_no_fp(parse_c):
    code = """
    int f(int *p) {
        if (p == 0) { return -1; }
        *p = 5;
        return 0;
    }
    """
    issues = _check(NullDerefChecker, parse_c, code)
    assert issues == [], [i.message for i in issues]


def test_b3_definite_null_deref_still_fires(parse_c):
    code = """
    int f(void) {
        int *p = 0;
        *p = 5;
        return 0;
    }
    """
    issues = _check(NullDerefChecker, parse_c, code)
    assert any("NULL pointer 'p'" in i.message for i in issues)


# --------------------------------------------------------------------------
# B4: freeing an untracked pointer (parameter) is NOT a Rule 22.2 violation;
#     freeing provably non-heap storage is.
# --------------------------------------------------------------------------

def test_b4_free_parameter_not_reported(parse_c):
    code = "void destroy(int *o) { free(o); }"
    issues = _check(MemoryLeakChecker, parse_c, code)
    assert "22.2" not in _rules(issues), [i.message for i in issues]


def test_b4_free_local_array_reported(parse_c):
    code = "void f(void) { int buf[4]; free(buf); }"
    issues = _check(MemoryLeakChecker, parse_c, code)
    assert "22.2" in _rules(issues)


def test_b4_free_address_of_local_reported(parse_c):
    code = "void f(void) { int x; int *p = &x; free(p); }"
    issues = _check(MemoryLeakChecker, parse_c, code)
    assert "22.2" in _rules(issues)


# --------------------------------------------------------------------------
# B5: escapes (return, store, unknown call) and the alloc-null-guard idiom
#     must not be reported as leaks.
# --------------------------------------------------------------------------

def test_b5_return_malloc_escape_no_leak(parse_c):
    code = """
    void *make(unsigned int n) {
        void *p = malloc(n);
        return p;
    }
    """
    issues = _check(MemoryLeakChecker, parse_c, code)
    assert not any("leak" in i.message.lower() for i in issues), [i.message for i in issues]


def test_b5_null_guard_return_idiom_no_leak(parse_c):
    code = """
    int g(void) {
        char *p = malloc(4);
        if (!p) { return -1; }
        free(p);
        return 0;
    }
    """
    issues = _check(MemoryLeakChecker, parse_c, code)
    assert not any("leak" in i.message.lower() for i in issues), [i.message for i in issues]


def test_b5_store_into_struct_escapes(parse_c):
    code = """
    struct holder { char *buf; };
    void fill(struct holder *h) {
        char *p = malloc(4);
        h->buf = p;
    }
    """
    issues = _check(MemoryLeakChecker, parse_c, code)
    assert not any("leak" in i.message.lower() for i in issues), [i.message for i in issues]


def test_b5_plain_leak_still_detected(parse_c):
    code = "void f(void) { char *p = malloc(4); (void)p; }"
    issues = _check(MemoryLeakChecker, parse_c, code)
    assert any("leak" in i.message.lower() for i in issues)


def test_b5_fopen_returned_no_leak(parse_c):
    code = """
    void *open_log(void) {
        void *f = fopen("log.txt", "w");
        return f;
    }
    """
    issues = _check(ResourceLeakChecker, parse_c, code)
    assert not any("leak" in i.message.lower() for i in issues), [i.message for i in issues]


def test_b5_fopen_leak_still_detected(parse_c):
    code = """
    void touch(void) {
        void *f = fopen("log.txt", "w");
        (void)f;
    }
    """
    issues = _check(ResourceLeakChecker, parse_c, code)
    assert any("leak" in i.message.lower() for i in issues)


# --------------------------------------------------------------------------
# B6: only the final member of a struct is a flexible array member.
# --------------------------------------------------------------------------

def test_b6_unsized_initialized_array_not_flexible(parse_c):
    code = 'void f(void) { char msg[] = "hi"; (void)msg[0]; }'
    issues = _check(MisraPointerChecker, parse_c, code)
    assert "18.7" not in _rules(issues), [i.message for i in issues]


def test_b6_array_parameter_not_flexible(parse_c):
    code = "int g(int a[]) { return a[0]; }"
    issues = _check(MisraPointerChecker, parse_c, code)
    assert "18.7" not in _rules(issues), [i.message for i in issues]


def test_b6_real_flexible_member_flagged(parse_c):
    code = "struct s { int n; int data[]; };"
    issues = _check(MisraPointerChecker, parse_c, code)
    assert "18.7" in _rules(issues)


# --------------------------------------------------------------------------
# W5: a label resets reachability (goto/label cleanup idiom).
# --------------------------------------------------------------------------

def test_w5_label_after_goto_not_unreachable(parse_c):
    code = """
    int f(int x) {
        if (x) { goto out; }
        return 0;
    out:
        return 1;
    }
    """
    issues = _check(DeadCodeChecker, parse_c, code)
    assert not any("Unreachable" in i.message for i in issues), [i.message for i in issues]


def test_w5_unreachable_still_detected(parse_c):
    code = "int f(int x) { return x; x = x + 1; return x; }"
    issues = _check(DeadCodeChecker, parse_c, code)
    assert any("Unreachable" in i.message for i in issues)


# --------------------------------------------------------------------------
# W6: no-op detection must use the correct operator sets.
# --------------------------------------------------------------------------

def test_w6_mul_zero_not_a_noop(parse_c):
    code = "int f(int x) { x *= 0; return x; }"
    issues = _check(DeadCodeChecker, parse_c, code)
    assert not any("no-op" in i.message for i in issues), [i.message for i in issues]


def test_w6_div_zero_reported_as_ub(parse_c):
    code = "int f(int x) { x /= 0; return x; }"
    issues = _check(DeadCodeChecker, parse_c, code)
    assert any("Division by zero" in i.message for i in issues)
    assert not any("no-op" in i.message for i in issues)


def test_w6_add_zero_is_noop(parse_c):
    code = "int f(int x) { x += 0; return x; }"
    issues = _check(DeadCodeChecker, parse_c, code)
    assert any("no-op" in i.message for i in issues)


def test_w6_and_all_ones_is_noop(parse_c):
    code = "int f(int x) { x &= ~0; return x; }"
    issues = _check(DeadCodeChecker, parse_c, code)
    assert any("no-op" in i.message for i in issues)


def test_w6_or_all_ones_not_a_noop(parse_c):
    code = "int f(int x) { x |= ~0; return x; }"
    issues = _check(DeadCodeChecker, parse_c, code)
    assert not any("no-op" in i.message for i in issues), [i.message for i in issues]


# --------------------------------------------------------------------------
# W8: Rule 12.1 bitwise/arithmetic precedence logic.
# --------------------------------------------------------------------------

def test_w8_arith_under_bitwise_flagged(parse_c):
    # `a & b + c` parses as `a & (b + c)` without any parentheses - unclear.
    code = "int f(int a, int b, int c) { return a & b + c; }"
    issues = _check(MisraExprChecker, parse_c, code)
    assert "12.1" in _rules(issues)


def test_w8_parenthesized_bitwise_under_arith_not_flagged(parse_c):
    # `a + (b & c)` can only be written WITH parentheses - already clear.
    code = "int f(int a, int b, int c) { return a + (b & c); }"
    issues = _check(MisraExprChecker, parse_c, code)
    assert "12.1" not in _rules(issues), [i.message for i in issues]


# --------------------------------------------------------------------------
# W10: Rule 10.1 must actually fire for bitwise ops on character operands.
# --------------------------------------------------------------------------

def test_w10_char_bitwise_operand_fires(parse_c):
    code = "int f(void) { return 'a' & 3; }"
    issues = _check(MisraTypesChecker, parse_c, code)
    assert "10.1" in _rules(issues)


# --------------------------------------------------------------------------
# W12: multi-label switch clauses satisfy Rule 16.3.
# --------------------------------------------------------------------------

def test_w12_multi_label_clause_with_break_ok(parse_c):
    code = """
    int f(int x) {
        int y = 0;
        switch (x) {
            case 1:
            case 2:
                y = 1;
                break;
            default:
                y = 0;
                break;
        }
        return y;
    }
    """
    issues = _check(MisraSwitchChecker, parse_c, code)
    assert "16.3" not in _rules(issues), [i.message for i in issues]


def test_w12_missing_break_still_detected(parse_c):
    code = """
    int f(int x) {
        int y = 0;
        switch (x) {
            case 1:
                y = 1;
            case 2:
                y = 2;
                break;
            default:
                break;
        }
        return y;
    }
    """
    issues = _check(MisraSwitchChecker, parse_c, code)
    assert "16.3" in _rules(issues)


# --------------------------------------------------------------------------
# W16: `= {0}` is the MISRA-sanctioned all-zero array initializer.
# --------------------------------------------------------------------------

def test_w16_zero_initializer_permitted(parse_c):
    code = "void f(void) { int a[4] = {0}; a[0] = 1; }"
    issues = _check(MisraInitChecker, parse_c, code)
    assert "9.3" not in _rules(issues), [i.message for i in issues]


def test_w16_partial_init_still_flagged(parse_c):
    code = "void f(void) { int a[4] = {1, 2}; a[0] = 1; }"
    issues = _check(MisraInitChecker, parse_c, code)
    assert "9.3" in _rules(issues)


# --------------------------------------------------------------------------
# W19: typedef'd bit-field types resolve to their underlying type.
# --------------------------------------------------------------------------

def test_w19_typedefed_bitfield_not_flagged(parse_c):
    code = """
    typedef unsigned int my_u32;
    struct reg { my_u32 mode : 4; my_u32 flag : 1; };
    """
    issues = _check(MisraBitFieldsChecker, parse_c, code)
    assert "6.1" not in _rules(issues), [i.message for i in issues]


def test_w19_bad_bitfield_type_still_flagged(parse_c):
    code = """
    typedef float badf;
    struct reg { badf mode : 4; };
    """
    issues = _check(MisraBitFieldsChecker, parse_c, code)
    assert "6.1" in _rules(issues)


# --------------------------------------------------------------------------
# Additional coverage for other fixed findings.
# --------------------------------------------------------------------------

def test_w2_dowhile_body_scanned_before_cond(parse_c):
    code = """
    int f(void) {
        int x;
        do { x = 1; } while (x < 3);
        return x;
    }
    """
    issues = _check(UninitVarsChecker, parse_c, code)
    assert issues == [], [i.message for i in issues]


def test_w3_typedef_struct_tracked_per_field(parse_c):
    code = """
    typedef struct { int a; int b; } S;
    int f(void) {
        S s;
        s.a = 1;
        s.b = 2;
        return s.a;
    }
    """
    issues = _check(UninitVarsChecker, parse_c, code)
    assert issues == [], [i.message for i in issues]


def test_w1_single_branch_init_does_not_leak_out(parse_c):
    code = """
    int f(int c) {
        int x;
        if (c) { x = 1; }
        return x;
    }
    """
    issues = _check(UninitVarsChecker, parse_c, code)
    assert any("'x'" in i.message for i in issues)


def test_w1_both_branches_init_is_clean(parse_c):
    code = """
    int f(int c) {
        int x;
        if (c) { x = 1; } else { x = 2; }
        return x;
    }
    """
    issues = _check(UninitVarsChecker, parse_c, code)
    assert issues == [], [i.message for i in issues]


def test_w7_array_dimension_counts_as_use(parse_c):
    code = "void f(void) { int n = 4; int buf[n]; buf[0] = 1; }"
    issues = _check(UnusedVarsChecker, parse_c, code)
    assert not any("Unused variable 'n'" in i.message for i in issues), \
        [i.message for i in issues]


def test_w17_struct_copy_init_not_flagged(parse_c):
    code = """
    struct S { int a; };
    void f(struct S t) { struct S s = t; s.a = 1; }
    """
    issues = _check(MisraInitChecker, parse_c, code)
    assert "9.2" not in _rules(issues), [i.message for i in issues]


def test_w18_char_array_string_init_not_flagged(parse_c):
    code = 'void f(void) { char buf[16] = "hello"; buf[0] = 0; }'
    issues = _check(MisraLiteralsChecker, parse_c, code)
    assert "7.4" not in _rules(issues), [i.message for i in issues]


def test_w20_enum_constant_array_dim_not_vla(parse_c):
    code = """
    enum { SIZE = 8 };
    void f(void) { int arr[SIZE]; arr[0] = 1; }
    """
    issues = _check(MisraPointerChecker, parse_c, code)
    assert "18.8" not in _rules(issues), [i.message for i in issues]


def test_w20_real_vla_still_flagged(parse_c):
    code = "void f(int n) { int arr[n]; arr[0] = 1; }"
    issues = _check(MisraPointerChecker, parse_c, code)
    assert "18.8" in _rules(issues)


def test_w21_else_if_chain_reported_once(parse_c):
    code = """
    void f(int x) {
        int y = 0;
        if (x == 1) { y = 1; }
        else if (x == 2) { y = 2; }
        else if (x == 3) { y = 3; }
    }
    """
    issues = _check(MisraControlChecker, parse_c, code)
    chain_issues = [i for i in issues if i.misra_rule and i.misra_rule.rule_id == "15.7"]
    assert len(chain_issues) == 1, [i.message for i in issues]


def test_w9_wide_shift_on_64bit_constant_not_flagged(parse_c):
    code = "unsigned long long f(void) { return 1ULL << 40; }"
    issues = _check(MisraExprChecker, parse_c, code)
    assert "12.2" not in _rules(issues), [i.message for i in issues]


def test_w9_wide_shift_on_int_still_flagged(parse_c):
    code = "int f(void) { return 1 << 40; }"
    issues = _check(MisraExprChecker, parse_c, code)
    assert "12.2" in _rules(issues)


def test_m1_va_list_decl_detected(parse_c):
    code = "void f(int n) { va_list ap; (void)n; }"
    issues = _check(MisraFuncChecker, parse_c, code)
    assert "17.1" in _rules(issues)


def test_w15_switch_all_returns_with_default(parse_c):
    code = """
    int f(int x) {
        switch (x) {
            case 1: return 1;
            case 2: return 2;
            default: return 0;
        }
    }
    """
    issues = _check(MisraFuncChecker, parse_c, code)
    assert "17.4" not in _rules(issues), [i.message for i in issues]


def test_w15_while_1_loop_never_falls_through(parse_c):
    code = """
    int f(void) {
        while (1) {
            int x = 1;
            if (x) { return x; }
        }
    }
    """
    issues = _check(MisraFuncChecker, parse_c, code)
    assert "17.4" not in _rules(issues), [i.message for i in issues]


def test_m9_double_fclose_reported(parse_c):
    code = """
    void f(void) {
        void *h = fopen("a", "r");
        fclose(h);
        fclose(h);
    }
    """
    issues = _check(ResourceLeakChecker, parse_c, code)
    assert any("closed twice" in i.message for i in issues)


def test_m9_reopen_clears_closed_state(parse_c):
    code = """
    void f(void) {
        void *h = fopen("a", "r");
        fclose(h);
        h = fopen("a", "r");
        fclose(h);
    }
    """
    issues = _check(ResourceLeakChecker, parse_c, code)
    assert not any("after it has been closed" in i.message for i in issues), \
        [i.message for i in issues]
    assert not any("closed twice" in i.message for i in issues), \
        [i.message for i in issues]


def test_m7_compound_assignment_reads_lvalue(parse_c):
    code = "int f(void) { int x; x += 1; return x; }"
    issues = _check(UninitVarsChecker, parse_c, code)
    assert any("'x'" in i.message for i in issues)

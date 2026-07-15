"""Tests for the uninitialized variables checker."""

from corvia.checkers.uninit_vars import UninitVarsChecker
from corvia.parser import _strip_gcc_calls


def _uninit_messages(checker, ast):
    return [
        i.message for i in checker.check(ast)
        if i.message and (
            "before initialization" in i.message.lower()
            or "uninitialized on some" in i.message.lower()
            or "does not initialize" in i.message.lower()
        )
    ]


def test_basic_uninit(parse_c):
    code = "int f(void) { int x; return x; }"
    ast, _ = parse_c(code)
    checker = UninitVarsChecker()
    checker.set_file("<test>")
    issues = checker.check(ast)
    assert any("may be used before initialization" in i.message for i in issues)
    assert any(i.misra_rule and i.misra_rule.rule_id == "9.1" for i in issues)


def test_initialized_var(parse_c):
    code = "int f(void) { int x = 10; return x; }"
    ast, _ = parse_c(code)
    checker = UninitVarsChecker()
    checker.set_file("<test>")
    issues = checker.check(ast)
    assert len(issues) == 0


def test_assigned_before_use(parse_c):
    code = "int f(void) { int x; x = 10; return x; }"
    ast, _ = parse_c(code)
    checker = UninitVarsChecker()
    checker.set_file("<test>")
    issues = checker.check(ast)
    assert len(issues) == 0


def test_partial_struct(parse_c):
    code = """
    struct s { int x; int y; int z; };
    int f(void) {
        struct s p;
        p.x = 1;
        return p.z;
    }
    """
    ast, _ = parse_c(code)
    checker = UninitVarsChecker()
    checker.set_file("<test>")
    issues = checker.check(ast)
    assert any("p.z" in i.message and "not be initialized" in i.message for i in issues)


def test_addr_of_out_param_not_reported(parse_c):
    """Passing &var to an (unknown/external) function is the idiomatic
    out-parameter pattern: the callee is assumed to initialize the object.
    Reporting it as uninitialized is a false positive (see timer_start(&timer)
    style code), so no 9.1 issue should be raised for `val` here."""
    code = """
    struct s { int x; int y; };
    void init(struct s *p);
    void f(void) {
        struct s val;
        val.x = 1;
        init(&val);
    }
    """
    ast, _ = parse_c(code)
    checker = UninitVarsChecker()
    checker.set_file("<test>")
    issues = checker.check(ast)
    assert not any(
        i.message and (
            "passed by reference" in i.message.lower()
            or "before initialization" in i.message.lower()
            or "uninitialized on some" in i.message.lower()
        )
        for i in issues
    )


def test_addr_of_local_then_use_not_reported(parse_c):
    """A plain local passed by address, then read, must not be flagged: the
    call is presumed to initialize it."""
    code = """
    void fill(int *p);
    int f(void) {
        int x;
        fill(&x);
        return x;
    }
    """
    ast, _ = parse_c(code)
    checker = UninitVarsChecker()
    checker.set_file("<test>")
    issues = checker.check(ast)
    assert not any(
        i.message and (
            "before initialization" in i.message.lower()
            or "uninitialized on some" in i.message.lower()
        )
        for i in issues
    )


def test_array_passed_by_name_to_memset_not_reported(parse_c):
    """An array decays to a writable pointer when passed by bare name, so
    `memset(buf, 0, sizeof(buf))` INITIALIZES buf - it must not be reported as
    a use-before-init. Regression: the checker previously treated the bare
    array name as a read (false positive across every crypto buffer that is
    zeroed via a project memset wrapper)."""
    code = """
    void hal_sec_memset(void *dest, int val, unsigned long n);
    void f(void) {
        unsigned char buf[16];
        hal_sec_memset((void *)buf, 0, sizeof(buf));
    }
    """
    ast, _ = parse_c(code)
    checker = UninitVarsChecker()
    checker.set_file("<test>")
    assert _uninit_messages(checker, ast) == []


def test_array_as_memcpy_dest_then_read_not_reported(parse_c):
    """`memcpy(v, src, 16)` fills v; a later read of v is safe. Both the bare
    name and the cast form must be recognized as an out-parameter write."""
    code = """
    void hal_sec_memcpy(void *dest, void *src, unsigned long n);
    void g(unsigned char *src) {
        unsigned char v[16];
        hal_sec_memcpy((void *)v, (void *)src, 16);
        hal_sec_memcpy((void *)src, (void *)v, 16);
    }
    """
    ast, _ = parse_c(code)
    checker = UninitVarsChecker()
    checker.set_file("<test>")
    assert _uninit_messages(checker, ast) == []


def test_pointer_var_passed_by_name_not_reported(parse_c):
    """A pointer variable passed by bare name gives the callee a writable
    address (out-parameter idiom), so it must not be flagged."""
    code = """
    void fill(int *p, int n);
    int h(void) {
        int *p;
        fill(p, 4);
        return *p;
    }
    """
    ast, _ = parse_c(code)
    checker = UninitVarsChecker()
    checker.set_file("<test>")
    assert _uninit_messages(checker, ast) == []


def test_scalar_passed_by_value_still_reported(parse_c):
    """A scalar passed BY VALUE is a genuine read: passing an uninitialized
    scalar must still be reported (the array/pointer relaxation must not leak
    to value arguments)."""
    code = """
    void use(int x);
    void f(void) {
        int id;
        use(id);
    }
    """
    ast, _ = parse_c(code)
    checker = UninitVarsChecker()
    checker.set_file("<test>")
    assert _uninit_messages(checker, ast) != []


def test_asm_output_operand_initializes_var(parse_c):
    """A GCC extended-asm output operand (`: "=r" (id)`) writes through the
    variable. The parser strips asm statements, so it must synthesize the
    output write; otherwise a var only written by asm looks uninitialized.
    Regression for dal_gic_get_iar0-style MRS reads."""
    code = (
        'unsigned int dal_gic_get_iar0(void) {'
        ' unsigned int id;'
        ' __asm volatile ("mrs %0, ICC_IAR0_EL1\\n" : "=r" (id));'
        ' return id; }'
    )
    stripped = _strip_gcc_calls(code)
    assert "= 0;" in stripped  # output write was synthesized
    ast, _ = parse_c(stripped)
    checker = UninitVarsChecker()
    checker.set_file("<test>")
    assert _uninit_messages(checker, ast) == []


def test_array_with_macro_size_still_addressable(parse_c):
    """An array whose dimension does not fold to a simple integer constant
    (e.g. `buf[SOME_MACRO]` expanding to a constant expression) is still an
    array and still addressable. Regression: keying array-ness off a
    constant-foldable size left such buffers non-addressable, re-introducing
    the memcpy/memset out-parameter false positive (hal_sec_rsassa_pss_verify's
    salt_buffer/seed_buf)."""
    code = """
    void hal_sec_memcpy(void *d, void *s, unsigned long n);
    void verify(unsigned char *src, unsigned long n) {
        unsigned char salt_buffer[8 + 64];
        (void)hal_sec_memcpy((void *)(salt_buffer), (void *)(src), n);
        (void)hal_sec_memcpy((void *)(src), (void *)(salt_buffer), n);
    }
    """
    ast, _ = parse_c(code)
    checker = UninitVarsChecker()
    checker.set_file("<test>")
    assert _uninit_messages(checker, ast) == []


def test_void_cast_call_out_param_not_reported(parse_c):
    """`(void)memset(buf, ...)` — a call wrapped in a cast-to-void statement —
    must still route through the out-parameter logic; the cast must not make
    the bare array look like a read."""
    code = """
    void hal_sec_memset(void *d, int v, unsigned long n);
    void f(void) {
        unsigned char buf[16];
        (void)hal_sec_memset((void *)buf, 0, sizeof(buf));
    }
    """
    ast, _ = parse_c(code)
    checker = UninitVarsChecker()
    checker.set_file("<test>")
    assert _uninit_messages(checker, ast) == []


def test_sizeof_before_out_param_not_reported(parse_c):
    """`sizeof(rng)` never reads the buffer's value (unevaluated operand), so
    `get_rand(sizeof(rng), rng)` must not flag rng even though the sizeof
    argument is checked BEFORE the output argument marks it initialized.
    Regression for hal_sec_verify_signature_compare's rng buffer."""
    code = """
    typedef unsigned char U8;
    typedef unsigned int U32;
    void hal_sec_get_true_rand(U32 len, U8 *out);
    void f(void) {
        U8 rng[6];
        hal_sec_get_true_rand((U32)sizeof(rng), (U8 *)rng);
    }
    """
    ast, _ = parse_c(code)
    checker = UninitVarsChecker()
    checker.set_file("<test>")
    assert _uninit_messages(checker, ast) == []


def test_partial_init_list_zero_fills_rest(parse_c):
    """C11 6.7.9p21: elements not covered by an initializer list are zero-
    initialized, so `char buf[11] = {0};` (or `{1, 2}`) is FULLY initialized.
    Reading it back - even with a variable index - must not be reported.
    Regression for sal_log_printer's print32d buffer."""
    code = """
    void put(char c);
    void f(unsigned int i) {
        char buf[11] = {0};
        int partial[8] = {1, 2};
        put(buf[i]);
        put((char)partial[i]);
    }
    """
    ast, _ = parse_c(code)
    checker = UninitVarsChecker()
    checker.set_file("<test>")
    issues = checker.check(ast)
    assert not any("partially initialized" in i.message for i in issues)
    assert _uninit_messages(checker, ast) == []


def test_va_start_builtin_initializes_va_list(parse_c):
    """va_start expands to __builtin_va_start(args, fmt), which WRITES args.
    The builtin stripper must synthesize that write instead of dropping it to
    a bare '0', or every correct varargs function looks uninitialized.
    Regression for sal_raw_printf."""
    code = (
        'typedef int va_list;'
        'void sal_raw_vprintf(char *fmt, va_list ap);'
        'void sal_raw_printf(char *fmt) {'
        ' va_list args;'
        ' __builtin_va_start(args, fmt);'
        ' sal_raw_vprintf(fmt, args);'
        ' __builtin_va_end(args); }'
    )
    stripped = _strip_gcc_calls(code)
    assert '((args) = 0)' in stripped
    ast, _ = parse_c(stripped)
    checker = UninitVarsChecker()
    checker.set_file("<test>")
    assert _uninit_messages(checker, ast) == []


def test_va_list_without_va_start_still_reported(parse_c):
    """A va_list read without va_start is a genuine uninitialized use and must
    still be reported (the va_start recovery must not blanket-initialize)."""
    code = (
        'typedef int va_list;'
        'void sal_raw_vprintf(char *fmt, va_list ap);'
        'void broken(char *fmt) {'
        ' va_list args;'
        ' sal_raw_vprintf(fmt, args); }'
    )
    stripped = _strip_gcc_calls(code)
    ast, _ = parse_c(stripped)
    checker = UninitVarsChecker()
    checker.set_file("<test>")
    assert _uninit_messages(checker, ast) != []


def test_loop_indexed_init_then_element_read_not_reported(parse_c):
    """The loop-init idiom `for (k = 0; k < 8; k++) t[k] = ...;` fully writes
    the array before it is read. The element tracker only records CONSTANT
    subscripts, so a variable-indexed loop write would otherwise leave `t`
    looking (partially) uninitialized and a later `t[3]` read would false-
    positive. Regression for hal_sec_pqc_mlkem_api.c's t[] buffers.

    Both passes must be clean: the linear pass emits the element-level
    "may not be initialized", and the CFG pass emits "uninitialized on some
    execution paths" on the zero-trip path."""
    code = """
    void use(unsigned char a);
    void f(void) {
        unsigned char t[8];
        unsigned int k;
        for (k = 0; k < 8; k++) {
            t[k] = (unsigned char)k;
        }
        use(t[3]);
    }
    """
    ast, _ = parse_c(code)
    checker = UninitVarsChecker()
    checker.set_file("<test>")
    issues = checker.check(ast)
    assert not any("may not be initialized" in i.message for i in issues)
    assert _uninit_messages(checker, ast) == []


def test_loop_indexed_init_while_and_do_while_not_reported(parse_c):
    """The loop-init relaxation applies to while and do-while loops too, not
    just for-loops."""
    code = """
    void use(unsigned char a);
    void wl(void) {
        unsigned char t[8];
        unsigned int k = 0;
        while (k < 8) { t[k] = (unsigned char)k; k++; }
        use(t[3]);
    }
    void dw(void) {
        unsigned char u[8];
        unsigned int j = 0;
        do { u[j] = (unsigned char)j; j++; } while (j < 8);
        use(u[3]);
    }
    """
    ast, _ = parse_c(code)
    checker = UninitVarsChecker()
    checker.set_file("<test>")
    assert _uninit_messages(checker, ast) == []
    issues = checker.check(ast)
    assert not any("may not be initialized" in i.message for i in issues)


def test_genuinely_uninit_array_without_loop_still_reported(parse_c):
    """The loop-init relaxation must not blanket-suppress: an array declared
    and read by constant index with NO write on any path is still a genuine
    uninitialized read."""
    code = """
    void use(unsigned char a);
    void f(void) {
        unsigned char t[8];
        use(t[3]);
    }
    """
    ast, _ = parse_c(code)
    checker = UninitVarsChecker()
    checker.set_file("<test>")
    issues = checker.check(ast)
    assert any("may not be initialized" in i.message for i in issues)


def test_scalar_beside_loop_filled_array_still_reported(parse_c):
    """A loop that fills `t` must not launder an unrelated scalar `y` that is
    genuinely uninitialized - the relaxation is per-array."""
    code = """
    void use(unsigned char a, int b);
    void f(void) {
        unsigned char t[8];
        int y;
        unsigned int k;
        for (k = 0; k < 8; k++) { t[k] = (unsigned char)k; }
        use(t[3], y);
    }
    """
    ast, _ = parse_c(code)
    checker = UninitVarsChecker()
    checker.set_file("<test>")
    assert _uninit_messages(checker, ast) != []


def test_struct_member_through_pointer_not_treated_as_local(parse_c):
    """`p->cq_len` reads the FIELD of the object `p`; the field identifier
    `cq_len` is not a local variable. The write `p->cq_len = 1` then the read
    `p->cq_len` must not be reported. Regression for hal_ufs.c's
    ->ctrl_info.cq_len flagged as a use-before-init of a local named cq_len."""
    code = """
    typedef int S;
    void use(int a);
    void f(S *p) {
        p->cq_len = 1;
        use(p->cq_len);
    }
    """
    ast, _ = parse_c(code)
    checker = UninitVarsChecker()
    checker.set_file("<test>")
    assert _uninit_messages(checker, ast) == []


def test_struct_member_by_value_field_read_not_reported(parse_c):
    """`s.a = 1; use(s.a);` initializes and reads field `a`; the field name
    must never be treated as a separate local variable."""
    code = """
    typedef struct { int a; int b; } S;
    void use(int a);
    void g(void) {
        S s;
        s.a = 1;
        use(s.a);
    }
    """
    ast, _ = parse_c(code)
    checker = UninitVarsChecker()
    checker.set_file("<test>")
    assert _uninit_messages(checker, ast) == []


def test_nested_struct_member_field_named_like_local_not_reported(parse_c):
    """A local `int cq_len;` that shares its name with a nested struct field
    accessed as `p->ctrl_info.cq_len` must not be flagged: the member access
    reads the struct field, never the same-named local. Regression for the CFG
    pass's generic recursion into StructRef.field. The genuine local read (if
    any) is unaffected - here cq_len is never actually read as a local."""
    code = """
    typedef int S;
    void use(int a);
    void f(S *p) {
        int cq_len;
        p->ctrl_info.cq_len = 1;
        use(p->ctrl_info.cq_len);
    }
    """
    ast, _ = parse_c(code)
    checker = UninitVarsChecker()
    checker.set_file("<test>")
    assert not any(
        i.message and "cq_len" in i.message
        and ("before initialization" in i.message.lower()
             or "uninitialized on some" in i.message.lower())
        for i in checker.check(ast)
    )


def test_uninit_pointer_base_of_member_still_reported(parse_c):
    """The StructRef relaxation only spares the FIELD name - a genuinely
    uninitialized pointer BASE (`S *p; use(p->x);`) must still be reported."""
    code = """
    typedef struct { int cq_len; } Ct;
    typedef struct { Ct ctrl_info; } S;
    void use(int a);
    void f(void) {
        S *p;
        use(p->ctrl_info.cq_len);
    }
    """
    ast, _ = parse_c(code)
    checker = UninitVarsChecker()
    checker.set_file("<test>")
    assert any(
        i.message and "'p'" in i.message
        and "uninitialized on some" in i.message.lower()
        for i in checker.check(ast)
    )


def test_asm_input_only_does_not_hide_genuine_uninit(parse_c):
    """An input-only asm (`:: "r" (...)`) does NOT write the variable, so a
    genuine uninitialized read after it must still be reported - the asm
    recovery must not blanket-initialize."""
    code = (
        'unsigned int bad(void) {'
        ' unsigned int id;'
        ' __asm volatile ("msr X, %0\\n" :: "r" ((unsigned long)1));'
        ' return id; }'
    )
    stripped = _strip_gcc_calls(code)
    assert "= 0;" not in stripped  # no output operand -> no synthesized write
    ast, _ = parse_c(stripped)
    checker = UninitVarsChecker()
    checker.set_file("<test>")
    assert _uninit_messages(checker, ast) != []

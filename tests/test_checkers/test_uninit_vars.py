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

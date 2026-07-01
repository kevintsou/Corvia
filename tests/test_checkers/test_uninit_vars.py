"""Tests for the uninitialized variables checker."""

from corvia.checkers.uninit_vars import UninitVarsChecker


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

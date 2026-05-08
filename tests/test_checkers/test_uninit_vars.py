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


def test_cross_func_partial(parse_c):
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
    assert any("passed by reference" in i.message.lower() or "partially initialized" in i.message.lower() for i in issues)

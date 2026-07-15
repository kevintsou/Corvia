"""Tests for the buffer overflow checker."""

from corvia.checkers.buffer_overflow import BufferOverflowChecker


def test_oob_access(parse_c):
    code = "void f(void) { int arr[10]; arr[10] = 1; }"
    ast, _ = parse_c(code)
    checker = BufferOverflowChecker()
    checker.set_file("<test>")
    issues = checker.check(ast)
    assert any("out of bounds" in i.message.lower() for i in issues)


def test_large_oob(parse_c):
    code = "int f(void) { int arr[5]; return arr[100]; }"
    ast, _ = parse_c(code)
    checker = BufferOverflowChecker()
    checker.set_file("<test>")
    issues = checker.check(ast)
    assert any("100" in i.message and "out of bounds" in i.message.lower() for i in issues)


def test_safe_access(parse_c):
    code = "int f(void) { int arr[10]; arr[0] = 1; arr[9] = 2; return arr[0]; }"
    ast, _ = parse_c(code)
    checker = BufferOverflowChecker()
    checker.set_file("<test>")
    issues = checker.check(ast)
    assert len(issues) == 0


def test_negative_index(parse_c):
    code = "int f(void) { int arr[5]; return arr[-1]; }"
    ast, _ = parse_c(code)
    checker = BufferOverflowChecker()
    checker.set_file("<test>")
    issues = checker.check(ast)
    assert any("Negative index" in i.message or "out of bounds" in i.message.lower() for i in issues)


def test_pointer_param_not_bounds_checked(parse_c):
    # A pointer parameter is an index into a caller-provided buffer and has no
    # statically known size, even when the pointer is advanced (`r += 5U`).
    code = (
        "typedef unsigned char U8;"
        "void f(U8 *r){ r[0]=1; r[5]=2; r+=5U; r[0]=3; }"
    )
    ast, _ = parse_c(code)
    checker = BufferOverflowChecker()
    checker.set_file("<test>")
    issues = checker.check(ast)
    assert len(issues) == 0


def test_array_param_no_dim_not_bounds_checked(parse_c):
    # `U8 r[]` decays to a pointer - no size to bound against.
    code = "typedef unsigned char U8; void h(U8 r[]){ r[3]=1; r[99]=2; }"
    ast, _ = parse_c(code)
    checker = BufferOverflowChecker()
    checker.set_file("<test>")
    issues = checker.check(ast)
    assert len(issues) == 0


def test_array_param_with_dim_not_bounds_checked(parse_c):
    # `U8 r[2]` also decays to a pointer; the dimension does not constrain the
    # accessible range, so `r[5]` must NOT be reported (this was the phantom
    # "array of size 2" false positive).
    code = "typedef unsigned char U8; void k(U8 r[2]){ r[5]=1; }"
    ast, _ = parse_c(code)
    checker = BufferOverflowChecker()
    checker.set_file("<test>")
    issues = checker.check(ast)
    assert len(issues) == 0


def test_local_array_still_checked_after_param_fix(parse_c):
    # A genuine local array with a constant dimension is still bounds-checked.
    code = "void g(void) { unsigned char buf[2]; buf[2] = 1; }"
    ast, _ = parse_c(code)
    checker = BufferOverflowChecker()
    checker.set_file("<test>")
    issues = checker.check(ast)
    assert any("out of bounds" in i.message.lower() for i in issues)

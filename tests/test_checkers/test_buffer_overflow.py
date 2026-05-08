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

"""Tests for CFG-based null dereference checker."""

import pytest
from corvia.parser import CParser
from corvia.checkers.null_deref import NullDerefChecker


@pytest.fixture
def parse_c():
    parser = CParser()
    def _parse(code):
        ast, _ = parser.parse_string(code)
        return ast
    return _parse


def test_basic_null_deref(parse_c):
    code = '''
    void f(void) {
        int *p = (void *)0;
        int x = *p;
    }
    '''
    ast = parse_c(code)
    checker = NullDerefChecker()
    checker.set_file("test.c")
    checker.check(ast)
    assert len(checker._issues) >= 1
    assert any("p" in i.message for i in checker._issues)


def test_null_arrow_deref(parse_c):
    code = '''
    struct node { int val; };
    void f(void) {
        struct node *n = (void *)0;
        int v = n->val;
    }
    '''
    ast = parse_c(code)
    checker = NullDerefChecker()
    checker.set_file("test.c")
    checker.check(ast)
    assert len(checker._issues) >= 1
    assert any("n" in i.message and "->" in i.message for i in checker._issues)


def test_safe_after_reassign(parse_c):
    code = '''
    void f(void) {
        int val = 10;
        int *p = (void *)0;
        p = &val;
        int x = *p;
    }
    '''
    ast = parse_c(code)
    checker = NullDerefChecker()
    checker.set_file("test.c")
    checker.check(ast)
    deref_issues = [i for i in checker._issues if "p" in i.message and "NULL" in i.message]
    assert len(deref_issues) == 0


def test_null_array_subscript(parse_c):
    code = '''
    void f(void) {
        int *arr = (void *)0;
        int x = arr[0];
    }
    '''
    ast = parse_c(code)
    checker = NullDerefChecker()
    checker.set_file("test.c")
    checker.check(ast)
    assert len(checker._issues) >= 1
    assert any("arr" in i.message for i in checker._issues)

"""Tests for the memory leak checker."""

import pytest
from corvia.parser import CParser
from corvia.checkers.memory_leak import MemoryLeakChecker


@pytest.fixture
def parse_c():
    parser = CParser()
    def _parse(code):
        ast, _ = parser.parse_string(code)
        return ast
    return _parse


def test_basic_leak(parse_c):
    code = '''
    typedef unsigned long size_t;
    void *malloc(size_t size);
    void free(void *ptr);
    void f(void) {
        int *p = (int *)malloc(10);
        p[0] = 1;
    }
    '''
    ast = parse_c(code)
    checker = MemoryLeakChecker()
    checker.set_file("test.c")
    checker.check(ast)
    assert len(checker._issues) >= 1
    assert any("p" in i.message and "leak" in i.message.lower() for i in checker._issues)


def test_no_leak(parse_c):
    code = '''
    typedef unsigned long size_t;
    void *malloc(size_t size);
    void free(void *ptr);
    void f(void) {
        int *p = (int *)malloc(10);
        p[0] = 1;
        free(p);
    }
    '''
    ast = parse_c(code)
    checker = MemoryLeakChecker()
    checker.set_file("test.c")
    checker.check(ast)
    leak_issues = [i for i in checker._issues if "leak" in i.message.lower()]
    assert len(leak_issues) == 0


def test_conditional_leak(parse_c):
    code = '''
    typedef unsigned long size_t;
    void *malloc(size_t size);
    void free(void *ptr);
    void f(int flag) {
        int *p = (int *)malloc(10);
        if (flag) {
            free(p);
        }
    }
    '''
    ast = parse_c(code)
    checker = MemoryLeakChecker()
    checker.set_file("test.c")
    checker.check(ast)
    assert len(checker._issues) >= 1
    assert any("p" in i.message for i in checker._issues)


def test_multiple_allocs(parse_c):
    code = '''
    typedef unsigned long size_t;
    void *malloc(size_t size);
    void free(void *ptr);
    void f(void) {
        int *a = (int *)malloc(10);
        int *b = (int *)malloc(20);
        free(a);
    }
    '''
    ast = parse_c(code)
    checker = MemoryLeakChecker()
    checker.set_file("test.c")
    checker.check(ast)
    leak_issues = [i for i in checker._issues if "leak" in i.message.lower()]
    assert any("b" in i.message for i in leak_issues)

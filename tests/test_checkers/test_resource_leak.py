"""Tests for the resource leak checker."""

import pytest
from covia.parser import CParser
from covia.checkers.resource_leak import ResourceLeakChecker


@pytest.fixture
def parse_c():
    parser = CParser()
    def _parse(code):
        ast, _ = parser.parse_string(code)
        return ast
    return _parse


def test_file_leak(parse_c):
    code = '''
    typedef void FILE;
    FILE *fopen(const char *path, const char *mode);
    int fclose(FILE *fp);
    int fprintf(FILE *fp, const char *fmt);
    void f(void) {
        FILE *fp = fopen("test.txt", "r");
        fprintf(fp, "hello");
    }
    '''
    ast = parse_c(code)
    checker = ResourceLeakChecker()
    checker.set_file("test.c")
    checker.check(ast)
    leak_issues = [i for i in checker._issues if "leak" in i.message.lower()]
    assert len(leak_issues) >= 1
    assert any("fp" in i.message for i in leak_issues)


def test_no_file_leak(parse_c):
    code = '''
    typedef void FILE;
    FILE *fopen(const char *path, const char *mode);
    int fclose(FILE *fp);
    int fprintf(FILE *fp, const char *fmt);
    void f(void) {
        FILE *fp = fopen("test.txt", "r");
        fprintf(fp, "hello");
        fclose(fp);
    }
    '''
    ast = parse_c(code)
    checker = ResourceLeakChecker()
    checker.set_file("test.c")
    checker.check(ast)
    leak_issues = [i for i in checker._issues if "leak" in i.message.lower()]
    assert len(leak_issues) == 0


def test_use_after_close(parse_c):
    code = '''
    typedef void FILE;
    FILE *fopen(const char *path, const char *mode);
    int fclose(FILE *fp);
    int fprintf(FILE *fp, const char *fmt);
    void f(void) {
        FILE *fp = fopen("test.txt", "w");
        fclose(fp);
        fprintf(fp, "bad");
    }
    '''
    ast = parse_c(code)
    checker = ResourceLeakChecker()
    checker.set_file("test.c")
    checker.check(ast)
    uac_issues = [i for i in checker._issues if "after" in i.message.lower() and "closed" in i.message.lower()]
    assert len(uac_issues) >= 1


def test_conditional_file_leak(parse_c):
    code = '''
    typedef void FILE;
    FILE *fopen(const char *path, const char *mode);
    int fclose(FILE *fp);
    void f(int flag) {
        FILE *fp = fopen("data.csv", "r");
        if (flag) {
            fclose(fp);
        }
    }
    '''
    ast = parse_c(code)
    checker = ResourceLeakChecker()
    checker.set_file("test.c")
    checker.check(ast)
    leak_issues = [i for i in checker._issues if "leak" in i.message.lower()]
    assert len(leak_issues) >= 1

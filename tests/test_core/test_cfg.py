"""Tests for CFG builder."""

import pytest
from pycparser import c_ast
from corvia.parser import CParser
from corvia.core.cfg import build_cfg


@pytest.fixture
def parse_c():
    parser = CParser()
    def _parse(code):
        ast, _ = parser.parse_string(code)
        return ast
    return _parse


def _get_func(ast, name="f"):
    for ext in ast.ext:
        if isinstance(ext, c_ast.FuncDef) and ext.decl.name == name:
            return ext
    return None


def test_linear_cfg(parse_c):
    code = '''
    void f(void) {
        int x = 1;
        int y = 2;
        int z = x + y;
    }
    '''
    ast = parse_c(code)
    func = _get_func(ast)
    cfg = build_cfg(func)
    assert cfg.entry is not None
    assert cfg.exit is not None
    assert len(cfg.blocks) >= 2


def test_if_cfg(parse_c):
    code = '''
    void f(int x) {
        int y;
        if (x > 0) {
            y = 1;
        } else {
            y = 2;
        }
    }
    '''
    ast = parse_c(code)
    func = _get_func(ast)
    cfg = build_cfg(func)
    assert cfg.entry is not None
    assert cfg.exit is not None
    assert len(cfg.blocks) >= 4


def test_while_cfg(parse_c):
    code = '''
    void f(void) {
        int i = 0;
        while (i < 10) {
            i = i + 1;
        }
    }
    '''
    ast = parse_c(code)
    func = _get_func(ast)
    cfg = build_cfg(func)
    assert cfg.entry is not None
    reachable = cfg.reachable_blocks()
    assert len(reachable) >= 3


def test_return_cfg(parse_c):
    code = '''
    int f(int x) {
        if (x > 0) {
            return 1;
        }
        return 0;
    }
    '''
    ast = parse_c(code)
    func = _get_func(ast)
    cfg = build_cfg(func)
    assert cfg.exit is not None
    assert len(cfg.exit.predecessors) >= 1

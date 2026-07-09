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


def _blocks_with(cfg, predicate):
    return [b for b in cfg.blocks if any(predicate(s) for s in b.statements)]


def _reaches(src, dst):
    seen = set()
    worklist = [src]
    while worklist:
        b = worklist.pop()
        if b in seen:
            continue
        seen.add(b)
        if b is dst:
            return True
        worklist.extend(b.successors)
    return False


def test_switch_post_switch_code_reachable_from_all_cases(parse_c):
    """Regression: with pycparser ASTs, `break` lives inside Case.stmts.
    The return block after the switch must be reachable from both the
    breaking case and the default case."""
    code = '''
    int f(int x) {
        int r;
        switch (x) {
        case 1:
            r = 1;
            break;
        default:
            r = 0;
        }
        return r;
    }
    '''
    ast = parse_c(code)
    func = _get_func(ast)
    cfg = build_cfg(func)

    return_blocks = _blocks_with(cfg, lambda s: isinstance(s, c_ast.Return))
    assert len(return_blocks) == 1
    ret = return_blocks[0]

    assign_blocks = _blocks_with(cfg, lambda s: isinstance(s, c_ast.Assignment))
    assert len(assign_blocks) == 2  # r = 1 and r = 0 in separate case blocks
    for case_block in assign_blocks:
        assert _reaches(case_block, ret)
    # And the whole function terminates.
    assert _reaches(cfg.entry, cfg.exit)


def test_switch_without_default_has_bypass_edge(parse_c):
    """A switch with no default may match no case at all: the post-switch
    code must be reachable without entering any case block."""
    code = '''
    int f(int x) {
        int r = 0;
        switch (x) {
        case 1:
            r = 1;
            break;
        }
        return r;
    }
    '''
    ast = parse_c(code)
    func = _get_func(ast)
    cfg = build_cfg(func)

    head_blocks = _blocks_with(cfg, lambda s: isinstance(s, c_ast.ID) and s.name == "x")
    assert len(head_blocks) == 1
    head = head_blocks[0]
    # The switch head branches to the case block AND to the after-block.
    assert len(head.successors) >= 2

    return_blocks = _blocks_with(cfg, lambda s: isinstance(s, c_ast.Return))
    assert len(return_blocks) == 1
    # There is a head successor that reaches the return without being a case
    # block (the "no case matches" bypass edge).
    case_blocks = _blocks_with(cfg, lambda s: isinstance(s, c_ast.Assignment))
    bypass = [s for s in head.successors if s not in case_blocks]
    assert any(_reaches(b, return_blocks[0]) for b in bypass)


def test_break_in_switch_inside_loop_exits_switch_not_loop(parse_c):
    """Regression: a break inside a switch nested in a while must connect to
    the switch's after-block (where the loop body continues), not to the
    loop's exit."""
    code = '''
    void f(int x) {
        while (x) {
            switch (x) {
            case 1:
                break;
            }
            x = x - 1;
        }
    }
    '''
    ast = parse_c(code)
    func = _get_func(ast)
    cfg = build_cfg(func)

    break_blocks = _blocks_with(cfg, lambda s: isinstance(s, c_ast.Break))
    assert len(break_blocks) == 1
    bb = break_blocks[0]
    # The break's successor is the switch after-block, which carries the
    # decrement statement that continues the loop body.
    assert any(
        any(isinstance(s, c_ast.Assignment) for s in succ.statements)
        for succ in bb.successors
    )
    # It must NOT jump straight out of the loop.
    assert all(not succ.is_exit for succ in bb.successors)


def test_label_with_structured_statement_gets_cfg(parse_c):
    """Regression: a structured statement after a label must be processed
    recursively, producing separate branch blocks."""
    code = '''
    void f(int x) {
    L:
        if (x) {
            x = 1;
        } else {
            x = 2;
        }
        if (x == 9) {
            goto L;
        }
    }
    '''
    ast = parse_c(code)
    func = _get_func(ast)
    cfg = build_cfg(func)

    assign_blocks = _blocks_with(cfg, lambda s: isinstance(s, c_ast.Assignment))
    assert len(assign_blocks) == 2  # both branches got their own blocks
    for b in assign_blocks:
        assert _reaches(cfg.entry, b)

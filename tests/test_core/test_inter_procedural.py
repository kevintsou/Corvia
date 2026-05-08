"""End-to-end inter-procedural tests via the engine.

These verify that summaries correctly flow into checkers (null-deref,
memory-leak, resource-leak, misra-func) so wrappers are recognized.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from covia.engine import AnalysisEngine


def _write(tmp_path: Path, name: str, content: str) -> str:
    p = tmp_path / name
    p.write_text(content)
    return str(p)


def test_wrapper_malloc_triggers_memory_leak(tmp_path):
    f = _write(
        tmp_path,
        "wrap.c",
        """
        void *malloc(unsigned long);
        void free(void *p);
        void *xalloc(unsigned long n) { return malloc(n); }
        void leaks(void) {
            char *p = xalloc(16);
        }
        """,
    )
    engine = AnalysisEngine()
    result = engine.analyze([f])
    leaks = [i for i in result.issues if i.checker_id == "memory-leak"]
    assert any("leak" in i.message.lower() and "p" in i.message for i in leaks)


def test_wrapper_fopen_triggers_resource_leak(tmp_path):
    f = _write(
        tmp_path,
        "rwrap.c",
        """
        typedef struct _IO_FILE FILE;
        FILE *fopen(const char *p, const char *m);
        int fclose(FILE *f);
        FILE *xopen(const char *p) { return fopen(p, "r"); }
        void leaks(const char *path) {
            FILE *f = xopen(path);
        }
        """,
    )
    engine = AnalysisEngine()
    result = engine.analyze([f])
    leaks = [i for i in result.issues if i.checker_id == "resource-leak"]
    assert any("leak" in i.message.lower() for i in leaks)


def test_callee_returning_null_propagates_to_null_deref(tmp_path):
    f = _write(
        tmp_path,
        "nd.c",
        """
        int *get_null(void) { return 0; }
        void boom(void) {
            int *p = get_null();
            *p = 1;
        }
        """,
    )
    engine = AnalysisEngine()
    result = engine.analyze([f])
    nds = [i for i in result.issues if i.checker_id == "null-deref"]
    assert any("NULL" in i.message and "p" in i.message for i in nds)


def test_indirect_recursion_via_call_graph(tmp_path):
    f = _write(
        tmp_path,
        "rec.c",
        """
        int b(int n);
        int a(int n) { return b(n - 1); }
        int b(int n) { return a(n - 1); }
        """,
    )
    engine = AnalysisEngine()
    result = engine.analyze([f])
    recs = [i for i in result.issues if i.checker_id == "misra-func"
            and "recursive" in i.message.lower()]
    names = {i.message for i in recs}
    assert any("'a'" in n for n in names) and any("'b'" in n for n in names)


def test_unused_return_value_17_7(tmp_path):
    f = _write(
        tmp_path,
        "ret.c",
        """
        int compute(int x) { return x + 1; }
        void caller(void) {
            compute(5);
        }
        """,
    )
    engine = AnalysisEngine()
    result = engine.analyze([f])
    ret_issues = [
        i for i in result.issues
        if i.checker_id == "misra-func" and "discarded" in i.message
    ]
    assert any("compute" in i.message for i in ret_issues)

"""Tests for the incremental analysis cache."""

from __future__ import annotations

from pathlib import Path

from corvia.core.cache import CacheManager, FileCache, hash_file
from corvia.engine import AnalysisEngine
from corvia.models import Issue, Severity


def test_hash_file_changes_with_content(tmp_path: Path):
    f = tmp_path / "a.c"
    f.write_text("int x;\n")
    h1 = hash_file(str(f))
    f.write_text("int y;\n")
    h2 = hash_file(str(f))
    assert h1 != h2


def test_save_and_load_roundtrip(tmp_path: Path):
    cache = CacheManager(tmp_path / "cache")
    entry = FileCache(
        path="/abs/foo.c",
        content_hash="deadbeef",
        mtime=123.0,
        issues=[
            Issue(
                checker_id="x",
                severity=Severity.WARNING,
                message="m",
                file="/abs/foo.c",
                line=1,
            )
        ],
        callees=["malloc"],
        defines=["foo"],
    )
    cache.save(entry)

    fresh = CacheManager(tmp_path / "cache")
    loaded = fresh.load("/abs/foo.c")
    assert loaded is not None
    assert loaded.content_hash == "deadbeef"
    assert loaded.callees == ["malloc"]
    assert len(loaded.issues) == 1
    assert loaded.issues[0].checker_id == "x"


def test_engine_writes_cache_on_first_run(tmp_path: Path):
    src = tmp_path / "a.c"
    src.write_text("int *get(void) { return 0; }\n")
    cache_dir = tmp_path / "corvia_cache"

    engine = AnalysisEngine(incremental=True, cache_dir=str(cache_dir))
    engine.analyze([str(src)])

    cache = CacheManager(cache_dir)
    entry = cache.load(str(src))
    assert entry is not None
    assert entry.content_hash == hash_file(str(src))


def test_unchanged_file_reuses_cache(tmp_path: Path):
    src = tmp_path / "a.c"
    src.write_text(
        """
        void *malloc(unsigned long);
        void leak(void) { char *p = malloc(8); }
        """
    )
    cache_dir = tmp_path / "corvia_cache"

    e1 = AnalysisEngine(incremental=True, cache_dir=str(cache_dir))
    r1 = e1.analyze([str(src)])
    assert any(i.checker_id == "memory-leak" for i in r1.issues)

    # Second run: same content -> reuses cache, must still report.
    e2 = AnalysisEngine(incremental=True, cache_dir=str(cache_dir))
    r2 = e2.analyze([str(src)])
    n_leak_1 = sum(1 for i in r1.issues if i.checker_id == "memory-leak")
    n_leak_2 = sum(1 for i in r2.issues if i.checker_id == "memory-leak")
    assert n_leak_1 == n_leak_2


def test_changed_file_invalidates(tmp_path: Path):
    src = tmp_path / "a.c"
    src.write_text("int *f(void) { return 0; }\n")
    cache_dir = tmp_path / "corvia_cache"

    AnalysisEngine(incremental=True, cache_dir=str(cache_dir)).analyze([str(src)])
    h1 = hash_file(str(src))

    # Modify file
    src.write_text("int *f(void) { return 0; } int extra(void) { return 1; }\n")
    h2 = hash_file(str(src))
    assert h1 != h2

    cache = CacheManager(cache_dir)
    changed, reusable = cache.determine_files_to_analyze([str(src)])
    assert str(src) in changed


def test_clean_cache(tmp_path: Path):
    cache_dir = tmp_path / "corvia_cache"
    src = tmp_path / "a.c"
    src.write_text("int x;\n")
    AnalysisEngine(incremental=True, cache_dir=str(cache_dir)).analyze([str(src)])

    cache = CacheManager(cache_dir)
    assert cache.load(str(src)) is not None
    cache.clear()
    fresh = CacheManager(cache_dir)
    assert fresh.load(str(src)) is None

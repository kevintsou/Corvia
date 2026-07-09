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


def test_env_hash_mismatch_invalidates(tmp_path: Path):
    """Regression: cache validity must depend on the analysis environment
    (flags/checkers/version), not only on file content."""
    src = tmp_path / "a.c"
    src.write_text("int x;\n")
    h = hash_file(str(src))

    m1 = CacheManager(tmp_path / "cache", env_hash="env-a")
    m1.save(FileCache(path=str(src), content_hash=h, mtime=0.0))
    assert m1.is_valid(str(src), h)

    m2 = CacheManager(tmp_path / "cache", env_hash="env-b")
    assert not m2.is_valid(str(src), h)

    m3 = CacheManager(tmp_path / "cache", env_hash="env-a")
    assert m3.is_valid(str(src), h)


def test_engine_env_change_invalidates_cache(tmp_path: Path):
    """Changing the selected checkers between runs must not reuse issues
    cached under the previous checker set."""
    src = tmp_path / "a.c"
    src.write_text(
        """
        void *malloc(unsigned long);
        void leak(void) { char *p = malloc(8); }
        """
    )
    cache_dir = tmp_path / "corvia_cache"

    r1 = AnalysisEngine(
        checker_ids=["memory-leak"], incremental=True, cache_dir=str(cache_dir)
    ).analyze([str(src)])
    assert any(i.checker_id == "memory-leak" for i in r1.issues)

    # Same file content, different checker selection: the cached
    # memory-leak issues must not resurface.
    r2 = AnalysisEngine(
        checker_ids=["syntax"], incremental=True, cache_dir=str(cache_dir)
    ).analyze([str(src)])
    assert all(i.checker_id != "memory-leak" for i in r2.issues)


def test_cache_key_normalizes_path_spelling(tmp_path: Path):
    """Regression: the same file reached via different path spellings must
    map to a single cache entry."""
    src = tmp_path / "a.c"
    src.write_text("int x;\n")

    m = CacheManager(tmp_path / "cache")
    m.save(FileCache(path=str(src), content_hash="h", mtime=0.0))

    fresh = CacheManager(tmp_path / "cache")
    alt_spelling = str(tmp_path / "sub" / ".." / "a.c")
    loaded = fresh.load(alt_spelling)
    assert loaded is not None
    assert loaded.content_hash == "h"


def test_incremental_matches_full_run_after_partial_change(tmp_path: Path):
    """Regression: incremental mode must build the AnalysisContext from ALL
    files, so summaries for functions in unchanged files keep flowing into
    checkers and results match a full (non-incremental) run."""
    a = tmp_path / "a.c"
    a.write_text("int *get_null(void) { return 0; }\n")
    b = tmp_path / "b.c"
    b.write_text(
        "int *get_null(void);\n"
        "void use(void) { int *p = get_null(); *p = 1; }\n"
    )
    cache_dir = tmp_path / "corvia_cache"

    r1 = AnalysisEngine(incremental=True, cache_dir=str(cache_dir)).analyze(
        [str(tmp_path)]
    )
    assert any(i.checker_id == "null-deref" for i in r1.issues)

    # Change ONLY b.c: a.c is served from cache, but its summary
    # (get_null returns NULL) must still be available to the checker pass.
    b.write_text(
        "int *get_null(void);\n"
        "void use2(void) { int *q = get_null(); *q = 2; }\n"
    )
    r2 = AnalysisEngine(incremental=True, cache_dir=str(cache_dir)).analyze(
        [str(tmp_path)]
    )
    full = AnalysisEngine().analyze([str(tmp_path)])

    def key(i):
        return (i.checker_id, Path(i.file).name, i.line, i.column, i.message)

    assert sorted(map(key, r2.issues)) == sorted(map(key, full.issues))
    assert any(i.checker_id == "null-deref" for i in r2.issues)


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

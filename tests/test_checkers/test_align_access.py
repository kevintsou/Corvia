"""Tests for the align-access external checker.

align-access ships in ``extensions/checkers`` rather than as a builtin, so the
suite loads it through the same ``--external-checkers`` path users do.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from corvia.engine import AnalysisEngine
from corvia.registry import CheckerRegistry


EXT_DIR = Path(__file__).resolve().parents[2] / "extensions" / "checkers"


@pytest.fixture(autouse=True)
def _isolate_registry():
    """Keep align-access out of the global registry seen by other tests.

    AnalysisEngine(external_checkers_dir=...) registers the checker as a side
    effect, which would otherwise leak into tests that assert the registry
    holds builtins only (tests/test_registry.py).
    """
    yield
    CheckerRegistry.reset()
    CheckerRegistry.load_builtin_checkers()


def _issues(fixtures_dir: Path):
    engine = AnalysisEngine(
        checker_ids=["align-access"],
        external_checkers_dir=str(EXT_DIR),
    )
    result = engine.analyze([str(fixtures_dir / "align_access.c")])
    return [i for i in result.issues if i.checker_id == "align-access"]


def _lines(fixtures_dir: Path) -> set[int]:
    return {i.line for i in _issues(fixtures_dir)}


# ---------- pattern 1: widening casts ----------


def test_u8_array_with_odd_offset_reported(fixtures_dir):
    """`*(U32 *)(buf + 1)` on a U8 array is provably misaligned."""
    assert 19 in _lines(fixtures_dir)


def test_u8_pointer_widened_reported(fixtures_dir):
    assert 25 in _lines(fixtures_dir)


def test_void_pointer_widened_reported(fixtures_dir):
    assert 31 in _lines(fixtures_dir)


def test_u16_to_u64_reported(fixtures_dir):
    """A 2-byte source widened to an 8-byte access."""
    assert 37 in _lines(fixtures_dir)


# ---------- false-positive guards ----------


def test_same_width_cast_not_reported(fixtures_dir):
    """Redundant `(U32 *)` on an existing U32* is harmless.

    Real case: dal_sec_sha_api.c:123 in the secure_boot tree.
    """
    assert 44 not in _lines(fixtures_dir)


def test_natural_u32_array_not_reported(fixtures_dir):
    assert 51 not in _lines(fixtures_dir)


def test_narrowing_cast_not_reported(fixtures_dir):
    assert 57 not in _lines(fixtures_dir)


def test_aligned_register_offsets_not_reported(fixtures_dir):
    """Offsets that are multiples of 4 must stay silent.

    Real cases: host.c:720-724 in the secure_boot tree.
    """
    reported = _lines(fixtures_dir)
    assert not (reported & {65, 66, 67})


# ---------- pattern 3: misaligned constant offsets ----------


def test_misaligned_register_offsets_reported(fixtures_dir):
    assert {73, 75} <= _lines(fixtures_dir)


def test_misaligned_constants_are_errors(fixtures_dir):
    """Constant misalignment is provable, so it is an error, not a warning."""
    from corvia.models import Severity

    by_line = {i.line: i for i in _issues(fixtures_dir)}
    assert by_line[73].severity == Severity.ERROR
    assert by_line[75].severity == Severity.ERROR


def test_widening_casts_are_warnings(fixtures_dir):
    """A widened source pointer is only *possibly* misaligned."""
    from corvia.models import Severity

    by_line = {i.line: i for i in _issues(fixtures_dir)}
    assert by_line[25].severity == Severity.WARNING


def test_misra_rule_attached(fixtures_dir):
    for issue in _issues(fixtures_dir):
        assert issue.misra_rule is not None
        assert issue.misra_rule.rule_id == "1.3"


def test_no_unexpected_findings(fixtures_dir):
    """The fixture's GOOD cases must produce nothing beyond the 8 BAD ones."""
    assert len(_issues(fixtures_dir)) == 8


# ---------- pattern 1b: &element address widened ----------


def test_local_array_runtime_index_reported(fixtures_dir):
    """`*(U32 *)&buf[i]` on a U8 array with a runtime index."""
    assert 89 in _lines(fixtures_dir)


def test_struct_member_runtime_index_reported(fixtures_dir):
    """Real pattern from secure_boot sal_log.c:89.

    `*(U32 *)&log->start[log->offset]` where start is U8* — the dominant
    real-world form, missed by the first version of this checker.
    """
    assert 95 in _lines(fixtures_dir)


def test_u32_element_address_not_reported(fixtures_dir):
    """`&words[i]` on a U32 array is already aligned - no widening."""
    assert 101 not in _lines(fixtures_dir)


# ---------- config-driven loading (Phase C-2) ----------


def test_engine_loads_external_checker_from_config(tmp_path, fixtures_dir):
    """[checkers] external must load the checker without any CLI flag.

    This is what lets the corvia_code_review skill pick up project checkers:
    the skill's command line is fixed and never passes --external-checkers.
    """
    from corvia.core.config import load
    from corvia import __version__

    cfg = tmp_path / "corvia.toml"
    cfg.write_text(
        f"# corvia_config_version: {__version__}\n"
        "[checkers]\n"
        f'external = "{EXT_DIR.as_posix()}"\n',
        encoding="utf-8",
    )
    config = load(cfg)

    engine = AnalysisEngine(checker_ids=["align-access"], config=config)
    result = engine.analyze([str(fixtures_dir / "align_access.c")])
    found = [i for i in result.issues if i.checker_id == "align-access"]
    assert len(found) == 8


def test_cli_flag_overrides_config_dir(tmp_path, fixtures_dir):
    """--external-checkers takes precedence over the configured directory."""
    from corvia.core.config import load
    from corvia import __version__

    empty_dir = tmp_path / "no_checkers"
    empty_dir.mkdir()
    cfg = tmp_path / "corvia.toml"
    cfg.write_text(
        f"# corvia_config_version: {__version__}\n"
        "[checkers]\n"
        f'external = "{empty_dir.as_posix()}"\n',
        encoding="utf-8",
    )
    config = load(cfg)

    # Config points at an empty dir; the CLI flag supplies the real one.
    engine = AnalysisEngine(
        checker_ids=["align-access"],
        external_checkers_dir=str(EXT_DIR),
        config=config,
    )
    result = engine.analyze([str(fixtures_dir / "align_access.c")])
    assert [i for i in result.issues if i.checker_id == "align-access"]

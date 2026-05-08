"""Tests for the misra-identifiers checker (Section 5)."""

from __future__ import annotations

from pathlib import Path

from covia.engine import AnalysisEngine


def _run(target: str):
    return AnalysisEngine(checker_ids=["misra-identifiers"]).analyze([target])


def test_shadowing_param_and_inner_scope(fixtures_dir):
    f = str(fixtures_dir / "misra_identifiers.c")
    result = _run(f)
    msgs = [i.message for i in result.issues]
    assert any("shadows" in m and "outer_var" in m for m in msgs)
    assert any("shadows" in m and "inner_local" in m for m in msgs)


def test_tag_uniqueness_struct_vs_union(fixtures_dir):
    f = str(fixtures_dir / "misra_identifiers.c")
    result = _run(f)
    msgs = [i.message for i in result.issues if i.misra_rule and i.misra_rule.rule_id == "5.7"]
    assert any("mything" in m for m in msgs)


def test_cross_file_external_collision(tmp_path: Path):
    a = tmp_path / "a.c"
    b = tmp_path / "b.c"
    a.write_text("int shared(int x) { return x; }\n")
    b.write_text("int shared(int y) { return y * 2; }\n")
    result = AnalysisEngine(checker_ids=["misra-identifiers"]).analyze([str(a), str(b)])
    rule_5_8 = [i for i in result.issues if i.misra_rule and i.misra_rule.rule_id == "5.8"]
    assert len(rule_5_8) >= 2  # one per file


def test_static_collision_internal_linkage(tmp_path: Path):
    a = tmp_path / "a.c"
    b = tmp_path / "b.c"
    a.write_text("static int helper(void) { return 1; }\n")
    b.write_text("static int helper(void) { return 2; }\n")
    result = AnalysisEngine(checker_ids=["misra-identifiers"]).analyze([str(a), str(b)])
    rule_5_9 = [i for i in result.issues if i.misra_rule and i.misra_rule.rule_id == "5.9"]
    assert rule_5_9

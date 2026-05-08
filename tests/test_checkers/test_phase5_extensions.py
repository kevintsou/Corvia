"""Tests for Phase 5 rule extensions: 1.4, 2.4, 2.6, 9.2, 9.3, 16.2, 22.5."""

from __future__ import annotations

from corvia.engine import AnalysisEngine


def _run(target: str, checkers: list[str]):
    return AnalysisEngine(checker_ids=checkers).analyze([target])


def _rule_ids(result):
    return {i.misra_rule.rule_id for i in result.issues if i.misra_rule}


def test_emergent_features_1_4(fixtures_dir):
    result = _run(str(fixtures_dir / "misra_phase5.c"), ["misra-stdlib"])
    assert "1.4" in _rule_ids(result)
    msgs = [i.message for i in result.issues if i.misra_rule and i.misra_rule.rule_id == "1.4"]
    assert any("thrd_create" in m or "atomic_load" in m or "atomic_int" in m or "thrd_t" in m for m in msgs)


def test_unused_label_2_6(fixtures_dir):
    result = _run(str(fixtures_dir / "misra_phase5.c"), ["unused-var"])
    msgs = [i.message for i in result.issues if i.misra_rule and i.misra_rule.rule_id == "2.6"]
    assert any("unused_one" in m for m in msgs)


def test_used_label_not_flagged_2_6(fixtures_dir):
    result = _run(str(fixtures_dir / "misra_phase5.c"), ["unused-var"])
    msgs = [i.message for i in result.issues if i.misra_rule and i.misra_rule.rule_id == "2.6"]
    assert not any("'done'" in m for m in msgs)


def test_aggregate_initializer_9_2(fixtures_dir):
    result = _run(str(fixtures_dir / "misra_phase5.c"), ["misra-init"])
    msgs = [i.message for i in result.issues if i.misra_rule and i.misra_rule.rule_id == "9.2"]
    assert any("'unbraced_struct'" in m for m in msgs)
    assert not any("'braced_struct'" in m for m in msgs)


def test_array_partial_init_9_3(fixtures_dir):
    result = _run(str(fixtures_dir / "misra_phase5.c"), ["misra-init"])
    msgs = [i.message for i in result.issues if i.misra_rule and i.misra_rule.rule_id == "9.3"]
    assert any("partial" in m for m in msgs)
    assert not any("'full'" in m for m in msgs)


def test_switch_nested_label_16_2(fixtures_dir):
    result = _run(str(fixtures_dir / "misra_phase5.c"), ["misra-switch"])
    assert "16.2" in _rule_ids(result)


def test_file_pointer_dereference_22_5(fixtures_dir):
    result = _run(str(fixtures_dir / "misra_phase5.c"), ["resource-leak"])
    msgs = [i.message for i in result.issues if i.misra_rule and i.misra_rule.rule_id == "22.5"]
    assert any("FILE" in m for m in msgs)

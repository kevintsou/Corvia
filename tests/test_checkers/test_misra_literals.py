"""Tests for the misra-literals checker (Section 7)."""

from __future__ import annotations

from corvia.engine import AnalysisEngine


def _run(target: str):
    return AnalysisEngine(checker_ids=["misra-literals"]).analyze([target])


def test_octal_constant_7_1(fixtures_dir):
    result = _run(str(fixtures_dir / "misra_literals.c"))
    rule_ids = {i.misra_rule.rule_id for i in result.issues if i.misra_rule}
    assert "7.1" in rule_ids


def test_lowercase_l_suffix_7_3(fixtures_dir):
    result = _run(str(fixtures_dir / "misra_literals.c"))
    msgs = [i.message for i in result.issues if i.misra_rule and i.misra_rule.rule_id == "7.3"]
    assert any("100l" in m for m in msgs)


def test_string_to_non_const_char_7_4(fixtures_dir):
    result = _run(str(fixtures_dir / "misra_literals.c"))
    msgs = [i.message for i in result.issues if i.misra_rule and i.misra_rule.rule_id == "7.4"]
    assert any("plain" in m for m in msgs)


def test_const_char_pointer_is_ok(fixtures_dir):
    result = _run(str(fixtures_dir / "misra_literals.c"))
    msgs = [i.message for i in result.issues if i.misra_rule and i.misra_rule.rule_id == "7.4"]
    assert not any("good" in m for m in msgs)

"""Tests for the misra-bitfields checker (Section 6)."""

from __future__ import annotations

from corvia.engine import AnalysisEngine


def _run(target: str):
    return AnalysisEngine(checker_ids=["misra-bitfields"]).analyze([target])


def test_disallowed_bitfield_type_6_1(fixtures_dir):
    result = _run(str(fixtures_dir / "misra_bitfields.c"))
    msgs = [i.message for i in result.issues if i.misra_rule and i.misra_rule.rule_id == "6.1"]
    assert any("small" in m for m in msgs)
    assert any("wide" in m for m in msgs)


def test_signed_single_bit_6_2(fixtures_dir):
    result = _run(str(fixtures_dir / "misra_bitfields.c"))
    msgs = [i.message for i in result.issues if i.misra_rule and i.misra_rule.rule_id == "6.2"]
    assert any("single_signed" in m for m in msgs)


def test_no_false_positive_for_allowed_types(fixtures_dir):
    result = _run(str(fixtures_dir / "misra_bitfields.c"))
    msgs = [i.message for i in result.issues if i.misra_rule and i.misra_rule.rule_id == "6.1"]
    assert not any("'a'" in m or "'b'" in m or "'c'" in m for m in msgs)

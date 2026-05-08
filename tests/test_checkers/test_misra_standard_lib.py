"""Tests for the misra-stdlib checker (Section 21)."""

from __future__ import annotations

from covia.engine import AnalysisEngine


def _run(target: str):
    return AnalysisEngine(checker_ids=["misra-stdlib"]).analyze([target])


def test_dynamic_memory_21_3(fixtures_dir):
    result = _run(str(fixtures_dir / "misra_standard_lib.c"))
    rule_ids = {i.misra_rule.rule_id for i in result.issues if i.misra_rule}
    assert "21.3" in rule_ids


def test_stdio_21_6(fixtures_dir):
    result = _run(str(fixtures_dir / "misra_standard_lib.c"))
    rule_ids = {i.misra_rule.rule_id for i in result.issues if i.misra_rule}
    assert "21.6" in rule_ids


def test_atoi_21_7(fixtures_dir):
    result = _run(str(fixtures_dir / "misra_standard_lib.c"))
    rule_ids = {i.misra_rule.rule_id for i in result.issues if i.misra_rule}
    assert "21.7" in rule_ids


def test_termination_21_8(fixtures_dir):
    result = _run(str(fixtures_dir / "misra_standard_lib.c"))
    msgs = [i.message for i in result.issues if i.misra_rule and i.misra_rule.rule_id == "21.8"]
    assert any("abort" in m or "exit" in m or "system" in m for m in msgs)


def test_setjmp_21_4(fixtures_dir):
    result = _run(str(fixtures_dir / "misra_standard_lib.c"))
    rule_ids = {i.misra_rule.rule_id for i in result.issues if i.misra_rule}
    assert "21.4" in rule_ids


def test_reserved_identifier_21_2(fixtures_dir):
    result = _run(str(fixtures_dir / "misra_standard_lib.c"))
    msgs = [i.message for i in result.issues if i.misra_rule and i.misra_rule.rule_id == "21.2"]
    assert any("__reserved_var" in m for m in msgs)

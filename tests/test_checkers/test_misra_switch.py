"""Tests for the misra-switch checker (Section 16)."""

from __future__ import annotations

from corvia.engine import AnalysisEngine


def _run(target: str):
    return AnalysisEngine(checker_ids=["misra-switch"]).analyze([target])


def _rules(result):
    return {i.misra_rule.rule_id for i in result.issues if i.misra_rule}


def test_too_few_clauses_16_6(fixtures_dir):
    result = _run(str(fixtures_dir / "misra_switch.c"))
    assert "16.6" in _rules(result)


def test_missing_default_16_4(fixtures_dir):
    result = _run(str(fixtures_dir / "misra_switch.c"))
    assert "16.4" in _rules(result)


def test_missing_break_16_3(fixtures_dir):
    result = _run(str(fixtures_dir / "misra_switch.c"))
    assert "16.3" in _rules(result)


def test_boolean_switch_16_7(fixtures_dir):
    result = _run(str(fixtures_dir / "misra_switch.c"))
    assert "16.7" in _rules(result)


def test_default_position_16_5(fixtures_dir):
    result = _run(str(fixtures_dir / "misra_switch.c"))
    assert "16.5" in _rules(result)


def test_well_formed_switch_clean(fixtures_dir):
    result = _run(str(fixtures_dir / "misra_switch.c"))
    well_formed_issues = [
        i for i in result.issues
        if "well_formed" in (i.context or "") or i.line >= 50
    ]
    assert all(i.misra_rule.rule_id != "16.6" for i in well_formed_issues if i.misra_rule)

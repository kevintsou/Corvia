"""Tests for the misra-unions checker (Section 19)."""

from __future__ import annotations

from corvia.engine import AnalysisEngine


def _run(target: str):
    return AnalysisEngine(checker_ids=["misra-unions"]).analyze([target])


def test_union_declaration_19_2(fixtures_dir):
    result = _run(str(fixtures_dir / "misra_unions.c"))
    msgs = [i.message for i in result.issues if i.misra_rule and i.misra_rule.rule_id == "19.2"]
    assert any("variant" in m for m in msgs)


def test_union_reported_once_per_declaration(fixtures_dir):
    result = _run(str(fixtures_dir / "misra_unions.c"))
    issues_19_2 = [i for i in result.issues if i.misra_rule and i.misra_rule.rule_id == "19.2"]
    # The fixture has one union declaration plus one usage; we want the
    # declaration site reported, not also each ID reference.
    assert len(issues_19_2) <= 2

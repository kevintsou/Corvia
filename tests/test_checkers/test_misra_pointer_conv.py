"""Tests for the misra-pointer-conv checker (Section 11)."""

from __future__ import annotations

from corvia.engine import AnalysisEngine


def _run(target: str):
    return AnalysisEngine(checker_ids=["misra-pointer-conv"]).analyze([target])


def test_function_pointer_cast(fixtures_dir):
    f = str(fixtures_dir / "misra_pointer_conv.c")
    result = _run(f)
    rule_ids = {i.misra_rule.rule_id for i in result.issues if i.misra_rule}
    assert "11.1" in rule_ids


def test_object_pointer_cross_cast(fixtures_dir):
    f = str(fixtures_dir / "misra_pointer_conv.c")
    result = _run(f)
    rule_ids = {i.misra_rule.rule_id for i in result.issues if i.misra_rule}
    assert "11.3" in rule_ids


def test_pointer_integer_conversion(fixtures_dir):
    f = str(fixtures_dir / "misra_pointer_conv.c")
    result = _run(f)
    rule_ids = {i.misra_rule.rule_id for i in result.issues if i.misra_rule}
    assert "11.4" in rule_ids


def test_void_to_object_pointer(fixtures_dir):
    f = str(fixtures_dir / "misra_pointer_conv.c")
    result = _run(f)
    rule_ids = {i.misra_rule.rule_id for i in result.issues if i.misra_rule}
    assert "11.5" in rule_ids


def test_object_to_float_cast(fixtures_dir):
    f = str(fixtures_dir / "misra_pointer_conv.c")
    result = _run(f)
    rule_ids = {i.misra_rule.rule_id for i in result.issues if i.misra_rule}
    assert "11.7" in rule_ids


def test_const_qualifier_drop(fixtures_dir):
    f = str(fixtures_dir / "misra_pointer_conv.c")
    result = _run(f)
    rule_ids = {i.misra_rule.rule_id for i in result.issues if i.misra_rule}
    assert "11.8" in rule_ids


def test_typedef_pointer_cast_not_misclassified(fixtures_dir):
    """A cast to a pointer typedef (HCMD_PTR) from void* must be classified as
    void->object (11.5), not the spurious pointer/integer (11.4) or
    void/arithmetic (11.6) that arises when a pointer typedef is mistaken for
    an integer. The fixture contains no genuine 11.6 cast, so any 11.6 here
    would be the typedef false positive."""
    f = str(fixtures_dir / "misra_pointer_conv.c")
    result = _run(f)
    rule_ids = [i.misra_rule.rule_id for i in result.issues if i.misra_rule]
    assert "11.6" not in rule_ids

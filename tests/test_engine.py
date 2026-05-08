"""Tests for the analysis engine."""

from covia.engine import AnalysisEngine
from covia.models import Severity


def test_analyze_clean_file(fixtures_dir):
    engine = AnalysisEngine(checker_ids=["syntax", "dead-code"])
    result = engine.analyze([str(fixtures_dir / "clean.c")])
    assert len(result.files_analyzed) == 1
    assert result.summary["total_files"] == 1


def test_analyze_directory(fixtures_dir):
    engine = AnalysisEngine(checker_ids=["syntax"])
    result = engine.analyze([str(fixtures_dir)])
    assert len(result.files_analyzed) > 1


def test_severity_filter(fixtures_dir):
    engine_all = AnalysisEngine(checker_ids=["dead-code"], min_severity=Severity.INFO)
    result_all = engine_all.analyze([str(fixtures_dir / "dead_code.c")])

    engine_err = AnalysisEngine(checker_ids=["dead-code"], min_severity=Severity.ERROR)
    result_err = engine_err.analyze([str(fixtures_dir / "dead_code.c")])

    assert len(result_err.issues) <= len(result_all.issues)


def test_misra_only_filter(fixtures_dir):
    engine = AnalysisEngine(misra_only=True)
    result = engine.analyze([str(fixtures_dir / "syntax_issues.c")])
    for issue in result.issues:
        assert issue.misra_rule is not None


def test_nonexistent_target():
    engine = AnalysisEngine()
    result = engine.analyze(["/nonexistent/path"])
    assert len(result.issues) == 1
    assert result.issues[0].severity == Severity.ERROR

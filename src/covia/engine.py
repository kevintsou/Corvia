"""Analysis engine that orchestrates parsing and checker execution."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from covia.models import AnalysisResult, Issue, MisraCategory, Severity
from covia.parser import CParser
from covia.registry import CheckerRegistry


class AnalysisEngine:
    def __init__(
        self,
        checker_ids: Optional[list[str]] = None,
        min_severity: Severity = Severity.INFO,
        misra_only: bool = False,
        misra_category: Optional[MisraCategory] = None,
        use_cpp: bool = False,
        include_dirs: Optional[list[str]] = None,
        external_checkers_dir: Optional[str] = None,
    ) -> None:
        CheckerRegistry.load_builtin_checkers()
        if external_checkers_dir:
            CheckerRegistry.load_external_checkers(external_checkers_dir)

        all_checkers = CheckerRegistry.get_all()
        if checker_ids:
            self._checker_classes = [
                c for c in all_checkers if c.checker_id in checker_ids
            ]
        else:
            self._checker_classes = all_checkers

        self._min_severity = min_severity
        self._misra_only = misra_only
        self._misra_category = misra_category
        self._parser = CParser(use_cpp=use_cpp, include_dirs=include_dirs)

    def analyze_file(self, filepath: str) -> list[Issue]:
        ast, parse_errors = self._parser.parse_file(filepath)
        if ast is None:
            return parse_errors

        issues: list[Issue] = list(parse_errors)
        for checker_cls in self._checker_classes:
            checker = checker_cls()
            checker.set_file(filepath)
            issues.extend(checker.check(ast))

        return self._filter_issues(issues)

    def analyze_directory(
        self, dirpath: str, extensions: tuple[str, ...] = (".c",)
    ) -> list[Issue]:
        issues: list[Issue] = []
        path = Path(dirpath)
        for ext in extensions:
            for f in sorted(path.rglob(f"*{ext}")):
                issues.extend(self.analyze_file(str(f)))
        return issues

    def analyze(self, targets: list[str]) -> AnalysisResult:
        result = AnalysisResult()

        for target in targets:
            p = Path(target)
            if p.is_file():
                result.files_analyzed.append(str(p))
                result.issues.extend(self.analyze_file(str(p)))
            elif p.is_dir():
                for f in sorted(p.rglob("*.c")):
                    result.files_analyzed.append(str(f))
                result.issues.extend(self.analyze_directory(str(p)))
            else:
                result.issues.append(
                    Issue(
                        checker_id="engine",
                        severity=Severity.ERROR,
                        message=f"Target not found: {target}",
                        file=target,
                        line=0,
                    )
                )

        result.issues.sort(key=lambda i: (i.file, i.line, i.column))
        return result

    def _filter_issues(self, issues: list[Issue]) -> list[Issue]:
        filtered = [i for i in issues if i.severity >= self._min_severity]

        if self._misra_only:
            filtered = [i for i in filtered if i.misra_rule is not None]

        if self._misra_category:
            filtered = [
                i
                for i in filtered
                if i.misra_rule and i.misra_rule.category == self._misra_category
            ]

        return filtered

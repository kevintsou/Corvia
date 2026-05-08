"""Analysis engine that orchestrates parsing and checker execution.

Two-pass architecture (Phase 3):
  Pass 1 — Parse all targets and build SymbolTable + CallGraph + FunctionSummaries.
  Pass 2 — Run every registered checker over each AST with the shared
           AnalysisContext attached, so checkers can perform inter-procedural
           queries (e.g. "does this callee return NULL? does it allocate?").
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from pycparser import c_ast

from covia.core.call_graph import build_call_graph
from covia.core.context import AnalysisContext
from covia.core.summary import compute_summaries
from covia.core.symbol_table import build_symbol_table
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

    def analyze(self, targets: list[str]) -> AnalysisResult:
        result = AnalysisResult()
        files = self._collect_files(targets, result)
        if not files:
            return result

        asts: dict[str, c_ast.FileAST] = {}
        for f in files:
            ast, parse_errors = self._parser.parse_file(f)
            result.issues.extend(parse_errors)
            if ast is not None:
                asts[f] = ast
                result.files_analyzed.append(f)

        ctx = self._build_context(asts)

        for filename, ast in asts.items():
            for checker_cls in self._checker_classes:
                checker = checker_cls()
                checker.set_file(filename)
                checker.set_context(ctx)
                issues = checker.check(ast)
                result.issues.extend(self._filter_issues(issues))

        result.issues.sort(key=lambda i: (i.file, i.line, i.column))
        return result

    def analyze_file(self, filepath: str) -> list[Issue]:
        ast, parse_errors = self._parser.parse_file(filepath)
        if ast is None:
            return parse_errors

        ctx = self._build_context({filepath: ast})
        issues: list[Issue] = list(parse_errors)
        for checker_cls in self._checker_classes:
            checker = checker_cls()
            checker.set_file(filepath)
            checker.set_context(ctx)
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

    def _collect_files(self, targets: list[str], result: AnalysisResult) -> list[str]:
        files: list[str] = []
        for target in targets:
            p = Path(target)
            if p.is_file():
                files.append(str(p))
            elif p.is_dir():
                for f in sorted(p.rglob("*.c")):
                    files.append(str(f))
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
        return files

    def _build_context(self, asts: dict[str, c_ast.FileAST]) -> AnalysisContext:
        symbol_table = build_symbol_table(asts)
        call_graph = build_call_graph(asts, symbol_table)
        summaries = compute_summaries(symbol_table, call_graph, asts)
        return AnalysisContext(
            symbol_table=symbol_table,
            call_graph=call_graph,
            summaries=summaries,
            asts=asts,
        )

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

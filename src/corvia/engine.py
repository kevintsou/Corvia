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

from corvia.core.cache import CacheManager, FileCache, hash_file
from corvia.core.call_graph import build_call_graph
from corvia.core.config import CorviaConfig, severity_from_string
from corvia.core.context import AnalysisContext
from corvia.core.summary import compute_summaries
from corvia.core.symbol_table import build_symbol_table
from corvia.models import AnalysisResult, Issue, MisraCategory, Severity
from corvia.parser import CParser
from corvia.registry import CheckerRegistry


class AnalysisEngine:
    def __init__(
        self,
        checker_ids: Optional[list[str]] = None,
        min_severity: Severity = Severity.INFO,
        misra_only: bool = False,
        misra_category: Optional[MisraCategory] = None,
        use_cpp: bool = False,
        include_dirs: Optional[list[str]] = None,
        cpp_defines: Optional[list[str]] = None,
        cpp_args: Optional[list[str]] = None,
        external_checkers_dir: Optional[str] = None,
        incremental: bool = False,
        cache_dir: Optional[str] = None,
        config: Optional[CorviaConfig] = None,
    ) -> None:
        CheckerRegistry.load_builtin_checkers()
        if external_checkers_dir:
            CheckerRegistry.load_external_checkers(external_checkers_dir)

        self._config = config

        all_checkers = CheckerRegistry.get_all()
        cli_checkers = checker_ids
        cfg_enabled = config.enabled_checkers if config else None
        cfg_disabled = set(config.disabled_checkers) if config else set()

        selected: list[type] = []
        for c in all_checkers:
            if cli_checkers is not None:
                if c.checker_id not in cli_checkers:
                    continue
            elif cfg_enabled is not None:
                if c.checker_id not in cfg_enabled:
                    continue
            if c.checker_id in cfg_disabled:
                continue
            selected.append(c)
        self._checker_classes = selected

        self._min_severity = min_severity
        self._misra_only = misra_only
        self._misra_category = misra_category

        merged_includes = list(include_dirs) if include_dirs else []
        merged_cpp_args = list(cpp_args) if cpp_args else []
        if config:
            merged_includes.extend(config.include_dirs)
            merged_cpp_args.extend(config.cpp_args)
            if not use_cpp and config.use_cpp:
                use_cpp = True
        self._parser = CParser(use_cpp=use_cpp, include_dirs=merged_includes or None, cpp_defines=cpp_defines, cpp_args=merged_cpp_args or None, auto_install=True)

        if incremental is False and config and config.cache_enabled:
            incremental = True
        if cache_dir is None and config and config.cache_dir:
            cache_dir = config.cache_dir
        self._incremental = incremental
        self._cache = (
            CacheManager(cache_dir or ".corvia_cache") if incremental else None
        )

    def analyze(self, targets: list[str]) -> AnalysisResult:
        result = AnalysisResult()
        files = self._collect_files(targets, result)
        if not files:
            return result

        result.files_analyzed.extend(files)

        if self._cache is not None:
            to_analyze, reusable = self._cache.determine_files_to_analyze(files)
            for f in reusable:
                cached = self._cache.load(f)
                if cached:
                    result.issues.extend(self._filter_issues(cached.issues))
            files_to_parse = sorted(to_analyze)
        else:
            files_to_parse = files

        asts: dict[str, c_ast.FileAST] = {}
        for f in files_to_parse:
            ast, parse_errors = self._parser.parse_file(f)
            result.issues.extend(parse_errors)
            if ast is not None:
                asts[f] = ast

        ctx = self._build_context(asts)

        for filename, ast in asts.items():
            file_issues: list[Issue] = []
            for checker_cls in self._checker_classes:
                checker = checker_cls()
                checker.set_file(filename)
                checker.set_context(ctx)
                file_issues.extend(checker.check(ast))

            if self._cache is not None:
                self._save_cache(filename, file_issues, ctx)

            result.issues.extend(self._filter_issues(file_issues))

        result.issues.sort(key=lambda i: (i.file, i.line, i.column))
        return result

    def _save_cache(
        self, filename: str, issues: list[Issue], ctx: AnalysisContext
    ) -> None:
        if self._cache is None:
            return
        try:
            content_hash = hash_file(filename)
        except OSError:
            return
        try:
            mtime = Path(filename).stat().st_mtime
        except OSError:
            mtime = 0.0

        callees = sorted({
            site.callee
            for caller, sites in ctx.call_graph.edges.items()
            for site in sites
            if site.file == filename
        })
        defines = sorted({
            f.name
            for f in ctx.symbol_table.all_functions()
            if f.is_definition and f.file == filename and not f.is_static
        })
        self._cache.save(
            FileCache(
                path=filename,
                content_hash=content_hash,
                mtime=mtime,
                issues=list(issues),
                callees=callees,
                defines=defines,
            )
        )

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
        adjusted: list[Issue] = []
        for i in issues:
            if self._config is not None:
                rule_id = i.misra_rule.rule_id if i.misra_rule else None
                override = self._config.severity_for(i.checker_id, rule_id)
                if override is not None:
                    if override == "off":
                        continue
                    new_sev = severity_from_string(override)
                    if new_sev is not None:
                        i = Issue(
                            checker_id=i.checker_id,
                            severity=new_sev,
                            message=i.message,
                            file=i.file,
                            line=i.line,
                            column=i.column,
                            end_line=i.end_line,
                            context=i.context,
                            misra_rule=i.misra_rule,
                        )
            adjusted.append(i)

        filtered = [i for i in adjusted if i.severity >= self._min_severity]

        if self._misra_only:
            filtered = [i for i in filtered if i.misra_rule is not None]

        if self._misra_category:
            filtered = [
                i
                for i in filtered
                if i.misra_rule and i.misra_rule.category == self._misra_category
            ]

        return filtered

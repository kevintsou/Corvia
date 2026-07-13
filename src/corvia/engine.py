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
from corvia.core.regex_symbol_export import extract_regex_symbol_graph, merge_symbol_graphs
from corvia.core.summary import compute_summaries
from corvia.core.symbol_export import serialize_symbol_graph
from corvia.core.symbol_table import build_symbol_table
from corvia.models import AnalysisResult, Issue, MisraCategory, Severity
from corvia.parser import CParser
from corvia.registry import CheckerRegistry
from typing import Callable, Optional

ProgressCallback = Callable[[int, int, str], None]


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
        incremental: Optional[bool] = None,
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
                # CLI --checkers takes precedence over config: a checker
                # explicitly requested on the command line runs even if the
                # config file disables it.
                if c.checker_id not in cli_checkers:
                    continue
            else:
                if cfg_enabled is not None and c.checker_id not in cfg_enabled:
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
        self._symbol_fallback_parser = CParser(
            use_cpp=False, keep_conditional_bodies=True
        )

        if incremental is None:
            incremental = False
        if cache_dir is None and config and config.cache_dir:
            cache_dir = config.cache_dir
        self._incremental = incremental
        env_hash = self._compute_env_hash(
            use_cpp=use_cpp,
            include_dirs=merged_includes,
            cpp_defines=cpp_defines or [],
            cpp_args=merged_cpp_args,
            checker_ids=sorted(c.checker_id for c in self._checker_classes),
        )
        self._cache = (
            CacheManager(cache_dir or ".corvia_cache", env_hash=env_hash)
            if incremental
            else None
        )

    @staticmethod
    def _compute_env_hash(
        *,
        use_cpp: bool,
        include_dirs: list[str],
        cpp_defines: list[str],
        cpp_args: list[str],
        checker_ids: list[str],
    ) -> str:
        """Fingerprint of everything (besides file content) that can change
        analysis results. Cached entries produced under a different
        environment (flags, selected checkers, Corvia version) are stale."""
        import hashlib
        import json

        from corvia import __version__

        payload = json.dumps(
            {
                "version": __version__,
                "use_cpp": use_cpp,
                "include_dirs": list(include_dirs),
                "cpp_defines": list(cpp_defines),
                "cpp_args": list(cpp_args),
                "checkers": list(checker_ids),
            },
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def analyze(self, targets: list[str], progress_callback: Optional[ProgressCallback] = None) -> AnalysisResult:
        result = AnalysisResult()
        files = self._collect_files(targets, result)
        if not files:
            return result

        result.files_analyzed.extend(files)

        source_files_resolved = {Path(f).resolve() for f in files}

        # Pass 1: the AnalysisContext (symbol table, call graph, summaries)
        # must reflect ALL collected files — building it from changed files
        # alone would drop summaries for functions in unchanged files and
        # make incremental results diverge from full runs. To keep that
        # guarantee without paying the expensive preprocess+parse for every
        # file, unchanged files load their pickled AST from the cache; the
        # context is then rebuilt from real ASTs exactly as in a full run.
        asts: dict[str, c_ast.FileAST] = {}
        for idx, f in enumerate(files):
            if progress_callback:
                progress_callback(idx + 1, len(files), str(Path(f).name))
            ast = None
            parse_errors: list[Issue] = []
            file_hash: Optional[str] = None
            if self._cache is not None:
                try:
                    file_hash = hash_file(f)
                except OSError:
                    file_hash = None
                if file_hash is not None:
                    cached_parse = self._cache.load_ast(f, file_hash)
                    if cached_parse is not None:
                        ast, parse_errors = cached_parse
            if ast is None:
                ast, parse_errors = self._parser.parse_file(f)
                if ast is not None and self._cache is not None and file_hash is not None:
                    self._cache.save_ast(f, file_hash, ast, parse_errors)
            result.issues.extend(self._filter_issues(parse_errors))
            if ast is not None:
                asts[f] = ast

        ctx = self._build_context(asts)

        files_to_check = list(asts.keys())
        if self._cache is not None:
            new_defines = {
                f: sorted({
                    fn.name
                    for fn in ctx.symbol_table.all_functions()
                    if fn.is_definition and fn.file == f and not fn.is_static
                })
                for f in files
            }
            to_analyze, reusable = self._cache.determine_files_to_analyze(
                files, new_defines=new_defines
            )
            for f in sorted(reusable):
                cached = self._cache.load(f)
                if cached:
                    result.issues.extend(self._filter_issues(cached.issues))
            files_to_check = [f for f in asts if f in to_analyze]

        total_files = len(files_to_check)
        for file_idx, filename in enumerate(files_to_check):
            ast = asts[filename]
            # Progress is reported per source file (not per file x checker), so
            # the count matches the number of files being analyzed rather than
            # ballooning to files * checkers.
            if progress_callback:
                progress_callback(file_idx + 1, total_files, f"check {Path(filename).name}")
            file_issues: list[Issue] = []
            for checker_cls in self._checker_classes:
                checker = checker_cls()
                checker.set_file(filename)
                checker.set_context(ctx)
                file_issues.extend(checker.check(ast))

            file_issues = [
                i for i in file_issues
                if not i.file or Path(i.file).resolve() in source_files_resolved
            ]

            if self._cache is not None:
                self._save_cache(filename, file_issues, ctx)

            result.issues.extend(self._filter_issues(file_issues))

        # Cross-file issues can appear both in a reused cache entry (stored
        # under the file whose checker produced them) and freshly from the
        # re-analyzed file they point at — keep a single copy.
        result.issues = self._dedupe_issues(result.issues)

        self._populate_context(result.issues)
        result.issues.sort(key=lambda i: (i.file, i.line, i.column))
        return result

    @staticmethod
    def _dedupe_issues(issues: list[Issue]) -> list[Issue]:
        """Drop duplicate issues, comparing on
        (checker_id, normalized file, line, column, message)."""
        import os

        norm_cache: dict[str, str] = {}

        def _norm(file: str) -> str:
            if file not in norm_cache:
                try:
                    norm_cache[file] = os.path.normcase(str(Path(file).resolve()))
                except OSError:
                    norm_cache[file] = file
            return norm_cache[file]

        seen: set[tuple[str, str, int, int, str]] = set()
        unique: list[Issue] = []
        for i in issues:
            key = (i.checker_id, _norm(i.file), i.line, i.column, i.message)
            if key in seen:
                continue
            seen.add(key)
            unique.append(i)
        return unique

    @staticmethod
    def _populate_context(issues: list[Issue]) -> None:
        """Fill each issue's ``context`` with its source line so consumers can
        show the offending code without re-reading files themselves.

        Best-effort: an issue keeps a context a checker already set, and lines
        that can't be read (missing file, out-of-range line) are left as-is.
        Files are read once and cached across issues.
        """
        line_cache: dict[str, list[str]] = {}
        for issue in issues:
            if issue.context or not issue.file or issue.line <= 0:
                continue
            lines = line_cache.get(issue.file)
            if lines is None:
                try:
                    lines = Path(issue.file).read_text(
                        encoding="utf-8", errors="replace"
                    ).splitlines()
                except OSError:
                    lines = []
                line_cache[issue.file] = lines
            if 1 <= issue.line <= len(lines):
                issue.context = lines[issue.line - 1].strip()

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

    def export_symbol_graph(self, targets: list[str]) -> dict:
        """Parse all target files and return a JSON-able symbol + call graph.

        Unlike ``analyze``, this always performs a full parse of every file
        (the incremental cache is intentionally bypassed): a call graph built
        from only the changed files would be incomplete, which defeats the
        purpose of exporting it for cross-file reasoning. No checkers run —
        this is parse + symbol/call-graph construction only.
        """
        result = AnalysisResult()
        files = self._collect_files(targets, result)

        asts: dict[str, c_ast.FileAST] = {}
        for f in files:
            ast, _ = self._parser.parse_file(f)
            if ast is None:
                # Symbol export is auxiliary context for cross-file reasoning.
                # If strict preprocessing fails on target-specific macros or
                # vendor headers, fall back to Corvia's tolerant parser instead
                # of emitting an empty/near-empty graph.
                ast, _ = self._symbol_fallback_parser.parse_file(f)
            if ast is not None:
                asts[f] = ast

        symbol_table = build_symbol_table(asts)
        call_graph = build_call_graph(asts, symbol_table)
        graph = serialize_symbol_graph(symbol_table, call_graph, asts)
        regex_graph = extract_regex_symbol_graph(files)
        return merge_symbol_graphs(graph, regex_graph)

    def analyze_file(self, filepath: str) -> list[Issue]:
        ast, parse_errors = self._parser.parse_file(filepath)
        if ast is None:
            return parse_errors

        ctx = self._build_context({filepath: ast})
        resolved = Path(filepath).resolve()
        issues: list[Issue] = list(parse_errors)
        for checker_cls in self._checker_classes:
            checker = checker_cls()
            checker.set_file(filepath)
            checker.set_context(ctx)
            checker_issues = [
                i for i in checker.check(ast)
                if not i.file or Path(i.file).resolve() == resolved
            ]
            issues.extend(checker_issues)
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
        import os

        files: list[str] = []
        seen: set[str] = set()

        def _add(path: Path) -> None:
            # Dedupe on the resolved path so overlapping targets (a file and
            # its parent directory, or the same directory twice) don't get
            # analyzed twice; first occurrence wins to preserve order.
            key = os.path.normcase(str(path.resolve()))
            if key not in seen:
                seen.add(key)
                files.append(str(path))

        for target in targets:
            p = Path(target)
            if p.is_file():
                _add(p)
            elif p.is_dir():
                for f in sorted(p.rglob("*.c")):
                    _add(f)
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

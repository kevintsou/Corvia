"""CORVIA command-line interface."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from corvia import __version__
from corvia.engine import AnalysisEngine
from corvia.models import AnalysisResult, MisraCategory, Severity
from corvia.registry import CheckerRegistry
from corvia.reporters.html_reporter import HtmlReporter
from corvia.reporters.json_reporter import JsonReporter
from corvia.reporters.md_reporter import MdReporter

try:
    from tqdm import tqdm
    _has_tqdm = True
except ImportError:
    _has_tqdm = False

_SEVERITY_MAP = {"info": Severity.INFO, "warning": Severity.WARNING, "error": Severity.ERROR}
_MISRA_CAT_MAP = {"mandatory": MisraCategory.MANDATORY, "required": MisraCategory.REQUIRED, "advisory": MisraCategory.ADVISORY}

_COLORS = {
    "error": "\033[1;31m",
    "warning": "\033[1;33m",
    "info": "\033[1;36m",
    "reset": "\033[0m",
    "dim": "\033[2m",
}


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="corvia",
        description="CORVIA - C language static analysis tool with MISRA C:2012 support",
    )
    p.add_argument("targets", nargs="*", help="Files or directories to analyze")
    p.add_argument("-V", "--version", action="version", version=f"corvia {__version__}")
    p.add_argument("-c", "--checkers", help="Comma-separated checker IDs to enable (default: all)")
    p.add_argument("-f", "--format", choices=["text", "json", "html", "md"], default="text", help="Output format (default: text)")
    p.add_argument("-o", "--output", help="Output file path")
    p.add_argument("--emit-symbols", metavar="PATH", help="Also write a JSON symbol table + call graph to PATH (for dependency-aware tooling)")
    p.add_argument("-s", "--severity", choices=["info", "warning", "error"], default="info", help="Minimum severity (default: info)")
    p.add_argument("--misra-only", action="store_true", help="Only show issues with MISRA rule mapping")
    p.add_argument("--misra-category", choices=["mandatory", "required", "advisory"], help="Filter by MISRA category")
    p.add_argument("--use-cpp", action="store_true", default=True, help="Use C preprocessor before parsing (default: enabled)")
    p.add_argument("--no-cpp", dest="use_cpp", action="store_false", help="Disable C preprocessor")
    p.add_argument("-I", "--include", action="append", default=[], help="Additional include directories")
    p.add_argument("-D", "--define", action="append", default=[], help="Preprocessor definitions (e.g., -DNAME=VALUE)")
    p.add_argument("--external-checkers", help="Directory containing external checker modules")
    p.add_argument("--list-checkers", action="store_true", help="List all available checkers and exit")
    p.add_argument("--no-color", action="store_true", help="Disable colored output")
    p.add_argument("--incremental", action=argparse.BooleanOptionalAction, default=None,
                   help="Reuse cached results for unchanged files (default: enabled)")
    p.add_argument("--cache-dir", help="Cache directory (default: .corvia_cache)")
    p.add_argument("--clean-cache", action="store_true", help="Delete cache and exit")
    p.add_argument("--config", help="Path to corvia.toml (default: auto-discover from cwd)")
    p.add_argument("--no-config", action="store_true", help="Ignore corvia.toml and use CLI flags only")
    p.add_argument("--cproject", help="Path to Eclipse .cproject file to extract include paths")
    p.add_argument("--cpp-args", action="append", default=[], help="Extra arguments passed to the C preprocessor (e.g. -march=arm)")
    return p


def _list_checkers() -> None:
    CheckerRegistry.load_builtin_checkers()
    checkers = CheckerRegistry.get_all()
    print(f"Available checkers ({len(checkers)}):\n")
    for cls in sorted(checkers, key=lambda c: c.checker_id):
        print(f"  {cls.checker_id:<20s} {cls.description}")
        if cls.misra_rules:
            rules = ", ".join(f"Rule {r.rule_id}" for r in cls.misra_rules)
            print(f"  {'':20s} MISRA: {rules}")
        print()


def _format_text(result: AnalysisResult, use_color: bool) -> str:
    lines: list[str] = []
    for issue in result.issues:
        sev = issue.severity.name.lower()
        if use_color:
            color = _COLORS.get(sev, "")
            reset = _COLORS["reset"]
            dim = _COLORS["dim"]
            loc = f"{issue.file}:{issue.line}:{issue.column}"
            misra = f" {dim}({issue.misra_rule}){reset}" if issue.misra_rule else ""
            lines.append(f"{loc}: {color}{sev}[{issue.checker_id}]{reset}{misra}: {issue.message}")
        else:
            loc = f"{issue.file}:{issue.line}:{issue.column}"
            misra = f" ({issue.misra_rule})" if issue.misra_rule else ""
            lines.append(f"{loc}: {sev}[{issue.checker_id}]{misra}: {issue.message}")

    if result.issues:
        lines.append("")
        s = result.summary
        lines.append(f"Summary: {s['total_issues']} issues ({s['ERROR']} errors, {s['WARNING']} warnings, {s['INFO']} info) in {s['total_files']} files")

        misra = result.misra_summary
        if misra:
            lines.append(f"MISRA rules violated: {len(misra)}")
    else:
        lines.append("No issues found.")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.list_checkers:
        _list_checkers()
        return 0

    if args.clean_cache:
        from corvia.core.cache import CacheManager
        CacheManager(args.cache_dir or ".corvia_cache").clear()
        print("Cache cleared.")
        return 0

    if not args.targets:
        parser.error("No targets specified. Use --list-checkers or provide files/directories.")

    checker_ids = [c.strip() for c in args.checkers.split(",")] if args.checkers else None
    min_severity = _SEVERITY_MAP[args.severity]
    misra_category = _MISRA_CAT_MAP.get(args.misra_category) if args.misra_category else None

    config = None
    cproject_includes: list[str] = []
    discover_base = "."
    if not args.no_config and args.targets:
        first_target = Path(args.targets[0])
        if first_target.is_absolute():
            discover_base = str(first_target.parent)
        elif not Path(discover_base).exists():
            discover_base = "."
    if not args.no_config:
        from corvia.core.config import ConfigError, discover_or_create, find_example_tomls, load, parse_cproject_include_paths, _EXAMPLE_TOML
        try:
            if args.config:
                config = load(args.config)
            else:
                config = discover_or_create(discover_base)
            cproject_path_str = args.cproject or (config.cproject if config else None)
            if cproject_path_str:
                cproject_path = Path(cproject_path_str)
                if not cproject_path.is_absolute() and args.targets:
                    first_target = Path(args.targets[0])
                    target_dir = first_target.parent
                    for parent in [target_dir] + list(target_dir.parents):
                        candidate = parent / cproject_path
                        if candidate.exists():
                            cproject_path = candidate
                            break
                    else:
                        cproject_path = cproject_path.resolve()
                else:
                    cproject_path = cproject_path.resolve()
                cproject_includes = parse_cproject_include_paths(cproject_path)
        except ConfigError:
            dest = Path(discover_base).resolve() / "corvia.toml"

            # 照舊寫入 corvia.toml.example 供使用者參考
            example_path = Path(discover_base).resolve() / "corvia.toml.example"
            try:
                example_path.write_text(_EXAMPLE_TOML, encoding="utf-8")
            except OSError:
                pass

            templates = find_example_tomls()
            selected = None

            if templates and sys.stdin.isatty():
                print("\nNo corvia.toml found. Choose a template to get started:\n", file=sys.stderr)
                for i, t in enumerate(templates, 1):
                    desc = ""
                    try:
                        first = t.read_text(encoding="utf-8").splitlines()[0]
                        if first.startswith("#"):
                            desc = "  " + first.lstrip("# ").strip()
                    except OSError:
                        pass
                    print(f"  [{i}] {t.name}{desc}", file=sys.stderr)
                print("  [0] Skip (add corvia.toml manually or use --no-config)\n", file=sys.stderr)
                try:
                    choice = input("Select [0]: ").strip()
                    idx = int(choice) if choice else 0
                    if 1 <= idx <= len(templates):
                        selected = templates[idx - 1]
                except (ValueError, EOFError, KeyboardInterrupt):
                    pass

            if selected:
                import shutil
                shutil.copy(selected, dest)
                print(f"Copied {selected.name} -> corvia.toml", file=sys.stderr)
                try:
                    config = load(str(dest))
                    print(f"Using config: {dest}", file=sys.stderr)
                except ConfigError as e2:
                    print(f"Error: {e2}", file=sys.stderr)
                    return 2
            else:
                print(
                    "No corvia.toml found. Use --no-config to skip, or copy a template from example_toml/.",
                    file=sys.stderr,
                )
                return 2
        if config and config.source_path:
            print(f"Using config: {config.source_path}", file=sys.stderr)

    output_format = args.format
    if config and config.output_format and "-f" not in (argv or sys.argv) and "--format" not in (argv or sys.argv):
        output_format = config.output_format

    no_color = args.no_color
    if config and config.no_color is not None and not args.no_color:
        no_color = config.no_color

    if args.incremental is None:
        # Not specified: config wins, then default to True (cache on by default for CLI)
        if config and config.cache_enabled is not None:
            incremental = config.cache_enabled
        else:
            incremental = True
    else:
        # User explicitly passed --incremental or --no-incremental: honour it
        incremental = args.incremental

    engine = AnalysisEngine(
        checker_ids=checker_ids,
        min_severity=min_severity,
        misra_only=args.misra_only,
        misra_category=misra_category,
        use_cpp=args.use_cpp,
        include_dirs=args.include + cproject_includes if (args.include or cproject_includes) else None,
        cpp_defines=args.define,
        cpp_args=args.cpp_args,
        external_checkers_dir=args.external_checkers,
        incremental=incremental,
        cache_dir=args.cache_dir,
        config=config,
    )

    files_for_progress = []
    for target in args.targets:
        p = Path(target)
        if p.is_file():
            files_for_progress.append(str(p))
        elif p.is_dir():
            files_for_progress.extend(str(f) for f in sorted(p.rglob("*.c")))

    if _has_tqdm and len(files_for_progress) > 1:
        progress_bar = tqdm(total=0, desc="Parsing", unit="file", ncols=80)
        def progress_callback(curr, total, name):
            if name.startswith("check "):
                if progress_bar.desc != "Checking":
                    progress_bar.reset(total=total)
                    progress_bar.set_description("Checking")
                progress_bar.set_description(f"Checking {name[6:]}")
            else:
                if total != progress_bar.total:
                    progress_bar.reset(total=total)
                progress_bar.set_description(f"Parsing {name}")
            progress_bar.update(curr - progress_bar.n)
        result = engine.analyze(args.targets, progress_callback=progress_callback)
        progress_bar.close()
    else:
        if len(files_for_progress) > 1:
            print(f"Processing {len(files_for_progress)} files...", file=sys.stderr)
        result = engine.analyze(args.targets)

    if output_format == "json":
        output = JsonReporter().generate(result)
    elif output_format == "html":
        output = HtmlReporter().generate(result)
    elif output_format == "md":
        output = MdReporter().generate(result)
    else:
        use_color = not no_color and sys.stdout.isatty()
        output = _format_text(result, use_color)

    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
        print(f"Report written to {args.output}")
    else:
        print(output)

    if args.emit_symbols:
        import json

        graph = engine.export_symbol_graph(args.targets)
        Path(args.emit_symbols).write_text(
            json.dumps(graph, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"Symbol graph written to {args.emit_symbols}", file=sys.stderr)

    has_errors = any(i.severity == Severity.ERROR for i in result.issues)
    return 1 if has_errors else 0


if __name__ == "__main__":
    sys.exit(main())

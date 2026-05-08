"""COVIA command-line interface."""

from __future__ import annotations

import argparse
import sys

from covia import __version__
from covia.engine import AnalysisEngine
from covia.models import AnalysisResult, MisraCategory, Severity
from covia.registry import CheckerRegistry
from covia.reporters.html_reporter import HtmlReporter
from covia.reporters.json_reporter import JsonReporter
from covia.reporters.md_reporter import MdReporter

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
        prog="covia",
        description="COVIA - C language static analysis tool with MISRA C:2012 support",
    )
    p.add_argument("targets", nargs="*", help="Files or directories to analyze")
    p.add_argument("-V", "--version", action="version", version=f"covia {__version__}")
    p.add_argument("-c", "--checkers", help="Comma-separated checker IDs to enable (default: all)")
    p.add_argument("-f", "--format", choices=["text", "json", "html", "md"], default="text", help="Output format (default: text)")
    p.add_argument("-o", "--output", help="Output file path")
    p.add_argument("-s", "--severity", choices=["info", "warning", "error"], default="info", help="Minimum severity (default: info)")
    p.add_argument("--misra-only", action="store_true", help="Only show issues with MISRA rule mapping")
    p.add_argument("--misra-category", choices=["mandatory", "required", "advisory"], help="Filter by MISRA category")
    p.add_argument("--use-cpp", action="store_true", help="Use C preprocessor before parsing")
    p.add_argument("-I", "--include", action="append", default=[], help="Additional include directories")
    p.add_argument("--external-checkers", help="Directory containing external checker modules")
    p.add_argument("--list-checkers", action="store_true", help="List all available checkers and exit")
    p.add_argument("--no-color", action="store_true", help="Disable colored output")
    p.add_argument("--incremental", action="store_true", help="Reuse cached results for unchanged files")
    p.add_argument("--cache-dir", help="Cache directory (default: .covia_cache)")
    p.add_argument("--clean-cache", action="store_true", help="Delete cache and exit")
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
        from covia.core.cache import CacheManager
        CacheManager(args.cache_dir or ".covia_cache").clear()
        print("Cache cleared.")
        return 0

    if not args.targets:
        parser.error("No targets specified. Use --list-checkers or provide files/directories.")

    checker_ids = [c.strip() for c in args.checkers.split(",")] if args.checkers else None
    min_severity = _SEVERITY_MAP[args.severity]
    misra_category = _MISRA_CAT_MAP.get(args.misra_category) if args.misra_category else None

    engine = AnalysisEngine(
        checker_ids=checker_ids,
        min_severity=min_severity,
        misra_only=args.misra_only,
        misra_category=misra_category,
        use_cpp=args.use_cpp,
        include_dirs=args.include if args.include else None,
        external_checkers_dir=args.external_checkers,
        incremental=args.incremental,
        cache_dir=args.cache_dir,
    )

    result = engine.analyze(args.targets)

    if args.format == "json":
        output = JsonReporter().generate(result)
    elif args.format == "html":
        output = HtmlReporter().generate(result)
    elif args.format == "md":
        output = MdReporter().generate(result)
    else:
        use_color = not args.no_color and sys.stdout.isatty()
        output = _format_text(result, use_color)

    if args.output:
        from pathlib import Path
        Path(args.output).write_text(output, encoding="utf-8")
        print(f"Report written to {args.output}")
    else:
        print(output)

    has_errors = any(i.severity == Severity.ERROR for i in result.issues)
    return 1 if has_errors else 0


if __name__ == "__main__":
    sys.exit(main())

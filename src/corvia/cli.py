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
        epilog="Config setup: use `corvia config detect/init` to create corvia.toml.",
    )
    p.add_argument("targets", nargs="*", help="Files or directories to analyze")
    p.add_argument("-V", "--version", action="version", version=f"corvia {__version__}")
    p.add_argument("-c", "--checkers", help="Comma-separated checker IDs to enable (default: all)")
    p.add_argument("-f", "--format", choices=["text", "json", "html", "md"], default=None, help="Output format (default: text, or output_format from corvia.toml)")
    p.add_argument("-o", "--output", help="Output file path")
    p.add_argument("--emit-symbols", metavar="PATH", help="Also write a JSON symbol table + call graph to PATH (for dependency-aware tooling)")
    p.add_argument("-s", "--severity", choices=["info", "warning", "error"], default="info", help="Minimum severity (default: info)")
    p.add_argument("--fail-on", choices=["error", "warning", "info"], default="error",
                   help="Exit with code 1 if any issue at or above this severity is found (default: error)")
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


# Verbs handled by the `corvia config` subcommand. Keep in sync with
# _build_config_parser(). A bare `corvia config <path>` where <path> is not
# one of these is treated as an analysis target, not a config command.
_CONFIG_VERBS = frozenset({"list-templates", "detect", "init"})


def _build_config_parser() -> argparse.ArgumentParser:
    from corvia.core.config_templates import list_config_templates

    template_ids = ["auto"] + [t.id for t in list_config_templates()]
    p = argparse.ArgumentParser(
        prog="corvia config",
        description="Manage project-level corvia.toml configuration files",
    )
    sub = p.add_subparsers(dest="command", required=True)

    list_p = sub.add_parser("list-templates", help="List available corvia.toml templates")
    list_p.add_argument("--json", action="store_true", help="Emit machine-readable JSON")

    detect_p = sub.add_parser("detect", help="Detect the best template for a target project")
    detect_p.add_argument("target", nargs="?", default=".", help="Project directory or source file")
    detect_p.add_argument("--json", action="store_true", help="Emit machine-readable JSON")

    init_p = sub.add_parser("init", help="Create corvia.toml for a target project")
    init_p.add_argument("target", nargs="?", default=".", help="Project directory or source file")
    init_p.add_argument("--template", choices=template_ids, default="auto", help="Template id (default: auto)")
    init_p.add_argument("--force", action="store_true", help="Overwrite an existing corvia.toml")
    init_p.add_argument("--dry-run", action="store_true", help="Print the generated config without writing it")
    init_p.add_argument("--soc", help="Override detected Phison SOC id, e.g. PS5801 or PT5801")
    init_p.add_argument("--json", action="store_true", help="Emit machine-readable JSON")

    return p


def _main_config(argv: list[str]) -> int:
    from corvia.core.config import ConfigError
    from corvia.core.config_templates import (
        detect_config_templates,
        dumps_json,
        init_config,
        list_config_templates,
    )

    parser = _build_config_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "list-templates":
            templates = [t.to_dict() for t in list_config_templates()]
            if args.json:
                print(dumps_json({"templates": templates}))
            else:
                for template in templates:
                    print(f"{template['id']:<10} {template['description']}")
            return 0

        if args.command == "detect":
            detections = [d.to_dict() for d in detect_config_templates(args.target)]
            if args.json:
                print(dumps_json({"target": str(Path(args.target).resolve()), "candidates": detections}))
            else:
                for candidate in detections:
                    reasons = "; ".join(candidate["reasons"])
                    print(f"{candidate['template_id']:<10} {candidate['confidence']:>3}%  {reasons}")
            return 0

        if args.command == "init":
            result = init_config(
                args.target,
                template_id=args.template,
                force=args.force,
                dry_run=args.dry_run,
                soc=args.soc,
            )
            if args.json:
                print(dumps_json(result))
            elif args.dry_run:
                print(result["content"])
            else:
                reasons = "; ".join(result["reasons"])
                print(f"Created {result['path']} using template '{result['template']}' ({reasons})")
            return 0
    except ConfigError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    parser.error(f"Unknown config command: {args.command}")
    return 2


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
    effective_argv = list(sys.argv[1:] if argv is None else argv)
    if effective_argv[:1] == ["config"]:
        rest = effective_argv[1:]
        # Only route to the config subcommand for a known verb (or help
        # request); otherwise a target literally named "config" is a path.
        if rest and rest[0] in (_CONFIG_VERBS | {"-h", "--help"}):
            return _main_config(rest)
        if not rest and not Path("config").exists():
            return _main_config(rest)

    parser = _build_parser()
    args = parser.parse_args(effective_argv)

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
        first_target = Path(args.targets[0]).resolve()
        if first_target.is_dir():
            discover_base = str(first_target)
        else:
            discover_base = str(first_target.parent)
    if not args.no_config:
        from corvia.core.config import ConfigError, discover_or_create, load, parse_cproject_include_paths
        try:
            if args.config:
                config = load(args.config, target_root=discover_base)
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
        except ConfigError as exc:
            from corvia.core.config_templates import init_config, list_config_templates

            selected = None
            if sys.stdin.isatty():
                print(f"\n{exc}\n", file=sys.stderr)
                print("Choose a corvia.toml template to initialize:\n", file=sys.stderr)
                templates = list_config_templates()
                print("  [a] auto       Let Corvia detect the best template", file=sys.stderr)
                for i, t in enumerate(templates, 1):
                    print(f"  [{i}] {t.id:<10} {t.description}", file=sys.stderr)
                print("  [0] Skip (add corvia.toml manually or use --no-config)\n", file=sys.stderr)
                try:
                    choice = input("Select [a]: ").strip().lower()
                    if choice in ("", "a", "auto"):
                        selected = "auto"
                    else:
                        idx = int(choice)
                        if 1 <= idx <= len(templates):
                            selected = templates[idx - 1].id
                except (ValueError, EOFError, KeyboardInterrupt):
                    selected = None

            if selected:
                try:
                    result = init_config(discover_base, template_id=selected)
                except ConfigError as e2:
                    print(f"Error: {e2}", file=sys.stderr)
                    return 2
                try:
                    config = load(str(result["path"]))
                    reasons = "; ".join(str(r) for r in result["reasons"])
                    print(
                        f"Created {result['path']} using template '{result['template']}' ({reasons})",
                        file=sys.stderr,
                    )
                    print(f"Using config: {result['path']}", file=sys.stderr)
                except ConfigError as e2:
                    print(f"Error: {e2}", file=sys.stderr)
                    return 2
            else:
                print(
                    "No corvia.toml found. Run `corvia config detect <project>` and "
                    "`corvia config init <project> --template auto`, or use --no-config to skip.",
                    file=sys.stderr,
                )
                return 2
        if config and config.source_path:
            print(f"Using config: {config.source_path}", file=sys.stderr)

    output_format = args.format
    if output_format is None:
        output_format = config.output_format if (config and config.output_format) else "text"

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
        checking_started = False
        def progress_callback(curr, total, name):
            nonlocal checking_started
            if name.startswith("check "):
                if not checking_started:
                    checking_started = True
                    progress_bar.reset(total=total)
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

    fail_threshold = _SEVERITY_MAP[args.fail_on]
    has_failures = any(i.severity >= fail_threshold for i in result.issues)
    return 1 if has_failures else 0


if __name__ == "__main__":
    sys.exit(main())

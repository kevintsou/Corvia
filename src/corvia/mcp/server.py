"""Corvia MCP server — exposes Corvia static analysis as MCP tools.

Tools:
    analyze        — Analyse a C file or directory, returns JSON results.
    list_checkers  — List all available checker IDs and descriptions.
    clean_cache    — Delete the incremental analysis cache.

Usage (stdio, compatible with Claude Desktop):
    corvia-mcp

Add to claude_desktop_config.json:
    {
        "mcpServers": {
            "corvia": { "command": "corvia-mcp" }
        }
    }
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "MCP support requires the 'mcp' package. "
        "Install it with:  pip install corvia[mcp]"
    ) from exc

from corvia.engine import AnalysisEngine
from corvia.models import MisraCategory, Severity
from corvia.registry import CheckerRegistry

# ---------------------------------------------------------------------------
# Severity / category maps (mirrors cli.py)
# ---------------------------------------------------------------------------
_SEVERITY_MAP: dict[str, Severity] = {
    "info": Severity.INFO,
    "warning": Severity.WARNING,
    "error": Severity.ERROR,
}
_MISRA_CAT_MAP: dict[str, MisraCategory] = {
    "mandatory": MisraCategory.MANDATORY,
    "required": MisraCategory.REQUIRED,
    "advisory": MisraCategory.ADVISORY,
}

# ---------------------------------------------------------------------------
# FastMCP server instance
# ---------------------------------------------------------------------------
mcp = FastMCP(
    "corvia",
    instructions=(
        "Corvia is a C language static analysis tool with MISRA C:2012 support. "
        "Use 'analyze' to run analysis on a C file or directory, "
        "'list_checkers' to see all available checkers, "
        "and 'clean_cache' to reset the incremental analysis cache."
    ),
)


# ---------------------------------------------------------------------------
# Tool: analyze
# ---------------------------------------------------------------------------
@mcp.tool()
def analyze(
    path: str,
    checkers: Optional[list[str]] = None,
    severity: str = "info",
    misra_only: bool = False,
    misra_category: Optional[str] = None,
    use_cpp: bool = True,
    include_dirs: Optional[list[str]] = None,
    defines: Optional[list[str]] = None,
    cpp_args: Optional[list[str]] = None,
    config: Optional[str] = None,
    no_config: bool = False,
    incremental: bool = True,
    cache_dir: Optional[str] = None,
) -> dict[str, Any]:
    """Run Corvia static analysis on a C file or directory.

    Args:
        path: Path to the C file or directory to analyse.
        checkers: List of checker IDs to enable (default: all checkers).
        severity: Minimum severity to report — "info", "warning", or "error".
        misra_only: If true, report only issues that have a MISRA rule mapping.
        misra_category: Filter by MISRA category — "mandatory", "required", or "advisory".
        use_cpp: Run the C preprocessor before parsing (default: true).
        include_dirs: Additional include search paths (equivalent to -I flags).
        defines: Preprocessor macro definitions (equivalent to -D flags).
        cpp_args: Extra arguments forwarded to the C preprocessor.
        config: Path to a corvia.toml configuration file. Auto-discovered if omitted.
        no_config: If true, ignore corvia.toml entirely and use only the parameters above.
        incremental: Cache results so unchanged files are skipped on subsequent runs.
        cache_dir: Directory used for the incremental cache. Defaults to .corvia_cache
            next to the analysis target (not the server working directory).

    Returns:
        A dict with keys:
            files_analyzed  — list of file paths that were processed
            summary         — {total_files, total_issues, ERROR, WARNING, INFO}
            issues          — list of issue dicts {checker_id, severity, message,
                              file, line, column, end_line, context, misra_rule}
            misra_summary   — {rule_id: {rule_id, category, description, violations}, ...}
    """
    min_severity = _SEVERITY_MAP.get(severity.lower(), Severity.INFO)
    misra_cat = _MISRA_CAT_MAP.get(misra_category.lower()) if misra_category else None

    # --- Config resolution (mirrors cli.py logic) ---
    resolved_config = None
    if not no_config:
        from corvia.core.config import ConfigError, discover, load

        try:
            if config:
                resolved_config = load(config)
            else:
                discover_base = str(Path(path).resolve().parent if Path(path).is_file()
                                    else Path(path).resolve())
                # discover() is a pure lookup — unlike discover_or_create()
                # it never writes a corvia.toml.example into the project.
                resolved_config = discover(discover_base)
        except ConfigError:
            # If no config found / error, continue without config
            resolved_config = None

    # Resolve cache_dir so we never fall back to the MCP server's cwd
    # (which may not be writable).  Priority:
    #   1. Caller-supplied cache_dir
    #   2. corvia.toml cache.dir setting
    #   3. .corvia_cache next to the analysis target
    resolved_cache_dir = cache_dir
    if resolved_cache_dir is None and resolved_config and resolved_config.cache_dir:
        resolved_cache_dir = resolved_config.cache_dir
    if resolved_cache_dir is None:
        target_path = Path(path).resolve()
        base_dir = target_path.parent if target_path.is_file() else target_path
        resolved_cache_dir = str(base_dir / ".corvia_cache")

    engine = AnalysisEngine(
        checker_ids=checkers,
        min_severity=min_severity,
        misra_only=misra_only,
        misra_category=misra_cat,
        use_cpp=use_cpp,
        include_dirs=include_dirs or None,
        cpp_defines=defines or None,
        cpp_args=cpp_args or None,
        incremental=incremental,
        cache_dir=resolved_cache_dir,
        config=resolved_config,
    )

    result = engine.analyze([path])
    return result.to_dict()


# ---------------------------------------------------------------------------
# Tool: list_checkers
# ---------------------------------------------------------------------------
@mcp.tool()
def list_checkers() -> list[dict[str, Any]]:
    """List all available Corvia checkers.

    Returns:
        A list of dicts, each with keys:
            id          — checker identifier (e.g. "null-deref", "misra-switch")
            description — short human-readable description
            misra_rules — list of MISRA rule IDs covered by this checker (may be empty)
    """
    CheckerRegistry.load_builtin_checkers()
    checkers = CheckerRegistry.get_all()
    return [
        {
            "id": cls.checker_id,
            "description": cls.description,
            "misra_rules": [r.rule_id for r in cls.misra_rules] if cls.misra_rules else [],
        }
        for cls in sorted(checkers, key=lambda c: c.checker_id)
    ]


# ---------------------------------------------------------------------------
# Tool: clean_cache
# ---------------------------------------------------------------------------
@mcp.tool()
def clean_cache(target_dir: str, cache_dir: Optional[str] = None) -> str:
    """Delete the Corvia incremental analysis cache for a project.

    Args:
        target_dir: Project directory (or a file inside it) whose cache
            should be removed. The cache directory is resolved relative to
            it, the same way `analyze` resolves its cache location.
        cache_dir: Explicit cache directory. Absolute paths are used as-is;
            relative paths are resolved against target_dir. Defaults to
            .corvia_cache next to target_dir.

    Returns:
        A confirmation message, or "no cache found" when nothing was deleted.
    """
    from corvia.core.cache import CacheManager

    target_path = Path(target_dir).resolve()
    base_dir = target_path.parent if target_path.is_file() else target_path
    if cache_dir is None:
        resolved = base_dir / ".corvia_cache"
    else:
        cache_path = Path(cache_dir)
        resolved = cache_path if cache_path.is_absolute() else base_dir / cache_path

    if not resolved.exists():
        return f"No cache found at {resolved}"
    CacheManager(str(resolved)).clear()
    return f"Cache cleared: {resolved}"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> None:
    """Start the Corvia MCP server (stdio transport)."""
    mcp.run()


if __name__ == "__main__":
    main()

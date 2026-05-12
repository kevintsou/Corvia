"""Project-level configuration loaded from `corvia.toml`.

Schema (all sections optional):

    [checkers]
    enabled  = ["null-deref", "memory-leak"]   # if set, only these run
    disabled = ["misra-unions"]                # subtracted from enabled set

    [severity]
    # Keys may be a checker id (e.g. "misra-stdlib") OR a MISRA rule id
    # (e.g. "21.3"). Values are "error" / "warning" / "info" / "off".
    "misra-stdlib" = "error"
    "21.3"         = "info"
    "19.2"         = "off"

    [paths]
    include = ["/usr/local/include"]   # -I equivalents
    use_cpp = true                     # invoke cpp before parsing

    [output]
    format   = "text"                  # text / json / md / html
    no_color = false

    [cache]
    enabled = true
    dir     = ".corvia_cache"

CLI flags always take precedence; values supplied here are defaults.
"""

from __future__ import annotations

import sys
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from corvia.models import Severity


def parse_cproject_include_paths(cproject_path: str | Path) -> list[str]:
    """Extract include paths from Eclipse .cproject file.

    Handles:
    - ${workspace_loc:/${ProjName}/path} -> project_dir/path
    - ${workspace_loc:/ProjectName/path} -> project_dir/path
    - Absolute Windows paths (D:\\...)

    Returns list of absolute directory paths.
    """
    path = Path(cproject_path)
    if not path.exists():
        return []

    content = path.read_text(encoding="utf-8")
    include_paths: list[str] = []
    proj_dir = path.parent

    name_match = re.search(r'<name>(\w+)</name>', content)
    project_name = name_match.group(1) if name_match else None

    def find_matching_brace(content: str, start: int) -> int:
        depth = 0
        i = start
        while i < len(content):
            if content[i] == '{':
                depth += 1
            elif content[i] == '}':
                depth -= 1
                if depth == 0:
                    return i
            i += 1
        return -1

    ws_loc_pattern = re.compile(r'\$\{workspace_loc:')
    for m in ws_loc_pattern.finditer(content):
        brace_end = find_matching_brace(content, m.start())
        if brace_end <= 0:
            continue

        full_match = content[m.start():brace_end + 1]
        inner = full_match[len('${workspace_loc:'):-1].lstrip('/')

        rel_path = inner
        if '${ProjName}' in inner:
            rel_path = inner.replace('${ProjName}', project_name or '')
            if project_name:
                rel_path = rel_path.replace(f'{project_name}/', '')
        elif project_name and inner.startswith(f'{project_name}/'):
            rel_path = inner[len(project_name) + 1:]

        rel_path_clean = rel_path.replace('/', '\\')
        if rel_path_clean.startswith('\\'):
            rel_path_clean = rel_path_clean[1:]
        full_path = str(proj_dir / rel_path_clean)

        if Path(full_path).exists() and full_path not in include_paths:
            include_paths.append(full_path)

    if str(proj_dir) not in include_paths:
        include_paths.insert(0, str(proj_dir))

    return include_paths


if sys.version_info >= (3, 11):
    import tomllib as _toml  # type: ignore[import]
else:  # pragma: no cover
    try:
        import tomli as _toml  # type: ignore[import]
    except ImportError:  # pragma: no cover
        _toml = None  # type: ignore[assignment]


_VALID_SEVERITIES = {"error", "warning", "info", "off"}


@dataclass
class CorviaConfig:
    enabled_checkers: Optional[list[str]] = None
    disabled_checkers: list[str] = field(default_factory=list)
    severity_overrides: dict[str, str] = field(default_factory=dict)
    include_dirs: list[str] = field(default_factory=list)
    use_cpp: bool = False
    output_format: Optional[str] = None
    no_color: Optional[bool] = None
    cache_enabled: Optional[bool] = None
    cache_dir: Optional[str] = None
    source_path: Optional[str] = None

    def severity_for(self, checker_id: str, rule_id: Optional[str]) -> Optional[str]:
        """Return the configured severity for a (checker, rule) pair, or None."""
        if rule_id and rule_id in self.severity_overrides:
            return self.severity_overrides[rule_id]
        if checker_id in self.severity_overrides:
            return self.severity_overrides[checker_id]
        return None

    def applies_to_checker(self, checker_id: str) -> bool:
        if checker_id in self.disabled_checkers:
            return False
        if self.enabled_checkers is not None and checker_id not in self.enabled_checkers:
            return False
        return True


class ConfigError(Exception):
    pass


def _validate(data: dict[str, Any], path: Path) -> CorviaConfig:
    config = CorviaConfig(source_path=str(path))

    checkers = data.get("checkers", {}) or {}
    if not isinstance(checkers, dict):
        raise ConfigError(f"{path}: [checkers] must be a table")
    if "enabled" in checkers:
        config.enabled_checkers = list(checkers["enabled"])
    if "disabled" in checkers:
        config.disabled_checkers = list(checkers["disabled"])

    severity = data.get("severity", {}) or {}
    if not isinstance(severity, dict):
        raise ConfigError(f"{path}: [severity] must be a table")
    for key, value in severity.items():
        if not isinstance(value, str) or value.lower() not in _VALID_SEVERITIES:
            raise ConfigError(
                f"{path}: severity for '{key}' must be one of {sorted(_VALID_SEVERITIES)}"
            )
        config.severity_overrides[str(key)] = value.lower()

    paths = data.get("paths", {}) or {}
    if "include" in paths:
        config.include_dirs = list(paths["include"])
    if "use_cpp" in paths:
        config.use_cpp = bool(paths["use_cpp"])

    output = data.get("output", {}) or {}
    if "format" in output:
        config.output_format = str(output["format"])
    if "no_color" in output:
        config.no_color = bool(output["no_color"])

    cache = data.get("cache", {}) or {}
    if "enabled" in cache:
        config.cache_enabled = bool(cache["enabled"])
    if "dir" in cache:
        config.cache_dir = str(cache["dir"])

    return config


def load(path: str | Path) -> CorviaConfig:
    if _toml is None:
        raise ConfigError(
            "TOML support requires Python 3.11+ or `pip install tomli`"
        )
    p = Path(path)
    with p.open("rb") as f:
        data = _toml.load(f)
    return _validate(data, p)


def discover(start: str | Path = ".") -> Optional[CorviaConfig]:
    """Walk upward from `start` looking for corvia.toml. Returns None if absent."""
    cur = Path(start).resolve()
    if cur.is_file():
        cur = cur.parent
    for candidate in [cur, *cur.parents]:
        config_file = candidate / "corvia.toml"
        if config_file.is_file():
            return load(config_file)
    return None


def severity_from_string(value: str) -> Optional[Severity]:
    v = value.lower()
    if v == "error":
        return Severity.ERROR
    if v == "warning":
        return Severity.WARNING
    if v == "info":
        return Severity.INFO
    return None  # "off" maps to None (means: silence)

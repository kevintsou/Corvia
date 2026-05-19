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
    cpp_args = "-march=arm -mthumb"    # extra flags passed to gcc/clang

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


def _find_make() -> Optional[str]:
    """Return the first available make executable on PATH."""
    import shutil
    for name in ("make", "mingw32-make", "gmake"):
        path = shutil.which(name)
        if path:
            return path
    return None


def _extract_flags_from_text(text: str, proj_dir: Path) -> tuple[list[str], list[str]]:
    """Parse -I and -D flags from compiler command output or Makefile text."""
    seen_inc: set[str] = set()
    seen_def: set[str] = set()
    include_dirs: list[str] = []
    cpp_defines: list[str] = []
    for line in text.splitlines():
        # Allow backslash in path tokens so Windows paths (D:\...) are captured.
        # Quoted form handles paths with spaces; unquoted allows any non-whitespace.
        for m in re.finditer(r'-I\s*("(?:[^"]+)"|[^\s"]+)', line):
            raw = m.group(1).strip('"')
            p = Path(raw)
            abs_p = str(p.resolve()) if p.is_absolute() else str((proj_dir / p).resolve())
            if abs_p not in seen_inc and Path(abs_p).is_dir():
                seen_inc.add(abs_p)
                include_dirs.append(abs_p)
        for m in re.finditer(r'-D([^\s"]+)', line):
            d = m.group(1)
            if d not in seen_def:
                seen_def.add(d)
                cpp_defines.append(d)
    return include_dirs, cpp_defines


def _parse_makefile_static(
    makefile_path: Path,
    extra_vars: Optional[dict[str, str]] = None,
    _visited: Optional[set[str]] = None,
) -> tuple[list[str], list[str]]:
    """Static Makefile parser: expand variables and extract -I/-D flags.

    Handles simple := / ?= / = assignments, $(VAR) expansion, $(abspath ...),
    $(dir ...), $(wildcard ...), and recursive 'include' directives.
    Does not execute shell commands — $(shell ...) is replaced with empty string.
    """
    if _visited is None:
        _visited = set()
    key = str(makefile_path.resolve())
    if key in _visited:
        return [], []
    _visited.add(key)

    try:
        raw = makefile_path.read_bytes()
    except OSError:
        return [], []

    # Normalise line endings: CRLF -> LF so line-continuation regex works uniformly
    content = raw.replace(b'\r\n', b'\n').replace(b'\r', b'\n').decode('utf-8', errors='replace')

    proj_dir = makefile_path.parent

    # Seed variables with CURDIR and any caller-supplied overrides
    vars_: dict[str, str] = {"CURDIR": str(proj_dir)}
    if extra_vars:
        vars_.update(extra_vars)

    # Join line continuations  (\<newline>[whitespace] -> single space)
    # NOTE: must use a compiled pattern with re.MULTILINE or a non-raw string
    # so that \n is the actual newline character (ASCII 10).
    _line_cont_re = re.compile(chr(92) + chr(92) + chr(10) + r'[ \t]*')
    content = _line_cont_re.sub(' ', content)

    # First pass: collect variable assignments (not recipes — skip tab-indented lines)
    for line in content.splitlines():
        if line.startswith('\t'):
            continue
        # := / ::= (immediate), ?= (default), = (recursive), += (append)
        m = re.match(r'^([A-Za-z_]\w*)\s*(\?=|:=|::=|\+=|=)\s*(.*)', line)
        if not m:
            continue
        name, op, val = m.group(1), m.group(2), m.group(3).strip()
        if op == '?=' and name in vars_:
            continue  # don't override existing value
        if op == '+=':
            vars_[name] = vars_.get(name, '') + ' ' + val
        else:
            vars_[name] = val

    def _expand(s: str, depth: int = 0) -> str:
        if depth > 20 or '$' not in s:
            return s

        def _sub(m: re.Match) -> str:
            # m.group(1) is the innermost content (no nested parens/braces)
            inner = m.group(1)
            # Built-in functions
            if inner.startswith('abspath '):
                arg = _expand(inner[8:].strip(), depth + 1)
                p = Path(arg)
                resolved = p.resolve() if p.is_absolute() else (proj_dir / p).resolve()
                return str(resolved)
            if inner.startswith('dir '):
                arg = _expand(inner[4:].strip(), depth + 1)
                return str(Path(arg).parent) + '/'
            if inner.startswith('notdir '):
                arg = _expand(inner[7:].strip(), depth + 1)
                return Path(arg).name
            if inner.startswith('wildcard ') or inner.startswith('shell ') \
                    or inner.startswith('call ') or inner.startswith('eval ') \
                    or inner.startswith('foreach ') or inner.startswith('filter') \
                    or inner.startswith('subst ') or inner.startswith('patsubst ') \
                    or inner.startswith('sort ') or inner.startswith('word ') \
                    or inner.startswith('words ') or inner.startswith('firstword ') \
                    or inner.startswith('lastword ') or inner.startswith('addprefix ') \
                    or inner.startswith('addsuffix ') or inner.startswith('join ') \
                    or inner.startswith('strip ') or inner.startswith('error ') \
                    or inner.startswith('warning ') or inner.startswith('info '):
                return ''  # skip dynamic / message functions
            if inner.startswith('or ') or inner.startswith('if ') \
                    or inner.startswith('and '):
                return ''
            # Plain variable lookup — recursively expand its value
            return _expand(vars_.get(inner, ''), depth + 1)

        # Expand from the inside out: repeatedly replace innermost $(...) / ${...}
        # that contain no nested parens/braces.  Stop when stable.
        result = s
        prev = None
        iters = 0
        while '$' in result and result != prev and iters < 30:
            prev = result
            result = re.sub(r'\$\(([^()]*)\)', _sub, result)
            result = re.sub(r'\$\{([^{}]*)\}', _sub, result)
            # Drop lone $ not followed by ( / { / word-char (auto-variables etc.)
            result = re.sub(r'\$[^({\w]', '', result)
            iters += 1
        return result

    # Expand all variables
    for k in list(vars_.keys()):
        vars_[k] = _expand(vars_[k])

    # Collect full text after expansion for -I/-D extraction
    expanded_lines: list[str] = []
    include_dirs: list[str] = []
    cpp_defines: list[str] = []

    for line in content.splitlines():
        if line.startswith('\t'):
            expanded_lines.append(_expand(line))
            continue
        # Handle 'include' directives recursively
        inc_m = re.match(r'^-?include\s+(.+)', line)
        if inc_m:
            inc_path_raw = _expand(inc_m.group(1).strip())
            for inc_tok in inc_path_raw.split():
                inc_p = Path(inc_tok)
                if not inc_p.is_absolute():
                    inc_p = proj_dir / inc_p
                sub_incs, sub_defs = _parse_makefile_static(inc_p, vars_, _visited)
                include_dirs.extend(sub_incs)
                cpp_defines.extend(sub_defs)
            continue
        expanded_lines.append(_expand(line))

    # Extract flags from all expanded lines
    text = '\n'.join(expanded_lines)
    more_incs, more_defs = _extract_flags_from_text(text, proj_dir)
    # Merge, preserving order and deduplicating
    seen_i = set(include_dirs)
    for d in more_incs:
        if d not in seen_i:
            seen_i.add(d)
            include_dirs.append(d)
    seen_d = set(cpp_defines)
    for d in more_defs:
        if d not in seen_d:
            seen_d.add(d)
            cpp_defines.append(d)

    return include_dirs, cpp_defines


def parse_makefile_include_paths(
    makefile_path: str | Path,
    make_target: str = "",
    make_args: Optional[list[str]] = None,
) -> tuple[list[str], list[str]]:
    """Extract -I include paths and -D defines from a Makefile.

    Strategy:
    1. Dynamic: run 'make -B -n' and parse GCC command lines (works on Linux/Mac/WSL).
    2. Static fallback: parse Makefile text and expand variables (works everywhere,
       including Windows where Linux-style Makefiles cannot be executed).

    Returns (include_dirs, cpp_defines).
    """
    import subprocess
    path = Path(makefile_path)
    if not path.exists():
        return [], []

    proj_dir = path.parent

    # --- Dynamic attempt ---
    make_cmd = _find_make()
    if make_cmd:
        cmd = [make_cmd, "-B", "-n", "-f", path.name]
        if make_args:
            cmd.extend(make_args)
        if make_target:
            cmd.append(make_target)
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                cwd=str(proj_dir), timeout=60,
            )
            output = result.stdout + result.stderr
            inc_dirs, cpp_defs = _extract_flags_from_text(output, proj_dir)
            if inc_dirs:
                return inc_dirs, cpp_defs
        except (subprocess.TimeoutExpired, OSError):
            pass

    # --- Static fallback ---
    # Seed extra variables from make_args (e.g. ["SOC_ID=PS5801"])
    extra: dict[str, str] = {}
    for arg in (make_args or []):
        kv = re.match(r'^([A-Za-z_]\w*)=(.*)', arg)
        if kv:
            extra[kv.group(1)] = kv.group(2)

    return _parse_makefile_static(path, extra_vars=extra)


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
    cpp_args: list[str] = field(default_factory=list)
    cproject: Optional[str] = None
    makefile: Optional[str] = None
    make_target: str = ""
    make_args: list[str] = field(default_factory=list)
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
        base = path.parent
        config.include_dirs = [
            str((base / d).resolve()) if not Path(d).is_absolute() else d
            for d in paths["include"]
        ]
    if "use_cpp" in paths:
        config.use_cpp = bool(paths["use_cpp"])
    if "cpp_args" in paths:
        val = paths["cpp_args"]
        if isinstance(val, str):
            config.cpp_args = val.split()
        elif isinstance(val, list):
            config.cpp_args = [str(v) for v in val]
        else:
            raise ConfigError(f"{path}: [paths] cpp_args must be a string or list")
    proj_dir = Path(config.source_path).parent

    if "cproject" in paths:
        # Eclipse CDT: explicit .cproject path
        config.cproject = str(paths["cproject"])
        cproject_path = proj_dir / config.cproject
        if cproject_path.exists():
            config.include_dirs = parse_cproject_include_paths(str(cproject_path))

    elif "makefile" in paths:
        # Makefile project: only when explicitly configured (avoids running make -B -n on every startup)
        config.makefile = str(paths["makefile"])

        if "make_target" in paths:
            config.make_target = str(paths["make_target"])

        if "make_args" in paths:
            val = paths["make_args"]
            if isinstance(val, str):
                config.make_args = val.split()
            elif isinstance(val, list):
                config.make_args = [str(v) for v in val]

        makefile_path = proj_dir / config.makefile
        inc_dirs, cpp_defs = parse_makefile_include_paths(
            makefile_path,
            make_target=config.make_target,
            make_args=config.make_args,
        )
        if inc_dirs:
            # Only override manual include list if Makefile returned results
            config.include_dirs = inc_dirs
        if cpp_defs and not config.cpp_args:
            # Only inject defines if user hasn't already set cpp_args
            config.cpp_args = [f"-D{d}" for d in cpp_defs]

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


_EXAMPLE_TOML = """\
# corvia.toml.example — Corvia configuration reference
# Copy this file to corvia.toml and edit to suit your project.
# All sections are optional; CLI flags always take precedence.

[checkers]
# enabled  = ["null-deref", "memory-leak", "uninit-var"]  # run only these checkers
# disabled = ["misra-unions", "misra-preproc"]             # exclude specific checkers

[severity]
# Override severity per checker-id or MISRA rule-id.
# Valid values: "error" | "warning" | "info" | "off"
# "19.2"        = "off"      # silence union advisory entirely
# "misra-expr"  = "info"     # downgrade all expression warnings to info
# "9.1"         = "error"    # promote uninitialized-variable to error

[paths]
use_cpp = false
# include  = ["/usr/local/include", "third_party/include"]  # extra -I paths
# cproject = ".cproject"          # Eclipse CDT: auto-extract include paths from .cproject
# makefile = "Makefile"           # Makefile: auto-detect include paths (mutually exclusive with cproject)
# make_target = "all"             # make target used for dry-run (optional)
# make_args = ["SOC_ID=PS5801"]   # extra variables passed to make / static parser
# cpp_args = "-march=armv7-a -mthumb"  # extra flags passed to the C preprocessor

[output]
format   = "text"   # text | json | md | html
no_color = false

[cache]
enabled = true
dir     = ".corvia_cache"
"""


def discover_or_create(start: str | Path = ".") -> Optional[CorviaConfig]:
    """Walk upward from `start` looking for corvia.toml.

    If not found, creates a ``corvia.toml.example`` in the start directory
    for the user to reference, then raises :class:`ConfigError` with an
    actionable message.  Returns None only if TOML support is unavailable.
    """
    config = discover(start)
    if config is not None:
        return config

    cur = Path(start).resolve()
    if cur.is_file():
        cur = cur.parent

    # Create the example file so the user has something to start from.
    example_path = cur / "corvia.toml.example"
    try:
        example_path.write_text(_EXAMPLE_TOML, encoding="utf-8")
        example_created = True
    except OSError:
        example_created = False

    msg_lines = [
        f"No corvia.toml found (searched upward from '{cur}').",
    ]
    if example_created:
        msg_lines += [
            f"An example configuration has been created at:",
            f"  {example_path}",
            "Copy it to corvia.toml, edit as needed, then re-run Corvia.",
        ]
    msg_lines.append("Run with --no-config to skip configuration file discovery.")
    raise ConfigError("\n".join(msg_lines))


def severity_from_string(value: str) -> Optional[Severity]:
    v = value.lower()
    if v == "error":
        return Severity.ERROR
    if v == "warning":
        return Severity.WARNING
    if v == "info":
        return Severity.INFO
    return None  # "off" maps to None (means: silence)

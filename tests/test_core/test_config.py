"""Tests for the corvia.toml configuration loader and engine integration."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from corvia.core.config import (
    ConfigError,
    discover,
    load,
    parse_cproject_include_paths,
    severity_from_string,
)
from corvia.engine import AnalysisEngine
from corvia.models import Severity


def _write(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content)
    return p


def test_load_minimal(tmp_path: Path):
    cfg = _write(tmp_path, "corvia.toml", "")
    config = load(cfg)
    assert config.enabled_checkers is None
    assert config.disabled_checkers == []
    assert config.severity_overrides == {}


def test_load_full_schema(tmp_path: Path):
    cfg = _write(
        tmp_path,
        "corvia.toml",
        """
[checkers]
enabled  = ["null-deref", "memory-leak"]
disabled = ["misra-unions"]

[severity]
"misra-stdlib" = "error"
"21.3"         = "info"
"19.2"         = "off"

[paths]
include = ["/usr/local/include"]
use_cpp = true

[output]
format   = "json"
no_color = true

[cache]
enabled = true
dir     = ".my_cache"
""",
    )
    config = load(cfg)
    assert config.enabled_checkers == ["null-deref", "memory-leak"]
    assert config.disabled_checkers == ["misra-unions"]
    assert config.severity_overrides["misra-stdlib"] == "error"
    assert config.severity_overrides["21.3"] == "info"
    assert config.severity_overrides["19.2"] == "off"
    assert config.include_dirs == ["/usr/local/include"]
    assert config.use_cpp is True
    assert config.output_format == "json"
    assert config.no_color is True
    assert config.cache_enabled is True
    assert config.cache_dir == ".my_cache"


def test_parse_cproject_include_paths_uses_platform_separators(tmp_path: Path):
    (tmp_path / ".project").write_text("<projectDescription><name>DemoProj</name></projectDescription>")
    for rel in ["src_root/duan/user", "src_root/framework/flibhal", "src_root/sal"]:
        (tmp_path / rel).mkdir(parents=True)
    cproject = _write(
        tmp_path,
        ".cproject",
        """
<cproject>
  <configuration>
    <option valueType="includePath">
      <listOptionValue builtIn="false" value="&quot;${workspace_loc:/${ProjName}/src_root/duan/user}&quot;"/>
      <listOptionValue builtIn="false" value="${workspace_loc:/DemoProj/src_root/framework/flibhal}"/>
      <listOptionValue builtIn="false" value="${workspace_loc:\\${ProjName}\\src_root\\sal}"/>
    </option>
  </configuration>
</cproject>
""",
    )

    include_dirs = parse_cproject_include_paths(cproject)

    assert str(tmp_path / "src_root" / "duan" / "user") in include_dirs
    assert str(tmp_path / "src_root" / "framework" / "flibhal") in include_dirs
    assert str(tmp_path / "src_root" / "sal") in include_dirs
    # The backslash-styled workspace_loc value must be normalized to the
    # platform separator. On Windows the platform form itself contains
    # backslashes, so this check is only meaningful on POSIX.
    if os.sep == "/":
        assert all("\\" not in p for p in include_dirs)


def test_invalid_severity_value_rejected(tmp_path: Path):
    cfg = _write(
        tmp_path,
        "corvia.toml",
        """
[severity]
"21.3" = "panic"
""",
    )
    with pytest.raises(ConfigError):
        load(cfg)


def test_severity_lookup_prefers_rule_over_checker():
    from corvia.core.config import CorviaConfig
    config = CorviaConfig(
        severity_overrides={"misra-stdlib": "error", "21.3": "info"},
    )
    assert config.severity_for("misra-stdlib", "21.3") == "info"
    assert config.severity_for("misra-stdlib", "21.6") == "error"
    assert config.severity_for("null-deref", None) is None


def test_discover_walks_upward(tmp_path: Path):
    nested = tmp_path / "a" / "b" / "c"
    nested.mkdir(parents=True)
    _write(tmp_path, "corvia.toml", "[checkers]\ndisabled = ['x']\n")
    config = discover(nested)
    assert config is not None
    assert config.disabled_checkers == ["x"]


def test_discover_returns_none_when_no_config(tmp_path: Path):
    nested = tmp_path / "child"
    nested.mkdir()
    assert discover(nested) is None


def test_engine_disables_checkers_via_config(tmp_path: Path):
    src = _write(
        tmp_path,
        "src.c",
        "union variant { int i; float f; };\nvoid use(void) { union variant v; v.i = 1; (void)v; }\n",
    )
    cfg_file = _write(
        tmp_path,
        "corvia.toml",
        '[checkers]\ndisabled = ["misra-unions"]\n',
    )
    config = load(cfg_file)
    engine = AnalysisEngine(config=config)
    result = engine.analyze([str(src)])
    assert all(i.checker_id != "misra-unions" for i in result.issues)


def test_engine_severity_override_silences_via_off(tmp_path: Path):
    src = _write(
        tmp_path,
        "src.c",
        "union variant { int i; };\nvoid use(void) { union variant v; v.i = 1; (void)v; }\n",
    )
    cfg_file = _write(
        tmp_path,
        "corvia.toml",
        '[severity]\n"19.2" = "off"\n',
    )
    config = load(cfg_file)
    engine = AnalysisEngine(config=config)
    result = engine.analyze([str(src)])
    assert all(
        not (i.misra_rule and i.misra_rule.rule_id == "19.2")
        for i in result.issues
    )


def test_engine_severity_override_promotes(tmp_path: Path):
    src = _write(
        tmp_path,
        "src.c",
        "union variant { int i; };\nvoid use(void) { union variant v; v.i = 1; (void)v; }\n",
    )
    cfg_file = _write(
        tmp_path,
        "corvia.toml",
        '[severity]\n"19.2" = "error"\n',
    )
    config = load(cfg_file)
    engine = AnalysisEngine(config=config)
    result = engine.analyze([str(src)])
    promoted = [i for i in result.issues
                if i.misra_rule and i.misra_rule.rule_id == "19.2"]
    assert promoted
    assert all(i.severity == Severity.ERROR for i in promoted)


def test_engine_applies_severity_override_to_parser_errors(tmp_path: Path):
    src = _write(tmp_path, "src.c", '#include "missing_header.h"\nint ok(void) { return 0; }\n')
    cfg_file = _write(
        tmp_path,
        "corvia.toml",
        """
[paths]
use_cpp = true

[severity]
"parser" = "warning"
""",
    )
    config = load(cfg_file)
    engine = AnalysisEngine(config=config, incremental=False)

    result = engine.analyze([str(src)])

    parser_issues = [i for i in result.issues if i.checker_id == "parser"]
    assert parser_issues
    assert all(i.severity == Severity.WARNING for i in parser_issues)


def test_severity_from_string():
    assert severity_from_string("error") == Severity.ERROR
    assert severity_from_string("warning") == Severity.WARNING
    assert severity_from_string("info") == Severity.INFO
    assert severity_from_string("off") is None
    assert severity_from_string("nope") is None


# ---------------------------------------------------------------------------
# Path variables (${TARGET_ROOT} / ${CONFIG_DIR}) and repo-boundary discovery
# ---------------------------------------------------------------------------


def test_include_target_root_variable(tmp_path: Path):
    """${TARGET_ROOT} anchors include paths to the analyzed tree, not the toml."""
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    tree = tmp_path / "checkout_a"
    (tree / "common" / "sal").mkdir(parents=True)
    cfg = _write(config_dir, "corvia.toml", '[paths]\ninclude = ["${TARGET_ROOT}/common/sal"]\n')

    config = load(cfg, target_root=tree)

    assert config.include_dirs == [str(tree / "common" / "sal")]


def test_include_config_dir_variable(tmp_path: Path):
    cfg = _write(tmp_path, "corvia.toml", '[paths]\ninclude = ["${CONFIG_DIR}/third_party"]\n')
    config = load(cfg, target_root=tmp_path / "elsewhere")
    assert config.include_dirs == [str(tmp_path / "third_party")]


def test_include_relative_still_anchors_to_config_dir(tmp_path: Path):
    """Plain relative entries keep the historical config-dir anchoring."""
    cfg = _write(tmp_path, "corvia.toml", '[paths]\ninclude = ["third_party"]\n')
    config = load(cfg, target_root=tmp_path / "elsewhere")
    assert config.include_dirs == [str((tmp_path / "third_party").resolve())]


def test_target_root_variable_without_target_falls_back_with_warning(tmp_path: Path):
    cfg = _write(tmp_path, "corvia.toml", '[paths]\ninclude = ["${TARGET_ROOT}/inc"]\n')
    with pytest.warns(UserWarning, match="TARGET_ROOT"):
        config = load(cfg)
    assert config.include_dirs == [str(tmp_path / "inc")]


def test_discover_passes_target_root(tmp_path: Path):
    """discover() defaults ${TARGET_ROOT} to the directory being analyzed."""
    repo = tmp_path / "repo"
    sub = repo / "src"
    (sub / "inc").mkdir(parents=True)
    _write(repo, "corvia.toml", '[paths]\ninclude = ["${TARGET_ROOT}/inc"]\n')

    config = discover(sub)

    assert config is not None
    assert config.include_dirs == [str(sub / "inc")]


def test_discover_stops_at_repo_boundary(tmp_path: Path):
    """A corvia.toml above the target's git repo must not be picked up."""
    _write(tmp_path, "corvia.toml", '[output]\nformat = "html"\n')  # foreign config
    repo = tmp_path / "project"
    (repo / ".git").mkdir(parents=True)
    src = repo / "src"
    src.mkdir()

    assert discover(src) is None


def test_discover_finds_config_at_repo_root(tmp_path: Path):
    """The repo root itself is still searched before the walk stops."""
    repo = tmp_path / "project"
    (repo / ".git").mkdir(parents=True)
    src = repo / "src"
    src.mkdir()
    _write(repo, "corvia.toml", '[output]\nformat = "json"\n')

    config = discover(src)

    assert config is not None
    assert config.output_format == "json"


def test_discover_respects_gitfile_worktree_boundary(tmp_path: Path):
    """.git may be a *file* (worktrees/submodules) — still a boundary."""
    _write(tmp_path, "corvia.toml", '[output]\nformat = "html"\n')
    repo = tmp_path / "wt"
    repo.mkdir()
    (repo / ".git").write_text("gitdir: ../real/.git/worktrees/wt\n")

    assert discover(repo) is None

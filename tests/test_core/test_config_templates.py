"""Tests for corvia.toml template detection and initialization."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from corvia.cli import main
from corvia.core.config import ConfigError
from corvia.core.config_templates import detect_config_templates, init_config


def test_detect_prefers_ds5_when_cproject_exists(tmp_path: Path):
    (tmp_path / ".cproject").write_text("<cproject />", encoding="utf-8")

    candidates = detect_config_templates(tmp_path)

    assert candidates[0].template_id == "ds5"
    assert candidates[0].confidence == 95


def test_init_auto_generates_dynamic_phison_include_paths(tmp_path: Path):
    (tmp_path / "common" / "include" / "phison_hw" / "PT5801" / "reg").mkdir(parents=True)
    (tmp_path / "common" / "config").mkdir(parents=True)

    result = init_config(tmp_path, template_id="auto")

    generated = (tmp_path / "corvia.toml").read_text(encoding="utf-8")
    assert result["template"] == "ps5801"
    assert 'template: ps5801' in generated
    assert 'common/include/phison_hw/PT5801/reg' in generated
    assert '-DSOC_ID=PT5801' in generated


def test_init_does_not_overwrite_without_force(tmp_path: Path):
    cfg = tmp_path / "corvia.toml"
    cfg.write_text("# existing\n", encoding="utf-8")

    with pytest.raises(ConfigError):
        init_config(tmp_path, template_id="minimal")

    assert cfg.read_text(encoding="utf-8") == "# existing\n"


def test_cli_config_detect_json(tmp_path: Path, capsys):
    (tmp_path / "Makefile").write_text("CFLAGS += -Iinclude\n", encoding="utf-8")

    rc = main(["config", "detect", str(tmp_path), "--json"])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["candidates"][0]["template_id"] == "makefile"


def test_cli_config_init_dry_run_json_does_not_write(tmp_path: Path, capsys):
    rc = main(["config", "init", str(tmp_path), "--template", "minimal", "--dry-run", "--json"])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["template"] == "minimal"
    assert payload["dry_run"] is True
    assert payload["written"] is False
    assert "[paths]" in payload["content"]
    assert not (tmp_path / "corvia.toml").exists()

"""CLI integration tests."""

from __future__ import annotations

import json

from corvia.cli import main


def test_cli_writes_context_and_symbol_graph(tmp_path):
    src = tmp_path / "demo.c"
    out = tmp_path / "findings.json"
    symbols = tmp_path / "symbols.json"
    cache_dir = tmp_path / ".corvia_cache"

    src.write_text(
        "\n".join(
            [
                "int helper(int x) { return x + 1; }",
                "int caller(void) { return helper(2); }",
                "void takes_unused(int unused) { }",
                "",
            ]
        ),
        encoding="utf-8",
    )

    rc = main(
        [
            "--no-config",
            "--no-incremental",
            "--cache-dir",
            str(cache_dir),
            "-f",
            "json",
            "-o",
            str(out),
            "--emit-symbols",
            str(symbols),
            str(src),
        ]
    )

    assert rc == 0

    findings = json.loads(out.read_text(encoding="utf-8"))
    unused = next(i for i in findings["issues"] if i["checker_id"] == "unused-var")
    assert "takes_unused" in unused["context"]

    graph = json.loads(symbols.read_text(encoding="utf-8"))
    functions = {f["name"]: f for f in graph["functions"]}
    assert {"helper", "caller", "takes_unused"} <= set(functions)
    assert any(
        e["caller"] == "caller" and e["callee"] == "helper"
        for e in graph["call_edges"]
    )


def test_emit_symbols_falls_back_when_cpp_parse_fails(tmp_path):
    src = tmp_path / "demo.c"
    out = tmp_path / "findings.json"
    symbols = tmp_path / "symbols.json"
    cache_dir = tmp_path / ".corvia_cache"

    src.write_text(
        '#include "missing_vendor_header.h"\n'
        "int symbol_survives(void) { return 7; }\n",
        encoding="utf-8",
    )
    (tmp_path / "corvia.toml").write_text(
        """
[paths]
use_cpp = true

[severity]
"parser" = "warning"
""",
        encoding="utf-8",
    )

    rc = main(
        [
            "--no-incremental",
            "--cache-dir",
            str(cache_dir),
            "-f",
            "json",
            "-o",
            str(out),
            "--emit-symbols",
            str(symbols),
            str(src),
        ]
    )

    assert rc == 0
    findings = json.loads(out.read_text(encoding="utf-8"))
    assert any(i["checker_id"] == "parser" for i in findings["issues"])

    graph = json.loads(symbols.read_text(encoding="utf-8"))
    functions = {f["name"] for f in graph["functions"]}
    assert "symbol_survives" in functions


def test_emit_symbols_uses_regex_fallback_for_parser_hostile_file(tmp_path):
    src = tmp_path / "vendor.c"
    out = tmp_path / "findings.json"
    symbols = tmp_path / "symbols.json"

    src.write_text(
        '#include "missing_vendor_header.h"\n'
        "void vendor_symbol(UNKNOWN_PTR pCmd) {\n"
        "    VENDOR_REG_WRITE(pCmd->dw[0]);\n"
        "}\n",
        encoding="utf-8",
    )
    (tmp_path / "corvia.toml").write_text(
        """
[paths]
use_cpp = true

[severity]
"parser" = "warning"
""",
        encoding="utf-8",
    )

    rc = main(
        [
            "--no-incremental",
            "-f",
            "json",
            "-o",
            str(out),
            "--emit-symbols",
            str(symbols),
            str(src),
        ]
    )

    assert rc == 0
    graph = json.loads(symbols.read_text(encoding="utf-8"))
    functions = {f["name"]: f for f in graph["functions"]}
    assert "vendor_symbol" in functions
    assert "VENDOR_REG_WRITE" in functions["vendor_symbol"]["callees"]


def _write_demo_source(tmp_path):
    src = tmp_path / "demo.c"
    src.write_text("void takes_unused(int unused) { }\n", encoding="utf-8")
    return src


def test_format_flag_overrides_config_output_format(tmp_path):
    """--format=json (equals form) must win over output.format in corvia.toml."""
    src = _write_demo_source(tmp_path)
    (tmp_path / "corvia.toml").write_text('[output]\nformat = "md"\n', encoding="utf-8")
    out = tmp_path / "report.out"

    rc = main(
        [
            "--no-incremental",
            "--cache-dir",
            str(tmp_path / ".corvia_cache"),
            "--format=json",
            "-o",
            str(out),
            str(src),
        ]
    )
    assert rc == 0
    json.loads(out.read_text(encoding="utf-8"))  # valid JSON => CLI flag won


def test_config_output_format_used_when_no_format_flag(tmp_path):
    """Without -f/--format, output.format from corvia.toml applies."""
    src = _write_demo_source(tmp_path)
    (tmp_path / "corvia.toml").write_text('[output]\nformat = "md"\n', encoding="utf-8")
    out = tmp_path / "report.out"

    rc = main(
        [
            "--no-incremental",
            "--cache-dir",
            str(tmp_path / ".corvia_cache"),
            "-o",
            str(out),
            str(src),
        ]
    )
    assert rc == 0
    assert out.read_text(encoding="utf-8").startswith("# CORVIA Analysis Report")


def test_fail_on_gates_exit_code(tmp_path):
    """Default --fail-on error keeps rc 0 for non-error issues; --fail-on info trips."""
    src = _write_demo_source(tmp_path)
    out = tmp_path / "report.out"
    base = [
        "--no-config",
        "--no-incremental",
        "--cache-dir",
        str(tmp_path / ".corvia_cache"),
        "-f",
        "json",
        "-o",
        str(out),
        str(src),
    ]

    assert main(base) == 0  # unused-var issues are not errors

    findings = json.loads(out.read_text(encoding="utf-8"))
    assert findings["issues"]  # demo source must produce at least one issue
    assert main(["--fail-on", "info", *base]) == 1

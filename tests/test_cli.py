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

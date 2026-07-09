"""CORVIA Language Server (LSP).

Run with:
    corvia-lsp --stdio
    corvia-lsp --tcp --host 127.0.0.1 --port 9999

The server analyzes a document on open and on save, then publishes
diagnostics. It uses CORVIA's incremental cache so repeated edits to a
single file in a workspace stay fast.

This module only imports pygls when invoked, so importing
`corvia.lsp.server` without pygls installed will fail with a friendly
error pointing at the [lsp] extras.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from corvia import __version__
from corvia.engine import AnalysisEngine
from corvia.lsp.converter import (
    file_uri_to_path,
    issue_to_diagnostic,
    issues_by_file,
    path_to_file_uri,
)


def _import_language_server():
    try:
        from lsprotocol import types
    except ImportError as e:
        raise SystemExit(
            "lsprotocol is not installed. Install with `pip install 'corvia[lsp]'`."
        ) from e
    try:
        from pygls.lsp.server import LanguageServer  # pygls >= 2.x
    except ImportError:
        try:
            from pygls.server import LanguageServer  # pygls 1.x
        except ImportError as e:
            raise SystemExit(
                "pygls is not installed. Install with `pip install 'corvia[lsp]'`."
            ) from e
    return LanguageServer, types


def create_server():
    LanguageServer, types = _import_language_server()

    server = LanguageServer("corvia-lsp", __version__)
    engine = AnalysisEngine(incremental=True)

    def _publish(uri: str, diagnostics: list[dict]) -> None:
        lsp_diags = []
        for d in diagnostics:
            r = d["range"]
            lsp_diags.append(
                types.Diagnostic(
                    range=types.Range(
                        start=types.Position(
                            line=r["start"]["line"],
                            character=r["start"]["character"],
                        ),
                        end=types.Position(
                            line=r["end"]["line"],
                            character=r["end"]["character"],
                        ),
                    ),
                    severity=types.DiagnosticSeverity(d["severity"]),
                    code=d.get("code"),
                    source=d.get("source", "corvia"),
                    message=d["message"],
                )
            )
        if hasattr(server, "text_document_publish_diagnostics"):  # pygls >= 2.x
            server.text_document_publish_diagnostics(
                types.PublishDiagnosticsParams(uri=uri, diagnostics=lsp_diags)
            )
        else:  # pygls 1.x
            server.publish_diagnostics(uri, lsp_diags)

    def _norm(path: str) -> str:
        return os.path.normcase(str(Path(path).resolve()))

    def _analyze_and_publish(uri: str) -> None:
        path = file_uri_to_path(uri)
        result = engine.analyze([path])
        grouped = issues_by_file(result.issues)
        analyzed = _norm(path)
        analyzed_published = False
        for file, issues in grouped.items():
            target_uri = path_to_file_uri(file)
            _publish(target_uri, [issue_to_diagnostic(i) for i in issues])
            if _norm(file) == analyzed:
                analyzed_published = True
        # Always clear diagnostics for the analyzed document itself, even
        # when other files (e.g. included headers) still have issues.
        if not analyzed_published:
            _publish(uri, [])

    @server.feature(types.TEXT_DOCUMENT_DID_OPEN)
    def did_open(params):
        _analyze_and_publish(params.text_document.uri)

    @server.feature(types.TEXT_DOCUMENT_DID_SAVE)
    def did_save(params):
        _analyze_and_publish(params.text_document.uri)

    return server


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="corvia-lsp", description="CORVIA Language Server")
    transport = p.add_mutually_exclusive_group()
    transport.add_argument("--stdio", action="store_true", help="Use stdio transport (default)")
    transport.add_argument("--tcp", action="store_true", help="Use TCP transport")
    p.add_argument("--host", default="127.0.0.1", help="TCP host (with --tcp)")
    p.add_argument("--port", type=int, default=9999, help="TCP port (with --tcp)")
    p.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        stream=sys.stderr,
    )
    server = create_server()
    if args.tcp:
        server.start_tcp(args.host, args.port)
    else:
        server.start_io()
    return 0


if __name__ == "__main__":
    sys.exit(main())

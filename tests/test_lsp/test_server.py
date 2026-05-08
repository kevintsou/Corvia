"""Smoke tests for the LSP server module.

Exercises only the parts that don't require an actual LSP transport
(loading the module, building the server with pygls available).
"""

from __future__ import annotations

import pytest


def test_server_module_importable():
    from corvia.lsp import server  # noqa: F401


def test_create_server_when_pygls_available():
    pytest.importorskip("pygls")
    pytest.importorskip("lsprotocol")
    from corvia.lsp.server import create_server

    server = create_server()
    assert server is not None


def test_argparse_defaults():
    from corvia.lsp.server import _build_parser

    args = _build_parser().parse_args([])
    assert args.tcp is False
    assert args.host == "127.0.0.1"
    assert args.port == 9999

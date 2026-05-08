"""Shared test fixtures for COVIA tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from covia.parser import CParser


@pytest.fixture
def fixtures_dir() -> Path:
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def parse_c():
    parser = CParser()

    def _parse(code: str, filename: str = "<test>"):
        return parser.parse_string(code, filename)

    return _parse

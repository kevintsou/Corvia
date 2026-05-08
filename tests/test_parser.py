"""Tests for the C parser wrapper."""

from corvia.parser import CParser


def test_parse_valid_string():
    parser = CParser()
    ast, errors = parser.parse_string("int main(void) { return 0; }")
    assert ast is not None
    assert errors == []


def test_parse_invalid_string():
    parser = CParser()
    ast, errors = parser.parse_string("int main( { return; }")
    assert ast is None
    assert len(errors) == 1
    assert errors[0].checker_id == "parser"


def test_parse_file(fixtures_dir):
    parser = CParser()
    ast, errors = parser.parse_file(str(fixtures_dir / "clean.c"))
    assert ast is not None
    assert errors == []


def test_parse_missing_file():
    parser = CParser()
    ast, errors = parser.parse_file("/nonexistent/file.c")
    assert ast is None
    assert len(errors) == 1
    assert "not found" in errors[0].message.lower()

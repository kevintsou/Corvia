"""C parser wrapper around pycparser."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from pycparser import CParser as _CParser
from pycparser import c_ast, parse_file

try:
    from pycparser.plyparser import ParseError  # pycparser < 3.0
except ImportError:
    from pycparser.c_parser import ParseError  # pycparser >= 3.0

from corvia.models import Issue, Severity


# Matches (in priority order): string literals, block comments, line comments.
# String literals are captured and re-emitted unchanged so we never strip
# content inside them.  Block comments are replaced with a single space to
# avoid accidentally joining adjacent tokens.  Line comments are replaced
# with a newline so line numbers stay correct for error reporting.
_COMMENT_RE = re.compile(
    r'"(?:[^"\\]|\\.)*"'       # double-quoted string literal
    r"|'(?:[^'\\]|\\.)*'"      # single-quoted char literal
    r"|/\*.*?\*/"              # /* block comment */
    r"|//[^\n]*",              # // line comment
    re.DOTALL,
)


def _strip_comments(code: str) -> str:
    """Remove C // and /* */ comments while preserving line numbers and
    leaving string/char literals untouched."""
    def _replace(m: re.Match) -> str:
        s = m.group(0)
        if s.startswith(("'", '"')):
            return s
        if s.startswith("/*"):
            # Preserve embedded newlines so line numbers stay correct.
            return "\n" * s.count("\n")
        # // comment: drop everything up to (but not including) the newline.
        return ""
    return _COMMENT_RE.sub(_replace, code)


def _fake_libc_dir() -> str:
    import pycparser
    return str(Path(pycparser.__file__).parent / "utils" / "fake_libc_include")


class CParser:
    def __init__(
        self,
        use_cpp: bool = False,
        cpp_path: str = "cpp",
        cpp_args: str = "",
        include_dirs: Optional[list[str]] = None,
    ) -> None:
        self._use_cpp = use_cpp
        self._cpp_path = cpp_path
        self._cpp_args = cpp_args
        self._include_dirs = include_dirs or []

    def _build_cpp_args(self) -> str:
        parts = [self._cpp_args] if self._cpp_args else []
        dirs = self._include_dirs + [_fake_libc_dir()]
        for d in dirs:
            parts.append(f"-I{d}")
        return " ".join(parts)

    def parse_file(self, filepath: str) -> tuple[Optional[c_ast.FileAST], list[Issue]]:
        def _make_error(msg: str) -> tuple[None, list[Issue]]:
            return None, [Issue(
                checker_id="parser",
                severity=Severity.ERROR,
                message=msg,
                file=filepath,
                line=0,
                column=0,
            )]

        if self._use_cpp:
            # Let pycparser invoke the C preprocessor directly.
            try:
                ast = parse_file(
                    filepath,
                    use_cpp=True,
                    cpp_path=self._cpp_path,
                    cpp_args=self._build_cpp_args(),
                )
                return ast, []
            except ParseError as e:
                return _make_error(str(e))
            except FileNotFoundError:
                return _make_error(f"File not found: {filepath}")
            except OSError as e:
                return _make_error(f"Cannot read file: {filepath}: {e}")

        # Without CPP: read the file ourselves so we control the encoding.
        # pycparser's parse_file opens files without specifying an encoding,
        # which fails on Windows when the file contains non-ASCII characters
        # (e.g. UTF-8 comments) and the system locale is CP950/GBK.
        try:
            code = Path(filepath).read_text(encoding="utf-8")
        except FileNotFoundError:
            return _make_error(f"File not found: {filepath}")
        except UnicodeDecodeError:
            # Fall back to latin-1 (byte-transparent) so the file is still
            # parseable even if it contains non-UTF-8 bytes.  C comments and
            # string literals with arbitrary bytes are valid C source.
            try:
                code = Path(filepath).read_text(encoding="latin-1")
            except OSError as e:
                return _make_error(f"Cannot read file: {filepath}: {e}")
        except OSError as e:
            return _make_error(f"Cannot read file: {filepath}: {e}")

        try:
            parser = _CParser()
            ast = parser.parse(_strip_comments(code), filename=filepath)
            return ast, []
        except ParseError as e:
            return _make_error(str(e))

    def parse_string(
        self, code: str, filename: str = "<string>"
    ) -> tuple[Optional[c_ast.FileAST], list[Issue]]:
        parser = _CParser()
        try:
            ast = parser.parse(_strip_comments(code), filename=filename)
            return ast, []
        except ParseError as e:
            issue = Issue(
                checker_id="parser",
                severity=Severity.ERROR,
                message=str(e),
                file=filename,
                line=0,
                column=0,
            )
            return None, [issue]

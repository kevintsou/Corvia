"""C parser wrapper around pycparser."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from pycparser import CParser as _CParser
from pycparser import c_ast, parse_file
from pycparser.plyparser import ParseError

from covia.models import Issue, Severity


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
        try:
            ast = parse_file(
                filepath,
                use_cpp=self._use_cpp,
                cpp_path=self._cpp_path,
                cpp_args=self._build_cpp_args() if self._use_cpp else "",
            )
            return ast, []
        except ParseError as e:
            issue = Issue(
                checker_id="parser",
                severity=Severity.ERROR,
                message=str(e),
                file=filepath,
                line=0,
                column=0,
            )
            return None, [issue]
        except FileNotFoundError:
            issue = Issue(
                checker_id="parser",
                severity=Severity.ERROR,
                message=f"File not found: {filepath}",
                file=filepath,
                line=0,
                column=0,
            )
            return None, [issue]

    def parse_string(
        self, code: str, filename: str = "<string>"
    ) -> tuple[Optional[c_ast.FileAST], list[Issue]]:
        parser = _CParser()
        try:
            ast = parser.parse(code, filename=filename)
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

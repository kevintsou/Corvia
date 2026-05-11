"""C parser wrapper around pycparser."""

from __future__ import annotations

import re
import shutil
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

# Matches preprocessor lines: #include, #define, #if, #endif, #else, #elif, #undef, #pragma, etc.
# Also matches multi-line macros (lines ending with \)
_PREPROC_RE = re.compile(
    r'^[ \t]*#[ \t]*(?:include|define|undef|pragma|if|elif|else|endif|warning|error)'
    r'[^\n]*\n',
    re.MULTILINE,
)

# Matches line continuation backslash before newline
_CONTINUATION_RE = re.compile(r'\\\n')


# Common typedef stubs to replace stripped macros/typedefs - no preprocessor directives
_COMMON_TYPE_STUBS = """
typedef unsigned char U8;
typedef unsigned short U16;
typedef unsigned int U32;
typedef unsigned long long U64;
typedef signed char S8;
typedef signed short S16;
typedef signed int S32;
typedef signed long long S64;
typedef unsigned char uint8_t;
typedef unsigned short uint16_t;
typedef unsigned int uint32_t;
typedef unsigned long long uint64_t;
typedef signed char int8_t;
typedef signed short int16_t;
typedef signed int int32_t;
typedef signed long long int64_t;
typedef unsigned char BOOL;
typedef unsigned char bool;
typedef int TRUE;
typedef int FALSE;
typedef void VOID;
typedef int INT;
typedef unsigned int UINT;
typedef char CHAR;
typedef unsigned char UCHAR;
typedef long LONG;
typedef unsigned long ULONG;
typedef short SHORT;
typedef unsigned short USHORT;
typedef unsigned long DWORD;
typedef unsigned short WORD;
typedef unsigned char BYTE;
typedef unsigned int HANDLE;
typedef void *PVOID;
typedef void *LPVOID;
typedef char *LPSTR;
typedef const char *LPCSTR;
typedef long off_t;
typedef unsigned int size_t;
static const int NULL_SIM = 0;
enum { PASS = 0, FAIL = 1 };
enum { TRUE_SIM = 1, FALSE_SIM = 0, ENABLE = 1, DISABLE = 0 };
enum { MAX_CH_NUM_SIM = 16 };
static const int MAX_CH_NUM = 16;
struct FW_SLOT { unsigned char data[128]; };
struct BootHeader_t { unsigned char data[256]; };
struct LaunchInfo_t { unsigned int section_index; unsigned int section_offset; unsigned int target_addr; unsigned int launch_size; };
struct CodeHeaderNew_t { unsigned char data[512]; };
struct ParallelReadStruct { unsigned char ubCH; unsigned char ubCE; unsigned int uwPage; unsigned char ubFrameCnt; unsigned int uwBlock; unsigned int ulBufBase; unsigned short uwColAdr; unsigned char ubStartFrame; };
struct L4KTable16B { unsigned char data[16]; };
struct CodeHeader_t { unsigned char data[256]; };
union L4KTableBitMap { unsigned int raw; struct { unsigned char Boot; unsigned char ubCodeMark; unsigned char ulLCA; unsigned char ubRevisionID; } BitMap; };
typedef U32 (*func_ptr_t)(void);
void *malloc(size_t n);
void free(void *p);
void *memcpy(void *dest, const void *src, size_t n);
void *memset(void *s, int c, size_t n);
int memcmp(const void *s1, const void *s2, size_t n);
"""

def _strip_preprocessor(code: str) -> str:
    """Remove preprocessor directives (#include, #define, #if, etc.) so pycparser can parse the file.
    Handles #if/#endif block pairs and single-line directives. Injects common type stubs."""
    code = _CONTINUATION_RE.sub("", code)
    lines = code.split('\n')
    result: list[str] = []
    depth = 0
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#if") or stripped.startswith("#elif") or stripped.startswith("#else"):
            result.append("")
            depth += 1
            continue
        if stripped.startswith("#endif"):
            result.append("")
            depth = max(0, depth - 1)
            continue
        if stripped.startswith("#") and depth == 0:
            result.append("")
            continue
        if depth > 0:
            result.append("")
        else:
            result.append(line)
    code = "\n".join(result)
    code = _COMMON_TYPE_STUBS + "\n" + code
    return code


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


def _try_fix_unknown_types(code: str) -> str | None:
    """Try to fix parse errors by auto-generating stubs for all unknown identifiers."""
    import re
    known = {
        'U8', 'U16', 'U32', 'U64', 'S8', 'S16', 'S32', 'S64',
        'uint8_t', 'uint16_t', 'uint32_t', 'uint64_t',
        'int8_t', 'int16_t', 'int32_t', 'int64_t',
        'BOOL', 'bool', 'TRUE', 'FALSE', 'VOID', 'INT', 'UINT',
        'CHAR', 'UCHAR', 'LONG', 'ULONG', 'SHORT', 'USHORT',
        'DWORD', 'WORD', 'BYTE', 'HANDLE', 'PVOID', 'LPVOID',
        'LPSTR', 'LPCSTR', 'size_t', 'off_t',
        'PASS', 'FAIL', 'ENABLE', 'DISABLE', 'MAX_CH_NUM',
        'NULL', 'TRUE_SIM', 'FALSE_SIM', 'NULL_SIM',
        'SECResult_e', 'SECResult_PASS', 'SECResult_FAIL',
        'BIT', 'BIT5', 'BIT6',
        'BOOT', 'BitMap', 'Boot',
        'FW_SLOT', 'BootHeader_t', 'LaunchInfo_t', 'CodeHeaderNew_t',
        'ParallelReadStruct', 'L4KTable16B', 'CodeHeader_t', 'L4KTableBitMap',
    }
    pattern = re.compile(r'\b([A-Z][A-Za-z0-9_]{1,})\b')
    found = set()
    for m in pattern.finditer(code):
        word = m.group(1)
        if word not in known and len(word) >= 2:
            found.add(word)

    if not found:
        return None

    stubs = "\n".join(f"typedef int {t};" for t in sorted(found))
    fixed_code = stubs + "\n" + code

    try:
        _CParser().parse(fixed_code)
        return fixed_code
    except ParseError:
        return None


def _fake_libc_dir() -> str:
    import pycparser
    return str(Path(pycparser.__file__).parent / "utils" / "fake_libc_include")


def _find_cpp() -> str:
    for name in ("cpp", "gcc", "clang", "cl"):
        path = shutil.which(name)
        if path:
            return path
    return "cpp"


class CParser:
    def __init__(
        self,
        use_cpp: bool = False,
        cpp_path: str | None = None,
        cpp_args: str = "",
        include_dirs: Optional[list[str]] = None,
        auto_install: bool = False,
    ) -> None:
        self._use_cpp = use_cpp
        self._cpp_path = cpp_path or _find_cpp()
        self._cpp_args = cpp_args
        self._include_dirs = include_dirs or []
        self._auto_install = auto_install

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
                if self._auto_install or self._use_cpp:
                    try:
                        from corvia.install import install_cpp
                        install_cpp()
                    except Exception:
                        pass
                return _make_error(
                    f"C preprocessor (cpp) not found. "
                    f"Install it with: pip install corvia[cpp] or run: corvia-install-cpp"
                )
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
            try:
                code = Path(filepath).read_text(encoding="latin-1")
            except OSError as e:
                return _make_error(f"Cannot read file: {filepath}: {e}")
        except OSError as e:
            return _make_error(f"Cannot read file: {filepath}: {e}")

        code = _strip_preprocessor(code)
        code = _strip_comments(code)

        try:
            parser = _CParser()
            ast = parser.parse(code, filename=filepath)
            return ast, []
        except ParseError as e:
            error_msg = str(e)
            if "before: *" in error_msg:
                fixed = _try_fix_unknown_types(code)
                if fixed:
                    parser2 = _CParser()
                    try:
                        ast = parser2.parse(fixed, filename=filepath)
                        return ast, []
                    except ParseError:
                        pass
                return _make_error(
                    f"Parse error (unknown type): {error_msg}\n"
                    f"Hint: Create a corvia.toml with [paths] include_dirs pointing to your header files, "
                    f"or use --use-cpp to enable the C preprocessor."
                )
            return _make_error(error_msg)

    def parse_string(
        self, code: str, filename: str = "<string>"
    ) -> tuple[Optional[c_ast.FileAST], list[Issue]]:
        code = _strip_preprocessor(code)
        code = _strip_comments(code)
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

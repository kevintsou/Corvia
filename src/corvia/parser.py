"""C parser wrapper around pycparser."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from subprocess import CalledProcessError
from typing import Optional

from pycparser import CParser as _CParser
from pycparser import c_ast, parse_file
from pycparser.c_ast import NodeVisitor

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
typedef int __gnuc_va_list;
typedef __gnuc_va_list va_list;
"""

_STUB_LINES = len(_COMMON_TYPE_STUBS.split('\n'))

# GCC extension keywords to strip from preprocessed output before pycparser parse
_GCC_KEYWORDS = [
    "__attribute__", "__attribute",
    "__inline__", "__inline",
    "__volatile__", "__volatile",
    "__const__", "__const",
    "__restrict__", "__restrict",
    "__extension__", "__extension",
    "__signed__", "__signed",
    "__asm__", "__asm",
    "__typeof__", "__typeof",
    "__noreturn__", "__noreturn",
    "__always_inline__",
    "__packed__",
    "__aligned__",
    "__section__",
    "__may_alias__",
    "__builtin_va_list",
    "__int64",
    "__int128",
    "__ptr32",
    "__ptr64",
    "__unaligned",
    "__w64",
    "__cdecl",
    "__stdcall",
    "__fastcall",
    "__thiscall",
    "__vectorcall",
    "__alignof__",
    "__alignof",
]
_GCC_KEYWORD_RE = re.compile(r'\b(' + '|'.join(re.escape(k) for k in _GCC_KEYWORDS) + r')\b')


def _strip_attributes(code: str) -> str:
    """Strip __attribute__((...)) constructs with proper bracket counting."""
    result: list[str] = []
    i = 0
    while i < len(code):
        m = re.search(r'\b__attribute__\s*\(\(', code[i:])
        if not m:
            result.append(code[i:])
            break
        result.append(code[i:i+m.start()])
        start = i + m.end()
        depth = 2
        j = start
        while j < len(code) and depth > 0:
            if code[j] == '(':
                depth += 1
            elif code[j] == ')':
                depth -= 1
            j += 1
        i = j
    return ''.join(result)


def _strip_preprocessor(code: str) -> str:
    """Remove preprocessor directives (#include, #define, #if, etc.) so pycparser can parse the file.
    Handles #if/#endif block pairs and single-line directives. Injects common type stubs.
    Also handles MSVC/ARM preprocessor output with binary artifacts by filtering garbage lines."""
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
            continue
        if len(stripped) > 10000:
            result.append("")
            continue
        result.append(line)
    code = "\n".join(result)
    code = re.sub(r'\b__builtin_va_list\b', 'int', code)
    code = _strip_attributes(code)
    code = _GCC_KEYWORD_RE.sub("", code)
    code = re.sub(r'\bregister\s+\w+(?:\s+\w+)*\s*\(\s*"[^"]*"\s*\)\s*=\s*[^;]+;', ';', code)
    code = re.sub(r'\s*\(\s*"[^"]*"\s*::[^;]*;', ';', code)
    code = re.sub(r'\b__builtin_unreachable\s*\(\s*\)', '', code)
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


def _build_line_map(text: str, target_file: str) -> list[tuple[int, str]]:
    """Build {line_in_text: (original_line, original_file)} mapping from # line markers.
    Interpolates line numbers between markers for accurate per-line mapping."""
    import re
    lines = text.split('\n')
    result = [(0, '')] * len(lines)
    cur_line = 0
    cur_file = ''
    last_marker_idx = -1
    last_marker_line = 0
    for i, line in enumerate(lines):
        m = re.match(r'#\s+(\d+)\s+"([^"]+)"', line)
        if m:
            cur_line = int(m.group(1))
            cur_file = m.group(2)
            last_marker_idx = i
            last_marker_line = cur_line
            result[i] = (0, '')
        elif cur_file and last_marker_idx >= 0:
            orig_line = last_marker_line + (i - last_marker_idx)
            result[i] = (orig_line, cur_file)
        else:
            result[i] = (cur_line, cur_file)
    return result


class _CoordRemapper(NodeVisitor):
    """Walk AST and remap all node coordinates using the line map."""

    def __init__(self, line_map: list[tuple[int, str]], target_file: str) -> None:
        self.line_map = line_map
        self.target_norm = Path(target_file).resolve()

    def generic_visit(self, node: c_ast.Node) -> None:
        if hasattr(node, 'coord') and node.coord is not None:
            coord = node.coord
            if coord.line is not None and 0 <= coord.line - 1 < len(self.line_map):
                orig_line, orig_file = self.line_map[coord.line - 1]
                if orig_file:
                    orig_path = Path(orig_file).resolve()
                    if orig_path == self.target_norm:
                        coord.line = orig_line
                    else:
                        coord.file = str(orig_path)
                        coord.line = orig_line
        super().generic_visit(node)


def _remap_ast(ast: c_ast.FileAST, line_map: list[tuple[int, str]], target_file: str) -> None:
    _CoordRemapper(line_map, target_file).visit(ast)


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
    import os
    return os.path.join(os.path.dirname(__file__), "utils", "fake_libc_include")


def _find_cpp() -> str:
    for name in ("cpp", "gcc", "clang", "cl"):
        path = shutil.which(name)
        if path:
            return path
    raise RuntimeError("No C preprocessor found (cpp/gcc/clang/cl). Install MinGW or LLVM.")


class CParser:
    def __init__(
        self,
        use_cpp: bool = False,
        cpp_path: str | None = None,
        cpp_args: str = "",
        cpp_defines: Optional[list[str]] = None,
        include_dirs: Optional[list[str]] = None,
        auto_install: bool = False,
    ) -> None:
        self._use_cpp = use_cpp
        self._cpp_path = cpp_path
        self._cpp_args = cpp_args
        self._cpp_defines = cpp_defines or []
        self._include_dirs = include_dirs or []
        self._auto_install = auto_install

    def _ensure_cpp_path(self) -> str:
        if self._cpp_path is None:
            self._cpp_path = _find_cpp()
        return self._cpp_path

    def _preprocess_file(self, filename: str, cpp_args_list: list[str]) -> tuple[str, str]:
        """Preprocess a file and capture both stdout and stderr."""
        import subprocess as sub
        cpp_path = self._ensure_cpp_path()
        path_list = [cpp_path] + cpp_args_list + [filename]

        try:
            proc = sub.Popen(
                path_list,
                stdout=sub.PIPE,
                stderr=sub.PIPE,
                text=True,
            )
            stdout, stderr = proc.communicate()
            if proc.returncode != 0:
                raise sub.CalledProcessError(proc.returncode, path_list, stdout, stderr)
            return stdout, ""
        except OSError as e:
            raise RuntimeError(
                f"Unable to invoke '{cpp_path}'. "
                f"Make sure its path was passed correctly. Original error: {e}"
            )

    def _preprocess_file_safe(self, filename: str, cpp_args_list: list[str]) -> tuple[str, str, int]:
        """Preprocess a file and capture stdout/stderr regardless of return code."""
        import subprocess as sub
        cpp_path = self._ensure_cpp_path()
        path_list = [cpp_path] + cpp_args_list + [filename]
        try:
            proc = sub.Popen(
                path_list,
                stdout=sub.PIPE,
                stderr=sub.PIPE,
                text=True,
                shell=False,
            )
            stdout, stderr = proc.communicate()
            return stdout, stderr, proc.returncode
        except OSError as e:
            raise RuntimeError(
                f"Unable to invoke '{cpp_path}'. "
                f"Make sure its path was passed correctly. Original error: {e}"
            )

    def _build_cpp_args(self) -> list[str]:
        parts: list[str] = ["-E"]
        if self._cpp_args:
            if isinstance(self._cpp_args, list):
                parts.extend(self._cpp_args)
            else:
                parts.extend(self._cpp_args.split())
        for d in self._cpp_defines:
            parts.append(f"-D{d}")
        dirs = self._include_dirs + [_fake_libc_dir()]
        for d in dirs:
            parts.append(f"-I{d}")
        return parts

    def _parse_cpp_errors(self, stderr: str, filepath: str) -> list[Issue]:
        issues: list[Issue] = []
        lines = stderr.split('\n')
        for line in lines:
            line = line.strip()
            if not line:
                continue
            if ': error:' not in line.lower() and ': fatal error:' not in line.lower() and ': warning:' not in line.lower():
                continue
            parts = line.split(':')
            if len(parts) < 3:
                continue
            try:
                path_part = parts[0].strip()
                rest_idx = 1
                if len(parts) > 3 and parts[1].strip().isdigit() and parts[2].strip().isdigit():
                    path_part = parts[0] + ":" + parts[1]
                    rest_idx = 2
                elif len(parts) > 2 and not parts[1].strip().isdigit():
                    if parts[2].strip().isdigit():
                        path_part = parts[0] + ":" + parts[1]
                        rest_idx = 2
                    elif len(parts) > 3 and parts[3].strip().isdigit():
                        path_part = parts[0] + ":" + parts[1] + ":" + parts[2]
                        rest_idx = 3
                linenum_str = parts[rest_idx].strip()
                if not linenum_str.isdigit():
                    continue
                linenum = int(linenum_str)
                sev = Severity.ERROR if 'error' in line.lower() else Severity.WARNING
                msg = ' '.join(parts[rest_idx + 2:]).strip()
                issues.append(Issue(
                    checker_id="parser",
                    severity=sev,
                    message=msg,
                    file=filepath if not path_part or '\\' not in path_part and '/' not in path_part else path_part,
                    line=linenum,
                    column=0,
                ))
            except (ValueError, IndexError):
                pass
        return issues[:50]

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
            cpp_args_list = self._build_cpp_args()
            try:
                text, stderr, returncode = self._preprocess_file_safe(filepath, cpp_args_list)
            except (OSError, RuntimeError) as e:
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

            if not text:
                combined = stderr.strip() if stderr else f"C preprocessor error (exit code {returncode})"
                issues = self._parse_cpp_errors(combined, filepath)
                if issues:
                    return None, issues
                first_line = combined.split('\n')[0] if combined else f"C preprocessor error (exit code {returncode})"
                return _make_error(first_line)

            try:
                line_map = _build_line_map(text, filepath)
                parser = _CParser()
                ast = parser.parse(text, filename=filepath)
                _remap_ast(ast, line_map, filepath, 'direct')
                return ast, []
            except ParseError as e:
                error_msg = str(e)
                if text and len(text) > 100:
                    fallback_text = _strip_preprocessor(text)
                    fallback_text = _strip_comments(fallback_text)
                    # Build a line map from the fallback text by re-parsing its # markers
                    fb_line_map = _build_line_map(text, filepath)
                    # Extend with stub entries - compute actual offset from line count difference
                    stub_lines = fallback_text.count('\n') - text.count('\n')
                    if stub_lines > 0:
                        fb_line_map = [(0, '')] * stub_lines + fb_line_map
                    fb_line_map = fb_line_map[:fallback_text.count('\n') + 1]
                    try:
                        fallback_parser = _CParser()
                        fallback_ast = fallback_parser.parse(fallback_text, filename=filepath)
                        _remap_ast(fallback_ast, fb_line_map, filepath)
                        return fallback_ast, []
                    except ParseError:
                        pass
                if text:
                    return None, [Issue(
                        checker_id="parser",
                        severity=Severity.ERROR,
                        message=f"Preprocessed output parse error: {error_msg}",
                        file=filepath,
                        line=0,
                        column=0,
                    )]
                combined = stderr.strip() if stderr else f"Preprocessing failed (exit code {returncode})"
                issues = self._parse_cpp_errors(combined, filepath)
                if issues:
                    return None, issues
                return _make_error(combined.split('\n')[0] if combined else f"Preprocessing failed (exit code {returncode})")

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

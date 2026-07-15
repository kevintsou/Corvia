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
enum { TRUE = 1, FALSE = 0 };
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

_STUB_TYPEDEF_RE = re.compile(r'\btypedef\b[^;()\[\]]*\b(\w+)\s*;')
_STUB_TYPEDEF_NAMES: frozenset[str] = frozenset(
    m.group(1) for m in _STUB_TYPEDEF_RE.finditer(_COMMON_TYPE_STUBS)
)

# Two patterns used by _strip_gcc_calls:
#   _ASM_CALL_KW_RE  — __asm__ / __asm statements (strip entirely)
#   _BUILTIN_CALL_KW_RE — __builtin_XXX() expressions (replace with 0)
_ASM_CALL_KW_RE = re.compile(
    r'\b(?:__asm__|__asm)\s*(?:__volatile__\s*|__volatile\s*|volatile\s*)?(?:goto\s*)?\('
)
_BUILTIN_CALL_KW_RE = re.compile(r'\b__builtin_\w+\s*\(')

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

# `__builtin_va_list` is a TYPE, not a decoration: deleting it leaves
# declarations like `int vprintf(const char *fmt,  args);` (cpp expands
# `va_list args` to `__builtin_va_list args`). Substitute a stand-in type.
_BUILTIN_VA_LIST_RE = re.compile(r'\b__builtin_va_list\b')


def _strip_attributes(code: str) -> str:
    """Strip __attribute__((...)) constructs with proper bracket counting.

    Newlines inside the removed span are re-emitted so line numbering stays
    stable for everything that follows.
    """
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
        result.append("\n" * code[i + m.start():j].count("\n"))
        i = j
    return ''.join(result)


# GNU range designator in initializers: `[0 ... N-1] = value`. pycparser has
# no support for it; dropping the designator leaves a plain (positional)
# initializer, which is good enough for static analysis of the values.
_RANGE_DESIGNATOR_RE = re.compile(r'\[[^\[\]\n]*?\.\.\.[^\[\]\n]*?\]\s*=')


def _strip_gnu_extensions_for_strict(text: str) -> str:
    """Make gcc-preprocessed output parseable by pycparser in the strict path.

    TF-A-style trees ship their own libc headers, so constructs like
    `__attribute__((__format__(__printf__, 1, 2)))` and GNU range designators
    survive preprocessing and abort the strict parse (losing marker-accurate
    coordinates to the stub fallback). All transformations preserve line
    numbering; preprocessor line markers are left untouched.
    """
    text = _strip_attributes(text)
    text = _strip_gcc_calls(text)
    text = _BUILTIN_VA_LIST_RE.sub("int", text)
    text = _GCC_KEYWORD_RE.sub("", text)
    return _RANGE_DESIGNATOR_RE.sub("", text)


def _strip_gcc_calls(code: str) -> str:
    """Strip __asm__/__asm calls and replace __builtin_XXX() calls with 0.

    Uses depth-counting (O(n)) to handle arbitrary nesting depth without the
    catastrophic backtracking that regex paren-matching suffers on code like
    __asm volatile("..." :: "r" ((T)(a | ((T)b << 16) | (((T)c << 24))))).

    __asm__ / __asm are stripped, but their OUTPUT operands are recovered: an
    extended-asm output like `: "=r" (id)` writes through `id`, so the strip
    synthesizes an assignment (`id = 0;`) in its place. Without this, a
    variable only ever written by inline asm looks uninitialized to the
    dataflow checkers (false "used before initialization"). Plain `__asm(...)`
    with no outputs is removed entirely (it is a statement).
    __builtin_XXX() are replaced with 0 (they are expressions — removing
    them would leave 'x = ;' which is a syntax error).
    """
    # Merge both match streams ordered by position.
    asm_matches = [('asm', m) for m in _ASM_CALL_KW_RE.finditer(code)]
    bi_matches = [('builtin', m) for m in _BUILTIN_CALL_KW_RE.finditer(code)]
    events = sorted(asm_matches + bi_matches, key=lambda e: e[1].start())

    result: list[str] = []
    pos = 0
    for kind, m in events:
        if m.start() < pos:
            continue  # already consumed by a previous (outer) match
        result.append(code[pos:m.start()])
        depth = 1
        body_start = m.end()  # right after the opening '('
        i = body_start
        while i < len(code) and depth > 0:
            c = code[i]
            if c in ('"', "'"):
                q = c
                i += 1
                while i < len(code):
                    if code[i] == '\\':
                        i += 2
                        continue
                    if code[i] == q:
                        i += 1
                        break
                    i += 1
                continue
            if c == '(':
                depth += 1
            elif c == ')':
                depth -= 1
            i += 1
        span_newlines = "\n" * code[m.start():i].count("\n")
        if kind == 'builtin':
            pos = i  # skip past the matching closing ')'
            name = code[m.start():m.end()].rstrip(' \t(').strip()
            if name in ('__builtin_va_start', '__builtin_va_copy'):
                # These builtins WRITE their first argument (the va_list being
                # started/copied). Replacing them with a bare '0' silently
                # drops that write, making a correctly va_start-ed va_list look
                # uninitialized downstream. Synthesize `((arg) = 0)` instead -
                # still a valid expression where the call appeared, and the
                # dataflow sees the initialization.
                body = code[body_start:i - 1]
                first_arg = _first_call_arg(body)
                if first_arg:
                    result.append(f'(({first_arg}) = 0)')
                else:
                    result.append('0')
            else:
                result.append('0')  # keep as a valid expression placeholder
        else:
            # 'asm': recover output-operand writes before dropping the statement.
            body = code[body_start:i - 1]  # inside the outer parens
            result.append(_asm_output_writes(body))
            # An asm statement ends with ';'; consume it so we don't leave a
            # stray ';' that turns the synthesized writes into a null statement.
            j = i
            while j < len(code) and code[j] in ' \t\r\n':
                j += 1
            if j < len(code) and code[j] == ';':
                j += 1
            span_newlines = "\n" * code[m.start():j].count("\n")
            pos = j
        # Re-emit the newlines swallowed with the removed span so line
        # numbering stays stable for everything after it.
        result.append(span_newlines)
    result.append(code[pos:])
    return ''.join(result)


def _first_call_arg(body: str) -> str:
    """Return the first top-level comma-separated argument of a call body."""
    depth = 0
    for idx, ch in enumerate(body):
        if ch in '([{':
            depth += 1
        elif ch in ')]}':
            depth -= 1
        elif ch == ',' and depth == 0:
            return body[:idx].strip()
    return body.strip()


# An extended-asm output operand: optional [symbolic name], a quoted constraint
# string containing '=' (write-only) or '+' (read-write), then a parenthesized
# lvalue expression. We synthesize `<lvalue> = <lvalue>;` for each so the
# dataflow checkers see the variable as written by the asm.
_ASM_OUTPUT_RE = re.compile(
    r'(?:\[\s*\w+\s*\]\s*)?"[^"]*[=+][^"]*"\s*\('
)


def _asm_output_writes(body: str) -> str:
    """Given the text inside an extended-asm `(...)`, return synthesized C
    assignment statements for each output operand's lvalue.

    Extended asm is `template : outputs : inputs : clobbers`. Only the first
    colon-section holds outputs, and only constraints containing '=' or '+'
    denote a write. Anything we cannot confidently parse yields no statement
    (safe: worst case reverts to the original strip-entirely behaviour)."""
    # Split off the template string literal, then take the first ':' section.
    # Find the end of the (possibly concatenated) template string(s).
    i = 0
    n = len(body)
    # Skip whitespace and a leading 'volatile'/'goto' already consumed by the
    # keyword regex, so body starts at the template. Walk to the first top-level
    # ':' that is not inside a string.
    depth = 0
    section_start = 0
    section_idx = 0
    outputs = ""
    while i < n:
        c = body[i]
        if c in ('"', "'"):
            q = c
            i += 1
            while i < n:
                if body[i] == '\\':
                    i += 2
                    continue
                if body[i] == q:
                    i += 1
                    break
                i += 1
            continue
        if c in '([{':
            depth += 1
        elif c in ')]}':
            depth -= 1
        elif c == ':' and depth == 0:
            if section_idx == 1:  # end of the outputs section
                outputs = body[section_start:i]
                break
            section_idx += 1
            section_start = i + 1
        i += 1
    else:
        # No further ':' after the outputs section (outputs run to end), or no
        # colon at all (no outputs).
        if section_idx == 1:
            outputs = body[section_start:]

    if not outputs.strip():
        return ""

    writes: list[str] = []
    for m in _ASM_OUTPUT_RE.finditer(outputs):
        # Capture the balanced parenthesized lvalue following the constraint.
        start = m.end()  # just after '('
        d = 1
        k = start
        while k < len(outputs) and d > 0:
            ch = outputs[k]
            if ch == '(':
                d += 1
            elif ch == ')':
                d -= 1
            k += 1
        lvalue = outputs[start:k - 1].strip()
        if lvalue:
            # Assign a constant, not `lvalue = lvalue`, so the synthesized write
            # does not itself read the (as-yet-uninitialized) output operand.
            writes.append(f"({lvalue}) = 0;")
    return " ".join(writes)


def _dedup_stub_typedefs(code: str) -> str:
    """Blank out typedef lines whose alias is already in _COMMON_TYPE_STUBS.

    Prevents pycparser duplicate-typedef errors when preprocessed system headers
    (e.g. ARM stddef.h) redefine types like size_t that _COMMON_TYPE_STUBS declares.
    """
    def _replace(m: re.Match) -> str:
        if m.group(1) in _STUB_TYPEDEF_NAMES:
            return '\n' * m.group(0).count('\n')
        return m.group(0)
    return _STUB_TYPEDEF_RE.sub(_replace, code)


def _strip_preprocessor(code: str, keep_conditional_bodies: bool = False) -> str:
    """Remove preprocessor directives (#include, #define, #if, etc.) so pycparser can parse the file.
    Handles #if/#endif block pairs and single-line directives. Injects common type stubs.
    Also handles MSVC/ARM preprocessor output with binary artifacts by filtering garbage lines.

    Line counts are preserved: every removed line is replaced by an empty
    line, and line-continuation backslashes are stripped in place (the
    newline is kept) so downstream line maps stay accurate."""
    lines = code.split('\n')
    result: list[str] = []
    depth = 0
    in_directive_continuation = False
    for line in lines:
        stripped = line.strip()
        if in_directive_continuation:
            # Continuation line of a multi-line preprocessor directive
            # (e.g. a #define whose body spans several lines): blank it,
            # keeping the newline so line numbering is stable.
            result.append("")
            in_directive_continuation = stripped.endswith("\\")
            continue
        if stripped.startswith("#"):
            in_directive_continuation = stripped.endswith("\\")
        if keep_conditional_bodies and stripped.startswith("#"):
            result.append("")
            continue
        # Only #if / #ifdef / #ifndef open a conditional block; #elif and
        # #else are alternatives *within* the current block and must not
        # increase the nesting depth (otherwise the matching #endif leaves
        # depth > 0 and every subsequent line gets blanked).
        if stripped.startswith("#if"):
            result.append("")
            depth += 1
            continue
        if stripped.startswith("#elif") or stripped.startswith("#else"):
            result.append("")
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
        if stripped.endswith("\\"):
            # Ordinary code line continuation: drop the backslash but keep
            # the line break (C is whitespace-insensitive outside strings),
            # so the total line count does not change.
            idx = line.rfind("\\")
            line = line[:idx] + line[idx + 1:]
        result.append(line)
    code = "\n".join(result)
    code = re.sub(r'\b__builtin_va_list\b', 'int', code)
    code = _strip_attributes(code)
    # Strip __asm__/__asm/__builtin_XXX(...) using depth-counting (no backtracking).
    code = _strip_gcc_calls(code)
    code = _BUILTIN_VA_LIST_RE.sub("int", code)
    code = _GCC_KEYWORD_RE.sub("", code)
    # GNU range designators (`[0 ... N-1] = v`) are not parseable by pycparser.
    code = _RANGE_DESIGNATOR_RE.sub("", code)
    code = re.sub(r'\bregister\s+\w+(?:\s+\w+)*\s*\(\s*"[^"]*"\s*\)\s*=\s*[^;]+;', ';', code)
    code = re.sub(r'\s*\(\s*"[^"]*"\s*::[^;]*;', ';', code)
    code = _dedup_stub_typedefs(code)
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
        # GCC/Clang emit '# N "file"'; MSVC cl emits '#line N "file"'.
        m = re.match(r'#\s*(?:line\s+)?(\d+)\s+"([^"]+)"', line)
        if m:
            cur_line = int(m.group(1))
            cur_file = m.group(2)
            last_marker_idx = i
            last_marker_line = cur_line
            result[i] = (0, '')
        elif cur_file and last_marker_idx >= 0:
            # A "# N \"file\"" marker means the *next* line is line N.
            orig_line = last_marker_line + (i - last_marker_idx) - 1
            result[i] = (orig_line, cur_file)
        else:
            result[i] = (cur_line, cur_file)
    return result


class _CoordRemapper(NodeVisitor):
    """Walk AST and remap all node coordinates using the line map.

    pycparser AST nodes frequently SHARE a single Coord object (e.g. an
    ArrayRef and its subscript). Since remapping mutates the Coord in place,
    each unique Coord must be remapped exactly once — remapping a shared
    Coord once per referencing node would apply the offset repeatedly and
    scatter issues onto unrelated lines/files.
    """

    def __init__(self, line_map: list[tuple[int, str]], target_file: str) -> None:
        self.line_map = line_map
        self.target_norm = Path(target_file).resolve()
        self._remapped: set[int] = set()

    def generic_visit(self, node: c_ast.Node) -> None:
        if hasattr(node, 'coord') and node.coord is not None:
            coord = node.coord
            if id(coord) in self._remapped:
                pass
            elif coord.line is not None and 0 <= coord.line - 1 < len(self.line_map):
                self._remapped.add(id(coord))
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


# Sentinel "file" for coordinates inside the injected type-stub preamble.
# Symbols declared there (NULL_SIM, L4KTableBitMap, ...) are analysis
# scaffolding, not user code: attributing them to the parsed .c file produced
# issues on out-of-range lines. With this sentinel the engine's source-file
# filter drops such issues naturally.
STUB_SENTINEL_FILE = "__corvia_type_stubs__"


def _stub_offset_line_map(parsed_text: str, offset: int, target_file: str) -> list[tuple[int, str]]:
    """Line map for text whose first `offset` lines are synthetic stub preamble.

    Stub lines map to STUB_SENTINEL_FILE so issues raised on stub symbols are
    attributed to the (filtered-out) sentinel, never to the user's file; every
    following line maps back to its position in the original source file.
    """
    total = parsed_text.count('\n') + 1
    stub_count = min(offset, total)
    line_map: list[tuple[int, str]] = [
        (i, STUB_SENTINEL_FILE) for i in range(1, stub_count + 1)
    ]
    line_map.extend((i, target_file) for i in range(1, total - stub_count + 1))
    return line_map


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
    # Everything the injected stub preamble already declares (typedef names,
    # enum constants, struct tags, libc prototypes) must never be re-stubbed:
    # the code being fixed usually embeds that preamble. Deriving the set
    # from the stubs keeps it in sync automatically.
    known |= set(re.findall(r'[A-Za-z_]\w+', _COMMON_TYPE_STUBS))
    # Names already typedef'd in the code itself must not be re-stubbed
    # (duplicate typedefs abort the parse). Both plain `typedef ... name;`
    # and struct-typedef closers `} name;` are collected; over-matching the
    # latter is harmless (it only skips a stub).
    defined = set(re.findall(r'typedef\b[^;{]*?\b(\w+)\s*;', code))
    defined |= set(re.findall(r'\}\s*(\w+)\s*;', code))

    patterns = (
        # CamelCase-style type names. Requires at least one lowercase letter:
        # ALL_CAPS identifiers are almost always macros, enum constants, or
        # linker symbols (BL_CODE_BASE, ...) — stubbing those as typedefs
        # conflicts with their real use and aborts the whole repair.
        re.compile(r'\b([A-Z][A-Z0-9_]*[a-z][A-Za-z0-9_]*)\b'),
        # POSIX/TF-A style lowercase `_t` types (cpu_context_t, ...): these
        # go undefined when their definition sits behind a compiled-out
        # conditional (e.g. ENABLE_SME_FOR_NS).
        re.compile(r'\b([a-z_][A-Za-z0-9_]*_t)\b'),
    )
    found = set()
    for pattern in patterns:
        for m in pattern.finditer(code):
            word = m.group(1)
            if word not in known and word not in defined and len(word) >= 2:
                found.add(word)

    if not found:
        return None

    # A candidate may actually be a variable/function/enum-constant, in which
    # case its `typedef int X;` stub conflicts. The parse error names the
    # offending token ("before: X"): drop it and retry a few times instead of
    # giving up on the first conflict.
    for _ in range(6):
        if not found:
            return None
        stubs = "\n".join(f"typedef int {t};" for t in sorted(found))
        fixed_code = stubs + "\n" + code
        try:
            _CParser().parse(fixed_code)
            return fixed_code
        except ParseError as e:
            msg = str(e)
            # Conflicts surface in several message shapes:
            #   "... before: X"                     (syntax clash at X)
            #   "Non-typedef 'X' previously declared as typedef ..."
            #   "Typedef 'X' previously declared as non-typedef ..."
            m = re.search(r'before: (\w+)', msg) or re.search(r"'(\w+)'", msg)
            if m and m.group(1) in found:
                found.discard(m.group(1))
            else:
                return None
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
        keep_conditional_bodies: bool = False,
    ) -> None:
        self._use_cpp = use_cpp
        self._cpp_path = cpp_path
        self._cpp_args = cpp_args
        self._cpp_defines = cpp_defines or []
        self._include_dirs = include_dirs or []
        self._auto_install = auto_install
        self._keep_conditional_bodies = keep_conditional_bodies

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
                encoding="utf-8",
                errors="replace",
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
                encoding="utf-8",
                errors="replace",
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
            except (OSError, RuntimeError):
                # No usable preprocessor: try to install one, then retry the
                # preprocessing once if the installation succeeded.
                installed = False
                try:
                    from corvia.install import install_cpp
                    installed = install_cpp() == 0
                except Exception:
                    installed = False
                text = None
                if installed:
                    self._cpp_path = None  # re-discover the freshly installed cpp
                    try:
                        text, stderr, returncode = self._preprocess_file_safe(
                            filepath, cpp_args_list
                        )
                    except (OSError, RuntimeError):
                        text = None
                if text is None:
                    return _make_error(
                        f"C preprocessor (cpp) not found. "
                        f"Install gcc/clang, or on Windows run: corvia-install-cpp"
                    )

            if returncode != 0:
                combined = stderr.strip() if stderr else f"C preprocessor error (exit code {returncode})"
                issues = self._parse_cpp_errors(combined, filepath)
                if issues:
                    return None, issues
                first_line = combined.split('\n')[0] if combined else f"C preprocessor error (exit code {returncode})"
                return _make_error(first_line)

            if not text:
                combined = stderr.strip() if stderr else f"C preprocessor error (exit code {returncode})"
                issues = self._parse_cpp_errors(combined, filepath)
                if issues:
                    return None, issues
                first_line = combined.split('\n')[0] if combined else f"C preprocessor error (exit code {returncode})"
                return _make_error(first_line)

            try:
                parser = _CParser()
                # gcc-isms that survive preprocessing (TF-A-style projects
                # ship their own libc headers with __attribute__ decorations,
                # GNU range designators, inline asm) abort pycparser; strip
                # them line-stably so the strict, marker-accurate parse
                # succeeds instead of degrading to the stub fallback.
                #
                # No _remap_ast here: pycparser consumes the preprocessor's
                # `# N "file"` line markers natively, so coordinates already
                # carry the original file/line. Remapping again would index
                # source line numbers into the preprocessed-text line map —
                # a double mapping that corrupted coordinates whenever the
                # source line number happened to fall within the map.
                ast = parser.parse(
                    _strip_gnu_extensions_for_strict(text), filename=filepath
                )
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
                        # Attribute the injected stub preamble to the sentinel
                        # file (not left as unmapped (0, '')): issues on stub
                        # symbols must never land in the user's file.
                        fb_line_map = [
                            (i, STUB_SENTINEL_FILE) for i in range(1, stub_lines + 1)
                        ] + fb_line_map
                    fb_line_map = fb_line_map[:fallback_text.count('\n') + 1]
                    try:
                        fallback_parser = _CParser()
                        fallback_ast = fallback_parser.parse(fallback_text, filename=filepath)
                        _remap_ast(fallback_ast, fb_line_map, filepath)
                        return fallback_ast, []
                    except ParseError as fb_err:
                        # Unknown-typedef failures (e.g. a type whose
                        # definition sits behind a compiled-out conditional)
                        # get one more chance with auto-generated type stubs,
                        # mirroring the non-cpp path's retry.
                        if "before: *" in str(fb_err):
                            fixed = _try_fix_unknown_types(fallback_text)
                            if fixed:
                                try:
                                    fixed_ast = _CParser().parse(
                                        fixed, filename=filepath
                                    )
                                    extra = (
                                        fixed.count('\n')
                                        - fallback_text.count('\n')
                                    )
                                    fixed_map = [
                                        (i, STUB_SENTINEL_FILE)
                                        for i in range(1, extra + 1)
                                    ] + fb_line_map
                                    fixed_map = fixed_map[:fixed.count('\n') + 1]
                                    _remap_ast(fixed_ast, fixed_map, filepath)
                                    return fixed_ast, []
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

        code = _strip_preprocessor(
            code, keep_conditional_bodies=self._keep_conditional_bodies
        )
        code = _strip_comments(code)

        try:
            parser = _CParser()
            ast = parser.parse(code, filename=filepath)
            # _strip_preprocessor prepended _COMMON_TYPE_STUBS — map lines back.
            _remap_ast(ast, _stub_offset_line_map(code, _STUB_LINES, filepath), filepath)
            return ast, []
        except ParseError as e:
            error_msg = str(e)
            if "before: *" in error_msg:
                fixed = _try_fix_unknown_types(code)
                if fixed:
                    parser2 = _CParser()
                    try:
                        ast = parser2.parse(fixed, filename=filepath)
                        # _try_fix_unknown_types prepends extra typedef stub
                        # lines on top of the _COMMON_TYPE_STUBS preamble.
                        extra = fixed.count('\n') - code.count('\n')
                        _remap_ast(
                            ast,
                            _stub_offset_line_map(fixed, _STUB_LINES + extra, filepath),
                            filepath,
                        )
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
            _remap_ast(ast, _stub_offset_line_map(code, _STUB_LINES, filename), filename)
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

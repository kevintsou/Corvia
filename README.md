# Corvia — C Static Analyzer with MISRA C:2012 Support

> 🌐 [English](#english) | [中文](#中文)

---

<a name="english"></a>

# English

Corvia is a Python-based static analysis tool for C code, inspired by Coverity. It detects bugs, undefined behaviour, and MISRA C:2012 rule violations using AST-level checks, CFG-based dataflow, and **inter-procedural / cross-file analysis** (Phase 3).

---

## Features

- **115+ MISRA C:2012 rules** covered across 20 sections
- **Inter-procedural analysis** — function summaries flow across files so wrappers (`xalloc`, `xopen`, `xfree`) are recognized as allocators / openers / closers
- **CFG-based dataflow analysis** for null dereference, uninitialized variables, memory and resource leaks
- **Symbol table + call graph** — detects indirect recursion, cross-file identifier collisions (5.1, 5.7, 5.8, 5.9), and unused non-void return values (17.7)
- **Incremental analysis** — content-hash cache + reverse-dependency invalidation; only re-analyze files that actually changed
- **LSP server** (`corvia-lsp`) — drop-in for any LSP-capable editor (VS Code, Neovim, Emacs, …)
- **Multiple output formats**: plain text (with color), JSON, HTML, Markdown
- **Extensible checker architecture** — drop in custom checkers via `--external-checkers`
- **MISRA filtering** — `--misra-only`, `--misra-category mandatory|required|advisory`

---

## Installation

**Requirements**: Python 3.9+

```bash
git clone https://github.com/kevintsou/Corvia.git
cd Corvia
pip install -e ".[dev]"          # base + dev tools
pip install -e ".[dev,lsp]"      # also install LSP server
```

---

## Usage

```bash
# Analyze a file or directory
corvia path/to/file.c
corvia src/

# Choose output format
corvia src/ --format json
corvia src/ --format html -o report.html
corvia src/ --format md   -o report.md

# Filter by severity
corvia src/ --severity warning

# Show only MISRA violations
corvia src/ --misra-only
corvia src/ --misra-only --misra-category required

# Enable specific checkers only
corvia src/ --checkers null-deref,memory-leak

# List all available checkers
corvia --list-checkers

# Use C preprocessor (for macro-heavy code)
corvia src/ --use-cpp -I/usr/include

# Load external custom checkers
corvia src/ --external-checkers ./custom_checkers/

# Incremental analysis (cache results between runs)
corvia src/ --incremental
corvia src/ --incremental --cache-dir .my_cache
corvia --clean-cache

# Run the LSP server
corvia-lsp --stdio
corvia-lsp --tcp --host 127.0.0.1 --port 9999
```

### Configuration (`corvia.toml`)

Place a `corvia.toml` in the project root (auto-discovered by walking
upward) to set defaults for the whole project. CLI flags always take
precedence.

```toml
[checkers]
enabled  = ["null-deref", "memory-leak"]   # if set, only these run
disabled = ["misra-unions"]                # subtracted from enabled

[severity]
"misra-stdlib" = "error"     # bump every misra-stdlib finding to error
"21.3"         = "info"      # demote rule 21.3 to info
"19.2"         = "off"       # silence rule 19.2 entirely

[paths]
include = ["/usr/local/include"]
use_cpp = true

[output]
format   = "text"                  # text / json / md / html
no_color = false

[cache]
enabled = true
dir     = ".corvia_cache"
```

Pass `--config <path>` to override discovery, or `--no-config` to
ignore the file entirely.

### Sample Output

```
test.c:12:5: error[null-deref] (MISRA C:2012 Rule 1.3 Required): Dereference of NULL pointer 'p'
test.c:20:3: warning[uninit-var] (MISRA C:2012 Rule 9.1 Required): Variable 'x' may be used uninitialized
test.c:35:1: error[memory-leak] (MISRA C:2012 Rule 22.1 Required): Memory allocated to 'buf' is never freed

Summary: 3 issues (2 errors, 1 warning, 0 info) in 1 file
MISRA rules violated: 3
```

---

## Checkers

| Checker ID | Description | MISRA Rules |
|---|---|---|
| `syntax` | Assignment in condition, missing braces | 13.4, 15.6 |
| `unused-vars` | Unused variables, tags, parameters | 2.2, 2.3, 2.7 |
| `uninit-var` | Uninitialized variable reads (CFG-based) | 9.1 |
| `dead-code` | Unreachable code, always-true/false conditions | 2.1, 14.3 |
| `null-deref` | NULL pointer dereference via `*`, `->`, `[]` (CFG + summaries) | 1.3 |
| `buffer-overflow` | Array index out of bounds | 1.3, 18.1 |
| `memory-leak` | malloc/calloc/realloc without free (CFG + summaries) | 22.1, 22.2 |
| `resource-leak` | fopen/popen without fclose, use-after-close (CFG + summaries) | 22.1, 22.6 |
| `misra-types` | Implicit/narrowing conversions, sign mixing | 10.1–10.8 |
| `misra-decl` | Missing types, extern misuse, static/inline rules | 8.1–8.14 |
| `misra-expr` | Operator precedence, side effects, comma operator | 12.1–12.5, 13.1–13.6 |
| `misra-control` | goto, switch, if-else completeness rules | 14.1–14.4, 15.1–15.7 |
| `misra-func` | stdarg prohibition, indirect recursion, unused return values | 17.1–17.8 |
| `misra-pointer` | Pointer arithmetic, array decay, function pointers | 18.1–18.8 |
| `misra-preproc` | Macro restrictions, `#include` ordering (AST-detectable) | 20.7, 20.10–20.12, 20.14 |
| **`misra-identifiers`** | External / typedef / tag / linkage uniqueness, scope shadowing | 5.1, 5.3, 5.6–5.9 |
| **`misra-pointer-conv`** | Function-pointer / object-pointer / void-pointer / qualifier casts | 11.1–11.9 |
| **`misra-stdlib`** | Forbidden Standard Library usage, reserved identifiers | 21.1–21.10, 21.12 |
| **`misra-bitfields`** | Bit-field type restrictions, signed single-bit detection | 6.1, 6.2 |
| **`misra-literals`** | Octal constants, lowercase suffix, string-to-non-const | 7.1, 7.3, 7.4 |
| **`misra-switch`** | Switch well-formedness, default presence/position, missing break, boolean switch | 16.1, 16.3–16.7 |
| **`misra-unions`** | union usage discouraged | 19.2 |

Bold entries were added in Phase 3 / Phase 4.

---

## MISRA C:2012 Coverage

<details>
<summary>All 115+ implemented rules (click to expand)</summary>

| Section | Rules |
|---|---|
| §1 — Undefined Behaviour | 1.3 |
| §2 — Unused Code | 2.1, 2.2, 2.3, 2.7 |
| §5 — Identifiers | 5.1, 5.3, 5.6, 5.7, 5.8, 5.9 |
| §6 — Types (bit-fields) | 6.1, 6.2 |
| §7 — Literals & Constants | 7.1, 7.3, 7.4 |
| §8 — Declarations & Definitions | 8.1–8.14 |
| §9 — Initialization | 9.1 |
| §10 — Type Conversions | 10.1–10.8 |
| §11 — Pointer Type Conversions | 11.1–11.9 |
| §12 — Expressions | 12.1–12.5 |
| §13 — Side Effects | 13.1–13.6 |
| §14 — Control Flow | 14.1–14.4 |
| §15 — Control Flow (if/switch) | 15.1–15.7 |
| §16 — Switch Statements | 16.1, 16.3, 16.4, 16.5, 16.6, 16.7 |
| §17 — Functions | 17.1–17.8 |
| §18 — Pointers & Arrays | 18.1–18.8 |
| §19 — Overlapping Storage | 19.2 |
| §20 — Preprocessing | 20.7, 20.10–20.12, 20.14 |
| §21 — Standard Libraries | 21.1, 21.2, 21.3, 21.4, 21.5, 21.6, 21.7, 21.8, 21.9, 21.10, 21.12 |
| §22 — Resources | 22.1, 22.2, 22.6 |

</details>

---

## Architecture

```
src/corvia/
├── cli.py                  # Argument parsing, colored output, entry point
├── engine.py               # Two-pass analysis orchestrator (parse-all → context → checkers)
├── parser.py               # pycparser wrapper with fake libc headers
├── registry.py             # Checker auto-discovery and registration
├── models.py               # Issue, MisraRule, Severity, AnalysisResult
├── core/
│   ├── cfg.py              # Control Flow Graph builder
│   ├── dataflow.py         # Generic ForwardAnalysis / BackwardAnalysis
│   ├── symbol_table.py     # Cross-file symbol table (Phase 3)
│   ├── call_graph.py       # Call graph + Tarjan SCC (Phase 3)
│   ├── summary.py          # FunctionSummary bottom-up computation (Phase 3)
│   ├── context.py          # AnalysisContext bundle for checkers (Phase 3)
│   └── cache.py            # Content-hash incremental cache (Phase 3)
├── checkers/
│   ├── base.py             # BaseChecker (NodeVisitor + report() + set_context())
│   ├── null_deref.py       # CFG + summary-aware null pointer analysis
│   ├── memory_leak.py      # CFG + summary-aware malloc/free tracking
│   ├── resource_leak.py    # CFG + summary-aware fopen/fclose tracking
│   ├── misra_identifiers.py     # §5 (Phase 3)
│   ├── misra_pointer_conv.py    # §11 (Phase 3)
│   ├── misra_standard_lib.py    # §21 (Phase 3)
│   └── ...                      # 12 other checkers
├── lsp/
│   ├── converter.py        # Issue → LSP Diagnostic (pygls-free) (Phase 3)
│   └── server.py           # corvia-lsp entry point (Phase 3)
└── reporters/
    ├── json_reporter.py
    ├── html_reporter.py
    └── md_reporter.py
```

### Two-Pass Analysis Pipeline (Phase 3)

```
Pass 1: parse all targets
  ↓
  build SymbolTable    (cross-file globals, statics, typedefs, tags)
  ↓
  build CallGraph      (every FuncCall edge, Tarjan SCC for recursion)
  ↓
  compute Summaries    (bottom-up over SCCs, fixpoint inside cycles)
  ↓
Pass 2: run every checker on every AST with shared AnalysisContext
```

This lets a checker analyzing `f` ask, in O(1):
- Does callee `g` ever return NULL?
- Does callee `g` allocate / open / free / close?
- Are `f` and `g` (mutually) recursive?

### Adding a Custom Checker

```python
# custom_checkers/my_checker.py
from pycparser import c_ast
from corvia.checkers.base import BaseChecker
from corvia.models import MisraRule, MisraCategory, Severity
from corvia.registry import CheckerRegistry

MY_RULE = MisraRule("15.5", MisraCategory.REQUIRED, "A function should have a single point of exit")

class SingleReturnChecker(BaseChecker):
    checker_id = "single-return"
    description = "Enforce single exit point per function"
    default_severity = Severity.WARNING
    misra_rules = [MY_RULE]

    def visit_FuncDef(self, node: c_ast.FuncDef) -> None:
        # Optional: use cross-function context
        if self._ctx and self._ctx.summary_of(node.decl.name):
            ...
        # ... your analysis logic
        pass

CheckerRegistry.register(SingleReturnChecker)
```

```bash
corvia src/ --external-checkers ./custom_checkers/
```

---

## Development

```bash
# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=corvia --cov-report=html

# Run a specific checker's tests
pytest tests/test_checkers/test_null_deref.py -v
```

**Test structure:**

```
tests/
├── fixtures/           # C source files used as test inputs
├── test_checkers/      # Per-checker unit tests
├── test_core/          # CFG, dataflow, symbol_table, call_graph, summary, cache
├── test_lsp/           # LSP converter + server smoke tests
├── test_reporters/     # JSON / Markdown reporter tests
├── test_engine.py
└── test_parser.py
```

Total: **118 tests passing**.

---

## Roadmap

- [x] **Phase 1 & 2** — AST checkers, CFG/dataflow framework, MISRA C:2012 §1, §2, §8–§10, §12–§15, §17, §18, §20, §22
- [x] **Phase 3** — SymbolTable + CallGraph + FunctionSummary inter-procedural analysis; MISRA §5, §11, §21; incremental cache; LSP server
- [x] **Phase 4** — MISRA §6 (bit-fields), §7 (literals), §16 (switch), §19 (overlapping storage)
- [x] **Phase 5** — 7 more rules across §1, §2, §9, §16, §22; `corvia.toml` project-config file
- [ ] VS Code extension wrapping `corvia-lsp`

---

## License

MIT

---

<a name="中文"></a>

# 中文

Corvia 是一款以 Python 實作的 C 語言靜態分析工具，靈感來自 Coverity。透過 AST 層級分析、基於控制流圖（CFG）的資料流分析，以及 **跨函式／跨檔案分析**（Phase 3），偵測程式錯誤、未定義行為以及 MISRA C:2012 規則違反。

---

## 功能特色

- 涵蓋 **20 個章節、115+ 條 MISRA C:2012 規則**
- **跨函式分析**：函式摘要會跨檔案傳遞，能辨識 `xalloc`、`xopen`、`xfree` 等包裝函式
- **CFG 資料流分析**：偵測空指標解引用、未初始化變數、記憶體與資源洩漏
- **符號表 + 呼叫圖**：偵測間接遞迴、跨檔識別字衝突（5.1、5.7、5.8、5.9）、未使用非 void 回傳值（17.7）
- **增量分析**：內容雜湊 cache + 反向依賴失效；只重分析真正有變動的檔案
- **LSP 伺服器**（`corvia-lsp`）：相容於 VS Code、Neovim、Emacs 等所有 LSP 編輯器
- **多種輸出格式**：純文字（彩色）、JSON、HTML、Markdown
- **可擴充的 checker 架構**：透過 `--external-checkers` 載入自訂檢查器
- **MISRA 過濾**：`--misra-only`、`--misra-category mandatory|required|advisory`

---

## 安裝方式

**需求**：Python 3.9+

```bash
git clone https://github.com/kevintsou/Corvia.git
cd Corvia
pip install -e ".[dev]"          # 基本 + 開發工具
pip install -e ".[dev,lsp]"      # 含 LSP 伺服器
```

---

## 使用方式

```bash
# 分析單一檔案或目錄
corvia path/to/file.c
corvia src/

# 指定輸出格式
corvia src/ --format json
corvia src/ --format html -o report.html
corvia src/ --format md   -o report.md

# 依嚴重程度過濾
corvia src/ --severity warning

# 只顯示 MISRA 規則違反
corvia src/ --misra-only
corvia src/ --misra-only --misra-category required

# 只啟用特定 checker
corvia src/ --checkers null-deref,memory-leak

# 列出所有可用 checker
corvia --list-checkers

# 使用 C 前處理器（適合含大量巨集的程式碼）
corvia src/ --use-cpp -I/usr/include

# 載入外部自訂 checker
corvia src/ --external-checkers ./custom_checkers/

# 增量分析
corvia src/ --incremental
corvia src/ --incremental --cache-dir .my_cache
corvia --clean-cache

# 啟動 LSP 伺服器
corvia-lsp --stdio
corvia-lsp --tcp --host 127.0.0.1 --port 9999
```

---

## Phase 3 技術亮點

### Two-Pass 分析管線

```
Pass 1：解析所有目標
  ↓
  建構 SymbolTable    （跨檔全域、靜態、typedef、tag）
  ↓
  建構 CallGraph      （所有 FuncCall 邊；用 Tarjan SCC 偵測遞迴）
  ↓
  計算 FunctionSummary （依 SCC 由下而上；遇到循環用 fixpoint 收斂）
  ↓
Pass 2：每個 checker 在每個 AST 上跑，共享 AnalysisContext
```

這讓分析 `f` 的 checker 可以在 O(1) 內查詢：
- callee `g` 是否可能回傳 NULL？
- callee `g` 是否會 allocate / open / free / close？
- `f` 與 `g` 是否（互相）遞迴？

### 增量分析

每個分析過的檔案會儲存：
- SHA-256 內容雜湊
- 上次的 Issue 列表
- 該檔呼叫的所有外部函式（callees）
- 該檔定義的所有 external linkage 函式（defines）

下次執行時：若 B.c 的 hash 改了 → A.c 若 callee 中含 B.c 的 defines，A.c 也會被重新分析。

---

## 開發路線圖

- [x] **Phase 1 & 2** — AST checker、CFG/dataflow 框架、MISRA §1, §2, §8–§10, §12–§15, §17, §18, §20, §22
- [x] **Phase 3** — SymbolTable + CallGraph + FunctionSummary 跨函式分析；MISRA §5, §11, §21；增量 cache；LSP 伺服器
- [x] **Phase 4** — MISRA §6（bit-field）、§7（字面量）、§16（switch）、§19（重疊儲存）
- [x] **Phase 5** — §1/§2/§9/§16/§22 補 7 條規則；`corvia.toml` 專案級設定檔
- [ ] 包裝 `corvia-lsp` 的 VS Code 擴充套件

---

## 授權

MIT

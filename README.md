# Corvia — C Static Analyzer with MISRA C:2012 Support

> 🌐 [English](#english) | [中文](#中文)

---

<a name="english"></a>

# English

Corvia is a Python-based static analysis tool for C code, inspired by Coverity. It detects bugs, undefined behaviour, and MISRA C:2012 rule violations using AST-level and CFG-based dataflow analysis.

---

## Features

- **66+ MISRA C:2012 rules** covered across 13 sections
- **CFG-based dataflow analysis** for null dereference, uninitialized variables, memory and resource leaks
- **Control Flow Graph (CFG)** builder with forward/backward analysis framework
- **Multiple output formats**: plain text (with color), JSON, HTML, Markdown
- **Extensible checker architecture** — drop in custom checkers via `--external-checkers`
- **MISRA filtering** — `--misra-only`, `--misra-category mandatory|required|advisory`

---

## Installation

**Requirements**: Python 3.9+

```bash
git clone https://github.com/kevintsou/Corvia.git
cd Corvia
pip install -e ".[dev]"
```

---

## Usage

```bash
# Analyze a file or directory
covia path/to/file.c
covia src/

# Choose output format
covia src/ --format json
covia src/ --format html -o report.html
covia src/ --format md   -o report.md

# Filter by severity
covia src/ --severity warning

# Show only MISRA violations
covia src/ --misra-only
covia src/ --misra-only --misra-category required

# Enable specific checkers only
covia src/ --checkers null-deref,memory-leak

# List all available checkers
covia --list-checkers

# Use C preprocessor (for macro-heavy code)
covia src/ --use-cpp -I/usr/include

# Load external custom checkers
covia src/ --external-checkers ./custom_checkers/
```

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
| `null-deref` | NULL pointer dereference via `*`, `->`, `[]` (CFG-based) | 1.3 |
| `buffer-overflow` | Array index out of bounds | 1.3, 18.1 |
| `memory-leak` | malloc/calloc/realloc without free (CFG-based) | 22.1, 22.2 |
| `resource-leak` | fopen/popen without fclose, use-after-close (CFG-based) | 22.1, 22.6 |
| `misra-types` | Implicit/narrowing conversions, sign mixing | 10.1–10.8 |
| `misra-decl` | Missing types, extern misuse, static/inline rules | 8.1–8.14 |
| `misra-expr` | Operator precedence, side effects, comma operator | 12.1–12.5, 13.1–13.6 |
| `misra-control` | goto, switch, if-else completeness rules | 14.1–14.4, 15.1–15.7 |
| `misra-func` | stdarg prohibition, implicit declarations, return values | 17.1–17.8 |
| `misra-pointer` | Pointer arithmetic, array decay, function pointers | 18.1–18.8 |
| `misra-preproc` | Macro restrictions, `#include` ordering (AST-detectable) | 20.7, 20.10–20.12, 20.14 |

---

## MISRA C:2012 Coverage

<details>
<summary>All 66+ implemented rules (click to expand)</summary>

| Section | Rules |
|---|---|
| §1 — Undefined Behaviour | 1.3 |
| §2 — Unused Code | 2.1, 2.2, 2.3, 2.7 |
| §8 — Declarations & Definitions | 8.1–8.14 |
| §9 — Initialization | 9.1 |
| §10 — Type Conversions | 10.1–10.8 |
| §12 — Expressions | 12.1–12.5 |
| §13 — Side Effects | 13.1–13.6 |
| §14 — Control Flow | 14.1–14.4 |
| §15 — Control Flow (if/switch) | 15.1–15.7 |
| §17 — Functions | 17.1–17.8 |
| §18 — Pointers & Arrays | 18.1–18.8 |
| §20 — Preprocessing | 20.7, 20.10–20.12, 20.14 |
| §22 — Resources | 22.1, 22.2, 22.6 |

</details>

---

## Architecture

```
src/covia/
├── cli.py                  # Argument parsing, colored output, entry point
├── engine.py               # Multi-file analysis orchestrator
├── parser.py               # pycparser wrapper with fake libc headers
├── registry.py             # Checker auto-discovery and registration
├── models.py               # Issue, MisraRule, Severity, AnalysisResult
├── core/
│   ├── cfg.py              # Control Flow Graph builder
│   └── dataflow.py         # Generic ForwardAnalysis / BackwardAnalysis
├── checkers/
│   ├── base.py             # BaseChecker (NodeVisitor + report())
│   ├── null_deref.py       # CFG-based null pointer analysis
│   ├── memory_leak.py      # CFG-based malloc/free tracking
│   ├── resource_leak.py    # CFG-based fopen/fclose tracking
│   ├── uninit_vars.py      # CFG-based uninitialized variable detection
│   └── ...                 # (11 more checkers)
└── reporters/
    ├── json_reporter.py
    ├── html_reporter.py
    └── md_reporter.py
```

### Adding a Custom Checker

```python
# custom_checkers/my_checker.py
from pycparser import c_ast
from covia.checkers.base import BaseChecker
from covia.models import MisraRule, MisraCategory, Severity
from covia.registry import CheckerRegistry

MY_RULE = MisraRule("15.5", MisraCategory.REQUIRED, "A function should have a single point of exit")

class SingleReturnChecker(BaseChecker):
    checker_id = "single-return"
    description = "Enforce single exit point per function"
    default_severity = Severity.WARNING
    misra_rules = [MY_RULE]

    def visit_FuncDef(self, node: c_ast.FuncDef) -> None:
        # ... your analysis logic
        pass

CheckerRegistry.register(SingleReturnChecker)
```

```bash
covia src/ --external-checkers ./custom_checkers/
```

---

## Development

```bash
# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=covia --cov-report=html

# Run a specific checker's tests
pytest tests/test_checkers/test_null_deref.py -v
```

**Test structure:**

```
tests/
├── fixtures/           # C source files used as test inputs
├── test_checkers/      # Per-checker unit tests (11 files)
├── test_core/          # CFG and dataflow framework tests
├── test_reporters/     # JSON and Markdown reporter tests
├── test_engine.py
└── test_parser.py
```

---

## Roadmap

- **Phase 3**: Inter-procedural / cross-file analysis (SymbolTable + CallGraph)
- **Phase 3**: Expand MISRA coverage to ~100+ rules (Sections 5, 6, 7, 11, 16, 19, 21)
- LSP / IDE integration
- Incremental analysis (only re-check changed files)

---

## License

MIT

---

<a name="中文"></a>

# 中文

Corvia 是一款以 Python 實作的 C 語言靜態分析工具，靈感來自 Coverity。透過 AST 層級分析與基於控制流圖（CFG）的資料流分析，偵測程式錯誤、未定義行為以及 MISRA C:2012 規則違反。

---

## 功能特色

- 涵蓋 **13 個章節、66+ 條 MISRA C:2012 規則**
- **CFG 資料流分析**：偵測空指標解引用、未初始化變數、記憶體與資源洩漏
- **控制流圖（CFG）**建構器，支援前向／後向分析框架
- **多種輸出格式**：純文字（彩色）、JSON、HTML、Markdown
- **可擴充的 checker 架構**：透過 `--external-checkers` 載入自訂檢查器
- **MISRA 過濾**：`--misra-only`、`--misra-category mandatory|required|advisory`

---

## 安裝方式

**需求**：Python 3.9+

```bash
git clone https://github.com/kevintsou/Corvia.git
cd Corvia
pip install -e ".[dev]"
```

---

## 使用方式

```bash
# 分析單一檔案或目錄
covia path/to/file.c
covia src/

# 指定輸出格式
covia src/ --format json
covia src/ --format html -o report.html
covia src/ --format md   -o report.md

# 依嚴重程度過濾
covia src/ --severity warning

# 只顯示 MISRA 規則違反
covia src/ --misra-only
covia src/ --misra-only --misra-category required

# 只啟用特定 checker
covia src/ --checkers null-deref,memory-leak

# 列出所有可用 checker
covia --list-checkers

# 使用 C 前處理器（適合含大量巨集的程式碼）
covia src/ --use-cpp -I/usr/include

# 載入外部自訂 checker
covia src/ --external-checkers ./custom_checkers/
```

### 輸出範例

```
test.c:12:5: error[null-deref] (MISRA C:2012 Rule 1.3 Required): Dereference of NULL pointer 'p'
test.c:20:3: warning[uninit-var] (MISRA C:2012 Rule 9.1 Required): Variable 'x' may be used uninitialized
test.c:35:1: error[memory-leak] (MISRA C:2012 Rule 22.1 Required): Memory allocated to 'buf' is never freed

Summary: 3 issues (2 errors, 1 warning, 0 info) in 1 file
MISRA rules violated: 3
```

---

## 檢查器一覽

| Checker ID | 說明 | MISRA 規則 |
|---|---|---|
| `syntax` | 條件式中的賦值、缺少大括號 | 13.4, 15.6 |
| `unused-vars` | 未使用的變數、型別標籤、參數 | 2.2, 2.3, 2.7 |
| `uninit-var` | 未初始化變數讀取（CFG 分析） | 9.1 |
| `dead-code` | 不可達程式碼、永真／永假條件 | 2.1, 14.3 |
| `null-deref` | 空指標解引用 `*`、`->`、`[]`（CFG 分析） | 1.3 |
| `buffer-overflow` | 陣列索引越界 | 1.3, 18.1 |
| `memory-leak` | malloc/calloc/realloc 未釋放（CFG 分析） | 22.1, 22.2 |
| `resource-leak` | fopen/popen 未關閉、關閉後使用（CFG 分析） | 22.1, 22.6 |
| `misra-types` | 隱式轉換、窄化轉換、有無號數混用 | 10.1–10.8 |
| `misra-decl` | 缺少型別宣告、extern 誤用、static/inline 規則 | 8.1–8.14 |
| `misra-expr` | 運算子優先順序、副作用、逗號運算子 | 12.1–12.5, 13.1–13.6 |
| `misra-control` | goto、switch、if-else 完整性規則 | 14.1–14.4, 15.1–15.7 |
| `misra-func` | 禁用 stdarg、隱式宣告、回傳值規則 | 17.1–17.8 |
| `misra-pointer` | 指標算術、陣列衰退、函式指標 | 18.1–18.8 |
| `misra-preproc` | 巨集限制、`#include` 順序（AST 可偵測部分） | 20.7, 20.10–20.12, 20.14 |

---

## MISRA C:2012 涵蓋範圍

<details>
<summary>全部 66+ 條已實作規則（點擊展開）</summary>

| 章節 | 規則 |
|---|---|
| §1 — 未定義行為 | 1.3 |
| §2 — 未使用程式碼 | 2.1, 2.2, 2.3, 2.7 |
| §8 — 宣告與定義 | 8.1–8.14 |
| §9 — 初始化 | 9.1 |
| §10 — 型別轉換 | 10.1–10.8 |
| §12 — 運算式 | 12.1–12.5 |
| §13 — 副作用 | 13.1–13.6 |
| §14 — 控制流 | 14.1–14.4 |
| §15 — 控制流（if/switch） | 15.1–15.7 |
| §17 — 函式 | 17.1–17.8 |
| §18 — 指標與陣列 | 18.1–18.8 |
| §20 — 前處理器 | 20.7, 20.10–20.12, 20.14 |
| §22 — 資源管理 | 22.1, 22.2, 22.6 |

</details>

---

## 系統架構

```
src/covia/
├── cli.py                  # 命令列參數解析、彩色輸出、程式進入點
├── engine.py               # 多檔案分析協調器
├── parser.py               # pycparser 封裝（含假 libc 標頭）
├── registry.py             # Checker 自動探索與註冊
├── models.py               # Issue、MisraRule、Severity、AnalysisResult
├── core/
│   ├── cfg.py              # 控制流圖建構器
│   └── dataflow.py         # 通用前向／後向分析框架
├── checkers/
│   ├── base.py             # BaseChecker（NodeVisitor + report()）
│   ├── null_deref.py       # CFG 空指標分析
│   ├── memory_leak.py      # CFG malloc/free 追蹤
│   ├── resource_leak.py    # CFG fopen/fclose 追蹤
│   ├── uninit_vars.py      # CFG 未初始化變數偵測
│   └── ...                 # （其餘 11 個 checker）
└── reporters/
    ├── json_reporter.py
    ├── html_reporter.py
    └── md_reporter.py
```

### 新增自訂 Checker

```python
# custom_checkers/my_checker.py
from pycparser import c_ast
from covia.checkers.base import BaseChecker
from covia.models import MisraRule, MisraCategory, Severity
from covia.registry import CheckerRegistry

MY_RULE = MisraRule("15.5", MisraCategory.REQUIRED, "A function should have a single point of exit")

class SingleReturnChecker(BaseChecker):
    checker_id = "single-return"
    description = "每個函式只能有一個回傳點"
    default_severity = Severity.WARNING
    misra_rules = [MY_RULE]

    def visit_FuncDef(self, node: c_ast.FuncDef) -> None:
        # ... 你的分析邏輯
        pass

CheckerRegistry.register(SingleReturnChecker)
```

```bash
covia src/ --external-checkers ./custom_checkers/
```

---

## 開發指南

```bash
# 執行所有測試
pytest tests/ -v

# 執行含覆蓋率報告
pytest tests/ --cov=covia --cov-report=html

# 執行特定 checker 的測試
pytest tests/test_checkers/test_null_deref.py -v
```

**測試結構：**

```
tests/
├── fixtures/           # 作為測試輸入的 C 原始碼
├── test_checkers/      # 各 checker 單元測試（11 個檔案）
├── test_core/          # CFG 與資料流框架測試
├── test_reporters/     # JSON 與 Markdown 報告器測試
├── test_engine.py
└── test_parser.py
```

---

## 開發路線圖

- **Phase 3**：跨函式／跨檔案分析（SymbolTable + CallGraph）
- **Phase 3**：擴充 MISRA 規則至 100+ 條（第 5、6、7、11、16、19、21 章節）
- LSP／IDE 整合
- 增量分析（只重新分析有變更的檔案）

---

## 授權

MIT

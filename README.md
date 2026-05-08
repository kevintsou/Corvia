# COVIA — C Language Static Analyzer

COVIA 是一款針對 C 語言的靜態分析工具，支援 MISRA C:2012 規則檢查，可偵測記憶體錯誤、空指標解參考、未初始化變數等常見問題，並提供多種輸出格式。

---

## 功能特色

- **AST-based 分析**：以 [pycparser](https://github.com/eliben/pycparser) 解析 C 原始碼，對 AST 進行遍歷分析
- **CFG 控制流圖**：自動建構函式層級的 Control Flow Graph，支援跨分支的資料流分析
- **MISRA C:2012 支援**：涵蓋型別、宣告、表達式、控制流、函式、指標、前處理器等分類的規則
- **多種輸出格式**：text（終端彩色輸出）、JSON、Markdown、HTML
- **可擴充架構**：支援外部自訂 checker 模組動態載入

---

## 安裝

需要 Python 3.9+。

```bash
git clone https://github.com/kevintsou/corvia.git
cd corvia
pip install -e .
```

安裝開發依賴（測試）：

```bash
pip install -e ".[dev]"
```

---

## 快速開始

分析單一檔案：

```bash
covia path/to/file.c
```

分析整個目錄：

```bash
covia path/to/src/
```

輸出 JSON 報告：

```bash
covia file.c -f json -o report.json
```

只列出 MISRA 相關問題：

```bash
covia file.c --misra-only
```

列出所有可用 checker：

```bash
covia --list-checkers
```

---

## 命令列選項

| 選項 | 說明 |
|------|------|
| `targets` | 要分析的檔案或目錄（可多個） |
| `-c, --checkers` | 逗號分隔的 checker ID，指定啟用哪些（預設全部） |
| `-f, --format` | 輸出格式：`text`、`json`、`html`、`md`（預設 `text`） |
| `-o, --output` | 輸出到檔案 |
| `-s, --severity` | 最低嚴重等級：`info`、`warning`、`error`（預設 `info`） |
| `--misra-only` | 只顯示有 MISRA 規則對應的問題 |
| `--misra-category` | 依 MISRA 分類篩選：`mandatory`、`required`、`advisory` |
| `--use-cpp` | 解析前先執行 C 前處理器 |
| `-I, --include` | 附加的 include 目錄（可多次使用） |
| `--external-checkers` | 含外部 checker 模組的目錄 |
| `--list-checkers` | 列出所有可用 checker 後離開 |
| `--no-color` | 關閉彩色輸出 |
| `-V, --version` | 顯示版本號 |

---

## 內建 Checker 一覽

### 通用問題

| Checker ID | 說明 |
|------------|------|
| `syntax` | 語法錯誤偵測 |
| `unused-vars` | 未使用的變數 |
| `uninit-vars` | 使用未初始化的變數 |
| `dead-code` | 無法到達的死碼（return 後的陳述式） |
| `null-deref` | NULL 指標解參考（CFG 跨分支分析） |
| `buffer-overflow` | 緩衝區溢位風險 |
| `memory-leak` | malloc/calloc/realloc 分配後未釋放 |
| `resource-leak` | fopen 開啟檔案後未關閉 |

### MISRA C:2012 規則

| Checker ID | 涵蓋規則 |
|------------|---------|
| `misra-types` | Rule 10.1–10.8：基本型別模型與型別轉換 |
| `misra-decl` | Rule 8.x：宣告與定義規則 |
| `misra-expr` | Rule 12.x, 13.x：表達式與副作用 |
| `misra-control` | Rule 14.x, 15.x：控制流規則 |
| `misra-func` | Rule 17.x：函式規則 |
| `misra-pointer` | Rule 11.x：指標型別轉換 |
| `misra-preproc` | Rule 20.x：前處理器使用限制 |

---

## 嚴重等級

| 等級 | 說明 |
|------|------|
| `ERROR` | 確定性的嚴重問題（如 NULL 解參考、記憶體洩漏） |
| `WARNING` | 潛在風險或 MISRA 違規 |
| `INFO` | 風格建議或低優先問題 |

分析完成後若有 `ERROR` 等級問題，CLI 回傳 exit code `1`，可整合至 CI/CD 管線。

---

## 輸出範例

### Text（終端）

```
src/main.c:15:5: error[null-deref] (MISRA C:2012 Rule 1.3 Required): Dereference of NULL pointer 'ptr'
src/main.c:23:3: warning[unused-vars]: Variable 'tmp' declared but never used

Summary: 2 issues (1 errors, 1 warnings, 0 info) in 1 files
MISRA rules violated: 1
```

### JSON

```json
{
  "summary": {
    "total_files": 1,
    "total_issues": 2,
    "ERROR": 1,
    "WARNING": 1,
    "INFO": 0
  },
  "misra_summary": {
    "1.3": {
      "rule_id": "1.3",
      "category": "Required",
      "description": "There shall be no occurrence of undefined behaviour",
      "violations": 1
    }
  },
  "files_analyzed": ["src/main.c"],
  "issues": [...]
}
```

---

## 專案結構

```
corvia/
├── pyproject.toml
└── src/covia/
    ├── cli.py              # 命令列入口
    ├── engine.py           # 分析引擎，協調 parser 與 checker
    ├── parser.py           # pycparser 封裝，產生 AST
    ├── registry.py         # Checker 動態載入與查詢
    ├── models.py           # 資料模型（Issue, AnalysisResult, MisraRule）
    ├── checkers/
    │   ├── base.py         # BaseChecker 抽象類別
    │   ├── null_deref.py   # CFG + 資料流分析的 NULL 檢查
    │   ├── memory_leak.py
    │   ├── misra_types.py
    │   └── ...             # 其他 checker
    ├── core/
    │   ├── cfg.py          # Control Flow Graph 建構
    │   └── dataflow.py     # 前向資料流分析框架
    └── reporters/
        ├── json_reporter.py
        ├── md_reporter.py
        └── html_reporter.py
```

---

## 自訂 Checker

建立一個 Python 檔案，繼承 `BaseChecker` 並向 `CheckerRegistry` 註冊：

```python
from covia.checkers.base import BaseChecker
from covia.models import Severity
from covia.registry import CheckerRegistry
from pycparser import c_ast

class MyChecker(BaseChecker):
    checker_id = "my-checker"
    description = "My custom check"
    default_severity = Severity.WARNING

    def visit_FuncCall(self, node: c_ast.FuncCall) -> None:
        # 在這裡實作檢查邏輯
        self.generic_visit(node)

CheckerRegistry.register(MyChecker)
```

載入外部 checker：

```bash
covia file.c --external-checkers ./my_checkers/
```

---

## 執行測試

```bash
pytest
pytest --cov=covia tests/
```

---

## 依賴

| 套件 | 用途 |
|------|------|
| `pycparser >= 2.21` | C 語言 AST 解析 |
| `jinja2 >= 3.1` | HTML 報告模板渲染 |

---

## 版本

`0.1.0` — COVIA C Static Analyzer Phase 1 & 2 初始實作

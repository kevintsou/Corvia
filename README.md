# CORVIA

A C language static analysis tool with **MISRA C:2012** support.

CORVIA parses C source code using pycparser and runs a suite of checkers to detect bugs, vulnerabilities, and MISRA violations.

---

## Features / 功能特色

- **23 built-in checkers**: Syntax errors, memory leaks, null pointer dereference, buffer overflow, uninitialized variables, dead code, resource leaks, and all MISRA C:2012 mandatory/required/advisory rules
- **C Preprocessor mode**: Preprocess files with gcc/clang before parsing, resolving `#include`, macros, and conditional compilation (enabled by default; use `--no-cpp` to disable)
- **Eclipse .cproject support**: Auto-discover include paths from `.cproject`
- **Makefile support**: Auto-detect include paths and defines from `Makefile` (runs `make -B -n` when available, falls back to static variable expansion for Windows/cross-platform use)
- **First-class config setup**: `corvia config detect/init` selects and generates `corvia.toml` from built-in templates, with machine-readable JSON for agents and CI
- **Location-independent configs**: `${TARGET_ROOT}` / `${CONFIG_DIR}` path variables let one config serve source trees checked out anywhere; config discovery stops at the repository boundary so an unrelated project's config is never picked up silently
- **Call graph export**: `--emit-symbols` writes a whole-program symbol table + call graph JSON; `corvia-graph` renders it as Graphviz DOT or Mermaid
- **CI gating**: `--fail-on {error,warning,info}` controls which severity makes the exit code non-zero
- **Multiple output formats**: text, JSON, HTML, Markdown
- **Incremental analysis**: Cache results to skip unchanged files (invalidated automatically when config, include paths, defines, checker selection, or Corvia version change)
- **MISRA category filtering**: Filter by mandatory / required / advisory
- **Extensible**: Load external checkers from a directory
- **LSP support**: Language Server Protocol for IDE integration
- **MCP server**: `corvia-mcp` exposes all analysis features as MCP tools for AI agent integration (Claude Desktop, etc.)

---

## Installation / 安裝

### Requirements / 環境需求

- Python **3.9+**（3.11 以下會自動加裝 `tomli` 以讀取 TOML）
- C preprocessor（gcc 或 clang）— 預設的 `--use-cpp` 模式需要。
  Windows 上若尚未安裝，可執行內附的輔助指令：
  ```bash
  corvia-install-cpp   # 透過 winget 安裝 LLVM-MinGW（會先詢問確認）
  ```
  沒有 preprocessor 時仍可用 `--no-cpp` 的 fallback 模式分析。

### From GitHub
```bash
pip install "corvia @ git+https://github.com/kevintsou/Corvia.git"
```

### From a local clone / 本機開發安裝
```bash
git clone https://github.com/kevintsou/Corvia.git
cd Corvia
pip install -e .
```

### Optional feature groups

> 注意：extras 不能直接寫在 git URL 後面（`pip install git+...git[lsp]` 是無效語法），
> 必須使用下方 `corvia[extra] @ git+URL` 的形式。

#### `[lsp]` — IDE 即時分析（VS Code / Neovim）

**適用情境：** 想在編輯器裡即時看到 Corvia 的警告，不需要手動執行 CLI。

```bash
pip install "corvia[lsp] @ git+https://github.com/kevintsou/Corvia.git"
```

安裝後啟動 Language Server：
```bash
corvia-lsp
```

在 VS Code 或 Neovim 的 LSP 設定中指向 `corvia-lsp`，即可在存檔時自動分析並在程式碼旁顯示問題標記。

---

#### `[mcp]` — AI Agent 整合（Claude Desktop / Claude Code）

**適用情境：** 想讓 Claude Desktop 或 Claude Code 直接呼叫 Corvia 分析工具，不需要手動下指令。

```bash
pip install "corvia[mcp] @ git+https://github.com/kevintsou/Corvia.git"
```

安裝後在 `claude_desktop_config.json` 加入：
```json
{
  "mcpServers": {
    "corvia": { "command": "corvia-mcp" }
  }
}
```

Claude 就可以直接說「幫我分析這個專案」並自動呼叫 Corvia。

---

#### `[lsp,mcp]` — 同時安裝兩者

```bash
pip install "corvia[lsp,mcp] @ git+https://github.com/kevintsou/Corvia.git"
```

---

**一般命令列使用不需要任何 extra，直接安裝基本版即可：**
```bash
pip install "corvia @ git+https://github.com/kevintsou/Corvia.git"
```

### Uninstall / 移除

```bash
pip uninstall corvia
```

---

## Quick Start / 快速開始

### Analyze a single file
```bash
corvia src/main.c
```

### Analyze a directory
```bash
corvia src/
```
C preprocessor and incremental caching are enabled by default.

### Disable C preprocessor mode
```bash
corvia --no-cpp src/
```

### Use a configuration file
Create `corvia.toml` in your project root manually, or let Corvia detect and
generate the closest matching template:

```bash
corvia config detect . --json
corvia config init . --template auto
```

Example `corvia.toml`:

```toml
[paths]
use_cpp = true
cproject = ".cproject"
cpp_args = "--target=armv7-unknown-windows-gnu -D_IC_TYPE_=IC_TYPE_FPGA_HAPS"
```

Then run:
```bash
corvia src/
```

A template with all available options is provided at `corvia.toml.example`.

---

## CLI Usage / 命令列用法

```
corvia [options] [targets ...]
```

| Option | Description |
|--------|-------------|
| `targets` | Files or directories to analyze (`.c` files) |
| `-h, --help` | Show help message |
| `-V, --version` | Show version |
| `-c, --checkers` | Comma-separated checker IDs to enable (default: all) |
| `-f, --format` | Output format: `text`, `json`, `html`, `md` (default: text) |
| `-o, --output` | Output file path |
| `-s, --severity` | Minimum severity: `info`, `warning`, `error` (default: info) |
| `--fail-on` | Exit non-zero when issues at/above this severity exist: `error`, `warning`, `info` (default: error) — useful for CI gating |
| `--misra-only` | Only show issues with MISRA rule mapping |
| `--misra-category` | Filter by MISRA category: `mandatory`, `required`, `advisory` |
| `--use-cpp` | Enable C preprocessor mode (default: enabled) |
| `--no-cpp` | Disable C preprocessor mode |
| `-I, --include` | Additional include directories (can be repeated) |
| `-D, --define` | Preprocessor definitions, e.g. `-DNAME=VALUE` |
| `--cpp-args` | Extra arguments for the C preprocessor |
| `--cproject` | Path to Eclipse `.cproject` file |
| `--config` | Path to `corvia.toml` (auto-discovered by default) |
| `--no-config` | Ignore `corvia.toml` and use CLI flags only |
| `--incremental` | Enable incremental analysis (default: enabled) |
| `--no-incremental` | Disable incremental analysis |
| `--cache-dir` | Cache directory (default: `.corvia_cache`) |
| `--clean-cache` | Delete cache and exit |
| `--list-checkers` | List all available checkers |
| `--external-checkers` | Directory containing external checker modules |
| `--emit-symbols` | Also write a JSON symbol table + call graph to PATH (for dependency-aware tooling; see Call Graph section) |
| `--no-color` | Disable colored output |

### Config setup commands

一條指令為任何專案（新 clone、新機器）生出正確的 `corvia.toml`：

```bash
corvia config init <project_dir> --template auto
```

`--template auto` 會掃描目標目錄的特徵、為每個範本打分，選最高分者生成：

| 偵測到的特徵 | 選中範本 | 產出內容 |
|-------------|---------|---------|
| 已有 `corvia.toml` | `existing` | 不生成（提示已存在；`--force` 才覆蓋重生） |
| `common/include/phison_hw/<SoC>` Phison 目錄結構 | `ps5801` | 現場走訪目錄，只列**實際存在**的 include 子目錄 + `-DSOC_ID=...` defines |
| `.cproject`（Eclipse CDT / ARM DS-5） | `ds5` | 設定 `cproject = ".cproject"`，include 由 .cproject 自動抽取 |
| `Makefile` | `makefile` | 用 make dry-run / 靜態解析抽 `-I`/`-D` |
| 都沒有 | `minimal` | 只開 use_cpp + cache 的最小可用設定 |

其他常用形式：

```bash
corvia config list-templates                          # 列出所有範本
corvia config detect <project_dir>                    # 只看偵測結果與信心分數，不寫檔
corvia config init <project_dir> --template auto --dry-run   # 預覽會生成什麼，不寫檔
corvia config init <project_dir> --template ps5801    # 跳過偵測，指名範本
corvia config init <project_dir> --template auto --force     # 已有 config 時強制重生
corvia config detect <project_dir> --json             # 機器可讀輸出（CI / AI agent 用）
```

`config init` never overwrites an existing `corvia.toml` unless `--force` is
supplied. Because the `ps5801` template renders include paths by walking the
actual directory tree, the generated config is correct for any checkout
location — new team members never need to copy a config from someone else.

Supported templates:

| Template | Description |
|----------|-------------|
| `auto` | Select the highest-confidence detected template |
| `ds5` | Eclipse CDT / ARM DS-5 project using `.cproject` include extraction |
| `ps5801` | Phison PS5801/PT5801 firmware; dynamically renders existing SoC include directories when present |
| `makefile` | Makefile-backed project using Corvia's `-I` / `-D` extraction |
| `minimal` | Portable fallback with preprocessing and cache enabled |

### Examples / 範例

```bash
# Basic analysis
corvia src/main.c

# Multiple targets
corvia src/main.c src/utils.c lib/

# With preprocessor (ARM target)
corvia --use-cpp --cpp-args="--target=armv7-unknown-windows-gnu" src/

# Without preprocessor (for simple code without includes)
corvia --no-cpp src/

# Disable incremental caching
corvia --no-incremental src/

# Filter by MISRA category
corvia --misra-category mandatory src/

# JSON output
corvia -f json -o result.json src/

# Enable only specific checkers
corvia -c misra-switch,null-deref src/

# Custom include paths
corvia -I /usr/local/include -I ./src/include src/

# Incremental analysis (enabled by default, use --no-incremental to disable)
corvia src/

# First-time setup on a fresh clone: auto-generate corvia.toml, then analyze
corvia config init . --template auto
corvia src/

# Apply a config stored outside the repo (use ${TARGET_ROOT} includes in it,
# and point corvia at the tree root)
corvia <tree_root> --config D:/configs/shared_corvia.toml

# CI gating: non-zero exit code when warnings (or worse) are found
corvia --fail-on warning -f json -o result.json src/
```

---

## Configuration / 設定檔 (`corvia.toml`)

CORVIA automatically discovers `corvia.toml` by walking upward from the target file's directory, **stopping at the repository boundary** (the first directory containing `.git`) so a config belonging to an unrelated project above your repo is never picked up silently. Use `--config <path>` to point at a config outside the repository explicitly. If no config file is found, run `corvia config detect` and `corvia config init` to generate one before analysis.

### Full configuration reference

```toml
[paths]
use_cpp = true                    # Enable C preprocessor mode
cproject = ".cproject"            # Eclipse project file for include paths
# OR use Makefile auto-detection (mutually exclusive with cproject):
makefile = "Makefile"             # Path to Makefile (auto-detected if omitted)
make_target = "all"               # Make target to dry-run (optional)
make_args = ["SOC_ID=PS5801"]     # Extra variables passed to make / static parser
cpp_args = "--target=armv7-unknown-windows-gnu -D_IC_TYPE_=IC_TYPE_FPGA_HAPS"
include = ["../common/include"]   # Additional include directories
# Relative include entries resolve against the corvia.toml directory.
# Path variables let one config serve source trees at different locations:
#   ${TARGET_ROOT} = the directory being analyzed
#   ${CONFIG_DIR}  = the directory containing corvia.toml
# include = ["${TARGET_ROOT}/common/sal", "${TARGET_ROOT}/common/config"]

[checkers]
enabled = ["null-deref", "misra-switch"]   # Only run these checkers (omit = all)
disabled = ["misra-unions"]                # Disable specific checkers

[severity]
# Override severity per checker id or MISRA rule id
# Values: "error" / "warning" / "info" / "off"
"parser" = "warning"
"21.3" = "info"
"19.2" = "off"

[output]
format = "text"      # text / json / md / html
no_color = false

[cache]
enabled = true       # Enable incremental analysis
dir = ".corvia_cache"
```

A complete annotated template is available at `corvia.toml.example`.

---

## Example Configurations / 範例設定檔

Ready-to-use `corvia.toml` templates are bundled with the package and exposed through `corvia config`:

| Template | Description |
|----------|-------------|
| `ps5801` | Phison PS5801/PT5801 firmware project; dynamically renders existing SoC include paths where possible |
| `ds5` | Eclipse CDT / ARM DS-5 project; auto-extracts include paths from `.cproject` |
| `makefile` | Makefile-backed project; extracts include paths and defines from `Makefile` |
| `minimal` | Generic fallback for projects that need manual include path tuning |

### How to use / 使用方式

1. Detect candidates:

```bash
corvia config detect your_project --json
```

2. Initialize config:

```bash
corvia config init your_project --template auto
```

3. Edit the file to match your project if needed (adjust paths, defines, SOC_ID, etc.).

4. Run Corvia from your project directory:

```bash
corvia src/
```

Corvia will automatically discover and load `corvia.toml` by walking upward from the target path.

> **Scan one build variant at a time.** MISRA cross-translation-unit rules
> (e.g. 5.8 "external identifiers shall be unique") assume a single linked
> program. If your tree contains mutually-exclusive build variants — such as
> `PS5801/` and `PT5801/`, only one of which is selected at build time — do
> **not** scan both together, or their same-named functions will be reported
> as duplicate definitions. Pass only the active variant's source directories
> as scan targets, e.g. `corvia common/source/phison_hw/PS5801 common/sal common/config`.

---

## Checkers / 檢查器

| ID | Description | MISRA |
|----|-------------|-------|
| `syntax` | C syntax errors | 13.4, 15.6 |
| `unused-var` | Unused variables | 2.2–2.4, 2.6–2.7 |
| `uninit-var` | Uninitialized variables | 9.1 |
| `dead-code` | Unreachable code | 2.1, 14.3 |
| `null-deref` | Null pointer dereference | 1.3 |
| `buffer-overflow` | Buffer overflow | 1.3, 18.1 |
| `memory-leak` | Memory leaks | 22.1–22.2 |
| `resource-leak` | Resource leaks | 22.1, 22.5–22.6 |
| `misra-types` | Type-related MISRA rules | 10.1–10.8 |
| `misra-decl` | Declaration rules | 8.1–8.14 |
| `misra-expr` | Expression and side effect rules | 12.1–12.5, 13.1–13.6 |
| `misra-control` | Control flow rules | 14.1–14.4, 15.1–15.7 |
| `misra-func` | Function rules | 17.1–17.8 |
| `misra-pointer` | Pointer and array rules | 18.1–18.8 |
| `misra-pointer-conv` | Pointer type conversion rules | 11.1–11.9 |
| `misra-preproc` | Preprocessor rules | 20.7, 20.10–20.12, 20.14 |
| `misra-stdlib` | Standard library and reserved identifiers | 1.4, 21.1–21.12 |
| `misra-bitfields` | Bit-field rules | 6.1–6.2 |
| `misra-literals` | Literal rules | 7.1–7.4 |
| `misra-switch` | Switch statement rules | 16.1–16.7 |
| `misra-unions` | Union usage | 19.2 |
| `misra-identifiers` | Identifier uniqueness and shadowing | 5.1, 5.3, 5.6–5.9 |
| `misra-init` | Aggregate / union initializer rules | 9.2–9.3 |

List all checkers with:
```bash
corvia --list-checkers
```

---

## Output Formats / 輸出格式

| Format | Flag | Description |
|--------|------|-------------|
| text | `-f text` | Colored terminal output (default) |
| json | `-f json` | JSON array of issues |
| html | `-f html` | Self-contained HTML report |
| md | `-f md` | Markdown report |

---

## Call Graph / 呼叫圖

Analysis can emit a whole-program symbol table + call graph as a byproduct
(C files only — the graph never covers headers-only constructs it can't see):

```bash
corvia src/ --emit-symbols symbols.json -o findings.json -f json
```

The JSON contains `functions` (definition site, signature, `is_static`,
callees), `call_edges` (caller → callee with call-site file/line),
`file_defines`, and `unresolved_callees` (called but defined outside the
scanned target, e.g. libc).

Visualize it with the bundled `corvia-graph` tool:

```bash
corvia-graph symbols.json -o graph.dot            # Graphviz DOT
dot -Tsvg graph.dot -o graph.svg                  #   → render (needs graphviz)

corvia-graph symbols.json --format mermaid        # Mermaid — paste into
                                                  #   GitLab/GitHub markdown
corvia-graph symbols.json --focus main --depth 2  # only main ± 2 hops
```

DOT output clusters functions by file, draws `static` functions dashed, and
grays out unresolved external callees. `--focus FUNC --depth N` trims large
firmware graphs down to the neighborhood you care about.

---

## LSP Support / LSP 支援

CORVIA provides a Language Server Protocol implementation for IDE integration.

```bash
pip install "corvia[lsp] @ git+https://github.com/kevintsou/Corvia.git"   # or: pip install -e ".[lsp]" from a clone
corvia-lsp
```

This starts an LSP server that can be connected to from editors like VS Code, Neovim, etc.

---

## MCP Server / MCP 伺服器

CORVIA provides a [Model Context Protocol](https://modelcontextprotocol.io) server that lets AI agents (e.g. Claude Desktop) call Corvia analysis tools directly.

### Installation

```bash
pip install "corvia[mcp] @ git+https://github.com/kevintsou/Corvia.git"   # or: pip install -e ".[mcp]" from a clone
```

### Available tools

| Tool | Description |
|------|-------------|
| `analyze` | Run static analysis on a C file or directory. Returns JSON with `issues`, `summary`, and `misra_summary`. Supports all analysis options: checkers, severity, misra_only, misra_category, use_cpp, include_dirs, defines, cpp_args, config, incremental, cache_dir |
| `list_checkers` | List all available checker IDs, descriptions, and MISRA rules |
| `clean_cache` | Delete the incremental analysis cache |

### Claude Desktop setup

Add to `claude_desktop_config.json`:

- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "corvia": {
      "command": "corvia-mcp"
    }
  }
}
```

Restart Claude Desktop — Corvia tools will appear in the tool list.

### Claude Code (CLI / VS Code extension) setup

**Option A — one-line command (recommended):**
```bash
claude mcp add corvia corvia-mcp
```

**Option B — manual config:**

Add to `settings.json`:
- **User-level** (all projects): `~/.claude/settings.json`
- **Project-level** (current project only): `.claude/settings.json`

```json
{
  "mcpServers": {
    "corvia": {
      "command": "corvia-mcp"
    }
  }
}
```

The VS Code extension shares the same settings as the Claude Code CLI — no separate configuration needed.

---

## Development / 開發

```bash
# Install in dev mode with all optional dependencies
pip install -e ".[dev,lsp,mcp]"

# Run tests
pytest

# Run with coverage
pytest --cov=corvia
```

### Project structure / 專案結構

```
corvia/
├── src/corvia/
│   ├── __init__.py
│   ├── cli.py            # CLI entry point
│   ├── engine.py         # Analysis engine
│   ├── parser.py         # C parser wrapper (pycparser)
│   ├── models.py         # Data models
│   ├── registry.py       # Checker registry
│   ├── install.py        # C preprocessor installer
│   ├── checkers/         # Built-in checkers
│   │   ├── misra_switch.py
│   │   ├── misra_types.py
│   │   ├── null_deref.py
│   │   └── ...
│   ├── core/
│   │   ├── config.py     # Configuration (corvia.toml)
│   │   ├── cache.py      # Incremental cache
│   │   ├── symbol_table.py
│   │   ├── call_graph.py
│   │   ├── context.py
│   │   └── ...
│   ├── reporters/        # Output formatters
│   │   ├── json_reporter.py
│   │   ├── html_reporter.py
│   │   ├── md_reporter.py
│   │   └── base.py
│   ├── lsp/              # LSP server
│   │   ├── server.py
│   │   └── converter.py
│   └── mcp/              # MCP server
│       └── server.py
├── example_toml/         # Ready-to-use corvia.toml templates
│   ├── corvia.toml.ps5801
│   └── corvia.toml.ds5
├── tests/
├── pyproject.toml
└── corvia.toml.example
```

---

## Changelog / 版本紀錄

### v0.5.6 (2026-07-15)
Further false-positive fixes found via a targeted rescan of a TF-A BL1 tree after v0.5.4's fixes and a `corvia.toml` include-path completion (`spi_bcfg.h`, `drivers/phison/framework` source tree — parser errors on that tree dropped 36 → 8, the remainder being an unrelated mbedtls `bignum.h` parse issue):
- **`null-deref` now recognizes `assert(p != NULL)` as a non-null guard.** TF-A code (`bl1_context_mgmt.c`, `bl1_fwu.c`) commonly guards a dereference with `assert(p != NULL)` instead of an early-exit `if`. With `ENABLE_ASSERTIONS` defined, the preprocessor expands `assert(e)` to the bare statement `(e) ? (void)0 : __assert(...);`; the checker now narrows the condition's variables to non-null past that statement, the same way it already does for `if (p == NULL) { return; }`. Without `ENABLE_ASSERTIONS`, `assert(e)` expands to `((void)0)` and `e` is discarded entirely by the preprocessor — that case remains out of scope (unrecoverable at the AST level). The `ps5801` config template now defines `-DENABLE_ASSERTIONS=1` so this recognition is active by default. Eliminated 10 of 11 null-deref findings on a 7-file BL1 rescan; the 11th was a genuine missing-NULL-check bug the checker correctly still reports.
- **`misra-expr` (12.3) no longer flags function-call argument lists as the comma operator.**
- **`uninit-var` no longer flags `init(&var)`-style out-parameters** (the address-of argument is now treated as an initializing write unless a function summary proves otherwise), nor function-scope `static` locals (zero-initialized by the C standard), nor a `for`-loop next-expression variable assigned in the loop body.
- **`misra-identifiers` (5.1/5.6/5.8/5.9) no longer compares project symbols against host toolchain / bundled libc-stub headers** (MinGW, ARM bare-metal, `fake_libc_include`) — those are not user definitions.
- **`misra-pointer-conv` (11.4/11.6) now resolves pointer typedefs** (`typedef struct x *X_PTR`) instead of misreading them as an integer type, which previously turned a valid `void*`→object-pointer cast into a spurious pointer/integer + void/arithmetic violation pair.
- Progress reporting during the checking phase is now per source file instead of per (file × checker) pair, so large trees no longer appear to "balloon" to files×checkers in the progress bar.

### v0.5.4 (2026-07-15)
Round-2 false-positive elimination, validated by a full before/after rescan of a 94-file firmware tree (8,873 → 2,564 issues, −71%; out-of-range line numbers 65 → 0; all audited true positives retained). Post-release manual audit of every remaining ERROR-level uninit-var/misra-func finding on that tree confirmed 20/20 true positives — no residual false-positive patterns:
- **buffer-overflow**: parameters and local non-array declarations now shadow same-named file-scope arrays (cpp-inlined headers declaring `r[2]` no longer bounds-check a `U8 *r` parameter)
- **misra-func 17.4**: `else if` chains are recognized — a bare `If` in `iffalse` recurses instead of failing the all-paths-return proof (88 → 2 ERRORs on the firmware tree)
- **Macro-expansion noise**: Rule 12.1 findings whose flagged operators do not appear on the reported source line are dropped — under `--use-cpp` a single unparenthesized register-macro expression no longer reports once per call site (6,627 → 752)
- **Type-stub attribution**: symbols from the injected stub preamble map to a sentinel file in both the non-cpp and cpp-fallback parse paths, so stub scaffolding (`NULL_SIM`, `L4KTableBitMap`, …) never produces issues in user files (eliminated all 65 beyond-end-of-file findings and 66 misra-unions artifacts)

### v0.5.3 (2026-07-15)
False-positive elimination driven by a line-by-line verification of a real firmware scan (2047 issues audited):
- **Coord double-remap fixed (root cause of scattered/out-of-range line numbers)**: pycparser AST nodes share Coord objects; the stub-offset remapper now maps each Coord exactly once instead of once per referencing node — issues no longer land on unrelated lines, comment lines, or beyond end-of-file
- **MISRA 11.4/11.5/11.6 now exempt the null pointer constant** (`NULL`, integer `0`, `(void *)0`) per the MISRA C:2012 exception — `(U32)NULL`-style casts and normal NULL usage no longer report
- **buffer-overflow no longer bounds-checks pointer/array parameters** (`U8 *r`, `U8 r[]`, `U8 r[2]`) — array parameters decay to pointers and carry no usable size
- **dead-code whitelists the `do { ... } while (0)` macro idiom**; genuine `while(0)` bodies and unreachable-after-return still report
- **uninit-var understands loop-driven initialization** (`for (k...) t[k] = ...` then read) and no longer treats struct member names (`p->cq_len`) as same-named locals
- **misra-pointer (18.x) is now scope- and typedef-aware** — integer variables (`U32 s; s += 4U`) shadowing a file-scope pointer are no longer misread as pointer arithmetic
- **Same-line/same-message issues at different columns are collapsed** (one logical violation, reported once); serialized `file` paths are normalized (no doubled backslashes)

### v0.5.2 (2026-07-14)
- **`ps5801` config template now covers the full TF-A BL1 (aarch32) tree.** Previously it only included the Phison `common/` sources, so scanning `bl1_32/trusted-firmware-a/` produced a cascade of "No such file or directory" parser errors (which in turn force no-cpp-style false positives). Added the TF-A include root, the aarch32 arch/libc/el3_runtime variants (this is the 32-bit / ARMv7 Cortex-A15 port, not aarch64), libfdt, the Phison driver header roots (`drivers/phison/{efuse,framework/*,host,host/pcie,sec,uart,ufs}`), the Phison platform roots (`plat/phison/...` providing `platform_def.h`, `phison_scatter.h`, `efuse_common.h`, `plat_bl1_libs.h`), two deeper PS5801 register subdirs (`reg/pcie_ctrl`, `reg/pmu`), `lib/phison`, and the external `mbedtls/include`. `ARM_ARCH_MAJOR=7` added to `cpp_args`. Verified by scanning the real BL1 tree until every resolvable `#include` was satisfied. Template-only change; no analyzer behavior change.

### v0.5.1 (2026-07-14)
- **Fixed `uninit-var` (MISRA 9.1) false positives on out-parameters**: a bare array/pointer name passed to a function (`memset(buf, 0, sizeof(buf))`) decays to a writable address, same as `&scalar` — the checker now treats it as a possible initialization instead of a read. Covers casts (`(void *)buf`), `(void)`-discarded call statements, and macro-sized arrays (`buf[MACRO_LEN]`). `sizeof`/`_Alignof` operands are also no longer treated as reads (C11 6.5.3.4), and any initializer list (`= {0}`) is now recognized as fully initializing the object (C11 6.7.9), not "partially initialized".
- **Fixed inline-asm and `va_start` write-loss in the parser**: stripping a GNU `__asm__` statement now recovers its output operands (`: "=r" (id)`) as a synthesized write, instead of discarding them along with the statement; `__builtin_va_start`/`__builtin_va_copy` now synthesize a write to their first argument instead of being replaced with a bare `0`. Both previously made correctly-written variables look uninitialized.
- Validated against a 94-file real-world C firmware tree: `uninit-var` findings dropped 46 → 1, with the sole survivor being an actual bug (a variable whose only assignment was commented out) — no loss of true positives. 21 new regression tests added.

### v0.5.0 (2026-07-13)
- **Incremental mode now skips re-parsing unchanged files**: parsed ASTs are cached (pickled, keyed on content + environment + interpreter/pycparser fingerprints), so the expensive preprocess+parse step — the dominant cost under `--use-cpp` — only runs for changed files. The analysis context is still rebuilt from real ASTs every run, so cross-file correctness is identical to a full run; corrupt or incompatible cache entries silently fall back to parsing.

### v0.4.0 (2026-07-09)
- **`corvia-graph`**: new console tool rendering `--emit-symbols` JSON as Graphviz DOT (clustered by file, static functions dashed, external callees grayed) or Mermaid (pasteable into GitLab/GitHub markdown), with `--focus FUNC --depth N` neighborhood trimming

### v0.3.0 (2026-07-09)

**New features**
- `${TARGET_ROOT}` / `${CONFIG_DIR}` path variables in `[paths] include` — one config serves source trees checked out at different locations
- Config discovery stops at the repository boundary (`.git`), so a corvia.toml belonging to an unrelated project above the repo is never applied silently; `--config` remains the explicit escape hatch
- `--fail-on {error,warning,info}` for CI exit-code gating
- Path-anchoring rules documented in every generated config template

**Correctness fixes (highlights of ~100 fixed review findings)**
- Preprocessor stripping: `#elif`/`#else` no longer corrupted nesting depth (code after the first `#if/#else/#endif` block was silently dropped); stub-preamble line offsets now remapped, so issues report real source lines
- CFG: switch statements rewritten with explicit break/continue target stacks — post-switch code reachable, no-default bypass edge added, switch-break inside loops no longer wired to the loop exit; labeled statements expand properly
- Cache: keyed on environment hash (config, include paths, defines, checker set, Corvia version), normalized paths; incremental runs now parse all files for full cross-file context and match full-run results
- Checkers: eliminated systematic false positives across 20+ checkers (for-loop counters, `== NULL` guards, `free()` of parameters, `return malloc(...)`, `{0}` initializers, typedef'd structs/bitfields, multi-label switch cases, and more); dead rule logic (10.1, 12.1, 8.14, 13.3, 17.1) now actually fires; unimplemented MISRA rule declarations removed
- Interfaces: HTML report XSS fixed (autoescape), config discovery starts at the target directory, `--format=json` no longer overridden by corvia.toml, pygls 1.x/2.x compatibility, MCP `analyze` no longer writes files into analyzed projects, Ctrl-C at the install prompt aborts instead of consenting
- Repository slimmed from 570MB to 32MB (experiment artifacts purged from history)

### v0.2.8 and earlier
- Symbol graph export (`--emit-symbols`), first-class config templates (`corvia config detect/init`), MCP server, LSP server, incremental analysis, 23 built-in checkers with MISRA C:2012 mapping

---

## License / 授權

MIT

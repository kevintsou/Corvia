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
- **Multiple output formats**: text, JSON, HTML, Markdown
- **Incremental analysis**: Cache results to skip unchanged files
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
| `--no-color` | Disable colored output |

### Config setup commands

```bash
corvia config list-templates
corvia config detect <project_dir>
corvia config init <project_dir> --template auto
```

Use `--json` with any config command for machine-readable output. `config init`
never overwrites an existing `corvia.toml` unless `--force` is supplied.

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

## License / 授權

MIT

# CORVIA

A C language static analysis tool with **MISRA C:2012** support.

CORVIA parses C source code using pycparser and runs a suite of checkers to detect bugs, vulnerabilities, and MISRA violations.

---

## Features / 功能特色

- **23 built-in checkers**: Syntax errors, memory leaks, null pointer dereference, buffer overflow, uninitialized variables, dead code, resource leaks, and all MISRA C:2012 mandatory/required/advisory rules
- **C Preprocessor mode**: Preprocess files with gcc/clang before parsing, resolving `#include`, macros, and conditional compilation (enabled by default; use `--no-cpp` to disable)
- **Eclipse .cproject support**: Auto-discover include paths from `.cproject`
- **Auto-config**: Auto-creates `corvia.toml` with sensible defaults when none exists
- **Multiple output formats**: text, JSON, HTML, Markdown
- **Incremental analysis**: Cache results to skip unchanged files
- **MISRA category filtering**: Filter by mandatory / required / advisory
- **Extensible**: Load external checkers from a directory
- **LSP support**: Language Server Protocol for IDE integration

---

## Installation / 安裝

### From PyPI (recommended)
```bash
pip install corvia
```

### From GitHub (latest development version)
```bash
pip install git+https://github.com/kevintsou/Corvia.git
```

For development:
```bash
pip install git+https://github.com/kevintsou/Corvia.git#egg=corvia[dev,lsp]
```

For LSP support:
```bash
pip install corvia[lsp]
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
Create `corvia.toml` in your project root (or run `corvia` without one and it will be auto-created):

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

CORVIA automatically discovers `corvia.toml` by walking upward from the target file's directory. If no config file is found, one is auto-created with defaults.

### Full configuration reference

```toml
[paths]
use_cpp = true                    # Enable C preprocessor mode
cproject = ".cproject"            # Eclipse project file for include paths
cpp_args = "--target=armv7-unknown-windows-gnu -D_IC_TYPE_=IC_TYPE_FPGA_HAPS"
include = ["../common/include"]   # Additional include directories

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

## Checkers / 檢查器

| ID | Description | MISRA |
|----|-------------|-------|
| `syntax` | C syntax errors | - |
| `unused-var` | Unused variables | - |
| `uninit-var` | Uninitialized variables | - |
| `dead-code` | Unreachable code | - |
| `null-deref` | Null pointer dereference | - |
| `buffer-overflow` | Buffer overflow | - |
| `memory-leak` | Memory leaks | - |
| `resource-leak` | Resource leaks | - |
| `misra-types` | Type-related MISRA rules | MISRA 10.1–10.8 |
| `misra-decl` | Declaration rules | MISRA 8.1–8.14 |
| `misra-expr` | Expression rules | MISRA 12.1–12.4 |
| `misra-control` | Control flow rules | MISRA 14.1–14.4, 15.1–15.7 |
| `misra-func` | Function rules | MISRA 16.1–16.7, 17.1–17.8 |
| `misra-pointer` | Pointer rules | MISRA 18.1–18.8 |
| `misra-pointer-conv` | Pointer conversion rules | MISRA 11.1–11.9 |
| `misra-preproc` | Preprocessor rules | MISRA 19.1–19.2, 20.1–20.14 |
| `misra-stdlib` | Standard library rules | MISRA 21.1–21.12 |
| `misra-bitfields` | Bit-field rules | MISRA 6.1–6.2 |
| `misra-literals` | Literal rules | MISRA 7.1–7.4 |
| `misra-switch` | Switch statement rules | MISRA 16.1–16.7 |
| `misra-unions` | Union rules | MISRA 9.5 |
| `misra-identifiers` | Identifier rules | MISRA 5.1–5.9 |
| `misra-init` | Initialization rules | MISRA 9.1–9.3 |

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
corvia-lsp
```

This starts an LSP server that can be connected to from editors like VS Code, Neovim, etc.

---

## Development / 開發

```bash
# Install in dev mode
pip install -e .[dev]

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
│   ├── engine.py          # Analysis engine
│   ├── parser.py          # C parser wrapper (pycparser)
│   ├── models.py          # Data models
│   ├── registry.py        # Checker registry
│   ├── install.py         # C preprocessor installer
│   ├── checkers/          # Built-in checkers
│   │   ├── misra_switch.py
│   │   ├── misra_types.py
│   │   ├── null_deref.py
│   │   └── ...
│   ├── core/
│   │   ├── config.py      # Configuration (corvia.toml)
│   │   ├── cache.py       # Incremental cache
│   │   ├── symbol_table.py
│   │   ├── call_graph.py
│   │   ├── context.py
│   │   └── ...
│   ├── reporters/         # Output formatters
│   │   ├── json_reporter.py
│   │   ├── html_reporter.py
│   │   ├── md_reporter.py
│   │   └── base.py
│   └── lsp/               # LSP server
│       ├── server.py
│       └── converter.py
├── tests/
├── pyproject.toml
└── corvia.toml.example
```

---

## License / 授權

MIT

# Corvia — C Static Analyzer with MISRA C:2012 Support

> 🌐 [English](#english) | [中文](#中文)

Corvia is a Python-based static analysis tool for C. It detects bugs, undefined behaviour, and **122+ MISRA C:2012 rules across 20 sections** using AST-level checks, CFG-based dataflow, and inter-procedural cross-file analysis. It ships as a CLI (`corvia`), an LSP server (`corvia-lsp`), and a VS Code extension.

```
corvia src/                        # CLI
corvia-lsp --stdio                 # LSP server (any LSP-aware editor)
corvia src/ --format json -o r.json
corvia src/ --misra-only --misra-category required
```

---

<a name="english"></a>

## Table of Contents

- [Highlights](#highlights)
- [Installation](#installation)
- [60-Second Quick Start](#60-second-quick-start)
- [CLI Reference](#cli-reference)
- [Output Formats](#output-formats)
- [Severity Levels & Exit Codes](#severity-levels--exit-codes)
- [Configuration File (`corvia.toml`)](#configuration-file-corviatoml)
- [Checkers](#checkers)
- [MISRA C:2012 Coverage](#misra-c2012-coverage)
- [Inter-Procedural Analysis](#inter-procedural-analysis)
- [Incremental Analysis](#incremental-analysis)
- [LSP Server](#lsp-server)
- [VS Code Extension](#vs-code-extension)
- [Writing Your Own Checker](#writing-your-own-checker)
- [Architecture](#architecture)
- [Development](#development)
- [Troubleshooting](#troubleshooting)
- [Roadmap](#roadmap)

---

## Highlights

- **122+ MISRA C:2012 rules** across 20 sections
- **23 checkers** organized by concern (memory, null pointers, resources, MISRA categories…)
- **Inter-procedural / cross-file analysis** — wrappers like `xalloc`, `xopen`, `xfree` are recognized as allocators / openers / closers. Indirect recursion (`f → g → f`) is detected via Tarjan SCC over the call graph
- **CFG-based dataflow** for null-dereference, uninitialized variables, memory leaks, and resource leaks across `if`/`else`/`switch`/loop branches
- **Project-level config** (`corvia.toml`) for per-checker / per-rule severity overrides, includes, output, and cache settings
- **Incremental cache** — content-hash + reverse-dependency invalidation, only re-analyzes files that actually changed
- **LSP server** (`corvia-lsp`) for live editor diagnostics (any LSP-capable editor)
- **VS Code extension** under `extensions/vscode-corvia/`
- **Claude Code skill** — install once, use `corvia-review` in any C/C++ project for automatic code review
- **Multiple output formats**: text (color), JSON, Markdown, HTML
- **Pluggable checkers** via `--external-checkers <dir>`

---

## Installation

**Requirements**: Python 3.9+. Optional: a C preprocessor on `PATH` (`cpp`/`clang`) for `--use-cpp`.

### Option 1: Claude Code Skill (Easiest)

If you use Claude Code, install the **corvia-review** skill:

```bash
git clone --depth 1 https://github.com/kevintsou/Corvia.git /tmp/corvia && \
cp -r /tmp/corvia/corvia_skill ~/.claude/skills/ && \
rm -rf /tmp/corvia
```

Then use `@corvia-review` in any C/C++ project, or ask Claude: *"幫我 code review 整份專案"* or *"Analyze this project"*.

### Option 2: Local Install (Development)

```bash
# Clone & install
git clone https://github.com/kevintsou/Corvia.git
cd Corvia

# Base install
pip install -e .

# Add development tools (pytest, coverage)
pip install -e ".[dev]"

# Add LSP server (`corvia-lsp` console script)
pip install -e ".[dev,lsp]"
```

This installs two console scripts:

| Command | Purpose |
|---|---|
| `corvia` | CLI analyzer |
| `corvia-lsp` | Language server (only with `[lsp]` extras) |

---

## Step-by-Step Beginner Guide

If you've never used a static analyzer before, follow this walkthrough end-to-end.

### Step 1 — Check Python is installed

Open a terminal and run:

```bash
python3 --version
```

You should see something like `Python 3.11.5`. Corvia needs **Python 3.9 or newer**.

- **macOS**: `brew install python` (Homebrew) or use the python.org installer.
- **Linux (Ubuntu/Debian)**: `sudo apt install python3 python3-pip`.
- **Windows**: download from <https://python.org> and tick "Add Python to PATH" during install.

### Step 2 — Get the code

```bash
git clone https://github.com/kevintsou/Corvia.git
cd Corvia
```

If you don't have `git`:

- **macOS**: `xcode-select --install`
- **Linux**: `sudo apt install git`
- **Windows**: <https://git-scm.com/download/win>

### Step 3 — Install Corvia

From the repository root:

```bash
pip install -e ".[dev,lsp]"
```

The `[dev,lsp]` part installs both test tooling and the LSP server. Verify both binaries land on your PATH:

```bash
corvia --version            # should print: corvia 0.1.0
corvia-lsp --help           # should show LSP options
```

If `command not found`, your shell isn't seeing pip's bin directory. Either restart your shell, or use the full path printed by:

```bash
python3 -m pip show -f corvia | grep -E 'Location|console_scripts'
```

### Step 4 — Try it on a sample file

Create a deliberately broken C file:

```c
/* hello.c */
#include <stdlib.h>

int main(void) {
    int *p = NULL;
    *p = 42;                /* null deref — should be flagged */

    char *buf = malloc(16); /* leaked — never freed */

    int unused;             /* warning */

    return 0;
}
```

Run Corvia:

```bash
corvia hello.c
```

You should see something like:

```
hello.c:5:5: error[null-deref] (MISRA C:2012 Rule 1.3 Required): Dereference of NULL pointer 'p'
hello.c:7:11: warning[memory-leak] (MISRA C:2012 Rule 22.1 Required): Potential memory leak: 'buf' allocated but not freed on all paths
hello.c:9:9: warning[unused-var] (MISRA C:2012 Rule 2.2 Required): Unused variable 'unused'

Summary: 3 issues (1 errors, 2 warnings, 0 info) in 1 files
MISRA rules violated: 3
```

Read each line as `file:line:column: severity[checker-id] (rule): message`.

### Step 5 — Try the JSON / HTML report (optional)

```bash
corvia hello.c --format json --output report.json
corvia hello.c --format html --output report.html
```

Open `report.html` in any browser to see a polished view.

### Step 6 — Make Corvia silent except for serious issues

```bash
corvia src/ --severity error            # only error-level
corvia src/ --misra-only                # only MISRA violations
corvia src/ --misra-only --misra-category mandatory
```

### Step 7 — Set up a project config

Create `corvia.toml` next to your source tree:

```toml
[checkers]
disabled = ["misra-unions"]

[severity]
"21.3" = "info"

[paths]
include = ["./include"]

[cache]
enabled = true
```

Then just run `corvia src/` — the file is auto-discovered. To verify:

```bash
corvia src/        # stderr will print "Using config: /abs/path/corvia.toml"
```

To temporarily ignore the file: `corvia src/ --no-config`.

### Step 8 — Speed up repeated runs

```bash
corvia src/ --incremental
```

The first run analyzes everything; later runs only re-check files whose SHA-256 changed (or whose dependencies changed). Cache lives in `.corvia_cache/`. Remove it any time:

```bash
corvia --clean-cache
```

### Step 9 — Run inside CI (GitHub Actions example)

```yaml
# .github/workflows/corvia.yml
name: Corvia
on: [push, pull_request]

jobs:
  analyze:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - run: pip install git+https://github.com/kevintsou/Corvia.git
      - run: corvia src/ --format json --output corvia-report.json
      - uses: actions/upload-artifact@v4
        with:
          name: corvia-report
          path: corvia-report.json
```

`corvia` exits **1** when `error`-severity issues exist, so the job fails automatically.

---

## Step-by-Step: Editor Integration

This section walks through wiring Corvia into your editor so you see diagnostics live, on every save.

### A. VS Code (recommended for beginners)

**A1.** Make sure the LSP server is installed:

```bash
pip install -e ".[lsp]"
which corvia-lsp                # macOS / Linux
where corvia-lsp                # Windows
```

If `which`/`where` shows a path, you're set. If not, see Troubleshooting below.

**A2.** Build the extension once (you only need to do this the first time):

```bash
cd extensions/vscode-corvia
npm install
npm run compile
```

You'll need Node.js 18+ ([nodejs.org](https://nodejs.org)) for `npm`.

**A3.** Install the extension into VS Code. Two options:

**Option 1 — Run from source (great for hacking on the extension)**

1. Open the `extensions/vscode-corvia/` folder in VS Code.
2. Press <kbd>F5</kbd>. A new "Extension Development Host" window opens.
3. Open any `.c` file there — you'll see Corvia's diagnostics in the gutter.

**Option 2 — Package and install (one-time install)**

```bash
cd extensions/vscode-corvia
npm run package                              # creates vscode-corvia-0.1.0.vsix
code --install-extension vscode-corvia-0.1.0.vsix
```

Restart VS Code. Open any C file — you should see squiggles for Corvia findings.

**A4.** Configure (optional). Open VS Code's settings (<kbd>Ctrl/Cmd</kbd>+<kbd>,</kbd>) and search for `corvia`:

| Setting | Default | When to change |
|---|---|---|
| `corvia.serverPath` | `corvia-lsp` | Set absolute path if VS Code can't find the binary. |
| `corvia.transport` | `stdio` | Change to `tcp` only if you run `corvia-lsp` separately. |
| `corvia.tcp.host` / `corvia.tcp.port` | `127.0.0.1` / `9999` | TCP coordinates. |
| `corvia.trace.server` | `off` | Set to `verbose` to debug LSP traffic in the Output panel. |

**A5.** Use the commands. <kbd>Ctrl/Cmd</kbd>+<kbd>Shift</kbd>+<kbd>P</kbd> opens the command palette. Useful entries:

- **Corvia: Restart Language Server** — after editing `corvia.toml` or upgrading the Python package
- **Corvia: Show Output Channel** — see the raw LSP transcript and any startup errors

**A6.** Verify it works.

1. Create `test.c` with the snippet from Step 4 above.
2. Save the file.
3. You should see red/yellow squiggles within a second.
4. Hover over a squiggle to read the message and MISRA rule.

If diagnostics never appear:
1. **Corvia: Show Output Channel** — read the error.
2. The most common cause is `corvia-lsp` not being on PATH. Set `corvia.serverPath` to the absolute path printed by `which corvia-lsp`.

### B. Neovim (built-in LSP)

Add to `init.lua`:

```lua
vim.api.nvim_create_autocmd("FileType", {
  pattern = "c",
  callback = function()
    vim.lsp.start({
      name = "corvia",
      cmd = { "corvia-lsp", "--stdio" },
      root_dir = vim.fs.dirname(
        vim.fs.find({ "corvia.toml", ".git" }, { upward = true })[1]
      ),
    })
  end,
})
```

Open any `.c` file — `:LspInfo` should show `corvia` running. Diagnostics appear via `:lua vim.diagnostic.config({ virtual_text = true })`.

### C. Emacs (eglot, built into Emacs 29+)

```elisp
(with-eval-after-load 'eglot
  (add-to-list 'eglot-server-programs
               '(c-mode . ("corvia-lsp" "--stdio"))))
;; Or for `lsp-mode`:
(with-eval-after-load 'lsp-mode
  (lsp-register-client
    (make-lsp-client
      :new-connection (lsp-stdio-connection '("corvia-lsp" "--stdio"))
      :major-modes '(c-mode)
      :server-id 'corvia)))
```

Then `M-x eglot` (or `lsp`) inside a C buffer.

### D. Helix

`~/.config/helix/languages.toml`:

```toml
[language-server.corvia]
command = "corvia-lsp"
args = ["--stdio"]

[[language]]
name = "c"
language-servers = ["corvia"]
```

### E. Sublime Text (LSP plugin)

Install the [LSP package](https://packagecontrol.io/packages/LSP), then:

```jsonc
// LSP user settings
{
  "clients": {
    "corvia": {
      "command": ["corvia-lsp", "--stdio"],
      "selector": "source.c"
    }
  }
}
```

Run **LSP: Enable Language Server Globally → corvia**.

### F. Standalone LSP server (any LSP client)

```bash
corvia-lsp --stdio                          # default
corvia-lsp --tcp --host 127.0.0.1 --port 9999
corvia-lsp --stdio -v                       # verbose logs on stderr
```

The server publishes diagnostics on `textDocument/didOpen` and `textDocument/didSave`. Each diagnostic has a stable `code` like `null-deref:MISRA-1.3` and a `codeDescription.href` linking to the MISRA rule's official page.

---

## 60-Second Quick Start

```bash
# 1. Analyze one file
corvia path/to/file.c

# 2. Analyze a whole directory (recursive .c discovery)
corvia src/

# 3. JSON report to file (good for CI)
corvia src/ --format json --output report.json

# 4. Only MISRA Required violations
corvia src/ --misra-only --misra-category required

# 5. Run only two checkers
corvia src/ --checkers null-deref,memory-leak

# 6. Speed up repeated runs
corvia src/ --incremental

# 7. List every available checker
corvia --list-checkers
```

If any `error`-severity issue is reported, `corvia` exits **1** so it slots straight into a CI pipeline.

---

## CLI Reference

Every flag of the `corvia` CLI:

### Targets

| Argument | Meaning |
|---|---|
| `targets...` | One or more files or directories to analyze. Directories are searched recursively for `*.c`. |

### Checker selection

| Flag | Default | Description |
|---|---|---|
| `-c`, `--checkers <ids>` | all | Comma-separated checker IDs to run. Example: `--checkers null-deref,memory-leak`. |
| `--external-checkers <dir>` | — | Directory with extra Python modules that register their own checkers. |
| `--list-checkers` | — | Print every registered checker (built-in + external) and exit. |

### Output

| Flag | Default | Description |
|---|---|---|
| `-f`, `--format <fmt>` | `text` | One of `text`, `json`, `md`, `html`. |
| `-o`, `--output <path>` | stdout | Write the report to a file instead of stdout. |
| `--no-color` | off | Disable ANSI colors in text output. |

### Filtering

| Flag | Default | Description |
|---|---|---|
| `-s`, `--severity <lvl>` | `info` | Minimum severity to report: `info` / `warning` / `error`. |
| `--misra-only` | off | Drop issues that don't carry a MISRA rule. |
| `--misra-category <cat>` | — | Filter by MISRA category: `mandatory` / `required` / `advisory`. |

### Parsing

| Flag | Default | Description |
|---|---|---|
| `--use-cpp` | off | Run the C preprocessor before parsing (needed for macro-heavy code). |
| `-I`, `--include <dir>` | — | Add an include directory; repeatable. Implies `--use-cpp`-style include search even without `--use-cpp` when used by the parser. |

### Incremental cache

| Flag | Default | Description |
|---|---|---|
| `--incremental` | off | Reuse cached results when a file's SHA-256 hasn't changed. |
| `--cache-dir <path>` | `.corvia_cache` | Where to write the cache. |
| `--clean-cache` | — | Delete every cache entry under `--cache-dir` and exit. |

### Configuration file

| Flag | Default | Description |
|---|---|---|
| `--config <path>` | auto | Use this `corvia.toml` instead of the auto-discovered one. |
| `--no-config` | off | Ignore `corvia.toml` entirely; rely on CLI flags only. |

### Misc

| Flag | Description |
|---|---|
| `-V`, `--version` | Print version and exit. |
| `-h`, `--help` | Show help and exit. |

---

## Output Formats

### Text (default)

```
test.c:12:5: error[null-deref] (MISRA C:2012 Rule 1.3 Required): Dereference of NULL pointer 'p'
test.c:20:3: warning[uninit-var] (MISRA C:2012 Rule 9.1 Required): Variable 'x' may be used uninitialized
test.c:35:1: error[memory-leak] (MISRA C:2012 Rule 22.1 Required): Memory allocated to 'buf' is never freed

Summary: 3 issues (2 errors, 1 warning, 0 info) in 1 file
MISRA rules violated: 3
```

`error` is red, `warning` yellow, `info` cyan when stdout is a TTY. Pipe to a file or pass `--no-color` to strip ANSI.

### JSON (`--format json`)

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
  "issues": [
    {
      "checker_id": "null-deref",
      "severity": "ERROR",
      "message": "Dereference of NULL pointer 'p'",
      "file": "src/main.c",
      "line": 12,
      "column": 5,
      "misra_rule": {
        "rule_id": "1.3",
        "category": "Required",
        "description": "..."
      }
    }
  ]
}
```

Stable schema — safe to consume from scripts and CI dashboards.

### Markdown (`--format md`)

A rendered Markdown report grouped by file and MISRA rule, suitable for code-review comments or PR templates.

### HTML (`--format html`)

A self-contained HTML page (Jinja2 template) for human browsing. Open with any browser.

---

## Severity Levels & Exit Codes

| Level | Use |
|---|---|
| `error` | Definite undefined behaviour or hard MISRA violations |
| `warning` | Likely bugs / suspicious patterns / Required-without-confirmation |
| `info` | Style / Advisory / hints |

| Exit code | Meaning |
|---|---|
| `0` | No `error`-severity issues |
| `1` | At least one `error` issue |
| `2` | Misuse of CLI / invalid `corvia.toml` |

---

## Configuration File (`corvia.toml`)

`corvia` looks for a `corvia.toml` walking upward from the current directory. CLI flags always win over the file. Pass `--no-config` to ignore.

Full schema — every section is optional:

```toml
[checkers]
# If `enabled` is set, only these run.
enabled  = ["null-deref", "memory-leak", "misra-types"]
# `disabled` is subtracted from the enabled set (or from "all" if enabled is unset).
disabled = ["misra-unions"]

[severity]
# Keys may be a checker id (e.g. "misra-stdlib") OR a MISRA rule id ("21.3").
# Values: "error" | "warning" | "info" | "off"
# Rule-id keys take precedence over checker-id keys for the same finding.
"misra-stdlib" = "error"     # promote every misra-stdlib finding to error
"21.3"         = "info"      # demote rule 21.3 specifically
"19.2"         = "off"       # silence rule 19.2 entirely

[paths]
include = ["/usr/local/include", "vendor/include"]   # -I equivalents
use_cpp = true                                       # invoke cpp before parsing

[output]
format   = "text"            # default format: text / json / md / html
no_color = false             # disable ANSI colors

[cache]
enabled = true               # equivalent to --incremental
dir     = ".corvia_cache"    # where to put cached results
```

When loaded, the CLI prints `Using config: /path/to/corvia.toml` to stderr.

---

## Checkers

`corvia --list-checkers` shows the live, registered list. Built-in:

| ID | Description | MISRA rules |
|---|---|---|
| `syntax` | Assignment in condition, missing braces | 13.4, 15.6 |
| `unused-var` | Unused vars, parameters, **tags (2.4)**, **labels (2.6)** | 2.2, 2.3, 2.4, 2.6, 2.7 |
| `uninit-var` | Use of uninitialized variables (CFG) | 9.1 |
| `dead-code` | Unreachable code, invariant conditions | 2.1, 14.3 |
| `null-deref` | NULL deref via `*`, `->`, `[]` (CFG + summaries) | 1.3 |
| `buffer-overflow` | Constant-index out-of-bounds on fixed arrays | 1.3, 18.1 |
| `memory-leak` | malloc/calloc/realloc without free (CFG + summaries) | 22.1, 22.2 |
| `resource-leak` | fopen/popen without fclose, **FILE* deref (22.5)**, use-after-close | 22.1, 22.5, 22.6 |
| `misra-types` | Implicit/narrowing conversions, sign mixing | 10.1–10.8 |
| `misra-decl` | extern misuse, static/inline rules, missing types | 8.1–8.14 |
| `misra-expr` | Operator precedence, side effects, comma operator | 12.1–12.5, 13.1–13.6 |
| `misra-control` | goto, if-else completeness | 14.1–14.4, 15.1–15.7 |
| `misra-func` | stdarg, **indirect recursion (17.2)**, **unused return (17.7)** | 17.1–17.8 |
| `misra-pointer` | Pointer arithmetic, array decay, function pointers | 18.1–18.8 |
| `misra-preproc` | Macro restrictions (AST-detectable subset) | 20.7, 20.10–20.12, 20.14 |
| `misra-identifiers` | External / typedef / tag / linkage uniqueness, scope shadowing | 5.1, 5.3, 5.6–5.9 |
| `misra-pointer-conv` | Function-ptr / object-ptr / void-ptr / qualifier casts, NULL constant | 11.1–11.9 |
| `misra-stdlib` | Forbidden Standard Library, reserved identifiers, **emergent features (1.4)** | 1.4, 21.1–21.10, 21.12 |
| `misra-bitfields` | Bit-field type allow-list, signed single-bit | 6.1, 6.2 |
| `misra-literals` | Octal constants, lowercase `l` suffix, string-to-non-const | 7.1, 7.3, 7.4 |
| `misra-switch` | Well-formedness, default presence/position, missing break, boolean switch, label position (16.2) | 16.1–16.7 |
| `misra-unions` | union usage discouraged | 19.2 |
| `misra-init` | Aggregate / union must be brace-enclosed; arrays must be fully initialized | 9.2, 9.3 |

### Examples — bad vs good

**`null-deref` (1.3)**
```c
int *get_ptr(void);
void use(void) {
    int *p = get_ptr();   // Corvia knows get_ptr may return NULL
    *p = 1;               // ❌ error[null-deref]
}
```
Fix:
```c
int *p = get_ptr();
if (p != NULL) {
    *p = 1;               // ✅
}
```

**`memory-leak` (22.1)**
```c
void *xalloc(unsigned long n) { return malloc(n); }   // wrapper

void leaky(void) {
    char *p = xalloc(16); // ❌ Corvia recognizes xalloc as allocator
}                         //    error[memory-leak]: 'p' not freed
```

**`misra-switch` (16.4 / 16.6)**
```c
switch (x) {              // ❌ warning[misra-switch] (16.4): no default
    case 1: y = 1; break; // ❌ warning[misra-switch] (16.6): only 1 clause
}
```

**`misra-bitfields` (6.1 / 6.2)**
```c
struct flags {
    char small : 2;       // ❌ 6.1: char not allowed
    int single : 1;       // ❌ 6.2: signed single-bit
    unsigned int ok : 4;  // ✅
};
```

**`misra-stdlib` (1.4)**
```c
#include <threads.h>
thrd_t worker;           // ❌ warning (1.4): emergent feature 'thrd_t'
thrd_create(&worker, ...);
```

---

## MISRA C:2012 Coverage

<details>
<summary>All 122+ implemented rules (click to expand)</summary>

| Section | Rules | Checker(s) |
|---|---|---|
| §1 Standards / Undefined Behaviour | 1.3, 1.4 | `null-deref`, `buffer-overflow`, `misra-stdlib` |
| §2 Unused Code | 2.1, 2.2, 2.3, 2.4, 2.6, 2.7 | `dead-code`, `unused-var` |
| §5 Identifiers | 5.1, 5.3, 5.6, 5.7, 5.8, 5.9 | `misra-identifiers` |
| §6 Types (bit-fields) | 6.1, 6.2 | `misra-bitfields` |
| §7 Literals & Constants | 7.1, 7.3, 7.4 | `misra-literals` |
| §8 Declarations & Definitions | 8.1–8.14 | `misra-decl` |
| §9 Initialization | 9.1, 9.2, 9.3 | `uninit-var`, `misra-init` |
| §10 Type Conversions | 10.1–10.8 | `misra-types` |
| §11 Pointer Type Conversions | 11.1–11.9 | `misra-pointer-conv` |
| §12 Expressions | 12.1–12.5 | `misra-expr` |
| §13 Side Effects | 13.1–13.6 | `misra-expr`, `syntax` |
| §14 Control Flow | 14.1–14.4 | `misra-control`, `dead-code` |
| §15 Control Flow (if/switch) | 15.1–15.7 | `misra-control`, `syntax` |
| §16 Switch Statements | 16.1, 16.2, 16.3, 16.4, 16.5, 16.6, 16.7 | `misra-switch` |
| §17 Functions | 17.1–17.8 | `misra-func` |
| §18 Pointers & Arrays | 18.1–18.8 | `misra-pointer`, `buffer-overflow` |
| §19 Overlapping Storage | 19.2 | `misra-unions` |
| §20 Preprocessing | 20.7, 20.10–20.12, 20.14 | `misra-preproc` |
| §21 Standard Libraries | 21.1, 21.2, 21.3, 21.4, 21.5, 21.6, 21.7, 21.8, 21.9, 21.10, 21.12 | `misra-stdlib` |
| §22 Resources | 22.1, 22.2, 22.5, 22.6 | `memory-leak`, `resource-leak` |

</details>

---

## Inter-Procedural Analysis

Phase 3 added a two-pass pipeline so every checker can ask cross-function and cross-file questions in O(1):

```
Pass 1: parse all targets
  ↓
  build SymbolTable    (cross-file globals, statics, typedefs, tags)
  ↓
  build CallGraph      (every FuncCall edge; Tarjan SCC for recursion)
  ↓
  compute Summaries    (bottom-up over SCCs; fixpoint inside cycles)
  ↓
Pass 2: every checker runs against every AST with shared AnalysisContext
```

Each `FunctionSummary` records `allocates`, `opens_resource`, `frees_param`, `closes_param`, `returns_null`, `params_must_not_be_null`, `has_side_effects`, `is_recursive`. That's how `null-deref` knows your `get_or_default()` wrapper might return NULL, and how `memory-leak` knows your `xalloc()` is really `malloc`.

---

## Incremental Analysis

```bash
corvia src/ --incremental
```

For each analyzed file, Corvia stores:

- SHA-256 of the file content
- Last produced issues
- The list of external functions the file **calls** (callees)
- The list of external functions the file **defines** (defines)

On the next run a file is re-analyzed only if its hash changed, or if a file it depends on (via callees → defines) changed. Cache lives in `.corvia_cache/` by default. Clear it with:

```bash
corvia --clean-cache
```

---

## LSP Server

`corvia-lsp` speaks the standard LSP. It analyzes a document on `didOpen` and `didSave` and publishes diagnostics with a stable `code` like `null-deref:MISRA-1.3` plus a `codeDescription.href` pointing at the official MISRA rule page.

```bash
# Default: stdio
corvia-lsp --stdio

# TCP (useful for some editors / docker)
corvia-lsp --tcp --host 127.0.0.1 --port 9999

# More verbose logging on stderr
corvia-lsp --stdio -v
```

Compatible with any LSP-aware editor (VS Code, Neovim, Helix, Emacs `eglot`/`lsp-mode`, Sublime LSP, IntelliJ LSP4IJ…).

### Neovim example

```lua
vim.lsp.start({
  name = "corvia",
  cmd = { "corvia-lsp", "--stdio" },
  filetypes = { "c" },
  root_dir = vim.fs.dirname(vim.fs.find({ "corvia.toml", ".git" }, { upward = true })[1]),
})
```

---

## VS Code Extension

The extension lives in `extensions/vscode-corvia/`.

```bash
cd extensions/vscode-corvia
npm install
npm run compile

# Either install in dev mode via "Developer: Install Extension from Location…"
# or package and install:
npm run package          # produces vscode-corvia-0.1.0.vsix
code --install-extension vscode-corvia-0.1.0.vsix
```

You also need `corvia-lsp` on `PATH`:

```bash
pip install 'corvia[lsp]'
which corvia-lsp
```

### Settings

| Setting | Default | Purpose |
|---|---|---|
| `corvia.serverPath` | `corvia-lsp` | Override if not on `PATH` |
| `corvia.transport` | `stdio` | `stdio` or `tcp` |
| `corvia.tcp.host` | `127.0.0.1` | TCP host |
| `corvia.tcp.port` | `9999` | TCP port |
| `corvia.trace.server` | `off` | LSP trace level: `off` / `messages` / `verbose` |

### Commands

- **Corvia: Restart Language Server**
- **Corvia: Show Output Channel**

---

## Writing Your Own Checker

A checker is a `BaseChecker` subclass that visits AST nodes via pycparser's NodeVisitor protocol. Drop the file into a directory and pass `--external-checkers <dir>`.

```python
# my_checkers/single_return.py
from pycparser import c_ast
from corvia.checkers.base import BaseChecker
from corvia.models import MisraRule, MisraCategory, Severity
from corvia.registry import CheckerRegistry

MY_RULE = MisraRule(
    "15.5", MisraCategory.ADVISORY,
    "A function should have a single point of exit",
)

class SingleReturnChecker(BaseChecker):
    checker_id = "single-return"
    description = "Enforce a single return per function"
    default_severity = Severity.WARNING
    misra_rules = [MY_RULE]

    def visit_FuncDef(self, node: c_ast.FuncDef) -> None:
        returns = []
        self._count_returns(node.body, returns)
        if len(returns) > 1:
            self.report(
                returns[1],
                f"Function '{node.decl.name}' has {len(returns)} return statements",
                Severity.WARNING,
                MY_RULE,
            )
        self.generic_visit(node)

    def _count_returns(self, node, out):
        if isinstance(node, c_ast.Return):
            out.append(node)
        for _, child in node.children():
            self._count_returns(child, out)


CheckerRegistry.register(SingleReturnChecker)
```

```bash
corvia src/ --external-checkers ./my_checkers/
corvia src/ --checkers single-return --external-checkers ./my_checkers/
```

Optional: use the inter-procedural context inside your checker.

```python
def visit_FuncCall(self, node):
    if self._ctx is None:
        return
    if isinstance(node.name, c_ast.ID):
        s = self._ctx.summary_of(node.name.name)
        if s and s.allocates:
            ...   # this call returns freshly allocated memory
```

---

## Architecture

```
src/corvia/
├── cli.py                  # Argument parsing, colored output, entry point
├── engine.py               # Two-pass orchestrator (parse-all → context → checkers)
├── parser.py               # pycparser wrapper with fake libc headers
├── registry.py             # Checker auto-discovery + external loader
├── models.py               # Issue, MisraRule, Severity, AnalysisResult
├── core/
│   ├── cfg.py              # Control Flow Graph builder
│   ├── dataflow.py         # Generic ForwardAnalysis / BackwardAnalysis
│   ├── symbol_table.py     # Cross-file SymbolTable + tag/typedef tracking
│   ├── call_graph.py       # CallGraph + Tarjan SCC
│   ├── summary.py          # FunctionSummary bottom-up computation
│   ├── context.py          # AnalysisContext bundle
│   ├── cache.py            # Content-hash incremental cache
│   └── config.py           # corvia.toml loader & validation
├── checkers/
│   ├── base.py             # BaseChecker (NodeVisitor + report() + set_context())
│   ├── null_deref.py
│   ├── memory_leak.py
│   ├── resource_leak.py
│   ├── misra_*.py          # 14 MISRA-specific modules
│   └── ...                 # 9 more
├── lsp/
│   ├── converter.py        # Issue → LSP Diagnostic (pygls-free)
│   └── server.py           # corvia-lsp entry point
└── reporters/
    ├── json_reporter.py
    ├── md_reporter.py
    └── html_reporter.py

extensions/
└── vscode-corvia/          # VS Code wrapper around corvia-lsp
```

---

## Development

```bash
# Install with dev + LSP extras
pip install -e ".[dev,lsp]"

# Run all tests
pytest tests/ -v

# Coverage
pytest tests/ --cov=corvia --cov-report=html

# Run a specific checker's tests
pytest tests/test_checkers/test_null_deref.py -v

# Run only inter-procedural integration tests
pytest tests/test_core/test_inter_procedural.py -v
```

Total suite: **150 tests passing**.

```
tests/
├── fixtures/           # C source files used as test inputs
├── test_checkers/      # Per-checker unit tests
├── test_core/          # CFG, dataflow, symbol_table, call_graph,
│                       # summary, cache, config tests
├── test_lsp/           # LSP converter + server smoke tests
├── test_reporters/     # JSON / Markdown reporter tests
├── test_engine.py
└── test_parser.py
```

---

## Troubleshooting

**`ModuleNotFoundError: No module named 'corvia'`**
You haven't installed the package. Run `pip install -e ".[dev]"` from the repo root.

**`pycparser.plyparser` import error**
You're on pycparser ≥ 3.0; `parser.py` already includes a compatibility shim. If you see this, your install is stale — reinstall.

**`corvia-lsp: command not found`**
Install the LSP extras: `pip install -e ".[lsp]"`. Or set `corvia.serverPath` in VS Code to the absolute path.

**Extension can't start the server**
`Corvia: Show Output Channel` shows the spawn error. Most often `corvia-lsp` isn't on the editor's PATH (some editors don't inherit your shell's PATH). Set `corvia.serverPath` to an absolute path.

**Lots of MISRA-stdlib noise about `printf`/`malloc`**
Either silence at the source (`#define`-style allow-lists upstream of corvia) or override severities in `corvia.toml`:
```toml
[severity]
"21.3" = "info"
"21.6" = "off"
```

**`Comments are not supported` parse error**
pycparser doesn't strip comments without a preprocessor. Add `--use-cpp` (and `-I` flags for your headers) so `cpp` runs first.

**Wrapper allocator not detected**
Make sure both wrapper and caller are passed in the same invocation (e.g. `corvia src/`). Cross-file analysis needs both files to be parsed in the same run.

---

## Roadmap

- [x] **Phase 1 & 2** — AST checkers, CFG / dataflow framework, MISRA §1, §2, §8–§10, §12–§15, §17, §18, §20, §22
- [x] **Phase 3** — SymbolTable + CallGraph + FunctionSummary; MISRA §5, §11, §21; incremental cache; LSP server
- [x] **Phase 4** — MISRA §6, §7, §16, §19
- [x] **Phase 5** — 7 more rules across §1, §2, §9, §16, §22; `corvia.toml` project config
- [x] **Phase 6** — VS Code extension under `extensions/vscode-corvia/`

---

## License

MIT

---

<a name="中文"></a>

## 目錄（中文）

- [特色](#特色)
- [安裝](#安裝)
- [新手逐步教學](#新手逐步教學)
- [編輯器整合](#編輯器整合)
- [60 秒快速入門](#60-秒快速入門)
- [CLI 完整旗標說明](#cli-完整旗標說明)
- [輸出格式](#輸出格式)
- [Severity 與 Exit Code](#severity-與-exit-code)
- [設定檔 corvia.toml](#設定檔-corviatoml)
- [Checker 一覽](#checker-一覽)
- [MISRA C:2012 涵蓋範圍](#misra-c2012-涵蓋範圍)
- [跨函式分析](#跨函式分析)
- [增量分析](#增量分析)
- [LSP 伺服器](#lsp-伺服器)
- [VS Code 擴充套件](#vs-code-擴充套件)
- [撰寫自訂 Checker](#撰寫自訂-checker)
- [架構](#架構)
- [開發](#開發)
- [疑難排解](#疑難排解)
- [Roadmap](#roadmap-中文)

---

## 特色

- **122+ 條 MISRA C:2012 規則**，涵蓋 20 個章節
- **23 個 checker**，按功能分類（記憶體、空指標、資源、MISRA 各章節…）
- **跨函式 / 跨檔分析** — `xalloc`、`xopen`、`xfree` 等 wrapper 會被識別為配置器／開啟器／釋放器；透過 Tarjan SCC 偵測間接遞迴（`f → g → f`）
- **CFG 資料流分析** — 空指標解參考、未初始化變數、記憶體洩漏、資源洩漏，在 `if`/`else`/`switch`/迴圈各分支都能追蹤
- **專案級設定檔**（`corvia.toml`）— 可調整各 checker／各規則的嚴重等級、include 路徑、輸出格式、快取設定
- **增量快取** — 以 SHA-256 內容雜湊 + 反向相依性失效，只重新分析真正有變動的檔案
- **LSP 伺服器**（`corvia-lsp`）— 任何支援 LSP 的編輯器均可獲得即時診斷
- **VS Code 擴充套件** — 位於 `extensions/vscode-corvia/`
- **Claude Code Skill** — 安裝一次，在任何 C/C++ 專案中使用 `corvia-review`，即可自動執行程式碼審查
- **多種輸出格式**：text（彩色）、JSON、Markdown、HTML
- **可插拔 checker** — 透過 `--external-checkers <dir>` 載入自訂模組

---

## 安裝

**需求**：Python 3.9+。選用：`PATH` 上有 C 前處理器（`cpp` / `clang`）以使用 `--use-cpp`。

### 方法一：Claude Code Skill（最簡單）

如果你使用 Claude Code，安裝 **corvia-review** skill：

```bash
git clone --depth 1 https://github.com/kevintsou/Corvia.git /tmp/corvia && \
cp -r /tmp/corvia/corvia_skill ~/.claude/skills/ && \
rm -rf /tmp/corvia
```

安裝後，在任何 C/C++ 專案中對 Claude 說「幫我 code review 整份專案」或「分析這個專案」，即可自動執行。

### 方法二：本機安裝（開發用）

```bash
git clone https://github.com/kevintsou/Corvia.git
cd Corvia

# 基本安裝
pip install -e .

# 加入開發工具（pytest、coverage）
pip install -e ".[dev]"

# 加入 LSP 伺服器（corvia-lsp 指令）
pip install -e ".[dev,lsp]"
```

安裝後會有兩個指令：

| 指令 | 用途 |
|---|---|
| `corvia` | CLI 分析工具 |
| `corvia-lsp` | LSP 語言伺服器（需安裝 `[lsp]` extras） |

---

## 新手逐步教學

如果你從未使用過靜態分析工具，請按照以下步驟操作。

### 步驟 1 — 確認 Python 已安裝

開啟終端機，執行：

```bash
python3 --version
```

應看到類似 `Python 3.11.5` 的輸出。Corvia 需要 **Python 3.9 以上**。

- **macOS**：`brew install python`（Homebrew）或至 python.org 下載安裝程式。
- **Linux（Ubuntu/Debian）**：`sudo apt install python3 python3-pip`。
- **Windows**：至 <https://python.org> 下載，安裝時記得勾選「Add Python to PATH」。

### 步驟 2 — 取得程式碼

```bash
git clone https://github.com/kevintsou/Corvia.git
cd Corvia
```

若沒有 `git`：

- **macOS**：`xcode-select --install`
- **Linux**：`sudo apt install git`
- **Windows**：<https://git-scm.com/download/win>

### 步驟 3 — 安裝 Corvia

在專案根目錄執行：

```bash
pip install -e ".[dev,lsp]"
```

`[dev,lsp]` 會同時安裝測試工具和 LSP 伺服器。驗證兩個指令是否在 PATH 上：

```bash
corvia --version      # 應顯示：corvia 0.1.0
corvia-lsp --help     # 應顯示 LSP 選項
```

若出現 `command not found`，表示 shell 找不到 pip 的 bin 目錄。重新開啟 shell，或用以下指令查出完整路徑：

```bash
python3 -m pip show -f corvia | grep -E 'Location|console_scripts'
```

### 步驟 4 — 試跑範例檔案

建立一個故意有問題的 C 檔案（不含 comments，pycparser 不支援）：

```c
typedef void *voidp;
typedef unsigned long size_t;
void *malloc(size_t n);

int main(void) {
    int *p = 0;
    *p = 42;

    char *buf = (char *)malloc(16);
    (void)buf;

    int unused;
    (void)unused;

    return 0;
}
```

執行 Corvia：

```bash
corvia hello.c
```

你應該會看到類似：

```
hello.c:6:9: error[null-deref]: Dereference of NULL pointer 'p'
hello.c:9:16: warning[memory-leak]: 'buf' allocated but not freed
hello.c:12:9: warning[unused-var]: Unused variable 'unused'

Summary: 3 issues (1 errors, 2 warnings, 0 info) in 1 files
```

每行格式為 `檔案:行:欄: 嚴重等級[checker-id]: 訊息`。

### 步驟 5 — 試用 JSON / HTML 報告（選用）

```bash
corvia hello.c --format json --output report.json
corvia hello.c --format html --output report.html
```

用瀏覽器開啟 `report.html` 可看到精美的報告頁面。

### 步驟 6 — 只顯示嚴重問題

```bash
corvia src/ --severity error          # 只顯示 error 等級
corvia src/ --misra-only              # 只顯示 MISRA 違規
corvia src/ --misra-only --misra-category mandatory
```

### 步驟 7 — 建立專案設定檔

在原始碼目錄旁建立 `corvia.toml`：

```toml
[checkers]
disabled = ["misra-unions"]

[severity]
"21.3" = "info"

[paths]
include = ["./include"]

[cache]
enabled = true
```

之後直接執行 `corvia src/`，設定檔會自動被找到。

```bash
corvia src/        # stderr 會顯示 "Using config: /path/corvia.toml"
```

暫時忽略設定檔：`corvia src/ --no-config`。

### 步驟 8 — 加速重複分析

```bash
corvia src/ --incremental
```

第一次會完整分析並建立快取；之後只重新檢查 SHA-256 有變化的檔案。快取存在 `.corvia_cache/`，可隨時清除：

```bash
corvia --clean-cache
```

### 步驟 9 — 在 CI 中執行（GitHub Actions 範例）

```yaml
# .github/workflows/corvia.yml
name: Corvia
on: [push, pull_request]

jobs:
  analyze:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - run: pip install git+https://github.com/kevintsou/Corvia.git
      - run: corvia src/ --format json --output corvia-report.json
      - uses: actions/upload-artifact@v4
        with:
          name: corvia-report
          path: corvia-report.json
```

有 `error` 等級的問題時，`corvia` 會以 exit code **1** 結束，CI 會自動失敗。

---

## 編輯器整合

### A. VS Code（新手推薦）

**A1.** 確認 LSP 伺服器已安裝：

```bash
pip install -e ".[lsp]"
which corvia-lsp      # macOS / Linux
where corvia-lsp      # Windows
```

**A2.** 建置擴充套件（只需執行一次）：

```bash
cd extensions/vscode-corvia
npm install
npm run compile
```

需要 Node.js 18+（[nodejs.org](https://nodejs.org)）。

**A3.** 安裝擴充套件，兩種方式：

**方式一 — 從原始碼執行（適合修改擴充套件）**

1. 用 VS Code 開啟 `extensions/vscode-corvia/` 目錄。
2. 按 <kbd>F5</kbd>，會開啟新的「Extension Development Host」視窗。
3. 在那個視窗開啟任意 `.c` 檔，即可在欄位看到 Corvia 診斷。

**方式二 — 封裝後安裝（一次性安裝）**

```bash
cd extensions/vscode-corvia
npm run package                              # 產生 vscode-corvia-0.1.0.vsix
code --install-extension vscode-corvia-0.1.0.vsix
```

重新啟動 VS Code，開啟 C 檔即可看到波浪底線。

**A4.** 設定（選用）。按 <kbd>Ctrl/Cmd</kbd>+<kbd>,</kbd> 搜尋 `corvia`：

| 設定 | 預設 | 用途 |
|---|---|---|
| `corvia.serverPath` | `corvia-lsp` | 若 VS Code 找不到 binary，設定絕對路徑 |
| `corvia.transport` | `stdio` | 改為 `tcp` 時需另外啟動 `corvia-lsp` |
| `corvia.tcp.host` / `corvia.tcp.port` | `127.0.0.1` / `9999` | TCP 連線設定 |
| `corvia.trace.server` | `off` | 設為 `verbose` 可在輸出面板看到 LSP 流量 |

**A5.** 命令面板指令（<kbd>Ctrl/Cmd</kbd>+<kbd>Shift</kbd>+<kbd>P</kbd>）：

- **Corvia: Restart Language Server** — 修改 `corvia.toml` 或升級套件後使用
- **Corvia: Show Output Channel** — 查看 LSP 原始紀錄與啟動錯誤

**A6.** 驗證

1. 建立有問題的 `test.c`（參考步驟 4）。
2. 儲存檔案。
3. 約一秒後應出現紅色 / 黃色波浪底線。
4. 滑鼠懸停波浪線可看到訊息與 MISRA 規則。

若診斷始終不出現：開啟 **Corvia: Show Output Channel** 查看錯誤。最常見原因是 `corvia-lsp` 不在 PATH 上，請將 `corvia.serverPath` 設為 `which corvia-lsp` 顯示的絕對路徑。

### B. Neovim（內建 LSP）

在 `init.lua` 加入：

```lua
vim.api.nvim_create_autocmd("FileType", {
  pattern = "c",
  callback = function()
    vim.lsp.start({
      name = "corvia",
      cmd = { "corvia-lsp", "--stdio" },
      root_dir = vim.fs.dirname(
        vim.fs.find({ "corvia.toml", ".git" }, { upward = true })[1]
      ),
    })
  end,
})
```

開啟 `.c` 檔後，`:LspInfo` 應顯示 `corvia` 正在執行。

### C. Emacs（eglot，Emacs 29+ 內建）

```elisp
(with-eval-after-load 'eglot
  (add-to-list 'eglot-server-programs
               '(c-mode . ("corvia-lsp" "--stdio"))))
;; 或使用 lsp-mode：
(with-eval-after-load 'lsp-mode
  (lsp-register-client
    (make-lsp-client
      :new-connection (lsp-stdio-connection '("corvia-lsp" "--stdio"))
      :major-modes '(c-mode)
      :server-id 'corvia)))
```

在 C buffer 中執行 `M-x eglot`（或 `lsp`）。

### D. Helix

`~/.config/helix/languages.toml`：

```toml
[language-server.corvia]
command = "corvia-lsp"
args = ["--stdio"]

[[language]]
name = "c"
language-servers = ["corvia"]
```

### E. Sublime Text（LSP 插件）

安裝 [LSP package](https://packagecontrol.io/packages/LSP)，然後：

```jsonc
{
  "clients": {
    "corvia": {
      "command": ["corvia-lsp", "--stdio"],
      "selector": "source.c"
    }
  }
}
```

執行 **LSP: Enable Language Server Globally → corvia**。

### F. 獨立 LSP 伺服器（任何 LSP 客戶端）

```bash
corvia-lsp --stdio                            # 預設
corvia-lsp --tcp --host 127.0.0.1 --port 9999
corvia-lsp --stdio -v                         # stderr 顯示詳細日誌
```

伺服器在 `textDocument/didOpen` 和 `textDocument/didSave` 時發布診斷，每條診斷帶有穩定的 `code`（如 `null-deref:MISRA-1.3`）和 `codeDescription.href`（連結到官方規則頁面）。

---

## 60 秒快速入門

```bash
# 1. 分析單一檔案
corvia path/to/file.c

# 2. 分析整個目錄（遞迴尋找 .c 檔）
corvia src/

# 3. 輸出 JSON 報告（適合 CI）
corvia src/ --format json --output report.json

# 4. 只顯示 MISRA Required 違規
corvia src/ --misra-only --misra-category required

# 5. 只跑兩個 checker
corvia src/ --checkers null-deref,memory-leak

# 6. 加速重複分析
corvia src/ --incremental

# 7. 列出所有 checker
corvia --list-checkers
```

有 `error` 等級問題時，`corvia` 以 exit code **1** 結束，可直接接入 CI 流程。

---

## CLI 完整旗標說明

### 分析目標

| 引數 | 說明 |
|---|---|
| `targets...` | 一個或多個檔案或目錄，目錄會遞迴搜尋 `*.c` |

### Checker 選擇

| 旗標 | 預設 | 說明 |
|---|---|---|
| `-c`, `--checkers <ids>` | 全部 | 以逗號分隔的 checker ID。例：`--checkers null-deref,memory-leak` |
| `--external-checkers <dir>` | — | 包含自訂 checker 模組的目錄 |
| `--list-checkers` | — | 列出所有已註冊的 checker 後離開 |

### 輸出

| 旗標 | 預設 | 說明 |
|---|---|---|
| `-f`, `--format <fmt>` | `text` | `text` / `json` / `md` / `html` |
| `-o`, `--output <path>` | stdout | 將報告寫入檔案 |
| `--no-color` | 關閉 | 停用 ANSI 彩色輸出 |

### 篩選

| 旗標 | 預設 | 說明 |
|---|---|---|
| `-s`, `--severity <lvl>` | `info` | 最低報告等級：`info` / `warning` / `error` |
| `--misra-only` | 關閉 | 只顯示有對應 MISRA 規則的問題 |
| `--misra-category <cat>` | — | `mandatory` / `required` / `advisory` |

### 解析

| 旗標 | 預設 | 說明 |
|---|---|---|
| `--use-cpp` | 關閉 | 解析前先執行 C 前處理器（macro 較多的程式碼需要此選項） |
| `-I`, `--include <dir>` | — | 加入 include 路徑，可重複使用 |

### 增量快取

| 旗標 | 預設 | 說明 |
|---|---|---|
| `--incremental` | 關閉 | 對 SHA-256 未變動的檔案沿用快取結果 |
| `--cache-dir <path>` | `.corvia_cache` | 快取存放目錄 |
| `--clean-cache` | — | 刪除所有快取後離開 |

### 設定檔

| 旗標 | 預設 | 說明 |
|---|---|---|
| `--config <path>` | 自動 | 指定 `corvia.toml` 路徑 |
| `--no-config` | 關閉 | 忽略 `corvia.toml`，只依賴 CLI 旗標 |

### 其他

| 旗標 | 說明 |
|---|---|
| `-V`, `--version` | 顯示版本後離開 |
| `-h`, `--help` | 顯示說明後離開 |

---

## 輸出格式

### Text（預設）

```
test.c:12:5: error[null-deref] (MISRA C:2012 Rule 1.3 Required): Dereference of NULL pointer 'p'
test.c:20:3: warning[uninit-var] (MISRA C:2012 Rule 9.1 Required): Variable 'x' may be used uninitialized
test.c:35:1: error[memory-leak] (MISRA C:2012 Rule 22.1 Required): Memory allocated to 'buf' is never freed

Summary: 3 issues (2 errors, 1 warning, 0 info) in 1 file
MISRA rules violated: 3
```

`error` 顯示為紅色，`warning` 黃色，`info` 青色。輸出到檔案或使用 `--no-color` 可關閉 ANSI 色碼。

### JSON（`--format json`）

```json
{
  "summary": { "total_files": 1, "total_issues": 2, "ERROR": 1, "WARNING": 1, "INFO": 0 },
  "issues": [
    {
      "checker_id": "null-deref",
      "severity": "ERROR",
      "message": "Dereference of NULL pointer 'p'",
      "file": "src/main.c",
      "line": 12,
      "column": 5,
      "misra_rule": { "rule_id": "1.3", "category": "Required" }
    }
  ]
}
```

### Markdown（`--format md`）

依檔案和 MISRA 規則分組的 Markdown 報告，適合貼在 PR 評論或 issue 描述中。

### HTML（`--format html`）

獨立 HTML 頁面（Jinja2 模板），用任何瀏覽器開啟即可瀏覽。

---

## Severity 與 Exit Code

| 等級 | 用途 |
|---|---|
| `error` | 確定性的未定義行為或嚴重 MISRA 違規 |
| `warning` | 可能的 bug / 可疑模式 / Required 規則 |
| `info` | 風格 / Advisory / 提示 |

| Exit code | 意義 |
|---|---|
| `0` | 沒有 `error` 等級的問題 |
| `1` | 至少一條 `error` |
| `2` | CLI 用法錯誤 / `corvia.toml` 格式錯誤 |

---

## 設定檔 corvia.toml

`corvia` 會從目前目錄向上尋找 `corvia.toml`。CLI 旗標永遠優先於設定檔。傳入 `--no-config` 可忽略設定檔。

完整 schema（所有區段均為選用）：

```toml
[checkers]
# 若設定 `enabled`，只跑這些 checker
enabled  = ["null-deref", "memory-leak", "misra-types"]
# `disabled` 從啟用集合中減去
disabled = ["misra-unions"]

[severity]
# key 可以是 checker id（如 "misra-stdlib"）或 MISRA rule id（如 "21.3"）
# value："error" | "warning" | "info" | "off"
# rule id 比 checker id 優先
"misra-stdlib" = "error"   # 將所有 misra-stdlib 問題升為 error
"21.3"         = "info"    # 將 rule 21.3 降為 info
"19.2"         = "off"     # 完全靜音

[paths]
include = ["/usr/local/include", "vendor/include"]  # 等同 -I
use_cpp = true                                      # 執行前處理器

[output]
format   = "text"     # 預設格式：text / json / md / html
no_color = false      # 停用 ANSI 彩色

[cache]
enabled = true        # 等同 --incremental
dir     = ".corvia_cache"
```

載入時會在 stderr 顯示 `Using config: /path/to/corvia.toml`。

---

## Checker 一覽

`corvia --list-checkers` 顯示目前已註冊的完整清單。內建共 23 個：

| ID | 說明 | MISRA 規則 |
|---|---|---|
| `syntax` | condition 中的賦值、缺少大括號 | 13.4, 15.6 |
| `unused-var` | 未使用的變數、參數、tag（2.4）、標籤（2.6） | 2.2, 2.3, 2.4, 2.6, 2.7 |
| `uninit-var` | 使用未初始化的變數（CFG 分析） | 9.1 |
| `dead-code` | 不可到達的程式碼、不變的條件 | 2.1, 14.3 |
| `null-deref` | `*`、`->`、`[]` 對 NULL 指標解參考（CFG + 函式摘要） | 1.3 |
| `buffer-overflow` | 固定陣列的常數索引越界 | 1.3, 18.1 |
| `memory-leak` | malloc/calloc/realloc 未 free（CFG + 函式摘要） | 22.1, 22.2 |
| `resource-leak` | fopen/popen 未 fclose、FILE* 解參考（22.5）、關閉後使用 | 22.1, 22.5, 22.6 |
| `misra-types` | 隱式 / 窄化轉換、有符號混用 | 10.1–10.8 |
| `misra-decl` | extern 誤用、static/inline 規則、缺少型別 | 8.1–8.14 |
| `misra-expr` | 運算子優先級、副作用、逗號運算子 | 12.1–12.5, 13.1–13.6 |
| `misra-control` | goto、if-else 完整性 | 14.1–14.4, 15.1–15.7 |
| `misra-func` | stdarg、間接遞迴（17.2）、忽略回傳值（17.7） | 17.1–17.8 |
| `misra-pointer` | 指標運算、陣列退化、函式指標 | 18.1–18.8 |
| `misra-preproc` | Macro 限制（AST 可偵測的子集） | 20.7, 20.10–20.12, 20.14 |
| `misra-identifiers` | 外部 / typedef / tag / 連結唯一性、作用域遮蔽 | 5.1, 5.3, 5.6–5.9 |
| `misra-pointer-conv` | 函式指標 / 物件指標 / void 指標 / 限定詞轉換、NULL 常數 | 11.1–11.9 |
| `misra-stdlib` | 禁用標準函式庫、保留識別字、新興特性（1.4） | 1.4, 21.1–21.10, 21.12 |
| `misra-bitfields` | 位元欄位型別限制、有符號單一位元 | 6.1, 6.2 |
| `misra-literals` | 八進位常數、小寫 `l` 後綴、字串字面值給非 const | 7.1, 7.3, 7.4 |
| `misra-switch` | 格式完整性、default 存在 / 位置、missing break、boolean switch、標籤位置（16.2） | 16.1–16.7 |
| `misra-unions` | 不建議使用 union | 19.2 |
| `misra-init` | 聚合 / union 必須使用大括號；陣列必須完整初始化 | 9.2, 9.3 |

### 範例 — 錯誤 vs 正確

**`null-deref`（1.3）**
```c
int *get_ptr(void);
void use(void) {
    int *p = get_ptr();   /* Corvia 知道 get_ptr 可能回傳 NULL */
    *p = 1;               /* ❌ error[null-deref] */
}
```
修正：
```c
int *p = get_ptr();
if (p != 0) {
    *p = 1;               /* ✅ */
}
```

**`memory-leak`（22.1）**
```c
void *xalloc(unsigned long n) { return malloc(n); }  /* wrapper */

void leaky(void) {
    char *p = xalloc(16); /* ❌ Corvia 識別 xalloc 為配置器 */
}                         /*    error[memory-leak]: 'p' 未被釋放 */
```

**`misra-switch`（16.4 / 16.6）**
```c
switch (x) {              /* ❌ warning[misra-switch] 16.4：沒有 default */
    case 1: y = 1; break; /* ❌ warning[misra-switch] 16.6：只有 1 個 case */
}
```

**`misra-bitfields`（6.1 / 6.2）**
```c
struct flags {
    char small : 2;       /* ❌ 6.1：不允許 char */
    int single : 1;       /* ❌ 6.2：有符號單一位元 */
    unsigned int ok : 4;  /* ✅ */
};
```

---

## MISRA C:2012 涵蓋範圍

<details>
<summary>全部 122+ 條已實作規則（點擊展開）</summary>

| 章節 | 規則 | Checker |
|---|---|---|
| §1 標準 / 未定義行為 | 1.3, 1.4 | `null-deref`, `buffer-overflow`, `misra-stdlib` |
| §2 未使用程式碼 | 2.1, 2.2, 2.3, 2.4, 2.6, 2.7 | `dead-code`, `unused-var` |
| §5 識別字 | 5.1, 5.3, 5.6, 5.7, 5.8, 5.9 | `misra-identifiers` |
| §6 型別（位元欄位） | 6.1, 6.2 | `misra-bitfields` |
| §7 字面值與常數 | 7.1, 7.3, 7.4 | `misra-literals` |
| §8 宣告與定義 | 8.1–8.14 | `misra-decl` |
| §9 初始化 | 9.1, 9.2, 9.3 | `uninit-var`, `misra-init` |
| §10 型別轉換 | 10.1–10.8 | `misra-types` |
| §11 指標型別轉換 | 11.1–11.9 | `misra-pointer-conv` |
| §12 運算式 | 12.1–12.5 | `misra-expr` |
| §13 副作用 | 13.1–13.6 | `misra-expr`, `syntax` |
| §14 控制流程 | 14.1–14.4 | `misra-control`, `dead-code` |
| §15 控制流程（if/switch） | 15.1–15.7 | `misra-control`, `syntax` |
| §16 switch 陳述式 | 16.1, 16.2, 16.3, 16.4, 16.5, 16.6, 16.7 | `misra-switch` |
| §17 函式 | 17.1–17.8 | `misra-func` |
| §18 指標與陣列 | 18.1–18.8 | `misra-pointer`, `buffer-overflow` |
| §19 重疊儲存區 | 19.2 | `misra-unions` |
| §20 前處理器 | 20.7, 20.10–20.12, 20.14 | `misra-preproc` |
| §21 標準函式庫 | 21.1, 21.2, 21.3, 21.4, 21.5, 21.6, 21.7, 21.8, 21.9, 21.10, 21.12 | `misra-stdlib` |
| §22 資源 | 22.1, 22.2, 22.5, 22.6 | `memory-leak`, `resource-leak` |

</details>

---

## 跨函式分析

兩個 pass 的管線讓每個 checker 都能在 O(1) 時間查詢跨函式 / 跨檔的資訊：

```
Pass 1：解析所有目標
  ↓
  建構 SymbolTable    （跨檔全域、靜態、typedef、tag）
  ↓
  建構 CallGraph      （所有 FuncCall 邊；Tarjan SCC 偵測遞迴）
  ↓
  計算 FunctionSummary（依 SCC 由下而上；遇到循環用 fixpoint）
  ↓
Pass 2：每個 checker 在每個 AST 上跑，共享 AnalysisContext
```

每個 `FunctionSummary` 記錄 `allocates`、`opens_resource`、`frees_param`、`closes_param`、`returns_null`、`params_must_not_be_null`、`has_side_effects`、`is_recursive`。這就是為什麼 `null-deref` 知道你的 `get_or_default()` wrapper 可能回傳 NULL，以及 `memory-leak` 知道你的 `xalloc()` 本質上是 `malloc`。

---

## 增量分析

```bash
corvia src/ --incremental
```

對每個分析過的檔案，Corvia 儲存：

- 檔案內容的 SHA-256
- 上次產生的問題清單
- 該檔案所**呼叫**的外部函式（callees）
- 該檔案所**定義**的外部函式（defines）

下次執行時，只有雜湊值改變、或其相依檔案改變的檔案才會重新分析。快取預設存在 `.corvia_cache/`，清除方式：

```bash
corvia --clean-cache
```

---

## LSP 伺服器

`corvia-lsp` 實作標準 LSP 協定，在 `didOpen` 和 `didSave` 時發布診斷，每條診斷帶有穩定的 `code`（如 `null-deref:MISRA-1.3`）和 `codeDescription.href`（連結到官方規則頁面）。

```bash
corvia-lsp --stdio                            # 預設：stdio
corvia-lsp --tcp --host 127.0.0.1 --port 9999 # TCP
corvia-lsp --stdio -v                         # stderr 詳細日誌
```

相容所有支援 LSP 的編輯器（VS Code、Neovim、Helix、Emacs eglot/lsp-mode、Sublime LSP、IntelliJ LSP4IJ…）。

---

## VS Code 擴充套件

擴充套件位於 `extensions/vscode-corvia/`。

```bash
cd extensions/vscode-corvia
npm install
npm run compile

# 開發模式：Developer: Install Extension from Location…
# 或封裝後安裝：
npm run package          # 產生 vscode-corvia-0.1.0.vsix
code --install-extension vscode-corvia-0.1.0.vsix
```

還需要 `corvia-lsp` 在 PATH 上：

```bash
pip install 'corvia[lsp]'
which corvia-lsp
```

### 設定

| 設定 | 預設 | 用途 |
|---|---|---|
| `corvia.serverPath` | `corvia-lsp` | 若不在 PATH 上，設定絕對路徑 |
| `corvia.transport` | `stdio` | `stdio` 或 `tcp` |
| `corvia.tcp.host` | `127.0.0.1` | TCP 主機 |
| `corvia.tcp.port` | `9999` | TCP 埠號 |
| `corvia.trace.server` | `off` | LSP 追蹤等級：`off` / `messages` / `verbose` |

### 命令

- **Corvia: Restart Language Server**
- **Corvia: Show Output Channel**

---

## 撰寫自訂 Checker

Checker 是繼承 `BaseChecker` 的子類別，透過 pycparser 的 NodeVisitor 協定造訪 AST 節點。將檔案放入目錄後，傳入 `--external-checkers <dir>` 即可載入。

```python
# my_checkers/single_return.py
from pycparser import c_ast
from corvia.checkers.base import BaseChecker
from corvia.models import MisraRule, MisraCategory, Severity
from corvia.registry import CheckerRegistry

MY_RULE = MisraRule(
    "15.5", MisraCategory.ADVISORY,
    "A function should have a single point of exit",
)

class SingleReturnChecker(BaseChecker):
    checker_id = "single-return"
    description = "每個函式應只有一個回傳點"
    default_severity = Severity.WARNING
    misra_rules = [MY_RULE]

    def visit_FuncDef(self, node: c_ast.FuncDef) -> None:
        returns = []
        self._count_returns(node.body, returns)
        if len(returns) > 1:
            self.report(
                returns[1],
                f"函式 '{node.decl.name}' 有 {len(returns)} 個 return",
                Severity.WARNING,
                MY_RULE,
            )
        self.generic_visit(node)

    def _count_returns(self, node, out):
        if isinstance(node, c_ast.Return):
            out.append(node)
        for _, child in node.children():
            self._count_returns(child, out)

CheckerRegistry.register(SingleReturnChecker)
```

```bash
corvia src/ --external-checkers ./my_checkers/
corvia src/ --checkers single-return --external-checkers ./my_checkers/
```

在 checker 中使用跨函式分析上下文：

```python
def visit_FuncCall(self, node):
    if self._ctx is None:
        return
    if isinstance(node.name, c_ast.ID):
        s = self._ctx.summary_of(node.name.name)
        if s and s.allocates:
            ...   # 此呼叫回傳的是新配置的記憶體
```

---

## 架構

```
src/corvia/
├── cli.py                  # 引數解析、彩色輸出、進入點
├── engine.py               # Two-pass 協調器（全部解析 → context → checker）
├── parser.py               # pycparser wrapper（含假 libc headers）
├── registry.py             # Checker 自動探索 + 外部載入
├── models.py               # Issue、MisraRule、Severity、AnalysisResult
├── core/
│   ├── cfg.py              # 控制流程圖（CFG）建構器
│   ├── dataflow.py         # 通用 ForwardAnalysis / BackwardAnalysis
│   ├── symbol_table.py     # 跨檔 SymbolTable + tag/typedef 追蹤
│   ├── call_graph.py       # CallGraph + Tarjan SCC
│   ├── summary.py          # FunctionSummary 由下而上計算
│   ├── context.py          # AnalysisContext 套件
│   ├── cache.py            # 內容雜湊增量快取
│   └── config.py           # corvia.toml 載入與驗證
├── checkers/
│   ├── base.py             # BaseChecker（NodeVisitor + report() + set_context()）
│   ├── null_deref.py
│   ├── memory_leak.py
│   ├── resource_leak.py
│   ├── misra_*.py          # 14 個 MISRA 專用模組
│   └── ...                 # 其餘 9 個
├── lsp/
│   ├── converter.py        # Issue → LSP Diagnostic（不依賴 pygls）
│   └── server.py           # corvia-lsp 進入點
└── reporters/
    ├── json_reporter.py
    ├── md_reporter.py
    └── html_reporter.py

extensions/
└── vscode-corvia/          # VS Code wrapper（連接 corvia-lsp）
```

---

## 開發

```bash
# 安裝開發 + LSP extras
pip install -e ".[dev,lsp]"

# 執行所有測試
pytest tests/ -v

# 覆蓋率
pytest tests/ --cov=corvia --cov-report=html

# 執行特定 checker 的測試
pytest tests/test_checkers/test_null_deref.py -v

# 只跑跨函式整合測試
pytest tests/test_core/test_inter_procedural.py -v
```

測試總計 **150 個**，全部通過。

```
tests/
├── fixtures/           # 測試用 C 原始碼
├── test_checkers/      # 各 checker 單元測試
├── test_core/          # CFG、dataflow、symbol_table、call_graph、
│                       # summary、cache、config 測試
├── test_lsp/           # LSP converter + server 煙霧測試
├── test_reporters/     # JSON / Markdown reporter 測試
├── test_engine.py
└── test_parser.py
```

---

## 疑難排解

**`ModuleNotFoundError: No module named 'corvia'`**
尚未安裝套件。在 repo 根目錄執行 `pip install -e ".[dev]"`。

**`pycparser.plyparser` 匯入錯誤**
你使用的是 pycparser ≥ 3.0；`parser.py` 已包含相容性 shim。若仍出現此錯誤，表示安裝過時，請重新安裝。

**`corvia-lsp: command not found`**
安裝 LSP extras：`pip install -e ".[lsp]"`。或將 `corvia.serverPath` 設為絕對路徑。

**擴充套件無法啟動伺服器**
`Corvia: Show Output Channel` 會顯示啟動錯誤。最常見原因是編輯器的 PATH 未繼承 shell 的 PATH，請將 `corvia.serverPath` 設為絕對路徑。

**大量 MISRA-stdlib 關於 `printf`/`malloc` 的噪音**
在 `corvia.toml` 調整嚴重等級：
```toml
[severity]
"21.3" = "info"
"21.6" = "off"
```

**`Comments are not supported` 解析錯誤**
pycparser 沒有前處理器時無法去除 comments。加上 `--use-cpp`（並加 `-I` 指定 headers 路徑）讓 `cpp` 先執行。

**Wrapper 配置器未被偵測**
確保 wrapper 和呼叫者在同一次呼叫中傳入（例如 `corvia src/`）。跨檔分析需要在同一次執行中解析兩個檔案。

---

## Roadmap（中文）

- [x] **Phase 1 & 2** — AST checker、CFG / 資料流框架、MISRA §1、§2、§8–§10、§12–§15、§17、§18、§20、§22
- [x] **Phase 3** — SymbolTable + CallGraph + FunctionSummary；MISRA §5、§11、§21；增量快取；LSP 伺服器
- [x] **Phase 4** — MISRA §6、§7、§16、§19
- [x] **Phase 5** — §1、§2、§9、§16、§22 各增加規則；`corvia.toml` 專案設定
- [x] **Phase 6** — VS Code 擴充套件（`extensions/vscode-corvia/`）

---

## 授權

MIT

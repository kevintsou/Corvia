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

## 中文版（精簡）

Corvia 是一款以 Python 實作、靈感來自 Coverity 的 C 語言靜態分析工具。涵蓋 **20 個章節、122+ 條 MISRA C:2012 規則**，提供 CLI、LSP 伺服器、VS Code 擴充套件三種使用方式。

### 安裝

```bash
git clone https://github.com/kevintsou/Corvia.git && cd Corvia
pip install -e ".[dev,lsp]"
```

### 常用指令

```bash
corvia src/                                   # 分析整個目錄
corvia file.c -f json -o report.json          # JSON 報告
corvia src/ --misra-only --misra-category required
corvia src/ --checkers null-deref,memory-leak
corvia src/ --incremental                     # 啟用快取
corvia --list-checkers                        # 列出所有 checker
corvia-lsp --stdio                            # 啟動 LSP 伺服器
```

### CLI 旗標一覽

| 類別 | 旗標 | 說明 |
|---|---|---|
| 目標 | `targets...` | 檔案或目錄 |
| 篩選 | `-c / --checkers <ids>` | 啟用指定 checker |
| 篩選 | `-s / --severity <lvl>` | 最低嚴重等級 (`info` / `warning` / `error`) |
| 篩選 | `--misra-only` | 只看 MISRA 違反 |
| 篩選 | `--misra-category <cat>` | `mandatory` / `required` / `advisory` |
| 輸出 | `-f / --format <fmt>` | `text` / `json` / `md` / `html` |
| 輸出 | `-o / --output <path>` | 寫入檔案 |
| 輸出 | `--no-color` | 關閉彩色 |
| 解析 | `--use-cpp` | 啟用前處理器 |
| 解析 | `-I / --include <dir>` | 加入 include 路徑（可重複） |
| 增量 | `--incremental` | 啟用快取 |
| 增量 | `--cache-dir <path>` | 快取目錄（預設 `.corvia_cache`） |
| 增量 | `--clean-cache` | 清除快取後離開 |
| 設定 | `--config <path>` | 指定 `corvia.toml` 路徑 |
| 設定 | `--no-config` | 忽略 `corvia.toml` |
| 自訂 | `--external-checkers <dir>` | 載入外部 checker 模組 |
| 一般 | `--list-checkers` | 列出所有 checker |
| 一般 | `-V / --version` | 版本 |
| 一般 | `-h / --help` | 說明 |

### 設定檔（`corvia.toml`）

從目前目錄向上尋找；CLI 旗標永遠勝過設定檔。

```toml
[checkers]
enabled  = ["null-deref", "memory-leak"]
disabled = ["misra-unions"]

[severity]
# checker id 或 MISRA rule id；rule id 比 checker id 優先
"misra-stdlib" = "error"
"21.3"         = "info"
"19.2"         = "off"   # 完全靜音

[paths]
include = ["/usr/local/include"]
use_cpp = true

[output]
format   = "text"
no_color = false

[cache]
enabled = true
dir     = ".corvia_cache"
```

### Severity 與 Exit code

| Severity | 用途 |
|---|---|
| `error` | 確定性的未定義行為／嚴重 MISRA |
| `warning` | 可能的 bug／可疑模式 |
| `info` | 風格／Advisory |

| Exit code | 意義 |
|---|---|
| `0` | 沒有 error 等級的問題 |
| `1` | 至少一條 error |
| `2` | CLI 用法錯／設定檔錯誤 |

### Two-pass 分析管線（Phase 3）

```
Pass 1：解析所有目標
  ↓
  建構 SymbolTable    （跨檔全域、靜態、typedef、tag）
  ↓
  建構 CallGraph      （所有 FuncCall 邊；用 Tarjan SCC 偵測遞迴）
  ↓
  計算 FunctionSummary（依 SCC 由下而上；遇到循環用 fixpoint）
  ↓
Pass 2：每個 checker 在每個 AST 上跑，共享 AnalysisContext
```

### LSP / VS Code

```bash
corvia-lsp --stdio                                  # 啟動 LSP（stdio）
corvia-lsp --tcp --host 127.0.0.1 --port 9999       # TCP

cd extensions/vscode-corvia
npm install && npm run compile
npm run package
code --install-extension vscode-corvia-0.1.0.vsix
```

VS Code 設定：`corvia.serverPath`、`corvia.transport`、`corvia.tcp.host/port`、`corvia.trace.server`。命令面板有 **Corvia: Restart Language Server** 與 **Corvia: Show Output Channel**。

### 自訂 Checker

```python
from pycparser import c_ast
from corvia.checkers.base import BaseChecker
from corvia.models import MisraRule, MisraCategory, Severity
from corvia.registry import CheckerRegistry

class MyChecker(BaseChecker):
    checker_id = "my-checker"
    description = "..."
    default_severity = Severity.WARNING
    misra_rules = []

    def visit_FuncCall(self, node):
        # self._ctx 提供跨檔分析資訊（Phase 3）
        self.generic_visit(node)

CheckerRegistry.register(MyChecker)
```

```bash
corvia src/ --external-checkers ./my_checkers/
```

### 開發

```bash
pip install -e ".[dev,lsp]"
pytest tests/ -v
pytest tests/ --cov=corvia
```

測試總計 **150 個**，全部通過。

### 授權

MIT

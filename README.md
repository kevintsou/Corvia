# COVIA — C Static Analyzer with MISRA C:2012 Support

COVIA is a Python-based static analysis tool for C code, inspired by Coverity. It detects bugs, undefined behaviour, and MISRA C:2012 rule violations using AST-level and CFG-based dataflow analysis.

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

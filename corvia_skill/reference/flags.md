# Corvia CLI Flags Reference

## Basic Usage
```
corvia [targets...] [flags]
```
`targets` — one or more files or directories to analyze (default: current directory)

---

## Output Control

| Flag | Default | Description |
|---|---|---|
| `-f`, `--format` | `text` | Output format: `text` (colored), `json`, `html`, `md` |
| `-o`, `--output` | stdout | Write output to a file instead of stdout |
| `-s`, `--severity` | `info` | Minimum severity to report: `info` / `warning` / `error` |
| `--no-color` | off | Disable ANSI color in text output |

---

## Checker Selection

| Flag | Description |
|---|---|
| `-c`, `--checkers` | Comma-separated checker IDs to enable (default: all) |
| `--misra-only` | Only show issues that map to a MISRA C:2012 rule |
| `--misra-category` | Filter by MISRA category: `mandatory` / `required` / `advisory` |
| `--list-checkers` | Print all available checker IDs and exit |
| `--external-checkers <dir>` | Load additional checker modules from a directory |

---

## Preprocessor

| Flag | Description |
|---|---|
| `--use-cpp` | Run the C preprocessor (`cpp` / `clang`) before parsing |
| `-I`, `--include <dir>` | Add an include directory (repeatable) |

---

## Incremental / Cache

| Flag | Default | Description |
|---|---|---|
| `--incremental` | off | Reuse cached results for files that have not changed (SHA-256 hash) |
| `--cache-dir <dir>` | `.corvia_cache` | Directory for the incremental cache |
| `--clean-cache` | — | Delete the cache directory and exit |

---

## Configuration

| Flag | Description |
|---|---|
| `--config <path>` | Path to `corvia.toml` (default: auto-discover upward from target) |
| `--no-config` | Ignore any `corvia.toml` and use only CLI flags |

---

## Misc

| Flag | Description |
|---|---|
| `-V`, `--version` | Show version and exit |

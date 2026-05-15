# Corvia Output Format Reference

## Text Output (default)

Each issue is one line:
```
<file>:<line>:<col>  [<severity>]  <checker-id>    <message>
```

Example:
```
src/main.c:42:5   [error]    null-deref        Pointer 'p' may be NULL (returned by malloc)
src/utils.c:18:1  [warning]  misra-func        MISRA C:2012 Rule 17.2: function 'foo' is recursive
src/io.c:7:3      [info]     resource-leak     FILE* 'f' may not be closed on all paths
```

---

## Severity Levels

| Severity | Meaning |
|---|---|
| `error` | High-confidence bug or mandatory MISRA violation — should be fixed |
| `warning` | Likely problem or required MISRA rule — review and fix |
| `info` | Advisory note or style issue — fix if possible |

---

## Exit Codes

| Code | Meaning |
|---|---|
| `0` | No **error**-level issues found — warnings and info are still reported but do not change the exit code |
| `1` | One or more **error**-level issues found |
| `2` | Configuration error — `corvia.toml` could not be loaded or is invalid |

---

## JSON Output (`--format json`)

```json
[
  {
    "file": "src/main.c",
    "line": 42,
    "col": 5,
    "severity": "error",
    "checker": "null-deref",
    "message": "Pointer 'p' may be NULL (returned by malloc)",
    "rule": null
  },
  {
    "file": "src/utils.c",
    "line": 18,
    "col": 1,
    "severity": "warning",
    "checker": "misra-func",
    "message": "MISRA C:2012 Rule 17.2: function 'foo' is recursive",
    "rule": "17.2"
  }
]
```

---

## Markdown Output (`--format md`)

Produces a GitHub-flavored Markdown table, suitable for pasting into PRs or issues.

---

## HTML Output (`--format html`)

Produces a standalone HTML file with syntax-highlighted source snippets and a filterable issue table.

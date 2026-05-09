# Corvia Checkers Reference

23 built-in checkers across two categories: **Bug Detection** and **MISRA C:2012**.

---

## Bug Detection Checkers

| Checker ID | What it detects |
|---|---|
| `null-deref` | Null pointer dereference — pointer used without NULL check after a call that may return NULL or after a failed allocation |
| `memory-leak` | Memory leak — heap allocation (`malloc`, `calloc`, `realloc`, or wrapper) not freed on all paths |
| `resource-leak` | Resource leak — file descriptor or `FILE*` opened but not closed on all paths |
| `unused-var` | Unused variables, unused tag declarations (MISRA 2.4), unused labels (MISRA 2.6) |
| `uninit-var` | Use of uninitialized variable detected via dataflow analysis |

---

## MISRA C:2012 Checkers

| Checker ID | MISRA Section | Rules covered |
|---|---|---|
| `misra-stdlib` | §1, §21 | 1.4 (non-standard extensions), 21.1–21.10, 21.12 (forbidden standard library usage) |
| `misra-func` | §17 | 17.2 (recursive functions), 17.3 (implicit function declaration), 17.7 (unused return value), 17.8 (modified parameters) |
| `misra-identifiers` | §5 | 5.1 (external identifier length), 5.3 (scope shadowing), 5.6 (typedef uniqueness), 5.7 (tag uniqueness), 5.8–5.9 (external/internal linkage uniqueness) |
| `misra-pointer-conv` | §11 | 11.1 (function pointer conversion), 11.3 (object pointer cast), 11.4 (integer↔pointer), 11.5 (void pointer), 11.6 (integer↔void pointer), 11.7 (pointer↔arithmetic), 11.8 (const/volatile qualifier cast), 11.9 (NULL macro) |
| `misra-bitfields` | §6 | 6.1 (bit-field type must be unsigned int / signed int / _Bool / enum), 6.2 (single-bit signed bit-field) |
| `misra-literals` | §7 | 7.1 (octal constants), 7.3 (lowercase 'l' suffix), 7.4 (string literal assigned to non-const char*) |
| `misra-switch` | §16 | 16.1 (well-formed switch), 16.2 (label placement), 16.3 (unconditional break), 16.4 (default clause required), 16.5 (default first or last), 16.6 (≥2 clauses), 16.7 (boolean expression) |
| `misra-unions` | §19 | 19.2 (union keyword advisory) |
| `misra-init` | §9 | 9.2 (brace-enclosed initializers), 9.3 (fully initialized arrays) |
| `misra-types` | §10 | 10.1–10.8 (essential type violations in expressions) |
| `misra-declarations` | §8 | 8.1 (implicit types), 8.2 (function prototype), 8.4 (external definition), 8.7 (file-scope when possible), 8.8 (static storage class) |
| `misra-comments` | §3 | 3.1 (C++ comments in C code) |
| `misra-control-flow` | §14 | 14.1 (unreachable code), 14.2 (for-loop), 14.3 (invariant boolean) |
| `misra-side-effects` | §13 | 13.1–13.6 (side effects in expressions, increment/decrement) |
| `misra-expressions` | §12 | 12.1 (operator precedence), 12.2 (shift count), 12.3 (comma operator), 12.4 (constant expressions) |
| `misra-preprocessor` | §20 | 20.1–20.14 (include guards, macro restrictions, undef) |
| `misra-conversions` | §10 | Composite conversions and casts |
| `misra-jumps` | §15 | 15.1–15.5 (goto, break, continue, return) |

---

## Enabling Specific Checkers

```bash
# Run only bug detectors
corvia src/ -c null-deref,memory-leak,resource-leak

# Run only MISRA checkers
corvia src/ --misra-only

# Run a single checker
corvia src/ -c misra-switch
```

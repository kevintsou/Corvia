# Corvia Checkers Reference

23 built-in checkers across two categories: **Bug Detection** and **MISRA C:2012**.

---

## Bug Detection Checkers

| Checker ID | What it detects |
|---|---|
| `null-deref` | Null pointer dereference — pointer used without NULL check after a call that may return NULL or after a failed allocation |
| `memory-leak` | Memory leak — heap allocation (`malloc`, `calloc`, `realloc`, or wrapper) not freed on all paths |
| `resource-leak` | Resource leak — file descriptor or `FILE*` opened but not closed on all paths |
| `uninit-var` | Use of uninitialized or partially initialized variable (MISRA C:2012 Rule 9.1), detected via dataflow analysis |
| `unused-var` | Unused local variables and function parameters |
| `dead-code` | Unreachable code after `return`/`break`/`continue`/`goto`, and invariant (`do-while(0)`) conditions (MISRA 14.3) |
| `buffer-overflow` | Constant-index out-of-bounds access on fixed-size arrays |
| `syntax` | Suspicious syntax patterns: assignment in conditions, missing braces around control-flow bodies |

---

## MISRA C:2012 Checkers

| Checker ID | MISRA Section | Rules covered |
|---|---|---|
| `misra-stdlib` | §21 | 21.x — forbidden Standard Library usage and reserved identifiers |
| `misra-func` | §17 | 17.1–17.8 — function rules (recursive, implicit declaration, unused return value, modified parameters) |
| `misra-identifiers` | §5 | 5.1 (external identifier length), 5.3 (scope shadowing), 5.6–5.9 (typedef/tag/external/internal linkage uniqueness) |
| `misra-pointer-conv` | §11 | 11.1–11.9 — pointer type conversion rules (function pointer, object pointer cast, integer↔pointer, void pointer, NULL macro) |
| `misra-pointer` | §18 | 18.1–18.8 — pointer and array rules (arithmetic, subtraction, relational operators, nesting depth, VLA) |
| `misra-bitfields` | §6 | 6.1 (bit-field type must be `unsigned int` / `signed int` / `_Bool`), 6.2 (single-bit signed bit-field) |
| `misra-literals` | §7 | 7.1 (octal constants), 7.3 (lowercase `l` suffix), 7.4 (string literal assigned to non-const `char*`) |
| `misra-switch` | §16 | 16.1, 16.3–16.7 — well-formed switch, unconditional break, default clause, boolean expression |
| `misra-unions` | §19 | 19.2 — `union` keyword advisory |
| `misra-init` | §9 | 9.2 (brace-enclosed initializers), 9.3 (fully initialized arrays) |
| `misra-types` | §10 | 10.1–10.8 — essential type model: type violations in expressions, conversions and casts |
| `misra-decl` | §8 | 8.1–8.14 — declaration and definition rules (implicit types, prototype form, external definition, storage class, `restrict`) |
| `misra-control` | §14, §15 | 14.1–14.4 (loop/if controlling expressions, invariant conditions) + 15.1–15.7 (`goto`, `break`, `continue`, `return`, `else`) |
| `misra-expr` | §12, §13 | 12.1–12.4 (operator precedence, shift, comma, unsigned wrap) + 13.1–13.6 (side effects in initializers, `&&`/`||`, `sizeof`) |
| `misra-preproc` | §20 | 20.x — preprocessor rules (include guards, macro restrictions, `undef`) — AST-detectable subset |

---

## Enabling Specific Checkers

```bash
# Run only bug detectors
corvia src/ -c null-deref,memory-leak,resource-leak,uninit-var,dead-code,buffer-overflow,syntax

# Run only MISRA checkers
corvia src/ --misra-only

# Run a single checker
corvia src/ -c misra-switch
```

---
name: corvia-review
description: Run Corvia static analyzer on the current C/C++ project. Use when
  the user asks to "review", "analyze", or "check" the whole project for bugs,
  memory issues, or code quality. Automatically installs corvia from GitHub if
  not present, then runs it on the current working directory.
---

# Corvia Code Review Skill

You are performing a static analysis code review using the **Corvia** analyzer.
Follow these steps exactly.

## Step 1 — Check Installation

Run:
```bash
which corvia
```

If the command is found, skip to Step 3.
If not found (`which` returns nothing or exits non-zero), proceed to Step 2.

## Step 2 — Install Corvia

Run:
```bash
pip install git+https://github.com/kevintsou/Corvia.git
```

Wait for it to complete, then verify with `corvia --version`.
If installation fails, report the error to the user and stop.

## Step 3 — Get Project Directory

Run:
```bash
pwd
```

Store the output as `<project_dir>`.

## Step 4 — Run Analysis

Run:
```bash
corvia <project_dir>
```

If the user provided extra flags (e.g. `--incremental`, `--format json`), append them.

For large projects, suggest using `--incremental` to speed up subsequent runs.

If you need flag details, read:
`~/.claude/skills/corvia_skill/reference/flags.md`

## Step 5 — Present Results

Structure the report as follows:

### Summary
- Total issues found
- Breakdown by severity: **error** / **warning** / **info**
- Exit code meaning (read `~/.claude/skills/corvia_skill/reference/output-format.md` if needed)

### Issues by Severity
List all **error** issues first, then **warning**, then **info**.
Format each as:
```
file:line  [severity]  checker-id — message
```

### Top Offending Files
List files with the most issues (top 5).

### Checker Summary
List which checkers fired and how many times.
For checker descriptions, read:
`~/.claude/skills/corvia_skill/reference/checkers.md`

### Recommendation
Give a brief actionable recommendation based on the findings.

---

If no issues are found, confirm the project is clean and exit code is 0.

Run the Corvia static analyzer on this project.

Usage:
- `/corvia` — analyze `src/` with default settings
- `/corvia src/myfile.c` — analyze a specific file
- `/corvia src/ --misra-only` — MISRA rules only
- `/corvia src/ --format json` — JSON output
- `/corvia --list-checkers` — show all available checkers

---

Run the following command and show the full output to the user:

```bash
corvia $ARGUMENTS
```

If `$ARGUMENTS` is empty, default to:

```bash
corvia src/
```

After showing the output, briefly summarize:
- How many issues were found
- The highest severity level seen (error / warning / info)
- Which checkers fired most often (if any)

If `corvia` is not found, remind the user to install it:
```bash
pip install -e ".[dev,lsp]"
```

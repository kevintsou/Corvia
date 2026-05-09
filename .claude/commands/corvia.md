Run the Corvia static analyzer on the current working directory.

Steps:
1. Use the Bash tool to get the current working directory: `pwd`
2. Run `corvia <cwd> $ARGUMENTS` using the Bash tool, where `<cwd>` is the result of step 1
3. Display the full output
4. Summarize: total issues found, highest severity, and which checkers fired most

If no output is produced, confirm the project is clean.
If `corvia` is not found, tell the user to run: `pip install -e ".[dev,lsp]"` from the Corvia repo root.

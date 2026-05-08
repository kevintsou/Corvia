"""MISRA C:2012 Section 5: Identifiers.

Implements Rules 5.1, 5.3, 5.6, 5.7, 5.8, 5.9. Rules 5.2, 5.4, 5.5 require
preprocessor / token-level information beyond pycparser's AST and are skipped.

Cross-file rules (5.1, 5.6-5.9) consult the SymbolTable from AnalysisContext.
For each violating pair, the issue is attributed to the symbol that lives in
the file currently being analyzed, so the same global pair is reported once
in each affected file (matching how compilers and IDEs attribute messages).
"""

from __future__ import annotations

from pycparser import c_ast

from covia.checkers.base import BaseChecker
from covia.models import Issue, MisraCategory, MisraRule, Severity
from covia.registry import CheckerRegistry


RULE_5_1 = MisraRule("5.1", MisraCategory.REQUIRED, "External identifiers shall be distinct")
RULE_5_3 = MisraRule("5.3", MisraCategory.REQUIRED, "An identifier declared in an inner scope shall not hide an identifier declared in an outer scope")
RULE_5_6 = MisraRule("5.6", MisraCategory.REQUIRED, "A typedef name shall be a unique identifier")
RULE_5_7 = MisraRule("5.7", MisraCategory.REQUIRED, "A tag name shall be a unique identifier")
RULE_5_8 = MisraRule("5.8", MisraCategory.REQUIRED, "Identifiers that define objects or functions with external linkage shall be unique")
RULE_5_9 = MisraRule("5.9", MisraCategory.ADVISORY, "Identifiers that define objects or functions with internal linkage should be unique")

_EXTERN_PREFIX_LEN = 31  # MISRA C:2012 minimum significance for external identifiers


class MisraIdentifiersChecker(BaseChecker):
    checker_id = "misra-identifiers"
    description = "MISRA C:2012 Rules 5.1/5.3/5.6-5.9: identifier uniqueness and shadowing"
    default_severity = Severity.WARNING
    misra_rules = [RULE_5_1, RULE_5_3, RULE_5_6, RULE_5_7, RULE_5_8, RULE_5_9]

    def check(self, ast: c_ast.FileAST):
        self._issues = []
        self._check_local_shadowing(ast)
        self._check_global_uniqueness()
        return list(self._issues)

    # --- Rule 5.3: inner-scope shadowing -------------------------------------

    def _check_local_shadowing(self, ast: c_ast.FileAST) -> None:
        outer: set[str] = set()
        for ext in ast.ext or []:
            if isinstance(ext, c_ast.Decl) and ext.name:
                outer.add(ext.name)
            elif isinstance(ext, c_ast.Typedef) and ext.name:
                outer.add(ext.name)
            elif isinstance(ext, c_ast.FuncDef) and ext.decl and ext.decl.name:
                outer.add(ext.decl.name)

        for ext in ast.ext or []:
            if isinstance(ext, c_ast.FuncDef):
                self._scan_function(ext, [outer])

    def _scan_function(self, fd: c_ast.FuncDef, scopes: list[set[str]]) -> None:
        param_names: set[str] = set()
        func_decl = fd.decl.type if fd.decl else None
        while isinstance(func_decl, c_ast.PtrDecl):
            func_decl = func_decl.type
        if isinstance(func_decl, c_ast.FuncDecl) and func_decl.args:
            for p in func_decl.args.params or []:
                if isinstance(p, c_ast.Decl) and p.name:
                    if any(p.name in s for s in scopes):
                        self.report(
                            p,
                            f"Parameter '{p.name}' shadows an outer-scope identifier",
                            Severity.WARNING,
                            RULE_5_3,
                        )
                    param_names.add(p.name)

        if fd.body:
            self._walk_compound(fd.body, scopes + [param_names])

    def _walk_compound(self, comp: c_ast.Compound, scopes: list[set[str]]) -> None:
        local: set[str] = set()
        scopes = scopes + [local]
        for item in comp.block_items or []:
            if isinstance(item, c_ast.Decl) and item.name:
                if any(item.name in s for s in scopes[:-1]):
                    self.report(
                        item,
                        f"Identifier '{item.name}' shadows an outer-scope identifier",
                        Severity.WARNING,
                        RULE_5_3,
                    )
                local.add(item.name)
            elif isinstance(item, c_ast.Compound):
                self._walk_compound(item, scopes)
            else:
                for _, child in item.children():
                    if isinstance(child, c_ast.Compound):
                        self._walk_compound(child, scopes)

    # --- Cross-file rules ----------------------------------------------------

    def _check_global_uniqueness(self) -> None:
        if self._ctx is None:
            return
        table = self._ctx.symbol_table

        self._check_5_1(table)
        self._check_5_6(table)
        self._check_5_7(table)
        self._check_5_8(table)
        self._check_5_9(table)

    def _emit_for_current_file(
        self, file: str, line: int, column: int, message: str, rule: MisraRule,
        severity: Severity = Severity.WARNING,
    ) -> None:
        if file != self._current_file:
            return
        self._issues.append(
            Issue(
                checker_id=self.checker_id,
                severity=severity,
                message=message,
                file=file,
                line=line,
                column=column,
                misra_rule=rule,
            )
        )

    def _check_5_1(self, table) -> None:
        seen: dict[str, list] = {}
        for sym in table.globals.values():
            if sym.is_static:
                continue
            seen.setdefault(sym.name[:_EXTERN_PREFIX_LEN], []).append(sym)
        for prefix, syms in seen.items():
            distinct_names = {s.name for s in syms}
            if len(distinct_names) > 1:
                for s in syms:
                    others = sorted(distinct_names - {s.name})
                    self._emit_for_current_file(
                        s.file, s.line, s.column,
                        f"External identifier '{s.name}' is not distinct from '{others[0]}' in first {_EXTERN_PREFIX_LEN} characters",
                        RULE_5_1,
                    )

    def _check_5_6(self, table) -> None:
        for typedef_name in table.typedefs:
            if typedef_name in table.globals:
                sym = table.globals[typedef_name]
                self._emit_for_current_file(
                    sym.file, sym.line, sym.column,
                    f"typedef name '{typedef_name}' collides with an external identifier",
                    RULE_5_6,
                )

    def _check_5_7(self, table) -> None:
        seen: dict[str, list] = {}
        for tag_key, tag in table.tags.items():
            seen.setdefault(tag.name, []).append((tag_key, tag))
        for name, items in seen.items():
            keys = {k for k, _ in items}
            if len(keys) > 1:
                for _, tag in items:
                    others = sorted(keys - {f"{tag.tag_kind} {tag.name}"})
                    self._emit_for_current_file(
                        tag.file, tag.line, tag.column,
                        f"tag name '{name}' is not unique (also used as {others[0]})",
                        RULE_5_7,
                    )

    def _check_5_8(self, table) -> None:
        defs: dict[str, list] = {}
        for sym in table._all_decls:
            if sym.is_definition and not sym.is_static and sym.scope == "global":
                defs.setdefault(sym.name, []).append(sym)
        for name, items in defs.items():
            files = {s.file for s in items}
            if len(files) > 1:
                for s in items:
                    self._emit_for_current_file(
                        s.file, s.line, s.column,
                        f"External identifier '{name}' is defined in multiple files: {', '.join(sorted(files))}",
                        RULE_5_8,
                    )

    def _check_5_9(self, table) -> None:
        owners: dict[str, list[str]] = {}
        for filename, locals_in_file in table.file_locals.items():
            for name in locals_in_file:
                owners.setdefault(name, []).append(filename)
        for name, files in owners.items():
            if len(files) > 1:
                for f in files:
                    sym = table.file_locals[f][name]
                    self._emit_for_current_file(
                        sym.file, sym.line, sym.column,
                        f"Internal-linkage identifier '{name}' is also defined in: {', '.join(sorted(set(files) - {f}))}",
                        RULE_5_9,
                        severity=Severity.INFO,
                    )


CheckerRegistry.register(MisraIdentifiersChecker)

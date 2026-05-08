"""Checker registry for dynamic loading and lookup."""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Optional

from covia.checkers.base import BaseChecker

_BUILTIN_MODULES = [
    "syntax",
    "unused_vars",
    "uninit_vars",
    "dead_code",
    "null_deref",
    "buffer_overflow",
    "misra_types",
    "misra_decl",
    "misra_expr",
    "misra_control",
    "misra_func",
    "misra_pointer",
    "misra_preproc",
    "memory_leak",
    "resource_leak",
    "misra_identifiers",
    "misra_pointer_conv",
    "misra_standard_lib",
]


class CheckerRegistry:
    _checkers: dict[str, type[BaseChecker]] = {}
    _loaded: bool = False

    @classmethod
    def register(cls, checker_cls: type[BaseChecker]) -> type[BaseChecker]:
        cls._checkers[checker_cls.checker_id] = checker_cls
        return checker_cls

    @classmethod
    def get(cls, checker_id: str) -> Optional[type[BaseChecker]]:
        cls._ensure_loaded()
        return cls._checkers.get(checker_id)

    @classmethod
    def get_all(cls) -> list[type[BaseChecker]]:
        cls._ensure_loaded()
        return list(cls._checkers.values())

    @classmethod
    def get_by_misra_rule(cls, rule_id: str) -> list[type[BaseChecker]]:
        cls._ensure_loaded()
        result = []
        for checker_cls in cls._checkers.values():
            for rule in checker_cls.misra_rules:
                if rule.rule_id == rule_id:
                    result.append(checker_cls)
                    break
        return result

    @classmethod
    def load_builtin_checkers(cls) -> None:
        if cls._loaded:
            return
        for mod_name in _BUILTIN_MODULES:
            try:
                importlib.import_module(f"covia.checkers.{mod_name}")
            except ImportError:
                pass
        cls._loaded = True

    @classmethod
    def load_external_checkers(cls, directory: str) -> None:
        path = Path(directory)
        if not path.is_dir():
            return
        import sys
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
        for py_file in path.glob("*.py"):
            if py_file.name.startswith("_"):
                continue
            mod_name = py_file.stem
            try:
                importlib.import_module(mod_name)
            except ImportError:
                pass

    @classmethod
    def _ensure_loaded(cls) -> None:
        if not cls._loaded:
            cls.load_builtin_checkers()

    @classmethod
    def reset(cls) -> None:
        cls._checkers.clear()
        cls._loaded = False

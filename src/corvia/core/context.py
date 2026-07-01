"""AnalysisContext: shared state passed to checkers for inter-procedural queries."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from pycparser import c_ast

from corvia.core.call_graph import CallGraph
from corvia.core.summary import FunctionSummary
from corvia.core.symbol_table import SymbolTable


@dataclass
class AnalysisContext:
    symbol_table: SymbolTable
    call_graph: CallGraph
    summaries: dict[str, FunctionSummary]
    asts: dict[str, c_ast.FileAST] = field(default_factory=dict)

    def summary_of(self, func_name: str) -> Optional[FunctionSummary]:
        return self.summaries.get(func_name)

    def is_alloc_function(self, func_name: str) -> bool:
        s = self.summaries.get(func_name)
        return bool(s and s.allocates)

    def is_open_function(self, func_name: str) -> bool:
        s = self.summaries.get(func_name)
        return bool(s and s.opens_resource)

    def is_free_function(self, func_name: str) -> bool:
        s = self.summaries.get(func_name)
        return bool(s and s.frees_param)

    def is_close_function(self, func_name: str) -> bool:
        s = self.summaries.get(func_name)
        return bool(s and s.closes_param)

    def function_returns_null(self, func_name: str) -> bool:
        s = self.summaries.get(func_name)
        if s is None:
            return False
        from corvia.core.summary import TriState
        return s.returns_null in (TriState.YES, TriState.MAYBE)

    def function_output_param_not_initialized(self, func_name: str, param_idx: int) -> bool:
        s = self.summaries.get(func_name)
        if s is None:
            return False
        return param_idx in s.output_params_not_initialized

    def function_initializes_output_param(self, func_name: str, param_idx: int) -> bool:
        """True if func_name writes through its param_idx-th pointer parameter
        (e.g. *p = ... or p->f = ...), thereby initializing the caller's object.

        Returns False for unknown/external functions: without a body we cannot
        prove initialization, so callers stay conservative. Address-of arguments
        to such functions are handled by the caller's own heuristics.
        """
        s = self.summaries.get(func_name)
        if s is None:
            return False
        return param_idx in s.output_params_initialized

"""Generic dataflow analysis framework over CFG."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Generic, TypeVar

from corvia.core.cfg import BasicBlock, CFG

T = TypeVar("T")

logger = logging.getLogger(__name__)


class ForwardAnalysis(ABC, Generic[T]):
    """Forward dataflow analysis: propagates facts from entry to exit."""

    @abstractmethod
    def initial_state(self) -> T:
        ...

    @abstractmethod
    def entry_state(self) -> T:
        ...

    @abstractmethod
    def transfer(self, block: BasicBlock, in_state: T) -> T:
        ...

    @abstractmethod
    def merge(self, states: list[T]) -> T:
        ...

    @abstractmethod
    def equal(self, a: T, b: T) -> bool:
        ...

    def analyze(self, cfg: CFG) -> dict[int, tuple[T, T]]:
        in_states: dict[int, T] = {}
        out_states: dict[int, T] = {}

        for block in cfg.blocks:
            if block.is_entry:
                in_states[block.id] = self.entry_state()
            else:
                in_states[block.id] = self.initial_state()
            out_states[block.id] = self.initial_state()

        changed = True
        max_iterations = len(cfg.blocks) * 10
        iteration = 0

        while changed and iteration < max_iterations:
            changed = False
            iteration += 1

            for block in cfg.blocks:
                if block.predecessors:
                    pred_outs = [out_states[p.id] for p in block.predecessors if p.id in out_states]
                    new_in = self.merge(pred_outs) if pred_outs else self.initial_state()
                elif block.is_entry:
                    new_in = self.entry_state()
                else:
                    new_in = self.initial_state()

                in_states[block.id] = new_in
                new_out = self.transfer(block, new_in)

                if not self.equal(out_states[block.id], new_out):
                    out_states[block.id] = new_out
                    changed = True

        if changed:
            # Fixpoint not reached within the iteration budget: results are
            # a sound-ish snapshot but may be imprecise. Warn, don't raise.
            logger.warning(
                "Forward dataflow analysis did not converge after %d "
                "iterations for CFG '%s' (%d blocks)",
                max_iterations,
                cfg.func_name,
                len(cfg.blocks),
            )

        return {bid: (in_states[bid], out_states[bid]) for bid in in_states}


class BackwardAnalysis(ABC, Generic[T]):
    """Backward dataflow analysis: propagates facts from exit to entry."""

    @abstractmethod
    def initial_state(self) -> T:
        ...

    @abstractmethod
    def exit_state(self) -> T:
        ...

    @abstractmethod
    def transfer(self, block: BasicBlock, out_state: T) -> T:
        ...

    @abstractmethod
    def merge(self, states: list[T]) -> T:
        ...

    @abstractmethod
    def equal(self, a: T, b: T) -> bool:
        ...

    def analyze(self, cfg: CFG) -> dict[int, tuple[T, T]]:
        in_states: dict[int, T] = {}
        out_states: dict[int, T] = {}

        for block in cfg.blocks:
            in_states[block.id] = self.initial_state()
            if block.is_exit:
                out_states[block.id] = self.exit_state()
            else:
                out_states[block.id] = self.initial_state()

        changed = True
        max_iterations = len(cfg.blocks) * 10
        iteration = 0

        while changed and iteration < max_iterations:
            changed = False
            iteration += 1

            for block in reversed(cfg.blocks):
                if block.successors:
                    succ_ins = [in_states[s.id] for s in block.successors if s.id in in_states]
                    new_out = self.merge(succ_ins) if succ_ins else self.initial_state()
                elif block.is_exit:
                    new_out = self.exit_state()
                else:
                    new_out = self.initial_state()

                out_states[block.id] = new_out
                new_in = self.transfer(block, new_out)

                if not self.equal(in_states[block.id], new_in):
                    in_states[block.id] = new_in
                    changed = True

        if changed:
            # Fixpoint not reached within the iteration budget: results are
            # a sound-ish snapshot but may be imprecise. Warn, don't raise.
            logger.warning(
                "Backward dataflow analysis did not converge after %d "
                "iterations for CFG '%s' (%d blocks)",
                max_iterations,
                cfg.func_name,
                len(cfg.blocks),
            )

        return {bid: (in_states[bid], out_states[bid]) for bid in in_states}

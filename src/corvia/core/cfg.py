"""Control Flow Graph construction from pycparser AST."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from pycparser import c_ast


@dataclass
class BasicBlock:
    id: int
    statements: list[c_ast.Node] = field(default_factory=list)
    successors: list[BasicBlock] = field(default_factory=list)
    predecessors: list[BasicBlock] = field(default_factory=list)
    is_entry: bool = False
    is_exit: bool = False
    label: Optional[str] = None

    def add_successor(self, block: BasicBlock) -> None:
        if block not in self.successors:
            self.successors.append(block)
        if self not in block.predecessors:
            block.predecessors.append(self)

    def __hash__(self) -> int:
        return self.id

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, BasicBlock):
            return NotImplemented
        return self.id == other.id

    def __repr__(self) -> str:
        succ_ids = [b.id for b in self.successors]
        return f"BB{self.id}(stmts={len(self.statements)}, succ={succ_ids})"


@dataclass
class CFG:
    entry: BasicBlock
    exit: BasicBlock
    blocks: list[BasicBlock] = field(default_factory=list)
    func_name: str = ""

    def get_block(self, block_id: int) -> Optional[BasicBlock]:
        for b in self.blocks:
            if b.id == block_id:
                return b
        return None

    def reachable_blocks(self) -> set[BasicBlock]:
        visited: set[BasicBlock] = set()
        worklist = [self.entry]
        while worklist:
            block = worklist.pop()
            if block in visited:
                continue
            visited.add(block)
            worklist.extend(block.successors)
        return visited


class CFGBuilder:
    """Builds a Control Flow Graph from a function body."""

    def __init__(self) -> None:
        self._block_counter = 0
        self._label_blocks: dict[str, BasicBlock] = {}
        self._pending_gotos: list[tuple[BasicBlock, str]] = []
        # Explicit break/continue target stacks. Loops push (after_block,
        # header_block); switches push only a break target. A `break` or
        # `continue` statement connects to the innermost matching target,
        # so a break inside a switch nested in a loop exits the switch, not
        # the loop.
        self._break_targets: list[BasicBlock] = []
        self._continue_targets: list[BasicBlock] = []

    def build(self, func_def: c_ast.FuncDef) -> CFG:
        self._block_counter = 0
        self._label_blocks = {}
        self._pending_gotos = []
        self._break_targets = []
        self._continue_targets = []

        entry = self._new_block()
        entry.is_entry = True
        exit_block = self._new_block()
        exit_block.is_exit = True

        if func_def.body and func_def.body.block_items:
            last = self._process_stmts(func_def.body.block_items, entry, exit_block)
            if last and last != exit_block:
                last.add_successor(exit_block)
        else:
            entry.add_successor(exit_block)

        for block, label in self._pending_gotos:
            if label in self._label_blocks:
                block.add_successor(self._label_blocks[label])

        all_blocks = self._collect_blocks(entry)
        if exit_block not in all_blocks:
            all_blocks.add(exit_block)

        func_name = func_def.decl.name if func_def.decl else "<anonymous>"
        return CFG(
            entry=entry,
            exit=exit_block,
            blocks=list(all_blocks),
            func_name=func_name,
        )

    def _new_block(self) -> BasicBlock:
        block = BasicBlock(id=self._block_counter)
        self._block_counter += 1
        return block

    def _process_stmts(
        self,
        stmts: list[c_ast.Node],
        current: BasicBlock,
        exit_block: BasicBlock,
    ) -> Optional[BasicBlock]:
        for stmt in stmts:
            result = self._process_stmt(stmt, current, exit_block)
            if result is None:
                return None
            current = result
        return current

    def _process_stmt(
        self,
        stmt: c_ast.Node,
        current: BasicBlock,
        exit_block: BasicBlock,
    ) -> Optional[BasicBlock]:
        if isinstance(stmt, c_ast.If):
            return self._process_if(stmt, current, exit_block)
        elif isinstance(stmt, c_ast.While):
            return self._process_while(stmt, current, exit_block)
        elif isinstance(stmt, c_ast.DoWhile):
            return self._process_dowhile(stmt, current, exit_block)
        elif isinstance(stmt, c_ast.For):
            return self._process_for(stmt, current, exit_block)
        elif isinstance(stmt, c_ast.Switch):
            return self._process_switch(stmt, current, exit_block)
        elif isinstance(stmt, c_ast.Return):
            current.statements.append(stmt)
            current.add_successor(exit_block)
            return None
        elif isinstance(stmt, c_ast.Break):
            current.statements.append(stmt)
            if self._break_targets:
                current.add_successor(self._break_targets[-1])
            return None
        elif isinstance(stmt, c_ast.Continue):
            current.statements.append(stmt)
            if self._continue_targets:
                current.add_successor(self._continue_targets[-1])
            return None
        elif isinstance(stmt, c_ast.Goto):
            current.statements.append(stmt)
            self._pending_gotos.append((current, stmt.name))
            return None
        elif isinstance(stmt, c_ast.Label):
            new_block = self._new_block()
            new_block.label = stmt.name
            self._label_blocks[stmt.name] = new_block
            current.add_successor(new_block)
            if stmt.stmt:
                # Recurse so structured statements after a label (if/while/
                # switch/...) get a proper CFG instead of being appended raw.
                return self._process_stmt(stmt.stmt, new_block, exit_block)
            return new_block
        elif isinstance(stmt, c_ast.Compound):
            if stmt.block_items:
                return self._process_stmts(stmt.block_items, current, exit_block)
            return current
        else:
            current.statements.append(stmt)
            return current

    def _process_if(
        self,
        node: c_ast.If,
        current: BasicBlock,
        exit_block: BasicBlock,
    ) -> Optional[BasicBlock]:
        current.statements.append(node.cond)

        true_block = self._new_block()
        current.add_successor(true_block)

        merge_block = self._new_block()

        if node.iftrue:
            if isinstance(node.iftrue, c_ast.Compound) and node.iftrue.block_items:
                true_end = self._process_stmts(node.iftrue.block_items, true_block, exit_block)
            else:
                true_end = self._process_stmt(node.iftrue, true_block, exit_block)
            if true_end is not None:
                true_end.add_successor(merge_block)
        else:
            true_block.add_successor(merge_block)

        if node.iffalse:
            false_block = self._new_block()
            current.add_successor(false_block)
            if isinstance(node.iffalse, c_ast.Compound) and node.iffalse.block_items:
                false_end = self._process_stmts(node.iffalse.block_items, false_block, exit_block)
            elif isinstance(node.iffalse, c_ast.If):
                false_end = self._process_if(node.iffalse, false_block, exit_block)
            else:
                false_end = self._process_stmt(node.iffalse, false_block, exit_block)
            if false_end is not None:
                false_end.add_successor(merge_block)
        else:
            current.add_successor(merge_block)

        return merge_block

    def _process_while(
        self,
        node: c_ast.While,
        current: BasicBlock,
        exit_block: BasicBlock,
    ) -> Optional[BasicBlock]:
        cond_block = self._new_block()
        current.add_successor(cond_block)
        if node.cond:
            cond_block.statements.append(node.cond)

        body_block = self._new_block()
        after_block = self._new_block()

        cond_block.add_successor(body_block)
        cond_block.add_successor(after_block)

        self._break_targets.append(after_block)
        self._continue_targets.append(cond_block)
        try:
            if node.stmt:
                if isinstance(node.stmt, c_ast.Compound) and node.stmt.block_items:
                    body_end = self._process_stmts(node.stmt.block_items, body_block, exit_block)
                else:
                    body_end = self._process_stmt(node.stmt, body_block, exit_block)
                if body_end is not None:
                    body_end.add_successor(cond_block)
            else:
                body_block.add_successor(cond_block)
        finally:
            self._continue_targets.pop()
            self._break_targets.pop()

        return after_block

    def _process_dowhile(
        self,
        node: c_ast.DoWhile,
        current: BasicBlock,
        exit_block: BasicBlock,
    ) -> Optional[BasicBlock]:
        body_block = self._new_block()
        current.add_successor(body_block)

        cond_block = self._new_block()
        after_block = self._new_block()

        self._break_targets.append(after_block)
        self._continue_targets.append(cond_block)
        try:
            if node.stmt:
                if isinstance(node.stmt, c_ast.Compound) and node.stmt.block_items:
                    body_end = self._process_stmts(node.stmt.block_items, body_block, exit_block)
                else:
                    body_end = self._process_stmt(node.stmt, body_block, exit_block)
                if body_end is not None:
                    body_end.add_successor(cond_block)
            else:
                body_block.add_successor(cond_block)
        finally:
            self._continue_targets.pop()
            self._break_targets.pop()

        if node.cond:
            cond_block.statements.append(node.cond)
        cond_block.add_successor(body_block)
        cond_block.add_successor(after_block)

        return after_block

    def _process_for(
        self,
        node: c_ast.For,
        current: BasicBlock,
        exit_block: BasicBlock,
    ) -> Optional[BasicBlock]:
        if node.init:
            current.statements.append(node.init)

        cond_block = self._new_block()
        current.add_successor(cond_block)
        if node.cond:
            cond_block.statements.append(node.cond)

        body_block = self._new_block()
        after_block = self._new_block()

        cond_block.add_successor(body_block)
        cond_block.add_successor(after_block)

        incr_block = self._new_block()
        if node.next:
            incr_block.statements.append(node.next)
        incr_block.add_successor(cond_block)

        self._break_targets.append(after_block)
        self._continue_targets.append(incr_block)
        try:
            if node.stmt:
                if isinstance(node.stmt, c_ast.Compound) and node.stmt.block_items:
                    body_end = self._process_stmts(node.stmt.block_items, body_block, exit_block)
                else:
                    body_end = self._process_stmt(node.stmt, body_block, exit_block)
                if body_end is not None:
                    body_end.add_successor(incr_block)
            else:
                body_block.add_successor(incr_block)
        finally:
            self._continue_targets.pop()
            self._break_targets.pop()

        return after_block

    def _process_switch(
        self,
        node: c_ast.Switch,
        current: BasicBlock,
        exit_block: BasicBlock,
    ) -> Optional[BasicBlock]:
        """Build the CFG for a switch statement.

        pycparser nests each case's statements (including its ``break``)
        inside ``Case.stmts`` / ``Default.stmts``, so break handling relies
        on the explicit break-target stack: a Break processed anywhere in a
        case body connects to this switch's after-block (not to an enclosing
        loop's exit). When the switch has no ``default`` label, an edge from
        the switch head to the after-block models "no case matches".
        """
        current.statements.append(node.cond)
        after_block = self._new_block()

        has_default = False
        self._break_targets.append(after_block)
        try:
            if node.stmt and isinstance(node.stmt, c_ast.Compound) and node.stmt.block_items:
                prev_block: Optional[BasicBlock] = None
                for item in node.stmt.block_items:
                    if isinstance(item, (c_ast.Case, c_ast.Default)):
                        case_block = self._new_block()
                        current.add_successor(case_block)
                        if prev_block is not None:
                            # Fall-through from the previous (break-less) case.
                            prev_block.add_successor(case_block)

                        if isinstance(item, c_ast.Default):
                            has_default = True
                        if isinstance(item, c_ast.Case):
                            case_block.statements.append(item.expr)
                        if item.stmts:
                            prev_block = self._process_stmts(item.stmts, case_block, exit_block)
                        else:
                            prev_block = case_block
                    else:
                        # Statement at switch level outside any label (e.g.
                        # ASTs shaped by fix_switch_cases where break is a
                        # sibling of Case). It only executes via fall-through.
                        if prev_block is not None:
                            prev_block = self._process_stmt(item, prev_block, exit_block)

                if prev_block is not None:
                    # Last case falls out of the switch.
                    prev_block.add_successor(after_block)
        finally:
            self._break_targets.pop()

        if not has_default:
            # No default: the switch may match no case and skip straight past.
            current.add_successor(after_block)

        return after_block

    def _collect_blocks(self, entry: BasicBlock) -> set[BasicBlock]:
        visited: set[BasicBlock] = set()
        worklist = [entry]
        while worklist:
            block = worklist.pop()
            if block in visited:
                continue
            visited.add(block)
            worklist.extend(block.successors)
        return visited


def build_cfg(func_def: c_ast.FuncDef) -> CFG:
    builder = CFGBuilder()
    return builder.build(func_def)

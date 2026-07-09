"""Incremental analysis cache.

Each analyzed file gets a JSON entry under the cache directory keyed by
the absolute file path. We persist:
  - content_hash (SHA-256) used to detect changes
  - mtime (defensive)
  - issues produced by the last analysis
  - the call graph dependency set: every external function called by this
    file. When a function defined in B changes, all files that called it
    are invalidated.
  - external definitions provided by this file, so we can compute the
    reverse dependency lookup.

The cache format is intentionally simple JSON with a schema_version so we
can break compatibility cleanly if needed.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from corvia.models import Issue, MisraCategory, MisraRule, Severity


# v2: added env_hash (analysis environment fingerprint) and normalized paths.
SCHEMA_VERSION = 2


def _normalize_path(file: str) -> str:
    """Canonical cache key for a file path (resolved + case-normalized)."""
    return os.path.normcase(str(Path(file).resolve()))


@dataclass
class FileCache:
    path: str
    content_hash: str
    mtime: float
    issues: list[Issue] = field(default_factory=list)
    callees: list[str] = field(default_factory=list)  # functions this file calls
    defines: list[str] = field(default_factory=list)  # external function names defined here
    env_hash: str = ""  # fingerprint of the analysis environment (flags/checkers/version)

    def to_json(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "path": self.path,
            "content_hash": self.content_hash,
            "mtime": self.mtime,
            "issues": [_issue_to_json(i) for i in self.issues],
            "callees": self.callees,
            "defines": self.defines,
            "env_hash": self.env_hash,
        }

    @classmethod
    def from_json(cls, data: dict) -> Optional["FileCache"]:
        if data.get("schema_version") != SCHEMA_VERSION:
            return None
        return cls(
            path=data["path"],
            content_hash=data["content_hash"],
            mtime=data["mtime"],
            issues=[_issue_from_json(d) for d in data.get("issues", [])],
            callees=list(data.get("callees", [])),
            defines=list(data.get("defines", [])),
            env_hash=str(data.get("env_hash", "")),
        )


def _issue_to_json(i: Issue) -> dict:
    d = i.to_dict()
    d["severity"] = i.severity.name
    return d


def _issue_from_json(d: dict) -> Issue:
    rule = None
    if d.get("misra_rule"):
        r = d["misra_rule"]
        rule = MisraRule(r["rule_id"], MisraCategory(r["category"]), r["description"])
    return Issue(
        checker_id=d["checker_id"],
        severity=Severity[d["severity"]],
        message=d["message"],
        file=d["file"],
        line=d["line"],
        column=d.get("column", 0),
        end_line=d.get("end_line"),
        context=d.get("context"),
        misra_rule=rule,
    )


def hash_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


class CacheManager:
    def __init__(
        self, cache_dir: str | Path = ".corvia_cache", env_hash: str = ""
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.env_hash = env_hash
        self._loaded: dict[str, FileCache] = {}

    def _entry_path(self, file: str) -> Path:
        # Key on the resolved, case-normalized path so the same file reached
        # via different spellings (relative vs absolute, case differences on
        # Windows) maps to a single cache entry. Hash the normalized path to
        # avoid filesystem-incompatible names.
        key = hashlib.sha256(_normalize_path(file).encode()).hexdigest()[:32]
        return self.cache_dir / f"{key}.json"

    def load(self, file: str) -> Optional[FileCache]:
        norm = _normalize_path(file)
        if norm in self._loaded:
            return self._loaded[norm]
        p = self._entry_path(file)
        if not p.exists():
            return None
        try:
            data = json.loads(p.read_text())
        except (OSError, json.JSONDecodeError):
            return None
        cache = FileCache.from_json(data)
        if cache is not None:
            self._loaded[norm] = cache
        return cache

    def save(self, cache: FileCache) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        # Store resolved paths so entries are stable across spellings.
        cache.path = str(Path(cache.path).resolve())
        if not cache.env_hash:
            cache.env_hash = self.env_hash
        p = self._entry_path(cache.path)
        p.write_text(json.dumps(cache.to_json(), indent=2))
        self._loaded[_normalize_path(cache.path)] = cache

    def is_valid(self, file: str, current_hash: str) -> bool:
        cached = self.load(file)
        return (
            cached is not None
            and cached.content_hash == current_hash
            and cached.env_hash == self.env_hash
        )

    def clear(self) -> None:
        if self.cache_dir.exists():
            for p in self.cache_dir.glob("*.json"):
                p.unlink()
        self._loaded.clear()

    def find_dependents(self, callee: str, all_files: list[str]) -> set[str]:
        """Return cached files that called `callee`."""
        result: set[str] = set()
        for f in all_files:
            cached = self.load(f)
            if cached and callee in cached.callees:
                result.add(f)
        return result

    def determine_files_to_analyze(
        self,
        files: list[str],
        new_defines: Optional[dict[str, list[str]]] = None,
    ) -> tuple[set[str], set[str]]:
        """Returns (files_to_analyze, files_reusable_from_cache).

        A file must be re-analyzed if:
          - It has no valid cache entry, OR
          - One of the symbols it depends on (functions it calls) was defined
            in a file that itself needs to be re-analyzed.

        ``new_defines`` optionally maps each file to the external function
        names it defines *now* (from a fresh parse). For a changed file the
        invalidation set is the union of its old cached defines and its new
        defines, so both removed and newly-added definitions invalidate
        callers. When ``new_defines`` is not supplied and a changed file has
        no cache entry (we cannot know what it defines), we conservatively
        invalidate every cached file — correctness over cache hits.
        """
        changed: set[str] = set()
        for f in files:
            try:
                h = hash_file(f)
            except OSError:
                changed.add(f)
                continue
            if not self.is_valid(f, h):
                changed.add(f)

        # Dependency invalidation: if a defining file changed, callers must
        # be re-analyzed because summaries may have shifted.
        invalidated_definers = set(changed)
        invalidated_symbols: set[str] = set()
        for f in invalidated_definers:
            cached = self.load(f)
            if cached:
                invalidated_symbols.update(cached.defines)
            elif new_defines is None:
                # Changed file with no cache entry and no fresh parse info:
                # its definitions are unknown, so conservatively re-analyze
                # everything rather than risk stale cross-file results.
                return set(files), set()
            if new_defines is not None:
                invalidated_symbols.update(new_defines.get(f, []))

        if invalidated_symbols:
            queue = list(invalidated_symbols)
            seen_callers: set[str] = set()
            while queue:
                sym = queue.pop()
                for f in files:
                    if f in seen_callers or f in changed:
                        continue
                    cached = self.load(f)
                    if cached and sym in cached.callees:
                        seen_callers.add(f)
                        changed.add(f)
                        # Cascade: this file's defines may now have new
                        # summaries downstream callers care about.
                        queue.extend(cached.defines)

        reusable = set(files) - changed
        return changed, reusable

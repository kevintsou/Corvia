"""FP-rate baseline: freeze per-checker issue counts on a known-good tree and
fail CI when any checker's count *rises* without an explicit re-baseline.

Motivation: Corvia's per-case regression tests (test_fp_regressions.py) pin
individual false positives so a *specific* one cannot silently return, but they
measure nothing about the *aggregate* count on a real tree. So every new
codebase surfaces a fresh batch of false positives as a surprise. A baseline
turns "the count went up" from a surprise into a gated, reviewed event: the
count is committed alongside the project, and a rise is a diff someone signs
off on (or fixes) rather than noise that erodes trust in the report.

Design:
- The baseline file (`.corvia_baseline.json`) is a *per-target-tree* artifact:
  it lives in the target project (next to its corvia.toml), not in the Corvia
  tool. Two projects have different baselines.
- The compare harness lives here in Corvia (reusable across projects).
- A checker whose count *rose* vs baseline => regression => `check` exits 1.
  A checker whose count *fell* => improvement, reported, never fails; the user
  may re-run `capture` to lock in the lower number.
- Counts are keyed by checker id and by severity, plus env metadata (Corvia
  version, config fingerprint, target list) so a legitimate bump (e.g. a Corvia
  upgrade that changes a checker) is visible and explained, not mysterious.

`parser` parse-error entries are counted separately (`parse_errors`), never
folded into checker counts: a parse error is a coverage gap, not a finding, and
must not mask a real checker-count change (see the parser-blame work / SKILL
Step 6).
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Optional

BASELINE_FILENAME = ".corvia_baseline.json"


def _is_parse_error(issue) -> bool:
    """A Corvia parse-error entry: checker id 'parser', synthetic line 0."""
    return getattr(issue, "checker_id", None) == "parser"


def counts_from_result(result) -> dict:
    """Reduce an AnalysisResult to the comparable count vectors.

    Returns per-checker counts (excluding parse errors), per-severity counts,
    and a separate parse-error count so a coverage gap never masks a checker
    change.
    """
    by_checker: Counter = Counter()
    by_severity: Counter = Counter()
    parse_errors = 0
    for issue in result.issues:
        if _is_parse_error(issue):
            parse_errors += 1
            continue
        by_checker[issue.checker_id] += 1
        by_severity[issue.severity.name] += 1
    return {
        "by_checker": dict(sorted(by_checker.items())),
        "by_severity": dict(sorted(by_severity.items())),
        "parse_errors": parse_errors,
        "total_findings": sum(by_checker.values()),
    }


def build_baseline(result, *, corvia_version: str, config_fingerprint: Optional[str],
                   targets: list[str]) -> dict:
    """Assemble the on-disk baseline document from an analysis result."""
    doc = counts_from_result(result)
    doc["_meta"] = {
        "corvia_version": corvia_version,
        "config_fingerprint": config_fingerprint,
        "targets": sorted(targets),
        "files_analyzed": len(result.files_analyzed),
    }
    return doc


def baseline_path(target_dir: str | Path) -> Path:
    return Path(target_dir) / BASELINE_FILENAME


def load_baseline(path: str | Path) -> dict:
    with Path(path).open("r", encoding="utf-8") as f:
        return json.load(f)


def save_baseline(path: str | Path, doc: dict) -> None:
    with Path(path).open("w", encoding="utf-8", newline="\n") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)
        f.write("\n")


def compare(baseline: dict, current: dict) -> dict:
    """Compare a fresh result's counts against the stored baseline.

    Returns a structured diff:
      - regressions: checkers whose count ROSE (baseline -> current). Any
        non-empty => the caller should fail.
      - improvements: checkers whose count FELL.
      - new_checkers: checkers present now but absent from the baseline
        (treated as regressions — a brand-new source of findings is exactly
        what a baseline exists to catch).
      - dropped_checkers: in baseline but zero now (an improvement).
      - parse_error_delta: change in parse-error count (informational; a rise
        means new coverage gaps, surfaced but not itself a checker regression).
    """
    base_c = baseline.get("by_checker", {})
    cur_c = current.get("by_checker", {})
    all_ids = sorted(set(base_c) | set(cur_c))

    regressions: list[dict] = []
    improvements: list[dict] = []
    new_checkers: list[dict] = []
    dropped_checkers: list[dict] = []

    for cid in all_ids:
        b = base_c.get(cid, 0)
        c = cur_c.get(cid, 0)
        if c == b:
            continue
        entry = {"checker": cid, "baseline": b, "current": c, "delta": c - b}
        if b == 0 and c > 0:
            new_checkers.append(entry)
        elif c == 0 and b > 0:
            dropped_checkers.append(entry)
        elif c > b:
            regressions.append(entry)
        else:
            improvements.append(entry)

    return {
        "regressions": regressions,
        "new_checkers": new_checkers,
        "improvements": improvements,
        "dropped_checkers": dropped_checkers,
        "parse_error_delta": current.get("parse_errors", 0) - baseline.get("parse_errors", 0),
        "baseline_total": baseline.get("total_findings", sum(base_c.values())),
        "current_total": current.get("total_findings", sum(cur_c.values())),
    }


def diff_has_regression(diff: dict) -> bool:
    """True when the fresh run introduced findings the baseline didn't have.

    A rise in an existing checker OR a brand-new checker both count. Drops and
    improvements never fail. Parse-error rises are surfaced but do not by
    themselves fail the gate (they are coverage gaps, reported separately).
    """
    return bool(diff["regressions"]) or bool(diff["new_checkers"])


def format_diff_text(diff: dict) -> str:
    """Human-readable diff summary for the `check` command."""
    lines: list[str] = []
    reg = diff["regressions"] + diff["new_checkers"]
    if reg:
        lines.append("REGRESSIONS (checker counts rose vs baseline):")
        for e in sorted(reg, key=lambda x: -x["delta"]):
            tag = " (new checker)" if e["baseline"] == 0 else ""
            lines.append(f"  + {e['checker']}: {e['baseline']} -> {e['current']} (+{e['delta']}){tag}")
    else:
        lines.append("No regressions: no checker's count rose above the baseline.")

    if diff["improvements"] or diff["dropped_checkers"]:
        lines.append("")
        lines.append("Improvements (counts fell — consider re-capturing the baseline):")
        for e in sorted(diff["improvements"] + diff["dropped_checkers"], key=lambda x: x["delta"]):
            gone = " (now zero)" if e["current"] == 0 else ""
            lines.append(f"  - {e['checker']}: {e['baseline']} -> {e['current']} ({e['delta']}){gone}")

    ped = diff["parse_error_delta"]
    if ped != 0:
        lines.append("")
        sign = "+" if ped > 0 else ""
        note = " (new coverage gaps — informational, not a checker regression)" if ped > 0 else ""
        lines.append(f"parse-error count changed: {sign}{ped}{note}")

    lines.append("")
    lines.append(f"totals: baseline {diff['baseline_total']} -> current {diff['current_total']} findings")
    return "\n".join(lines)

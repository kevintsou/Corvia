"""Tests for the checker registry."""

from __future__ import annotations

from corvia.registry import CheckerRegistry


def test_builtin_checkers_load():
    CheckerRegistry.load_builtin_checkers()
    checkers = CheckerRegistry.get_all()
    assert checkers
    assert all(getattr(c, "checker_id", None) for c in checkers)


def test_registry_repopulates_after_reset():
    """Regression: reset() used to clear the registry permanently because
    decorator registration does not re-run when modules are already
    imported."""
    CheckerRegistry.load_builtin_checkers()
    before = {c.checker_id for c in CheckerRegistry.get_all()}
    assert before

    CheckerRegistry.reset()
    assert not CheckerRegistry._checkers

    CheckerRegistry.load_builtin_checkers()
    after = {c.checker_id for c in CheckerRegistry.get_all()}
    assert after == before


def test_get_triggers_lazy_reload_after_reset():
    CheckerRegistry.load_builtin_checkers()
    some_id = CheckerRegistry.get_all()[0].checker_id

    CheckerRegistry.reset()
    # get()/get_all() lazily reload builtins.
    assert CheckerRegistry.get(some_id) is not None

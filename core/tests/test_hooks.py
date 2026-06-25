"""Tests for the hook registry."""

import logging

import pytest

from shilljudge_core.hooks import (
    CALCULATE_SCORE,
    ENRICH_LEADERBOARD,
    ENRICH_THREAD,
    EVENT_BUS,
    FORMAT_EXPORT,
    ON_SUBMISSION,
    UI_SLOT,
    WEBHOOK_SLOT,
    HookRegistry,
)


# ---------------------------------------------------------------------------
# No-op behaviour (no handlers registered)
# ---------------------------------------------------------------------------


def test_no_op_pipeline_returns_input_unchanged():
    r = HookRegistry()
    thread = {"id": "1", "text": "hello"}
    assert r.call(ENRICH_THREAD, thread) == thread


def test_no_op_calculate_score_returns_score_unchanged():
    r = HookRegistry()
    result = r.call(CALCULATE_SCORE, {"id": "1"}, 42.0)
    assert result == 42.0


def test_no_op_collect_returns_empty_dict():
    r = HookRegistry()
    assert r.call(UI_SLOT, "main") == {}


def test_no_op_fire_and_forget_does_nothing():
    r = HookRegistry()
    r.call(WEBHOOK_SLOT, {"event": "ping"})
    r.call(EVENT_BUS, "topic", {"payload": 1})


# ---------------------------------------------------------------------------
# Single handler
# ---------------------------------------------------------------------------


def test_single_handler_pipeline():
    r = HookRegistry()

    def add_field(thread):
        return {**thread, "enriched": True}

    r.register(ENRICH_THREAD, add_field)
    result = r.call(ENRICH_THREAD, {"id": "1"})
    assert result == {"id": "1", "enriched": True}


def test_single_handler_on_submission():
    r = HookRegistry()

    def filter_ids(post_ids, context):
        return [p for p in post_ids if p != "bad"]

    r.register(ON_SUBMISSION, filter_ids)
    result = r.call(ON_SUBMISSION, ["good", "bad", "also_good"], {"user": "x"})
    assert result == ["good", "also_good"]


# ---------------------------------------------------------------------------
# Multi-handler pipeline ordering
# ---------------------------------------------------------------------------


def test_multi_handler_priority_ordering():
    r = HookRegistry()
    order = []

    def first(thread):
        order.append("first")
        return {**thread, "first": True}

    def second(thread):
        order.append("second")
        return {**thread, "second": True}

    r.register(ENRICH_THREAD, second, priority=20)
    r.register(ENRICH_THREAD, first, priority=10)
    result = r.call(ENRICH_THREAD, {"id": "1"})

    assert order == ["first", "second"]
    assert result == {"id": "1", "first": True, "second": True}


def test_equal_priority_uses_insertion_order():
    r = HookRegistry()
    order = []

    def a(thread):
        order.append("a")
        return thread

    def b(thread):
        order.append("b")
        return thread

    r.register(ENRICH_THREAD, a, priority=5)
    r.register(ENRICH_THREAD, b, priority=5)
    r.call(ENRICH_THREAD, {"id": "1"})
    assert order == ["a", "b"]


def test_calculate_score_threads_score_arg_not_thread():
    """score is arg index 1; thread must pass through unchanged."""
    r = HookRegistry()
    received_threads = []

    def double_score(thread, score):
        received_threads.append(thread)
        return score * 2.0

    def add_ten(thread, score):
        received_threads.append(thread)
        return score + 10.0

    r.register(CALCULATE_SCORE, double_score, priority=10)
    r.register(CALCULATE_SCORE, add_ten, priority=20)
    thread = {"id": "1"}
    result = r.call(CALCULATE_SCORE, thread, 5.0)

    assert result == 20.0  # (5.0 * 2) + 10
    assert all(t is thread for t in received_threads)  # thread not mutated between calls


# ---------------------------------------------------------------------------
# Exception isolation
# ---------------------------------------------------------------------------


def test_pipeline_exception_does_not_stop_later_handlers(caplog):
    r = HookRegistry()

    def exploding(thread):
        raise RuntimeError("boom")

    def safe(thread):
        return {**thread, "safe": True}

    r.register(ENRICH_THREAD, exploding, priority=10)
    r.register(ENRICH_THREAD, safe, priority=20)

    with caplog.at_level(logging.ERROR, logger="shilljudge_core.hooks"):
        result = r.call(ENRICH_THREAD, {"id": "1"})

    assert result.get("safe") is True
    assert "exploding" in caplog.text


def test_fire_and_forget_exception_does_not_stop_later_handlers(caplog):
    r = HookRegistry()
    called = []

    def exploding(event):
        raise ValueError("fire error")

    def safe(event):
        called.append("safe")

    r.register(WEBHOOK_SLOT, exploding, priority=10)
    r.register(WEBHOOK_SLOT, safe, priority=20)

    with caplog.at_level(logging.ERROR, logger="shilljudge_core.hooks"):
        r.call(WEBHOOK_SLOT, {"event": "test"})

    assert "safe" in called
    assert "exploding" in caplog.text


# ---------------------------------------------------------------------------
# Deregister
# ---------------------------------------------------------------------------


def test_deregister_removes_handler():
    r = HookRegistry()

    def handler(thread):
        return {**thread, "modified": True}

    r.register(ENRICH_THREAD, handler)
    r.deregister(ENRICH_THREAD, handler)
    result = r.call(ENRICH_THREAD, {"id": "1"})
    assert "modified" not in result


def test_deregister_unknown_hook_is_noop():
    r = HookRegistry()

    def handler(thread):
        return thread

    r.deregister(ENRICH_THREAD, handler)  # never registered — must not raise


# ---------------------------------------------------------------------------
# Collect (ui_slot)
# ---------------------------------------------------------------------------


def test_collect_merges_handler_dicts():
    r = HookRegistry()

    def slot_a(_slot):
        return {"header": "<b>Hello</b>"}

    def slot_b(_slot):
        return {"footer": "<p>Bye</p>"}

    r.register(UI_SLOT, slot_a)
    r.register(UI_SLOT, slot_b)
    result = r.call(UI_SLOT, "main")
    assert result == {"header": "<b>Hello</b>", "footer": "<p>Bye</p>"}


# ---------------------------------------------------------------------------
# Module-level exports
# ---------------------------------------------------------------------------


def test_module_registry_and_constants_importable():
    from shilljudge_core import (
        CALCULATE_SCORE as CS,
        ENRICH_LEADERBOARD as EL,
        ENRICH_THREAD as ET,
        EVENT_BUS as EB,
        FORMAT_EXPORT as FE,
        ON_SUBMISSION as OS,
        UI_SLOT as US,
        WEBHOOK_SLOT as WS,
        registry,
    )

    assert isinstance(registry, HookRegistry)
    assert OS == "on_submission"
    assert ET == "enrich_thread"
    assert CS == "calculate_score"
    assert EL == "enrich_leaderboard"
    assert FE == "format_export"
    assert US == "ui_slot"
    assert WS == "webhook_slot"
    assert EB == "event_bus"


def test_unknown_hook_raises():
    r = HookRegistry()
    with pytest.raises(ValueError, match="Unknown hook"):
        r.call("not_a_real_hook")

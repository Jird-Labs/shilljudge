"""Hook registry for shilljudge-core extension points."""

import logging

logger = logging.getLogger(__name__)

# Named hook constants — use these at call sites to avoid string typos
ON_SUBMISSION = "on_submission"
ENRICH_THREAD = "enrich_thread"
CALCULATE_SCORE = "calculate_score"
ENRICH_LEADERBOARD = "enrich_leaderboard"
FORMAT_EXPORT = "format_export"
UI_SLOT = "ui_slot"
WEBHOOK_SLOT = "webhook_slot"
EVENT_BUS = "event_bus"

_PIPELINE = "pipeline"
_COLLECT = "collect"
_FIRE = "fire"

# dispatch type + index of the argument that threads through pipeline handlers
# (on_submission: post_ids is arg 0; calculate_score: score is arg 1)
_HOOK_META: dict[str, tuple[str, int]] = {
    ON_SUBMISSION: (_PIPELINE, 0),
    ENRICH_THREAD: (_PIPELINE, 0),
    CALCULATE_SCORE: (_PIPELINE, 1),
    ENRICH_LEADERBOARD: (_PIPELINE, 0),
    FORMAT_EXPORT: (_PIPELINE, 0),
    UI_SLOT: (_COLLECT, 0),
    WEBHOOK_SLOT: (_FIRE, 0),
    EVENT_BUS: (_FIRE, 0),
}


class HookRegistry:
    def __init__(self) -> None:
        # (priority, insertion_order, handler) — insertion order breaks priority ties
        self._handlers: dict[str, list[tuple[int, int, object]]] = {}
        self._counter: int = 0

    def register(self, name: str, handler, priority: int = 0) -> None:
        if name not in self._handlers:
            self._handlers[name] = []
        self._handlers[name].append((priority, self._counter, handler))
        self._counter += 1
        self._handlers[name].sort(key=lambda x: (x[0], x[1]))

    @property
    def known_hooks(self) -> frozenset:
        return frozenset(_HOOK_META.keys())

    def deregister(self, name: str, handler) -> None:
        if name not in self._handlers:
            return
        self._handlers[name] = [
            (p, c, h) for p, c, h in self._handlers[name] if h is not handler
        ]

    def call(self, name: str, *args):
        meta = _HOOK_META.get(name)
        if meta is None:
            raise ValueError(f"Unknown hook: {name!r}")

        dispatch, threaded_idx = meta
        handlers = self._handlers.get(name, [])

        if dispatch == _PIPELINE:
            args = list(args)
            for _, _, handler in handlers:
                try:
                    args[threaded_idx] = handler(*args)
                except Exception:
                    handler_name = getattr(handler, "__name__", repr(handler))
                    logger.exception("Hook %r: handler %r raised", name, handler_name)
            return args[threaded_idx]

        if dispatch == _COLLECT:
            merged: dict = {}
            for _, _, handler in handlers:
                try:
                    result = handler(*args)
                    if isinstance(result, dict):
                        merged.update(result)
                except Exception:
                    handler_name = getattr(handler, "__name__", repr(handler))
                    logger.exception("Hook %r: handler %r raised", name, handler_name)
            return merged

        # _FIRE: fire-and-forget, one failure must not stop others
        for _, _, handler in handlers:
            try:
                handler(*args)
            except Exception:
                handler_name = getattr(handler, "__name__", repr(handler))
                logger.exception("Hook %r: handler %r raised", name, handler_name)


registry = HookRegistry()

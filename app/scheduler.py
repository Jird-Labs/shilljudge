"""Background public-metrics polling engine (DEV-26).

Periodically re-fetches every post in the active contest from X, stores the
latest public metrics (used for scoring) via ``upsert_post_data`` and appends a
timestamped row to ``post_metric_snapshots`` for history. On an X 429 it backs
off for the ``retry-after`` window and surfaces that via ``get_poll_status`` so
the frontend can warn users.

The app has no single app-wide authenticated client (tokens are per-user), so
``start_scheduler`` takes a *client provider*: a callable returning a context
manager that yields an authenticated ``xdk.Client`` (or ``None`` when no usable
token is available). The provider is responsible for building the client and
persisting any refreshed token on exit.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None  # created fresh on each start_scheduler()
_rate_limit_state: dict = {"status": "ok", "rate_limited_until": None, "last_poll_at": None}
_client_provider = None  # callable -> context manager yielding Client | None


def get_poll_status() -> dict:
    """Snapshot of poller health for GET /status (returns a copy)."""
    return _rate_limit_state.copy()


async def _poll_metrics(client) -> None:
    """Re-fetch and re-score every post in the active contest using ``client``."""
    from database import (
        get_active_contest,
        get_active_contest_post_ids,
        insert_metric_snapshot,
        upsert_post_data,
    )
    from engagement import analyze_post_engagement
    from x_client import DEFAULT_TWEET_FIELDS
    import requests

    contest = get_active_contest()
    if not contest:
        return

    weights = {k: v for k, v in contest.items() if k.startswith("weight_")}
    post_ids = get_active_contest_post_ids()
    logger.info("Polling %d posts for contest %s", len(post_ids), contest["contest_id"])

    for post_id in post_ids:
        try:
            # Step 1: fetch the full post object (public metrics).
            resp = client.posts.get_by_id(
                id=post_id,
                tweet_fields=DEFAULT_TWEET_FIELDS,
                expansions=["author_id"],
                user_fields=["id", "username", "public_metrics"],
            )
            result = resp.model_dump() if hasattr(resp, "model_dump") else resp
            tweet = result.get("data") if isinstance(result, dict) else None
            if not tweet or not tweet.get("id"):
                logger.warning("Post %s not found on X (deleted?), skipping.", post_id)
                continue

            # Step 2: optionally fetch the low-follower engagement count (auth required).
            low_count = analyze_post_engagement(client, post_id)

            # Step 3: store latest metrics + rescore, then append a history snapshot.
            upsert_post_data(tweet, low_count, weights=weights)
            insert_metric_snapshot(tweet, datetime.now(timezone.utc).isoformat())

            _rate_limit_state["status"] = "ok"
            _rate_limit_state["rate_limited_until"] = None
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 429:
                retry_after = int(e.response.headers.get("retry-after", 900))
                until = (datetime.now(timezone.utc) + timedelta(seconds=retry_after)).isoformat()
                _rate_limit_state["status"] = "rate_limited"
                _rate_limit_state["rate_limited_until"] = until
                logger.warning("X API rate limit hit. Pausing until %s.", until)
                break
            logger.exception("HTTP error polling post %s", post_id)
        except Exception:
            logger.exception("Error polling post %s, skipping.", post_id)

    _rate_limit_state["last_poll_at"] = datetime.now(timezone.utc).isoformat()


async def _run_poll() -> None:
    """Scheduled job: resolve an authenticated client via the provider, then poll."""
    if _client_provider is None:
        return
    with _client_provider() as client:
        if client is None:
            logger.info("No authenticated X client available for polling; skipping this run.")
            return
        await _poll_metrics(client)


def start_scheduler(client_provider, interval_seconds: int) -> None:
    """Begin polling every ``interval_seconds``. ``client_provider`` is a callable
    returning a context manager that yields an authenticated ``Client`` or ``None``.

    A fresh ``AsyncIOScheduler`` is created on each call so it binds to the current
    running event loop (the app's lifespan loop) and never carries stale loop state.
    """
    global _client_provider, _scheduler
    _client_provider = client_provider
    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(_run_poll, "interval", seconds=interval_seconds, id="poll_metrics")
    _scheduler.start()


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown()
    _scheduler = None

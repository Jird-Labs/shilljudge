"""Tests for the public-metrics polling engine (DEV-26).

_poll_metrics is exercised directly with a mock xdk client (no event loop /
APScheduler needed beyond one start/stop test). Each test resets the module-level
rate-limit state so ordering can't leak status between tests.
"""
import asyncio
from contextlib import contextmanager

import pytest
import requests

from shilljudge_core import database
import scheduler
from shilljudge_core.database import create_contest, create_thread, upsert_post_data


# ── Mock xdk client ───────────────────────────────────────────────────────────

class _Resp:
    def __init__(self, data):
        self._data = data

    def model_dump(self):
        return {"data": self._data}


class _EmptyPage:
    data = []


class _MockPosts:
    def __init__(self, tweets, raise_429=False):
        self._tweets = tweets
        self._raise_429 = raise_429

    def get_by_id(self, id, **kwargs):
        if self._raise_429:
            r = requests.Response()
            r.status_code = 429
            r.headers["retry-after"] = "60"
            raise requests.HTTPError(response=r)
        return _Resp(self._tweets.get(id))  # data is None for a deleted/missing post

    def get_liking_users(self, id, **kwargs):
        yield _EmptyPage()

    def get_reposted_by(self, id, **kwargs):
        yield _EmptyPage()


class MockClient:
    def __init__(self, tweets, raise_429=False):
        self.posts = _MockPosts(tweets, raise_429)


def _tweet(post_id, likes):
    return {
        "id": post_id,
        "author_id": "user1",
        "text": f"tweet {post_id}",
        "created_at": "2024-01-01T00:00:00Z",
        "public_metrics": {
            "retweet_count": 1, "reply_count": 1, "like_count": likes,
            "quote_count": 1, "bookmark_count": 1, "impression_count": 1000,
        },
    }


def _seed_contest_with_posts():
    """Active contest with a 2-post thread (likes=100 at seed time)."""
    create_contest("Active", None, "2020-01-01", "2099-12-31")
    upsert_post_data(_tweet("111", 100))
    upsert_post_data(_tweet("222", 100))
    create_thread(["111", "222"])


@pytest.fixture(autouse=True)
def _reset_poll_state():
    scheduler._rate_limit_state.clear()
    scheduler._rate_limit_state.update(
        {"status": "ok", "rate_limited_until": None, "last_poll_at": None}
    )
    yield


# ── _poll_metrics ─────────────────────────────────────────────────────────────

def test_poll_metrics_refetches_posts_and_records_snapshots(test_db):
    _seed_contest_with_posts()
    # The live API now reports 999 likes — a poll must overwrite the stored value.
    client = MockClient({"111": _tweet("111", 999), "222": _tweet("222", 999)})

    asyncio.run(scheduler._poll_metrics(client))

    with database.get_connection() as conn:
        likes = conn.execute("SELECT likes FROM posts WHERE post_id = '111'").fetchone()["likes"]
        snaps = conn.execute(
            "SELECT post_id, likes FROM post_metric_snapshots ORDER BY post_id"
        ).fetchall()
    assert likes == 999  # posts table reflects latest poll
    assert [(r["post_id"], r["likes"]) for r in snaps] == [("111", 999), ("222", 999)]
    status = scheduler.get_poll_status()
    assert status["status"] == "ok"
    assert status["last_poll_at"] is not None


def test_poll_metrics_no_active_contest_is_noop(test_db):
    asyncio.run(scheduler._poll_metrics(MockClient({})))
    with database.get_connection() as conn:
        snaps = conn.execute("SELECT * FROM post_metric_snapshots").fetchall()
    assert snaps == []


def test_poll_metrics_skips_deleted_post(test_db):
    _seed_contest_with_posts()
    # Post 222 was deleted on X → get_by_id returns data=None for it.
    client = MockClient({"111": _tweet("111", 5)})

    asyncio.run(scheduler._poll_metrics(client))

    with database.get_connection() as conn:
        ids = {r["post_id"] for r in conn.execute("SELECT post_id FROM post_metric_snapshots").fetchall()}
    assert ids == {"111"}  # 111 recorded, 222 skipped, no crash
    assert scheduler.get_poll_status()["status"] == "ok"


def test_poll_metrics_rate_limited_sets_status_and_backs_off(test_db):
    _seed_contest_with_posts()
    client = MockClient({}, raise_429=True)

    asyncio.run(scheduler._poll_metrics(client))

    status = scheduler.get_poll_status()
    assert status["status"] == "rate_limited"
    assert status["rate_limited_until"] is not None
    with database.get_connection() as conn:
        snaps = conn.execute("SELECT * FROM post_metric_snapshots").fetchall()
    assert snaps == []  # broke out before any successful upsert


def test_get_poll_status_returns_a_copy(test_db):
    status = scheduler.get_poll_status()
    status["status"] = "mutated"
    assert scheduler.get_poll_status()["status"] == "ok"


# ── _run_poll (client-provider wiring) ────────────────────────────────────────

def test_run_poll_skips_when_provider_yields_no_client(test_db):
    _seed_contest_with_posts()

    @contextmanager
    def provider():
        yield None

    scheduler._client_provider = provider
    asyncio.run(scheduler._run_poll())

    with database.get_connection() as conn:
        snaps = conn.execute("SELECT * FROM post_metric_snapshots").fetchall()
    assert snaps == []


def test_run_poll_polls_when_provider_yields_client(test_db):
    _seed_contest_with_posts()
    client = MockClient({"111": _tweet("111", 7), "222": _tweet("222", 7)})

    @contextmanager
    def provider():
        yield client

    scheduler._client_provider = provider
    asyncio.run(scheduler._run_poll())

    with database.get_connection() as conn:
        count = conn.execute("SELECT COUNT(*) AS c FROM post_metric_snapshots").fetchone()["c"]
    assert count == 2


# ── start/stop (APScheduler glue) ─────────────────────────────────────────────

def test_start_scheduler_registers_job_then_stops(test_db):
    @contextmanager
    def provider():
        yield None

    async def _run():
        scheduler.start_scheduler(provider, 300)
        sched = scheduler._scheduler  # capture before stop_scheduler() drops the ref
        assert sched.running
        assert sched.get_jobs()  # a poll job was registered
        scheduler.stop_scheduler()
        # AsyncIOScheduler.shutdown() defers the stop via call_soon_threadsafe,
        # so yield one loop tick before checking it actually stopped.
        await asyncio.sleep(0)
        assert not sched.running
        assert scheduler._scheduler is None

    asyncio.run(_run())

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# Provide dummy OAuth credentials so pydantic-settings can initialise Settings
# without a real .env file.  Tests mock the X client so no real credentials are used.
os.environ.setdefault("X_CLIENT_ID", "test-dummy-client-id")
os.environ.setdefault("X_CLIENT_SECRET", "test-dummy-client-secret")

import pytest
from fastapi.testclient import TestClient

from shilljudge_core import database
from app import app, limiter
from auth import get_current_user, get_x_client_for_user

# Disable rate limiting globally in tests — the shared in-memory counter would
# accumulate across tests (same client IP, one per-minute window for the whole
# run) and trigger 429s before the suite finishes. slowapi gates on ``enabled``.
limiter.enabled = False

MOCK_TWEETS = {
    "111": {
        "id": "111",
        "author_id": "user1",
        "text": "First tweet in thread",
        "created_at": "2024-01-01T00:00:00.000Z",
        "public_metrics": {
            "retweet_count": 10,
            "reply_count": 5,
            "like_count": 100,
            "quote_count": 3,
            "bookmark_count": 20,
            "impression_count": 1000,
        },
    },
    "222": {
        "id": "222",
        "author_id": "user1",
        "text": "Second tweet in thread",
        "created_at": "2024-01-01T00:00:01.000Z",
        "public_metrics": {
            "retweet_count": 5,
            "reply_count": 2,
            "like_count": 50,
            "quote_count": 1,
            "bookmark_count": 10,
            "impression_count": 500,
        },
    },
    # 333 is user1's self-reply to 111 (referenced_tweets carries the parent id;
    # there is no native in_reply_to_post_id field in the X v2 API).
    "333": {
        "id": "333",
        "author_id": "user1",
        "text": "Self-reply to the first tweet",
        "created_at": "2024-01-01T00:00:02.000Z",
        "in_reply_to_user_id": "user1",
        "referenced_tweets": [{"type": "replied_to", "id": "111"}],
        "public_metrics": {
            "retweet_count": 1,
            "reply_count": 0,
            "like_count": 10,
            "quote_count": 0,
            "bookmark_count": 2,
            "impression_count": 100,
        },
    },
}

# Id used to simulate a deleted/missing tweet: the X API returns 200 with no
# `data` (rather than an HTTP error), which the preview must surface as a
# "deleted" marker instead of failing the whole batch.
DELETED_POST_ID = "404404"

MOCK_USER = {
    "x_id": "user1",
    "x_username": "testuser",
    "name": "Test User",
    "profile_image_url": None,
    "wallet_address": None,
    "stake_verified": 0,
    "stake_checked_at": None,
    "is_admin": 0,
}

MOCK_ADMIN_USER = {
    "x_id": "admin1",
    "x_username": "adminuser",
    "name": "Admin User",
    "profile_image_url": None,
    "wallet_address": None,
    "stake_verified": 0,
    "stake_checked_at": None,
    "is_admin": 1,
}


class _MockPostItem:
    def __init__(self, data):
        self._data = data

    def model_dump(self):
        return self._data


class _MockPostsResponse:
    def __init__(self, ids):
        self.data = [_MockPostItem(MOCK_TWEETS[i]) for i in ids if i in MOCK_TWEETS]
        self.errors = [{"id": i, "detail": "not found"} for i in ids if i not in MOCK_TWEETS]


class _MockSinglePostResponse:
    def __init__(self, tweet_data):
        self._data = tweet_data

    def model_dump(self):
        return {"data": self._data}


class _MockEmptyPage:
    def __init__(self):
        self.data = []


class MockXClient:
    class _Posts:
        def get_by_ids(self, ids, tweet_fields=None):
            return _MockPostsResponse(ids)

        def get_by_id(self, id, tweet_fields=None, **kwargs):
            # A deleted tweet comes back from X as 200 with no data (not an HTTP error).
            if id == DELETED_POST_ID:
                return _MockSinglePostResponse(None)
            tweet = MOCK_TWEETS.get(id)
            if not tweet:
                import requests as req
                r = req.Response()
                r.status_code = 404
                raise req.HTTPError(response=r)
            return _MockSinglePostResponse(tweet)

        def get_liking_users(self, id, **kwargs):
            yield _MockEmptyPage()

        def get_reposted_by(self, id, **kwargs):
            yield _MockEmptyPage()

    class _Users:
        def get_by_ids(self, ids, user_fields=None):
            class R:
                data = []
            return R()

        def get_me(self, user_fields=None):
            class R:
                class data:
                    id = "user1"
                    def model_dump(self):
                        return {"id": "user1", "username": "testuser", "name": "Test User"}
            return R()

    posts = _Posts()
    users = _Users()


@pytest.fixture()
def test_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test.db"
    monkeypatch.setattr(database, "DB_PATH", db_file)
    database.init_db()
    # Pre-insert user1 so foreign key constraints pass in DB-level tests
    with database.get_connection() as conn:
        conn.execute("INSERT INTO users (x_id, x_username) VALUES ('user1', 'testuser')")
    return db_file


@pytest.fixture()
def client(test_db):
    """Anonymous client — no auth overrides."""
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture()
def user_client(test_db):
    """Authenticated client acting as testuser (non-admin)."""
    mock = MockXClient()
    app.dependency_overrides[get_current_user] = lambda: MOCK_USER
    app.dependency_overrides[get_x_client_for_user] = lambda: mock
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def admin_client(test_db):
    """Authenticated client acting as nrsetoken (admin)."""
    mock = MockXClient()
    app.dependency_overrides[get_current_user] = lambda: MOCK_ADMIN_USER
    app.dependency_overrides[get_x_client_for_user] = lambda: mock
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def submit_client(test_db):
    """Anonymous client with the app-level X client overridden to MockXClient
    (for the public /submit + /submit/preview endpoints)."""
    from app import get_app_x_client
    mock = MockXClient()
    app.dependency_overrides[get_app_x_client] = lambda: mock
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
    app.dependency_overrides.clear()

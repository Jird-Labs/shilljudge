import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
import database
from database import create_contest

# Minimal standalone mock — not imported from conftest to avoid module-not-found in dynamic tests
class _StandaloneMockXClient:
    class _Posts:
        _TWEETS = {
            "111": {"id": "111", "author_id": "user1", "text": "t1", "created_at": "2024-01-01T00:00:00Z",
                    "public_metrics": {"retweet_count": 0, "reply_count": 0, "like_count": 5,
                                       "quote_count": 0, "bookmark_count": 0, "impression_count": 100}},
            "222": {"id": "222", "author_id": "user1", "text": "t2", "created_at": "2024-01-01T00:00:01Z",
                    "public_metrics": {"retweet_count": 0, "reply_count": 0, "like_count": 2,
                                       "quote_count": 0, "bookmark_count": 0, "impression_count": 50}},
        }

        class _PostItem:
            def __init__(self, d): self._d = d
            def model_dump(self): return self._d

        def get_by_ids(self, ids, **kw):
            class R:
                pass
            r = R()
            r.data = [_StandaloneMockXClient._Posts._PostItem(_StandaloneMockXClient._Posts._TWEETS[i])
                      for i in ids if i in _StandaloneMockXClient._Posts._TWEETS]
            r.errors = [{"id": i} for i in ids if i not in _StandaloneMockXClient._Posts._TWEETS]
            return r

        def get_by_id(self, id, **kw):
            t = self._TWEETS.get(id)
            if not t:
                import requests as req; r = req.Response(); r.status_code = 404
                raise req.HTTPError(response=r)
            class R:
                def model_dump(self): return {"data": t}
            return R()

        def get_liking_users(self, id, **kw):
            class P: data = []
            yield P()

        def get_reposted_by(self, id, **kw):
            class P: data = []
            yield P()

    class _Users:
        def get_by_ids(self, ids, **kw):
            class R: data = []
            return R()

    posts = _Posts()
    users = _Users()


# ── Auth matrix ──────────────────────────────────────────────────────────────

def test_leaderboard_is_public(client):
    resp = client.get("/leaderboard")
    assert resp.status_code == 200


def test_preview_requires_auth(client):
    resp = client.post("/submissions/preview", json={"url": "https://x.com/u/status/111"})
    assert resp.status_code == 401


def test_confirm_requires_auth(client):
    resp = client.post("/submissions/confirm", json={"post_ids": ["111"]})
    assert resp.status_code == 401


def test_manage_contests_requires_admin(client):
    resp = client.get("/manage/contests")
    assert resp.status_code == 401


def test_manage_contests_forbidden_for_non_admin(user_client):
    resp = user_client.get("/manage/contests")
    assert resp.status_code == 403


def test_manage_contests_accessible_to_admin(admin_client):
    resp = admin_client.get("/manage/contests")
    assert resp.status_code == 200


# ── Preview ───────────────────────────────────────────────────────────────────

def test_preview_returns_post_without_persisting(user_client, test_db):
    resp = user_client.post("/submissions/preview", json={"url": "https://x.com/u/status/111"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["post"]["id"] == "111"


# ── Metric weights (DEV-24) ───────────────────────────────────────────────────

from database import get_active_contest, get_connection, upsert_post_data

_WEIGHT_KEYS = (
    "weight_likes", "weight_retweets", "weight_replies",
    "weight_quotes", "weight_bookmarks", "weight_impressions",
)

_TWEET = {
    "id": "900", "author_id": "user1", "text": "weighted", "created_at": "2024-01-01T00:00:00Z",
    "public_metrics": {"retweet_count": 10, "reply_count": 5, "like_count": 100,
                       "quote_count": 3, "bookmark_count": 20, "impression_count": 1000},
}


def test_upsert_default_weights_match_base(test_db):
    upsert_post_data(dict(_TWEET, id="900"))
    upsert_post_data(dict(_TWEET, id="901"), weights={k: 1.0 for k in _WEIGHT_KEYS})
    with get_connection() as conn:
        base = conn.execute("SELECT score FROM thread_scores WHERE post_id = '900'").fetchone()["score"]
        weighted = conn.execute("SELECT score FROM thread_scores WHERE post_id = '901'").fetchone()["score"]
    assert weighted == pytest.approx(base)


def test_upsert_custom_weights(test_db):
    upsert_post_data(dict(_TWEET, id="902"), weights={"weight_likes": 2.0})
    with get_connection() as conn:
        row = conn.execute("SELECT ratio, score FROM thread_scores WHERE post_id = '902'").fetchone()
    # interactions = 10+5+200+3+20 = 238; ratio = 0.238; score = 238 + 300*0.238
    assert row["ratio"] == pytest.approx(0.238)
    assert row["score"] == pytest.approx(309.4)


def test_create_contest_defaults_weights_to_one(test_db):
    c = create_contest("W", None, "2025-01-01", "2025-01-31")
    for key in _WEIGHT_KEYS:
        assert c[key] == pytest.approx(1.0), key


def test_create_contest_rejects_negative_weight(test_db):
    with pytest.raises(ValueError, match=r">=\s*0|negative"):
        create_contest("Bad", None, "2025-01-01", "2025-01-31", weights={"weight_likes": -1.0})


def test_get_active_contest_returns_weights(test_db):
    create_contest("W", None, "2025-01-01", "2025-01-31", weights={"weight_likes": 2.0})
    active = get_active_contest()
    assert active["weight_likes"] == pytest.approx(2.0)
    assert active["weight_retweets"] == pytest.approx(1.0)


def test_create_contest_negative_weight_returns_422(admin_client):
    resp = admin_client.post("/manage/contests", json={
        "title": "Bad", "start_date": "2025-01-01", "end_date": "2025-01-31",
        "weight_likes": -1.0,
    })
    assert resp.status_code == 422


def test_create_contest_with_weights_persists(admin_client):
    resp = admin_client.post("/manage/contests", json={
        "title": "Weighted", "start_date": "2025-01-01", "end_date": "2025-01-31",
        "weight_likes": 2.0, "weight_impressions": 0.5,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["weight_likes"] == pytest.approx(2.0)
    assert body["weight_impressions"] == pytest.approx(0.5)
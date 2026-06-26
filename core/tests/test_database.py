"""Core database + scoring + leaderboard + contest tests.

These are the canonical tests for the public scoring formula and foundation queries.
All numbers must remain byte-for-byte identical to the original ShillJudge implementation.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

import shilljudge_core.database as database
from shilljudge_core.database import (
    clear_thread_score_override,
    create_contest,
    create_thread,
    find_active_contest_thread_for_post,
    get_active_contest_post_ids,
    get_connection,
    get_contest_thread_ids,
    get_leaderboard,
    get_metadata,
    get_thread,
    get_thread_post_ids,
    get_thread_score,
    insert_metric_snapshot,
    recompute_thread_total_score,
    score_post,
    set_thread_score_override,
    upsert_post_data,
)


TWEET_1 = {
    "id": "111",
    "author_id": "user1",
    "text": "First tweet",
    "created_at": "2024-01-01T00:00:00Z",
    "public_metrics": {
        "retweet_count": 10,
        "reply_count": 5,
        "like_count": 100,
        "quote_count": 3,
        "bookmark_count": 20,
        "impression_count": 1000,
    },
}

TWEET_2 = {
    "id": "222",
    "author_id": "user1",
    "text": "Second tweet",
    "created_at": "2024-01-01T00:00:01Z",
    "public_metrics": {
        "retweet_count": 5,
        "reply_count": 2,
        "like_count": 50,
        "quote_count": 1,
        "bookmark_count": 10,
        "impression_count": 500,
    },
}


def test_upsert_post_stores_metrics(test_db):
    upsert_post_data(TWEET_1)
    with database.get_connection() as conn:
        post = conn.execute("SELECT * FROM posts WHERE post_id = '111'").fetchone()
    assert post is not None
    assert post["likes"] == 100
    assert post["impressions"] == 1000
    assert post["text"] == "First tweet"


def test_upsert_post_creates_score_base_formula(test_db):
    """No low_follower_engagements → base formula (same as before)."""
    upsert_post_data(TWEET_1)
    with database.get_connection() as conn:
        score_row = conn.execute("SELECT * FROM thread_scores WHERE post_id = '111'").fetchone()
    assert score_row is not None
    # interactions = 138, impressions = 1000, low = 0
    # valid = 138, ratio = (138-0)/1000 = 0.138, score = 138 + 300*0.138
    assert score_row["ratio"] == pytest.approx(138 / 1000)
    assert score_row["score"] == pytest.approx(138 + 300.0 * (138 / 1000))


def test_upsert_post_scoring_with_low_follower_engagements(test_db):
    """Confirmed formula: 100 interactions, 20 low, 1000 impressions → score 98."""
    tweet = {
        "id": "333",
        "author_id": "user1",
        "text": "Test",
        "created_at": "2024-01-01T00:00:00Z",
        "public_metrics": {
            "retweet_count": 0, "reply_count": 0, "like_count": 100,
            "quote_count": 0, "bookmark_count": 0, "impression_count": 1000,
        },
    }
    upsert_post_data(tweet, low_follower_engagements=20)
    with database.get_connection() as conn:
        score_row = conn.execute("SELECT * FROM thread_scores WHERE post_id = '333'").fetchone()
    # valid = 100 - 20 = 80; ratio = (80 - 20) / 1000 = 0.06; score = 80 + 300*0.06 = 98
    assert score_row["ratio"] == pytest.approx(0.06)
    assert score_row["score"] == pytest.approx(98.0)


def test_upsert_post_score_floored_at_zero(test_db):
    """Heavy low-follower engagement: floor keeps score >= 0."""
    tweet = {
        "id": "444",
        "author_id": "user1",
        "text": "Test",
        "created_at": "2024-01-01T00:00:00Z",
        "public_metrics": {
            "retweet_count": 0, "reply_count": 0, "like_count": 10,
            "quote_count": 0, "bookmark_count": 0, "impression_count": 1000,
        },
    }
    upsert_post_data(tweet, low_follower_engagements=10)
    with database.get_connection() as conn:
        score_row = conn.execute("SELECT * FROM thread_scores WHERE post_id = '444'").fetchone()
    assert score_row["ratio"] == pytest.approx(0.0)
    assert score_row["score"] == pytest.approx(0.0)


def test_create_thread_links_posts(test_db):
    upsert_post_data(TWEET_1)
    upsert_post_data(TWEET_2)
    thread = create_thread(["111", "222"])
    assert thread["post_count"] == 2
    assert thread["total_score"] > 0
    with database.get_connection() as conn:
        links = conn.execute(
            "SELECT post_id FROM thread_posts WHERE thread_id = ?", (thread["thread_id"],)
        ).fetchall()
    assert {r["post_id"] for r in links} == {"111", "222"}


def test_create_thread_total_score_is_sum(test_db):
    upsert_post_data(TWEET_1)
    upsert_post_data(TWEET_2)

    with database.get_connection() as conn:
        s1 = conn.execute("SELECT score FROM thread_scores WHERE post_id = '111'").fetchone()["score"]
        s2 = conn.execute("SELECT score FROM thread_scores WHERE post_id = '222'").fetchone()["score"]

    thread = create_thread(["111", "222"])
    assert thread["total_score"] == pytest.approx(s1 + s2)


def test_create_thread_requires_nonempty(test_db):
    with pytest.raises(ValueError, match="empty"):
        create_thread([])


def test_create_thread_missing_post_raises(test_db):
    with pytest.raises(ValueError):
        create_thread(["nonexistent_id"])


def test_leaderboard_includes_threads(test_db):
    upsert_post_data(TWEET_1)
    upsert_post_data(TWEET_2)
    create_thread(["111", "222"])
    data = get_leaderboard()
    assert "threads" in data
    assert len(data["threads"]) == 1
    t = data["threads"][0]
    assert t["post_count"] == 2
    assert t["total_score"] > 0


def test_leaderboard_threads_top_text(test_db):
    upsert_post_data(TWEET_1)
    upsert_post_data(TWEET_2)
    create_thread(["111", "222"])
    data = get_leaderboard()
    assert data["threads"][0]["top_text"] == "First tweet"


def test_set_user_admin(test_db):
    upsert_post_data(TWEET_1)
    with database.get_connection() as conn:
        assert conn.execute("SELECT is_admin FROM users WHERE x_id = 'user1'").fetchone()["is_admin"] == 0
    database.set_user_admin("user1", True)
    with database.get_connection() as conn:
        assert conn.execute("SELECT is_admin FROM users WHERE x_id = 'user1'").fetchone()["is_admin"] == 1
    database.set_user_admin("user1", False)
    with database.get_connection() as conn:
        assert conn.execute("SELECT is_admin FROM users WHERE x_id = 'user1'").fetchone()["is_admin"] == 0


def test_participation_status_defaults_to_active(test_db):
    upsert_post_data(TWEET_1)
    with database.get_connection() as conn:
        row = conn.execute("SELECT participation_status FROM users WHERE x_id = 'user1'").fetchone()
    assert row["participation_status"] == "active"


def test_set_user_participation(test_db):
    upsert_post_data(TWEET_1)
    database.set_user_participation("user1", "suspended")
    with database.get_connection() as conn:
        assert conn.execute(
            "SELECT participation_status FROM users WHERE x_id = 'user1'"
        ).fetchone()["participation_status"] == "suspended"
    database.set_user_participation("user1", "active")
    with database.get_connection() as conn:
        assert conn.execute(
            "SELECT participation_status FROM users WHERE x_id = 'user1'"
        ).fetchone()["participation_status"] == "active"


def test_get_all_users_includes_participation_and_created_at(test_db):
    users = database.get_all_users()
    assert users, "expected the pre-seeded user1"
    row = next(u for u in users if u["x_id"] == "user1")
    assert "participation_status" in row
    assert "created_at" in row
    assert row["participation_status"] == "active"


def test_get_all_users_search_filters_by_username(test_db):
    with database.get_connection() as conn:
        conn.execute("INSERT INTO users (x_id, x_username) VALUES ('user2', 'alice')")
        conn.execute("INSERT INTO users (x_id, x_username) VALUES ('user3', 'alicia')")
        conn.execute("INSERT INTO users (x_id, x_username) VALUES ('user4', 'bob')")
    matches = {u["x_username"] for u in database.get_all_users(q="ali")}
    assert matches == {"alice", "alicia"}
    assert {u["x_username"] for u in database.get_all_users(q="bob")} == {"bob"}


def test_delete_user_removes_threads(test_db):
    upsert_post_data(TWEET_1)
    upsert_post_data(TWEET_2)
    create_thread(["111", "222"])
    database.delete_user_data("user1")
    with database.get_connection() as conn:
        threads = conn.execute("SELECT * FROM threads").fetchall()
        thread_posts = conn.execute("SELECT * FROM thread_posts").fetchall()
    assert threads == []
    assert thread_posts == []


# ── Contest tests ─────────────────────────────────────────────────────────────

def test_create_contest_stores_prize_and_thread_length(test_db):
    c = database.create_contest("Shill Bowl", None, "2025-01-01", "2025-01-31", prize="$500", thread_length=3)
    assert c["prize"] == "$500"
    assert c["thread_length"] == 3
    assert c["status"] == "active"


def test_create_contest_defaults(test_db):
    c = database.create_contest("Default Contest", None, "2025-01-01", "2025-01-31")
    assert c["thread_length"] == 1
    assert c["prize"] is None
    assert c["status"] == "active"


def test_single_active_enforcement_create(test_db):
    database.create_contest("First", None, "2025-01-01", "2025-01-31")
    with pytest.raises(ValueError, match="active contest already exists"):
        database.create_contest("Second", None, "2025-02-01", "2025-02-28")


def test_create_second_non_active_contest_allowed(test_db):
    database.create_contest("First", None, "2025-01-01", "2025-01-31")
    c = database.create_contest("Ended", None, "2024-01-01", "2024-01-31", status="ended")
    assert c["status"] == "ended"


def test_single_active_enforcement_update(test_db):
    database.create_contest("Active", None, "2025-01-01", "2025-01-31")
    c2 = database.create_contest("Archived", None, "2024-01-01", "2024-01-31", status="archived")
    with pytest.raises(ValueError, match="active contest already exists"):
        database.update_contest(c2["contest_id"], {"status": "active"})


def test_update_active_to_active_same_contest_allowed(test_db):
    c = database.create_contest("Active", None, "2025-01-01", "2025-01-31")
    result = database.update_contest(c["contest_id"], {"status": "active", "title": "Active Renamed"})
    assert result["title"] == "Active Renamed"
    assert result["status"] == "active"


def test_archive_retains_data(test_db):
    upsert_post_data(TWEET_1)
    c = database.create_contest("Shill Bowl", None, "2025-01-01", "2025-01-31")
    create_thread(["111"])
    archived = database.delete_contest(c["contest_id"])
    assert archived is True
    with database.get_connection() as conn:
        row = conn.execute(
            "SELECT status FROM thread_contests WHERE contest_id = ?", (c["contest_id"],)
        ).fetchone()
        threads = conn.execute("SELECT * FROM threads").fetchall()
        posts = conn.execute("SELECT * FROM posts").fetchall()
    assert row["status"] == "archived"
    assert len(threads) == 1
    assert len(posts) == 1


def test_archive_nonexistent_returns_false(test_db):
    assert database.delete_contest(999) is False


def test_get_all_contests_includes_archived(test_db):
    database.create_contest("Active", None, "2025-01-01", "2025-01-31")
    c2 = database.create_contest("Old", None, "2024-01-01", "2024-01-31", status="archived")
    contests = database.get_all_contests()
    statuses = {c["contest_id"]: c["status"] for c in contests}
    assert statuses[c2["contest_id"]] == "archived"


def test_get_active_contest_uses_status(test_db):
    database.create_contest("Active", None, "2025-01-01", "2025-01-31")
    active = database.get_active_contest()
    assert active is not None
    assert active["contest_id"] is not None
    database.delete_contest(active["contest_id"])
    assert database.get_active_contest() is None


# ── Metric weight tests (DEV-24) ──────────────────────────────────────────────

WEIGHT_KEYS = (
    "weight_likes", "weight_retweets", "weight_replies",
    "weight_quotes", "weight_bookmarks", "weight_impressions",
)


def test_create_contest_defaults_all_weights_to_one(test_db):
    c = database.create_contest("Weighted", None, "2025-01-01", "2025-01-31")
    for key in WEIGHT_KEYS:
        assert c[key] == pytest.approx(1.0), key


def test_create_contest_stores_custom_weights(test_db):
    c = database.create_contest(
        "Weighted", None, "2025-01-01", "2025-01-31",
        weights={"weight_likes": 2.0, "weight_impressions": 0.5},
    )
    assert c["weight_likes"] == pytest.approx(2.0)
    assert c["weight_impressions"] == pytest.approx(0.5)
    # unspecified weights still default to 1.0
    assert c["weight_retweets"] == pytest.approx(1.0)


def test_create_contest_rejects_negative_weight(test_db):
    with pytest.raises(ValueError, match=r">=\s*0|negative"):
        database.create_contest(
            "Bad", None, "2025-01-01", "2025-01-31",
            weights={"weight_likes": -1.0},
        )


def test_update_contest_changes_weights(test_db):
    c = database.create_contest("Weighted", None, "2025-01-01", "2025-01-31")
    updated = database.update_contest(c["contest_id"], {"weight_likes": 3.0})
    assert updated["weight_likes"] == pytest.approx(3.0)


def test_update_contest_rejects_negative_weight(test_db):
    c = database.create_contest("Weighted", None, "2025-01-01", "2025-01-31")
    with pytest.raises(ValueError, match=r">=\s*0|negative"):
        database.update_contest(c["contest_id"], {"weight_bookmarks": -0.5})


def test_get_active_contest_returns_weights(test_db):
    database.create_contest("Weighted", None, "2025-01-01", "2025-01-31",
                            weights={"weight_likes": 2.0})
    active = database.get_active_contest()
    assert active["weight_likes"] == pytest.approx(2.0)
    assert active["weight_retweets"] == pytest.approx(1.0)


def test_default_weights_match_base_formula(test_db):
    """Passing all-1.0 weights must produce byte-for-byte the unweighted score."""
    upsert_post_data(dict(TWEET_1, id="w1"))  # no weights → baseline
    upsert_post_data(dict(TWEET_1, id="w2"), weights={k: 1.0 for k in WEIGHT_KEYS})
    with database.get_connection() as conn:
        base = conn.execute("SELECT ratio, score FROM thread_scores WHERE post_id = 'w1'").fetchone()
        weighted = conn.execute("SELECT ratio, score FROM thread_scores WHERE post_id = 'w2'").fetchone()
    assert weighted["ratio"] == pytest.approx(base["ratio"])
    assert weighted["score"] == pytest.approx(base["score"])


# ── Polling engine helpers (DEV-26) ───────────────────────────────────────────

def test_get_active_contest_post_ids_returns_posts_in_active_contest(test_db):
    create_contest("Active", None, "2025-01-01", "2025-12-31")
    upsert_post_data(TWEET_1)
    upsert_post_data(TWEET_2)
    create_thread(["111", "222"])
    assert set(get_active_contest_post_ids()) == {"111", "222"}


def test_get_active_contest_post_ids_empty_when_no_active_contest(test_db):
    upsert_post_data(TWEET_1)
    create_thread(["111"])  # thread has no contest_id (no active contest)
    assert get_active_contest_post_ids() == []


def test_get_active_contest_post_ids_excludes_other_contests(test_db):
    """Only posts belonging to the currently-active contest are returned."""
    old = create_contest("Old", None, "2024-01-01", "2024-12-31")
    upsert_post_data(TWEET_1)
    create_thread(["111"])  # linked to the (then active) old contest
    database.delete_contest(old["contest_id"])  # archive it
    create_contest("New", None, "2025-01-01", "2025-12-31")
    upsert_post_data(TWEET_2)
    create_thread(["222"])  # linked to the new active contest
    assert get_active_contest_post_ids() == ["222"]


def test_insert_metric_snapshot_records_timestamped_row(test_db):
    upsert_post_data(TWEET_1)
    insert_metric_snapshot(TWEET_1, "2025-06-25T12:00:00+00:00")
    with database.get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM post_metric_snapshots WHERE post_id = '111'"
        ).fetchone()
    assert row is not None
    assert row["polled_at"] == "2025-06-25T12:00:00+00:00"
    assert row["likes"] == 100
    assert row["retweets"] == 10
    assert row["impressions"] == 1000


def test_insert_metric_snapshot_appends_history(test_db):
    """Each poll appends a new row; history is retained."""
    upsert_post_data(TWEET_1)
    insert_metric_snapshot(TWEET_1, "2025-06-25T12:00:00+00:00")
    insert_metric_snapshot(dict(TWEET_1, public_metrics={**TWEET_1["public_metrics"], "like_count": 150}),
                           "2025-06-25T13:00:00+00:00")
    with database.get_connection() as conn:
        rows = conn.execute(
            "SELECT likes FROM post_metric_snapshots WHERE post_id = '111' ORDER BY polled_at"
        ).fetchall()
    assert [r["likes"] for r in rows] == [100, 150]


def test_custom_weights_produce_weighted_score(test_db):
    """TWEET_1: rt10 rp5 like100 qt3 bm20 imp1000; weight likes x2 → +100 interactions."""
    upsert_post_data(dict(TWEET_1, id="w3"), weights={"weight_likes": 2.0})
    with database.get_connection() as conn:
        row = conn.execute("SELECT ratio, score FROM thread_scores WHERE post_id = 'w3'").fetchone()
    # weighted interactions = 10 + 5 + 100*2 + 3 + 20 = 238; impressions = 1000
    # ratio = 238/1000 = 0.238; score = 238 + 300*0.238 = 309.4
    assert row["ratio"] == pytest.approx(0.238)
    assert row["score"] == pytest.approx(309.4)


def test_weighted_impressions_applied(test_db):
    """Halving impression weight doubles the ratio contribution."""
    upsert_post_data(dict(TWEET_1, id="w4"), weights={"weight_impressions": 0.5})
    with database.get_connection() as conn:
        row = conn.execute("SELECT ratio, score FROM thread_scores WHERE post_id = 'w4'").fetchone()
    # interactions = 138; weighted impressions = 500; ratio = 138/500 = 0.276
    assert row["ratio"] == pytest.approx(0.276)
    assert row["score"] == pytest.approx(138 + 300.0 * 0.276)


def test_score_post_matches_base_formula():
    # interactions = 10+5+100+3+20 = 138; impressions = 1000; low = 0
    # ratio = 138/1000 = 0.138; score = 138 + 300*0.138 = 179.4
    score, ratio = score_post(TWEET_1["public_metrics"], None, None)
    assert ratio == pytest.approx(0.138)
    assert score == pytest.approx(179.4)


def test_score_post_applies_weights():
    # like weight doubled: interactions = 10+5+200+3+20 = 238; ratio = 0.238
    score, ratio = score_post(TWEET_1["public_metrics"], None, {"weight_likes": 2.0})
    assert ratio == pytest.approx(0.238)
    assert score == pytest.approx(309.4)


def test_score_post_subtracts_low_follower_count():
    # low = 8: valid = 130; ratio = max((130-8)/1000, 0) = 0.122; score = 130 + 36.6 = 166.6
    score, ratio = score_post(TWEET_1["public_metrics"], 8, None)
    assert ratio == pytest.approx(0.122)
    assert score == pytest.approx(166.6)


def test_score_post_zero_impressions_gives_zero_ratio():
    score, ratio = score_post({"like_count": 5, "impression_count": 0}, None, None)
    assert ratio == 0.0
    assert score == 5.0


def test_calculate_score_hook_applied(test_db):
    """upsert_post_data routes the base score through the CALCULATE_SCORE hook."""
    from shilljudge_core.hooks import registry, CALCULATE_SCORE

    def double(_tweet, score):
        return score * 2

    registry.register(CALCULATE_SCORE, double)
    try:
        upsert_post_data(dict(TWEET_1, id="w5"))
        with database.get_connection() as conn:
            row = conn.execute("SELECT score FROM thread_scores WHERE post_id = 'w5'").fetchone()
        base = 138 + 300.0 * (138 / 1000)
        assert row["score"] == pytest.approx(base * 2)
    finally:
        registry.deregister(CALCULATE_SCORE, double)


# ── Rescore + admin override (DEV-27) ─────────────────────────────────────────

def _make_contest_thread():
    """Helper: active contest + a 2-post thread. Returns (contest_id, thread_id)."""
    c = create_contest("Rescore", None, "2025-01-01", "2025-12-31")
    upsert_post_data(TWEET_1)
    upsert_post_data(TWEET_2)
    thread = create_thread(["111", "222"])
    return c["contest_id"], thread["thread_id"]


def test_get_thread_returns_row_with_contest(test_db):
    cid, tid = _make_contest_thread()
    thread = get_thread(tid)
    assert thread is not None
    assert thread["thread_id"] == tid
    assert thread["contest_id"] == cid
    assert thread["post_count"] == 2


def test_get_thread_missing_returns_none(test_db):
    assert get_thread(999) is None


def test_get_thread_post_ids(test_db):
    _cid, tid = _make_contest_thread()
    assert set(get_thread_post_ids(tid)) == {"111", "222"}


def test_get_contest_thread_ids(test_db):
    cid, tid = _make_contest_thread()
    assert get_contest_thread_ids(cid) == [tid]


def test_find_duplicate_returns_thread_id(test_db):
    create_contest("C", None, "2020-01-01", "2099-12-31")
    upsert_post_data(TWEET_1)
    thread = create_thread(["111"])
    assert find_active_contest_thread_for_post("111") == thread["thread_id"]


def test_find_duplicate_none_for_unknown_post(test_db):
    create_contest("C", None, "2020-01-01", "2099-12-31")
    upsert_post_data(TWEET_1)
    create_thread(["111"])
    assert find_active_contest_thread_for_post("999") is None


def test_find_duplicate_none_without_active_contest(test_db):
    # No contest created → thread.contest_id is NULL → not a duplicate within "active".
    upsert_post_data(TWEET_1)
    create_thread(["111"])
    assert find_active_contest_thread_for_post("111") is None


def test_recompute_thread_total_score_reflects_new_metrics(test_db):
    _cid, tid = _make_contest_thread()
    original = get_thread(tid)["total_score"]
    # Re-score post 111 with doubled likes (simulating fresh metrics from X).
    hotter = dict(TWEET_1, public_metrics={**TWEET_1["public_metrics"], "like_count": 200})
    upsert_post_data(hotter)
    new_total = recompute_thread_total_score(tid)
    assert new_total > original
    assert get_thread(tid)["total_score"] == pytest.approx(new_total)


def test_set_override_stores_note_and_admin(test_db):
    _cid, tid = _make_contest_thread()
    set_thread_score_override(tid, 9999.0, "manual boost", "admin1")
    with get_connection() as conn:
        meta = get_metadata(conn, "threads", "thread_id", tid, "admin")
    assert meta["override_score"] == pytest.approx(9999.0)
    assert meta["note"] == "manual boost"
    assert meta["by"] == "admin1"


def test_get_thread_score_prefers_override(test_db):
    _cid, tid = _make_contest_thread()
    computed = get_thread(tid)["total_score"]
    base = get_thread_score(tid)
    assert base["is_overridden"] is False
    assert base["score"] == pytest.approx(computed)

    set_thread_score_override(tid, 9999.0, "boost", "admin1")
    overridden = get_thread_score(tid)
    assert overridden["is_overridden"] is True
    assert overridden["score"] == pytest.approx(9999.0)
    assert overridden["total_score"] == pytest.approx(computed)


def test_clear_override_reverts_to_computed(test_db):
    _cid, tid = _make_contest_thread()
    computed = get_thread(tid)["total_score"]
    set_thread_score_override(tid, 9999.0, "boost", "admin1")
    clear_thread_score_override(tid)
    reverted = get_thread_score(tid)
    assert reverted["is_overridden"] is False
    assert reverted["score"] == pytest.approx(computed)


def test_override_score_of_zero_is_honored(test_db):
    """A 0.0 override is a real override, not 'absent' (falsy-value guard)."""
    _cid, tid = _make_contest_thread()
    set_thread_score_override(tid, 0.0, "disqualified", "admin1")
    result = get_thread_score(tid)
    assert result["is_overridden"] is True
    assert result["score"] == pytest.approx(0.0)


def test_leaderboard_thread_prefers_override(test_db):
    _cid, tid = _make_contest_thread()
    computed = get_thread(tid)["total_score"]
    set_thread_score_override(tid, 9999.0, "boost", "admin1")
    data = get_leaderboard()
    row = next(t for t in data["threads"] if t["thread_id"] == tid)
    assert row["is_overridden"] is True
    assert row["score"] == pytest.approx(9999.0)
    assert row["total_score"] == pytest.approx(computed)


def test_leaderboard_thread_computed_when_no_override(test_db):
    _cid, tid = _make_contest_thread()
    computed = get_thread(tid)["total_score"]
    data = get_leaderboard()
    row = next(t for t in data["threads"] if t["thread_id"] == tid)
    assert row["is_overridden"] is False
    assert row["score"] == pytest.approx(computed)


def test_leaderboard_reorders_by_effective_score(test_db):
    """An override that vaults a low thread above a high one reorders the rail."""
    create_contest("Reorder", None, "2025-01-01", "2025-12-31")
    upsert_post_data(TWEET_1)   # higher base score
    upsert_post_data(TWEET_2)   # lower base score
    high = create_thread(["111"])["thread_id"]
    low = create_thread(["222"])["thread_id"]
    # Override the low thread far above the high one.
    set_thread_score_override(low, 1_000_000.0, "boost", "admin1")
    data = get_leaderboard()
    ordered = [t["thread_id"] for t in data["threads"]]
    assert ordered.index(low) < ordered.index(high)


# ── Leaderboard pagination + sorting (DEV-28) ─────────────────────────────────

def _seed_contest_with_threads(scores: list[int]) -> list[int]:
    """Active contest + one single-post thread per like-count in ``scores``.
    Returns the thread_ids in creation order."""
    create_contest("Sortable", None, "2025-01-01", "2025-12-31")
    thread_ids = []
    for i, likes in enumerate(scores):
        pid = f"p{i}"
        upsert_post_data(dict(
            TWEET_1, id=pid,
            public_metrics={**TWEET_1["public_metrics"], "like_count": likes},
        ))
        thread_ids.append(create_thread([pid])["thread_id"])
    return thread_ids


def test_leaderboard_returns_pagination_metadata(test_db):
    _seed_contest_with_threads([100])
    data = get_leaderboard()
    assert data["total_count"] == 1
    assert data["sort_by"] == "score"
    assert data["sort_dir"] == "desc"
    assert data["limit"] == 20
    assert data["offset"] == 0


def test_leaderboard_limit_and_offset_paginate(test_db):
    _seed_contest_with_threads([300, 200, 100])
    page1 = get_leaderboard(limit=1, offset=0)
    page2 = get_leaderboard(limit=1, offset=1)
    assert page1["total_count"] == 3
    assert len(page1["threads"]) == 1
    assert len(page2["threads"]) == 1
    assert page1["threads"][0]["thread_id"] != page2["threads"][0]["thread_id"]
    # Default sort is score desc → page1 holds the highest-scoring thread.
    assert page1["threads"][0]["score"] >= page2["threads"][0]["score"]


def test_leaderboard_limit_clamped_to_100(test_db):
    data = get_leaderboard(limit=10_000)
    assert data["limit"] == 100


def test_leaderboard_negative_offset_clamped_to_zero(test_db):
    data = get_leaderboard(offset=-5)
    assert data["offset"] == 0


def test_leaderboard_invalid_sort_by_falls_back_to_score(test_db):
    """Unknown sort columns (incl. injection attempts) fall back to score, never SQL."""
    _seed_contest_with_threads([100])
    data = get_leaderboard(sort_by="score; DROP TABLE threads")
    assert data["sort_by"] == "score"
    assert len(data["threads"]) == 1  # table intact, query still ran


def test_leaderboard_invalid_sort_dir_defaults_desc(test_db):
    data = get_leaderboard(sort_dir="sideways")
    assert data["sort_dir"] == "desc"


def test_leaderboard_sort_by_score_asc(test_db):
    _seed_contest_with_threads([300, 100, 200])
    data = get_leaderboard(sort_by="score", sort_dir="asc")
    scores = [t["score"] for t in data["threads"]]
    assert scores == sorted(scores)


def test_leaderboard_sort_by_likes_desc(test_db):
    _seed_contest_with_threads([100, 300, 200])
    data = get_leaderboard(sort_by="likes", sort_dir="desc")
    likes = [t["likes"] for t in data["threads"]]
    assert likes == sorted(likes, reverse=True)


def test_leaderboard_threads_include_aggregated_metrics(test_db):
    """Thread rows expose engagement metrics summed across their posts."""
    create_contest("C", None, "2025-01-01", "2025-12-31")
    upsert_post_data(TWEET_1)
    upsert_post_data(TWEET_2)
    create_thread(["111", "222"])
    t = get_leaderboard()["threads"][0]
    assert t["likes"] == 150          # 100 + 50
    assert t["retweets"] == 15        # 10 + 5
    assert t["impressions"] == 1500   # 1000 + 500


def test_leaderboard_views_alias_sorts_by_impressions(test_db):
    """'views' is an accepted alias mapping to the impressions column."""
    create_contest("C", None, "2025-01-01", "2025-12-31")
    upsert_post_data(TWEET_2)         # 500 impressions
    upsert_post_data(TWEET_1)         # 1000 impressions
    create_thread(["222"])
    create_thread(["111"])
    data = get_leaderboard(sort_by="views", sort_dir="desc")
    assert data["sort_by"] == "views"
    impressions = [t["impressions"] for t in data["threads"]]
    assert impressions == [1000, 500]

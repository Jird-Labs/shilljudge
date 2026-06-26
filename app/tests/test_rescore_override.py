"""DEV-27: admin rescore endpoints + manual score override.

These tests drive the new endpoints end-to-end against the mocked X client
(MOCK_TWEETS in conftest). DB state (contest + thread) is seeded directly via
the database module, mirroring the core test style.
"""
from shilljudge_core import database
import pytest


def _seed_contest_thread(weights: dict | None = None):
    """Active contest + a 2-post thread (posts 111 & 222). Returns (contest_id, thread_id)."""
    contest = database.create_contest(
        "Rescore", None, "2025-01-01", "2025-12-31", weights=weights or {}
    )
    from tests.conftest import MOCK_TWEETS

    database.upsert_post_data(MOCK_TWEETS["111"])
    database.upsert_post_data(MOCK_TWEETS["222"])
    thread = database.create_thread(["111", "222"])
    return contest["contest_id"], thread["thread_id"]


# ── Auth matrix ───────────────────────────────────────────────────────────────

def test_rescore_requires_auth(client, test_db):
    cid, tid = _seed_contest_thread()
    assert client.post(f"/threads/{tid}/rescore").status_code == 401


def test_rescore_forbidden_for_non_admin(user_client, test_db):
    cid, tid = _seed_contest_thread()
    assert user_client.post(f"/threads/{tid}/rescore").status_code == 403


def test_override_requires_admin(user_client, test_db):
    cid, tid = _seed_contest_thread()
    resp = user_client.patch(f"/threads/{tid}/score", json={"override_score": 5.0, "note": "x"})
    assert resp.status_code == 403


def test_rescore_all_forbidden_for_non_admin(user_client, test_db):
    cid, tid = _seed_contest_thread()
    assert user_client.post(f"/contests/{cid}/rescore-all").status_code == 403


# ── Rescore ───────────────────────────────────────────────────────────────────

def test_rescore_reflects_new_weights(admin_client, test_db):
    cid, tid = _seed_contest_thread()
    original = database.get_thread(tid)["total_score"]
    # Heavier like weighting should raise the recomputed score.
    database.update_contest(cid, {"weight_likes": 2.0})

    resp = admin_client.post(f"/threads/{tid}/rescore")
    assert resp.status_code == 200
    body = resp.json()
    assert body["thread_id"] == tid
    assert body["new_score"] > original
    assert database.get_thread(tid)["total_score"] == pytest.approx(body["new_score"])


def test_rescore_appends_metric_snapshot(admin_client, test_db):
    cid, tid = _seed_contest_thread()
    admin_client.post(f"/threads/{tid}/rescore")
    with database.get_connection() as conn:
        rows = conn.execute(
            "SELECT COUNT(*) AS n FROM post_metric_snapshots WHERE post_id IN ('111', '222')"
        ).fetchone()
    assert rows["n"] >= 2


def test_rescore_missing_thread_returns_404(admin_client, test_db):
    assert admin_client.post("/threads/999/rescore").status_code == 404


def test_rescore_all_rescores_every_thread(admin_client, test_db):
    cid, tid = _seed_contest_thread()
    # A second thread in the same contest (reuses the already-stored post 222).
    database.create_thread(["222"])
    resp = admin_client.post(f"/contests/{cid}/rescore-all")
    assert resp.status_code == 200
    body = resp.json()
    assert body["contest_id"] == cid
    assert body["rescored"] == 2


def test_rescore_all_missing_contest_returns_404(admin_client, test_db):
    assert admin_client.post("/contests/999/rescore-all").status_code == 404


# ── Manual override ───────────────────────────────────────────────────────────

def test_override_sets_effective_score(admin_client, test_db):
    cid, tid = _seed_contest_thread()
    resp = admin_client.patch(
        f"/threads/{tid}/score", json={"override_score": 9999.0, "note": "manual boost"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["is_overridden"] is True
    assert body["score"] == pytest.approx(9999.0)


def test_override_is_stored_with_note_and_admin(admin_client, test_db):
    cid, tid = _seed_contest_thread()
    admin_client.patch(
        f"/threads/{tid}/score", json={"override_score": 42.0, "note": "audit reason"}
    )
    with database.get_connection() as conn:
        meta = database.get_metadata(conn, "threads", "thread_id", tid, "admin")
    assert meta["override_score"] == pytest.approx(42.0)
    assert meta["note"] == "audit reason"
    assert meta["by"] == "admin1"


def test_override_takes_precedence_on_leaderboard(admin_client, test_db):
    cid, tid = _seed_contest_thread()
    admin_client.patch(f"/threads/{tid}/score", json={"override_score": 9999.0, "note": "boost"})
    data = admin_client.get("/leaderboard").json()
    row = next(t for t in data["threads"] if t["thread_id"] == tid)
    assert row["is_overridden"] is True
    assert row["score"] == pytest.approx(9999.0)


def test_clear_override_reverts_to_computed(admin_client, test_db):
    cid, tid = _seed_contest_thread()
    computed = database.get_thread(tid)["total_score"]
    admin_client.patch(f"/threads/{tid}/score", json={"override_score": 9999.0, "note": "boost"})
    resp = admin_client.patch(f"/threads/{tid}/score", json={"override_score": None})
    assert resp.status_code == 200
    body = resp.json()
    assert body["is_overridden"] is False
    assert body["score"] == pytest.approx(computed)


def test_override_missing_thread_returns_404(admin_client, test_db):
    resp = admin_client.patch("/threads/999/score", json={"override_score": 1.0, "note": "x"})
    assert resp.status_code == 404

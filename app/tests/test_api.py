import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from shilljudge_core import database
from shilljudge_core.database import create_contest


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
    assert data["author"]["x_username"] == "testuser"
    # Nothing should be in the posts table yet
    with database.get_connection() as conn:
        row = conn.execute("SELECT * FROM posts WHERE post_id = '111'").fetchone()
    assert row is None


def test_preview_invalid_url_returns_422(user_client):
    resp = user_client.post("/submissions/preview", json={"url": "not-a-url"})
    assert resp.status_code == 422


def test_preview_other_authors_post_returns_403(test_db):
    """MOCK_TWEETS["111"] has author_id "user1"; override current user to a different x_id."""
    from app import app
    from auth import get_current_user, get_x_client_for_user
    from fastapi.testclient import TestClient

    other_user = {"x_id": "other_user", "x_username": "someone_else",
                  "name": "Other", "profile_image_url": None,
                  "wallet_address": None, "stake_verified": 0, "stake_checked_at": None}
    app.dependency_overrides[get_current_user] = lambda: other_user
    app.dependency_overrides[get_x_client_for_user] = lambda: _StandaloneMockXClient()

    with TestClient(app) as c:
        resp = c.post("/submissions/preview", json={"url": "https://x.com/u/status/111"})
    assert resp.status_code == 403
    assert resp.json()["detail"]["error"] == "not_your_post"
    app.dependency_overrides.clear()


# ── Confirm ───────────────────────────────────────────────────────────────────

def test_confirm_persists_posts_and_creates_thread(user_client):
    resp = user_client.post("/submissions/confirm", json={"post_ids": ["111", "222"]})
    assert resp.status_code == 200
    data = resp.json()
    assert data["fetched"] == 2
    assert data["post_count"] == 2
    assert data["total_score"] > 0
    assert data["errors"] == []


def test_confirm_deduplicates_ids(user_client):
    resp = user_client.post("/submissions/confirm", json={"post_ids": ["111", "111", "222"]})
    assert resp.status_code == 200
    assert resp.json()["post_count"] == 2


def test_confirm_unknown_id_goes_to_errors(user_client):
    resp = user_client.post("/submissions/confirm", json={"post_ids": ["111", "999"]})
    assert resp.status_code == 200
    data = resp.json()
    assert data["fetched"] == 1
    assert len(data["errors"]) == 1


def test_confirm_all_unknown_returns_422(user_client):
    resp = user_client.post("/submissions/confirm", json={"post_ids": ["999", "888"]})
    assert resp.status_code == 422


def test_confirm_empty_list_returns_422(user_client):
    resp = user_client.post("/submissions/confirm", json={"post_ids": []})
    assert resp.status_code == 422


# ── Stake gate ────────────────────────────────────────────────────────────────

def test_stake_gate_no_wallet_blocks_submission(user_client, test_db, monkeypatch):
    import app as app_module
    create_contest("Test", None, "2020-01-01", "2099-12-31", must_stake_token=True)

    called = []
    monkeypatch.setattr(app_module, "check_wallet_staked", lambda w: called.append(w) or True)

    resp = user_client.post("/submissions/confirm", json={"post_ids": ["111"]})
    assert resp.status_code == 400
    assert resp.json()["detail"]["error"] == "wallet_required"
    assert called == []


def test_stake_gate_not_staked_blocks_submission(test_db, monkeypatch):
    import solana_client
    from app import app
    from auth import get_current_user, get_x_client_for_user
    from fastapi.testclient import TestClient

    create_contest("Test", None, "2020-01-01", "2099-12-31", must_stake_token=True)

    user_with_wallet = {
        "x_id": "user1", "x_username": "testuser", "name": "Test User",
        "profile_image_url": None, "wallet_address": "ABC123wallet",
        "stake_verified": 0, "stake_checked_at": None,
    }
    app.dependency_overrides[get_current_user] = lambda: user_with_wallet
    app.dependency_overrides[get_x_client_for_user] = lambda: _StandaloneMockXClient()
    import app as app_module
    monkeypatch.setattr(app_module, "check_wallet_staked", lambda w: False)

    with TestClient(app) as c:
        resp = c.post("/submissions/confirm", json={"post_ids": ["111"]})
    assert resp.status_code == 403
    assert resp.json()["detail"]["error"] == "stake_required"
    app.dependency_overrides.clear()


def test_stake_gate_staked_allows_submission(test_db, monkeypatch):
    import solana_client
    from app import app
    from auth import get_current_user, get_x_client_for_user
    from fastapi.testclient import TestClient

    create_contest("Test", None, "2020-01-01", "2099-12-31", must_stake_token=True)

    user_with_wallet = {
        "x_id": "user1", "x_username": "testuser", "name": "Test User",
        "profile_image_url": None, "wallet_address": "ABC123wallet",
        "stake_verified": 0, "stake_checked_at": None,
    }
    app.dependency_overrides[get_current_user] = lambda: user_with_wallet
    app.dependency_overrides[get_x_client_for_user] = lambda: _StandaloneMockXClient()
    import app as app_module
    monkeypatch.setattr(app_module, "check_wallet_staked", lambda w: True)

    with TestClient(app) as c:
        resp = c.post("/submissions/confirm", json={"post_ids": ["111"]})
    assert resp.status_code == 200
    app.dependency_overrides.clear()


def test_stake_gate_disabled_skips_solana(user_client, test_db, monkeypatch):
    import app as app_module
    create_contest("Test", None, "2020-01-01", "2099-12-31", must_stake_token=False)

    called = []
    monkeypatch.setattr(app_module, "check_wallet_staked", lambda w: called.append(w) or True)

    resp = user_client.post("/submissions/confirm", json={"post_ids": ["111"]})
    assert resp.status_code == 200
    assert called == []


# ── Leaderboard ───────────────────────────────────────────────────────────────

def test_leaderboard_includes_threads_key(client):
    resp = client.get("/leaderboard")
    assert resp.status_code == 200
    data = resp.json()
    assert "threads" in data
    assert isinstance(data["threads"], list)


def test_leaderboard_threads_populated_after_confirm(user_client):
    user_client.post("/submissions/confirm", json={"post_ids": ["111", "222"]})
    resp = user_client.get("/leaderboard")
    data = resp.json()
    assert len(data["threads"]) == 1
    t = data["threads"][0]
    assert t["post_count"] == 2
    assert t["total_score"] > 0


def test_leaderboard_returns_pagination_metadata(client):
    data = client.get("/leaderboard").json()
    assert "total_count" in data
    assert data["sort_by"] == "score"
    assert data["sort_dir"] == "desc"
    assert data["limit"] == 20
    assert data["offset"] == 0


def test_leaderboard_pagination_query_params(user_client):
    user_client.post("/submissions/confirm", json={"post_ids": ["111"]})
    user_client.post("/submissions/confirm", json={"post_ids": ["222"]})
    data = user_client.get("/leaderboard?limit=1&offset=0").json()
    assert data["total_count"] == 2
    assert len(data["threads"]) == 1
    assert data["limit"] == 1
    assert data["offset"] == 0


def test_leaderboard_limit_capped_at_100(client):
    data = client.get("/leaderboard?limit=5000").json()
    assert data["limit"] == 100


def test_leaderboard_sort_query_params_echoed(client):
    data = client.get("/leaderboard?sort=likes&dir=asc").json()
    assert data["sort_by"] == "likes"
    assert data["sort_dir"] == "asc"


def test_leaderboard_enrich_hook_adds_columns(user_client):
    """A registered ENRICH_LEADERBOARD handler enriches each thread row."""
    from shilljudge_core.hooks import registry, ENRICH_LEADERBOARD

    user_client.post("/submissions/confirm", json={"post_ids": ["111"]})

    def add_col(rows):
        for r in rows:
            r["premium_flag"] = True
        return rows

    registry.register(ENRICH_LEADERBOARD, add_col)
    try:
        data = user_client.get("/leaderboard").json()
        assert data["threads"]
        assert all(r["premium_flag"] is True for r in data["threads"])
    finally:
        registry.deregister(ENRICH_LEADERBOARD, add_col)


def test_leaderboard_base_response_has_no_premium_columns(user_client):
    """Extensions load at startup but no premium column (e.g. premium_flag) should appear;
    community extensions may add their own columns, but not premium-gated ones."""
    user_client.post("/submissions/confirm", json={"post_ids": ["111"]})
    data = user_client.get("/leaderboard").json()
    assert all("premium_flag" not in r for r in data["threads"])


# ── Poll status (public) ──────────────────────────────────────────────────────

def test_status_is_public_and_reports_poll_state(client):
    resp = client.get("/status")
    assert resp.status_code == 200
    data = resp.json()
    assert set(data) == {"status", "rate_limited_until", "last_poll_at"}
    assert data["status"] in ("ok", "rate_limited")


# ── First-user auto-admin ─────────────────────────────────────────────────────

def _make_oauth_mocks(user_id: str, username: str):
    """Return (FakeAuth class, fake_build_user_client fn) for /oauth/login + /oauth/callback."""
    class _FakeAuth:
        def __init__(self, **kw): pass
        def get_authorization_url(self): return "https://x.com/fake"
        def get_code_verifier(self): return "verifier"
        def set_pkce_parameters(self, v): pass
        def exchange_code(self, code): return {"access_token": "token"}

    class _Data:
        def model_dump(self):
            return {"id": user_id, "username": username}

    class _UsersResource:
        def get_me(self, user_fields=None):
            class _Resp:
                data = _Data()
            return _Resp()

        def get_by_ids(self, ids, **kw):
            class _R:
                data = []
            return _R()

    class _FakeClient:
        token = {"access_token": "token"}
        users = _UsersResource()

    return _FakeAuth, lambda s, t: _FakeClient()


def _run_oauth_callback(app, monkeypatch, app_module, user_id: str, username: str):
    from fastapi.testclient import TestClient
    FakeAuth, fake_build = _make_oauth_mocks(user_id, username)
    monkeypatch.setattr(app_module, "OAuth2PKCEAuth", FakeAuth)
    monkeypatch.setattr(app_module, "build_user_client", fake_build)
    monkeypatch.setattr(app_module, "save_user_token", lambda x_id, t: None)
    with TestClient(app, raise_server_exceptions=True) as c:
        c.get("/oauth/login", follow_redirects=False)
        resp = c.get("/oauth/callback?code=fake", follow_redirects=False)
    return resp


def test_first_user_auto_becomes_admin(tmp_path, monkeypatch):
    from shilljudge_core import database
    import app as app_module
    from app import app

    db_file = tmp_path / "test.db"
    monkeypatch.setattr(database, "DB_PATH", db_file)

    resp = _run_oauth_callback(app, monkeypatch, app_module, "user_first", "firstuser")
    assert resp.status_code == 302

    user = database.get_user("user_first")
    assert user is not None
    assert user["is_admin"] == 1


def test_second_user_not_auto_admin(tmp_path, monkeypatch):
    from shilljudge_core import database
    import app as app_module
    from app import app

    db_file = tmp_path / "test.db"
    monkeypatch.setattr(database, "DB_PATH", db_file)

    _run_oauth_callback(app, monkeypatch, app_module, "user_first", "firstuser")
    _run_oauth_callback(app, monkeypatch, app_module, "user_second", "seconduser")

    assert not database.get_user("user_second")["is_admin"]


# ── Contest admin ─────────────────────────────────────────────────────────────

def test_admin_can_create_and_delete_contest(admin_client):
    resp = admin_client.post("/manage/contests", json={
        "title": "Test", "start_date": "2025-01-01", "end_date": "2025-12-31",
        "must_stake_token": True,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["must_stake_token"] == 1
    cid = data["contest_id"]

    del_resp = admin_client.delete(f"/manage/contests/{cid}")
    assert del_resp.status_code == 200

    # Leaderboard should still load after contest deleted
    lb = admin_client.get("/leaderboard")
    assert lb.status_code == 200


# ── User management (admin) ───────────────────────────────────────────────────

def test_manage_users_requires_admin(client):
    assert client.get("/manage/users").status_code == 401


def test_manage_users_forbidden_for_non_admin(user_client):
    assert user_client.get("/manage/users").status_code == 403


def test_manage_users_includes_participation_status(admin_client):
    users = admin_client.get("/manage/users").json()
    assert users
    row = next(u for u in users if u["x_id"] == "user1")
    assert row["participation_status"] == "active"
    assert "created_at" in row


def test_manage_users_search_filter(admin_client):
    with database.get_connection() as conn:
        conn.execute("INSERT INTO users (x_id, x_username) VALUES ('u_alice', 'alice')")
        conn.execute("INSERT INTO users (x_id, x_username) VALUES ('u_bob', 'bob')")
    matches = {u["x_username"] for u in admin_client.get("/manage/users?q=ali").json()}
    assert matches == {"alice"}


def test_patch_user_grants_admin(admin_client):
    resp = admin_client.patch("/manage/user/user1", json={"is_admin": True})
    assert resp.status_code == 200
    assert resp.json()["is_admin"] == 1
    with database.get_connection() as conn:
        assert conn.execute("SELECT is_admin FROM users WHERE x_id = 'user1'").fetchone()["is_admin"] == 1


def test_patch_user_suspends_and_unsuspends(admin_client):
    resp = admin_client.patch("/manage/user/user1", json={"participation_status": "suspended"})
    assert resp.status_code == 200
    assert resp.json()["participation_status"] == "suspended"
    resp = admin_client.patch("/manage/user/user1", json={"participation_status": "active"})
    assert resp.json()["participation_status"] == "active"


def test_patch_user_self_demotion_forbidden(admin_client):
    """Admin (admin1) cannot revoke their own admin status."""
    resp = admin_client.patch("/manage/user/admin1", json={"is_admin": False})
    assert resp.status_code == 403
    assert resp.json()["detail"]["message"] == "Cannot revoke your own admin status."


def test_patch_user_self_can_still_suspend(admin_client):
    """Self-demotion guard only blocks is_admin=False, not other fields."""
    with database.get_connection() as conn:
        conn.execute("INSERT INTO users (x_id, x_username, is_admin) VALUES ('admin1', 'adminuser', 1)")
    resp = admin_client.patch("/manage/user/admin1", json={"participation_status": "suspended"})
    assert resp.status_code == 200


def test_patch_user_not_found(admin_client):
    assert admin_client.patch("/manage/user/ghost", json={"is_admin": True}).status_code == 404


def test_patch_user_requires_admin(user_client):
    assert user_client.patch("/manage/user/user1", json={"is_admin": True}).status_code == 403


def test_patch_user_invalid_status_rejected(admin_client):
    assert admin_client.patch("/manage/user/user1", json={"participation_status": "banned"}).status_code == 422


def test_admin_can_update_contest(admin_client):
    resp = admin_client.post("/manage/contests", json={
        "title": "Old", "start_date": "2025-01-01", "end_date": "2025-12-31",
    })
    cid = resp.json()["contest_id"]

    upd = admin_client.put(f"/manage/contests/{cid}", json={"title": "New", "must_stake_token": True})
    assert upd.status_code == 200
    data = upd.json()
    assert data["title"] == "New"
    assert data["must_stake_token"] == 1


# ── DEV-23: reply metadata in preview ─────────────────────────────────────────

def test_preview_includes_reply_metadata_for_self_reply(user_client):
    """A self-reply preview surfaces in_reply_to_user_id and the derived
    in_reply_to_post_id (from referenced_tweets)."""
    resp = user_client.post("/submissions/preview", json={"url": "https://x.com/u/status/333"})
    assert resp.status_code == 200
    post = resp.json()["post"]
    assert post["in_reply_to_user_id"] == "user1"
    assert post["in_reply_to_post_id"] == "111"


def test_preview_reply_metadata_null_for_top_level_post(user_client):
    """A non-reply post still carries the reply keys, both null."""
    resp = user_client.post("/submissions/preview", json={"url": "https://x.com/u/status/111"})
    assert resp.status_code == 200
    post = resp.json()["post"]
    assert post["in_reply_to_user_id"] is None
    assert post["in_reply_to_post_id"] is None


# ── DEV-23: deleted/missing post handling in preview ──────────────────────────

def test_preview_deleted_post_returns_marker_not_error(user_client):
    """When X returns 200 with no data (deleted tweet), preview returns a
    status:deleted marker rather than a 5xx/404."""
    from tests.conftest import DELETED_POST_ID
    resp = user_client.post(
        "/submissions/preview", json={"url": f"https://x.com/u/status/{DELETED_POST_ID}"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "deleted"
    assert data["post_id"] == DELETED_POST_ID


# ── DEV-23: admin delete thread ───────────────────────────────────────────────

def _seed_thread():
    """Insert two posts and a thread directly via core; return the thread_id."""
    from shilljudge_core.database import create_thread, upsert_post_data
    from tests.conftest import MOCK_TWEETS
    upsert_post_data(MOCK_TWEETS["111"])
    upsert_post_data(MOCK_TWEETS["222"])
    return create_thread(["111", "222"])["thread_id"]


def test_admin_delete_thread_removes_it(admin_client):
    tid = _seed_thread()
    resp = admin_client.delete(f"/manage/thread/{tid}")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    with database.get_connection() as conn:
        assert conn.execute("SELECT 1 FROM threads WHERE thread_id = ?", (tid,)).fetchone() is None
        assert conn.execute("SELECT 1 FROM thread_posts WHERE thread_id = ?", (tid,)).fetchone() is None


def test_admin_delete_thread_missing_returns_404(admin_client):
    assert admin_client.delete("/manage/thread/99999").status_code == 404


def test_delete_thread_requires_admin(user_client):
    tid = _seed_thread()
    assert user_client.delete(f"/manage/thread/{tid}").status_code == 403


def test_confirm_fires_enrich_thread_hook(user_client):
    """The ENRICH_THREAD hook fires for every thread assembled through the app."""
    from shilljudge_core.hooks import registry, ENRICH_THREAD

    seen = []

    def record(thread):
        seen.append(thread.get("thread_id"))
        return thread

    registry.register(ENRICH_THREAD, record)
    try:
        resp = user_client.post("/submissions/confirm", json={"post_ids": ["111"]})
        assert resp.status_code == 200
        assert seen == [resp.json()["thread_id"]]
    finally:
        registry.deregister(ENRICH_THREAD, record)

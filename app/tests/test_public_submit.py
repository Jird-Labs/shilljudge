import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import database
from app import app
from database import create_contest


def test_get_optional_user_returns_none_without_session(test_db):
    from auth import get_optional_user

    class _Req:
        session = {}

    assert get_optional_user(_Req()) is None


def test_get_optional_user_returns_user_with_session(test_db):
    from auth import get_optional_user

    class _Req:
        session = {"x_id": "user1"}

    user = get_optional_user(_Req())
    assert user is not None and user["x_id"] == "user1"


def test_get_optional_user_none_when_user_missing(test_db):
    from auth import get_optional_user

    class _Req:
        session = {"x_id": "ghost"}

    assert get_optional_user(_Req()) is None


def test_preview_returns_post_and_estimated_score(submit_client):
    create_contest("C", None, "2020-01-01", "2099-12-31")
    resp = submit_client.post("/submit/preview", json={"url": "https://x.com/u/status/111"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["post"]["id"] == "111"
    assert data["estimated_score"] > 0
    # Preview never persists
    with database.get_connection() as conn:
        assert conn.execute("SELECT 1 FROM posts WHERE post_id = '111'").fetchone() is None


def test_preview_invalid_url_returns_422(submit_client):
    resp = submit_client.post("/submit/preview", json={"url": "not-a-url"})
    assert resp.status_code == 422


def test_preview_no_app_token_returns_503(client):
    # `client` fixture sets no get_app_x_client override and the DB has no oauth_tokens.
    resp = client.post("/submit/preview", json={"url": "https://x.com/u/status/111"})
    assert resp.status_code == 503
    assert resp.json()["detail"]["error"] == "submission_unavailable"


def test_submit_creates_thread_and_returns_score(submit_client):
    create_contest("C", None, "2020-01-01", "2099-12-31")
    resp = submit_client.post("/submit", json={"url": "https://x.com/u/status/111"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert isinstance(data["thread_id"], int)
    assert data["score"] > 0
    with database.get_connection() as conn:
        assert conn.execute("SELECT 1 FROM posts WHERE post_id = '111'").fetchone() is not None


def test_submit_invalid_url_returns_422(submit_client):
    assert submit_client.post("/submit", json={"url": "not-a-url"}).status_code == 422


def test_submit_duplicate_returns_existing_thread(submit_client):
    create_contest("C", None, "2020-01-01", "2099-12-31")
    first = submit_client.post("/submit", json={"url": "https://x.com/u/status/111"}).json()
    assert first["status"] == "ok"
    dup = submit_client.post("/submit", json={"url": "https://x.com/u/status/111"}).json()
    assert dup["status"] == "duplicate"
    assert dup["existing_thread_id"] == first["thread_id"]
    # Not stored a second time → still exactly one thread
    with database.get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) c FROM threads").fetchone()["c"] == 1


def test_submit_no_app_token_returns_503(client):
    resp = client.post("/submit", json={"url": "https://x.com/u/status/111"})
    assert resp.status_code == 503


def test_submit_on_submission_rejection_returns_403(submit_client):
    create_contest("C", None, "2020-01-01", "2099-12-31")
    from hooks import registry, ON_SUBMISSION

    def reject(post_ids, ctx):
        return []

    registry.register(ON_SUBMISSION, reject)
    try:
        resp = submit_client.post("/submit", json={"url": "https://x.com/u/status/111"})
        assert resp.status_code == 403
        assert resp.json()["detail"]["error"] == "submission_rejected"
    finally:
        registry.deregister(ON_SUBMISSION, reject)


def test_submit_suspended_session_returns_403(submit_client, monkeypatch):
    from auth import get_optional_user
    monkeypatch.setitem(
        app.dependency_overrides,
        get_optional_user,
        lambda: {"x_id": "user1", "participation_status": "suspended"},
    )
    resp = submit_client.post("/submit", json={"url": "https://x.com/u/status/111"})
    assert resp.status_code == 403
    assert resp.json()["detail"]["error"] == "suspended"


def test_submit_low_follower_failure_falls_back_to_none(submit_client, monkeypatch):
    create_contest("C", None, "2020-01-01", "2099-12-31")
    import app as app_module
    monkeypatch.setattr(app_module, "analyze_post_engagement", lambda c, pid: None)
    resp = submit_client.post("/submit", json={"url": "https://x.com/u/status/111"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_submit_no_active_contest_returns_409(submit_client):
    resp = submit_client.post("/submit", json={"url": "https://x.com/u/status/111"})
    assert resp.status_code == 409
    assert resp.json()["detail"]["error"] == "no_active_contest"


def test_preview_no_active_contest_returns_409(submit_client):
    resp = submit_client.post("/submit/preview", json={"url": "https://x.com/u/status/111"})
    assert resp.status_code == 409
    assert resp.json()["detail"]["error"] == "no_active_contest"


def test_submit_suspended_user_from_db_returns_403(submit_client, monkeypatch):
    import database
    from auth import get_optional_user
    with database.get_connection() as conn:
        conn.execute("UPDATE users SET participation_status='suspended' WHERE x_id='user1'")
    monkeypatch.setitem(app.dependency_overrides, get_optional_user, lambda: database.get_user("user1"))
    resp = submit_client.post("/submit", json={"url": "https://x.com/u/status/111"})
    assert resp.status_code == 403
    assert resp.json()["detail"]["error"] == "suspended"

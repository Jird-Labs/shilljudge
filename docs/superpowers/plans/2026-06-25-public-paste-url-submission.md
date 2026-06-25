# Public paste-URL submission + duplicate detection — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let anyone (no X login) paste an X post URL and submit it as a thread, with duplicate detection against the active contest.

**Architecture:** Two new public FastAPI endpoints (`POST /submit/preview`, `POST /submit`) on `thread-helper/backend/app.py`, fed by an app-level X client built from a stored token (reusing the poller's selection). A pure `score_post()` helper and a `find_active_contest_thread_for_post()` query are added to the SQLite layer. A new public `SubmitPage.jsx` drives the two-call preview→confirm flow.

**Tech Stack:** Python 3 / FastAPI / slowapi / SQLite (raw `sqlite3`) / `xdk` X client; React / Vite / Tailwind / react-router-dom / lucide-react.

## Global Constraints

- **Mirror DB-layer changes in BOTH copies:** `core/src/shilljudge_core/database.py` AND `thread-helper/backend/database.py` are independent duplicates. Any function added/changed in one must be byte-identical in the other.
- **Preserve the public scoring math exactly:** `score = max(valid + 300.0 * (ratio), 0)` where `valid = interactions - low_follower_engagements` and `ratio = max((valid - low) / impressions, 0)` (0 when impressions ≤ 0). Existing tests (`test_default_weights_match_base_formula`, `test_calculate_score_hook_applied`) must stay green.
- **No new auth surface:** public endpoints take no `get_current_user` dependency; they use an *optional* session lookup only.
- **Core has no FastAPI/X/React code** (per `core/CLAUDE.md`): the endpoints, the X-client dependency, and `analyze_post_engagement` usage live in `thread-helper`, never in `core`.
- **Both new endpoints are rate-limited** with `@limiter.limit(settings.rate_limit_submissions)`.
- Run backend tests: `cd thread-helper/backend && uv run pytest`. Run core tests: `cd core && uv run pytest`.

---

## File Structure

- `core/src/shilljudge_core/database.py` — add `score_post()`, `find_active_contest_thread_for_post()`; refactor `upsert_post_data` to call `score_post`.
- `core/tests/test_database.py` — unit tests for both new functions.
- `thread-helper/backend/database.py` — mirror `score_post()` + `find_active_contest_thread_for_post()`; mirror the `upsert_post_data` refactor.
- `thread-helper/backend/auth.py` — add `get_optional_user()`.
- `thread-helper/backend/app.py` — add `get_app_x_client()` dependency + `POST /submit/preview` + `POST /submit`; new imports.
- `thread-helper/backend/tests/conftest.py` — add `submit_client` fixture.
- `thread-helper/backend/tests/test_public_submit.py` — new endpoint tests.
- `thread-helper/frontend/src/api.js` — add `submitPreview`, `submitThread`.
- `thread-helper/frontend/src/pages/SubmitPage.jsx` — new public page.
- `thread-helper/frontend/src/App.jsx` — public `/submit` route.
- `thread-helper/frontend/src/components/Layout.jsx` — nav entry.
- `thread-helper/frontend/vite.config.js` — proxy `/submit`.

---

### Task 1: Pure `score_post()` helper (core, then mirror)

Extract the inline scoring formula from `upsert_post_data` into a pure function so the public preview can estimate a score without storing. Behavior of `upsert_post_data` is unchanged.

**Files:**
- Modify: `core/src/shilljudge_core/database.py` (the `upsert_post_data` body around lines 287–301)
- Test: `core/tests/test_database.py`
- Mirror: `thread-helper/backend/database.py` (its `upsert_post_data`, around line 240)

**Interfaces:**
- Produces: `score_post(metrics: dict, low_follower_engagements: int | None = None, weights: dict | None = None) -> tuple[float, float]` returning `(score, ratio)`. Pure — no DB, no hook dispatch.

- [ ] **Step 1: Write the failing tests**

Add to `core/tests/test_database.py` (the file already defines `TWEET_1` and imports from `shilljudge_core.database`; add `score_post` to that import list):

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd core && uv run pytest tests/test_database.py -k score_post -v`
Expected: FAIL with `ImportError` / `cannot import name 'score_post'`.

- [ ] **Step 3: Implement `score_post` and refactor `upsert_post_data`**

In `core/src/shilljudge_core/database.py`, add this function immediately **above** `def upsert_post_data(`:

```python
def score_post(
    metrics: dict[str, Any],
    low_follower_engagements: int | None = None,
    weights: dict[str, Any] | None = None,
) -> tuple[float, float]:
    """Compute ``(score, ratio)`` for a post's ``public_metrics`` under the given
    contest ``weights``. Pure: no DB access, no hook dispatch. ``upsert_post_data`` uses
    this for persistence; the public preview endpoint uses it to estimate a score
    without storing. Absent/all-1.0 weights reproduce the unweighted score exactly."""
    w = weights or {}
    interactions = (
        (metrics.get("retweet_count") or 0) * w.get("weight_retweets", 1.0)
        + (metrics.get("reply_count") or 0) * w.get("weight_replies", 1.0)
        + (metrics.get("like_count") or 0) * w.get("weight_likes", 1.0)
        + (metrics.get("quote_count") or 0) * w.get("weight_quotes", 1.0)
        + (metrics.get("bookmark_count") or 0) * w.get("weight_bookmarks", 1.0)
    )
    impressions = (metrics.get("impression_count") or 0) * w.get("weight_impressions", 1.0)
    low = low_follower_engagements or 0
    valid = interactions - low
    ratio = max((valid - low) / impressions, 0.0) if impressions > 0 else 0.0
    score = max(valid + 300.0 * ratio, 0.0)
    return score, ratio
```

Then in `upsert_post_data`, replace the inline computation (the block from `interactions = (` through `score = max(valid + 300.0 * ratio, 0.0)`, currently lines ~288–300) with:

```python
    score, ratio = score_post(metrics, low_follower_engagements, weights)
```

Leave the following line `score = registry.call(CALCULATE_SCORE, tweet, score)` and everything after it unchanged.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd core && uv run pytest tests/test_database.py -v`
Expected: PASS — the new `score_post` tests AND all existing tests (esp. `test_default_weights_match_base_formula`, `test_calculate_score_hook_applied`).

- [ ] **Step 5: Mirror into thread-helper**

Apply the identical change to `thread-helper/backend/database.py`: add the same `score_post` function above its `upsert_post_data`, and replace that function's inline formula block with `score, ratio = score_post(metrics, low_follower_engagements, weights)`. Keep the trailing `score = registry.call(CALCULATE_SCORE, tweet, score)` line.

Run: `cd thread-helper/backend && uv run pytest tests/test_database.py -v`
Expected: PASS (no behavioral change).

- [ ] **Step 6: Commit**

```bash
git add core/src/shilljudge_core/database.py core/tests/test_database.py thread-helper/backend/database.py
git commit -m "feat(DEV-25): extract pure score_post() helper (mirrored core + thread-helper)"
```

---

### Task 2: `find_active_contest_thread_for_post()` duplicate query (core, then mirror)

**Files:**
- Modify: `core/src/shilljudge_core/database.py` (add after `get_thread_post_ids`/near the thread queries)
- Test: `core/tests/test_database.py`
- Mirror: `thread-helper/backend/database.py`

**Interfaces:**
- Consumes: `_get_active_contest_id(conn)` (existing private helper).
- Produces: `find_active_contest_thread_for_post(post_id: str) -> int | None` — the thread_id of a thread in the *active* contest already containing `post_id`, else `None` (also `None` when there is no active contest).

- [ ] **Step 1: Write the failing tests**

Add to `core/tests/test_database.py` (add `create_contest` and `find_active_contest_thread_for_post` to the imports if not present — `create_contest` is already imported):

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd core && uv run pytest tests/test_database.py -k find_duplicate -v`
Expected: FAIL with `cannot import name 'find_active_contest_thread_for_post'`.

- [ ] **Step 3: Implement the query**

In `core/src/shilljudge_core/database.py`, add (e.g. directly after `get_thread_post_ids`):

```python
def find_active_contest_thread_for_post(post_id: str) -> int | None:
    """Return the thread_id of a thread in the *active* contest that already contains
    ``post_id``, or None when there is no active contest or no such thread. Used to
    detect duplicate public submissions."""
    with get_connection() as conn:
        active_id = _get_active_contest_id(conn)
        if active_id is None:
            return None
        row = conn.execute(
            """
            SELECT tp.thread_id
            FROM thread_posts tp
            JOIN threads t ON tp.thread_id = t.thread_id
            WHERE t.contest_id = ? AND tp.post_id = ?
            LIMIT 1
            """,
            (active_id, post_id),
        ).fetchone()
        return row["thread_id"] if row else None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd core && uv run pytest tests/test_database.py -k find_duplicate -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Mirror into thread-helper + export**

Add the identical `find_active_contest_thread_for_post` function to `thread-helper/backend/database.py` (after its `get_thread_post_ids`).

Run: `cd thread-helper/backend && uv run pytest -q`
Expected: PASS (no regressions).

- [ ] **Step 6: Commit**

```bash
git add core/src/shilljudge_core/database.py core/tests/test_database.py thread-helper/backend/database.py
git commit -m "feat(DEV-25): add find_active_contest_thread_for_post() duplicate query (mirrored)"
```

---

### Task 3: Backend plumbing — optional-user + app-level X client dependencies

**Files:**
- Modify: `thread-helper/backend/auth.py` (add `get_optional_user`)
- Modify: `thread-helper/backend/app.py` (add `get_app_x_client`, imports)
- Test: `thread-helper/backend/tests/test_public_submit.py` (new)

**Interfaces:**
- Consumes: `get_user` (auth.py already imports it); `_select_poller_x_id()`, `load_user_token`, `save_user_token`, `build_user_client`, `_tokens_differ`, `settings` (all already present in app.py).
- Produces:
  - `get_optional_user(request: Request) -> dict | None` — logged-in user dict if a valid session exists, else `None`; never raises.
  - `get_app_x_client() -> Generator[Client, None, None]` — yields an app-level X client from a stored token (admin preferred); raises `HTTPException(503, {"error": "submission_unavailable", ...})` when no usable token; persists a refreshed token on exit.

- [ ] **Step 1: Write the failing tests**

Create `thread-helper/backend/tests/test_public_submit.py`:

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd thread-helper/backend && uv run pytest tests/test_public_submit.py -v`
Expected: FAIL with `cannot import name 'get_optional_user'`.

- [ ] **Step 3: Implement `get_optional_user`**

In `thread-helper/backend/auth.py`, add after `get_current_user`:

```python
def get_optional_user(request: Request) -> dict[str, Any] | None:
    """Return the logged-in user dict if a valid session exists, else None. Unlike
    ``get_current_user`` this never raises — for public endpoints that allow anonymous
    access but still want an optional session check (e.g. the suspended-user guard)."""
    x_id = request.session.get("x_id")
    if not x_id:
        return None
    return get_user(x_id)
```

- [ ] **Step 4: Implement `get_app_x_client` in app.py**

In `thread-helper/backend/app.py`:

1. Add to the top imports: `from collections.abc import Generator`.
2. Extend the auth import (line 23) to: `from auth import get_current_user, get_optional_user, get_x_client_for_user, require_admin`.
3. Extend the hooks import (line 59) to: `from hooks import ENRICH_LEADERBOARD, ON_SUBMISSION, registry`.
4. Extend the database import block (lines 25–57) to also import: `find_active_contest_thread_for_post`, `score_post`.
5. Add this dependency immediately after the existing `_poll_client` context manager (~line 173):

```python
def get_app_x_client() -> Generator[Client, None, None]:
    """Yield an app-level authenticated X client built from a stored token (admin
    preferred) for public/no-login endpoints. Raises 503 when no usable token is
    stored. Persists a refreshed token on exit (mirrors _poll_client)."""
    x_id = _select_poller_x_id()
    token = load_user_token(x_id) if x_id else None
    if not x_id or not token or not token.get("access_token"):
        raise HTTPException(
            status_code=503,
            detail={
                "error": "submission_unavailable",
                "message": "Submissions are temporarily unavailable (no connected X app credentials).",
            },
        )
    client = build_user_client(settings, token)
    token_before = copy.deepcopy(client.token)
    try:
        yield client
    finally:
        token_after = client.token
        if _tokens_differ(token_before, token_after) and token_after:
            save_user_token(x_id, token_after)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd thread-helper/backend && uv run pytest tests/test_public_submit.py -v`
Expected: PASS (3 passed). The app.py edits must import cleanly (run `uv run python -c "import app"` if unsure).

- [ ] **Step 6: Commit**

```bash
git add thread-helper/backend/auth.py thread-helper/backend/app.py thread-helper/backend/tests/test_public_submit.py
git commit -m "feat(DEV-25): add optional-user + app-level X client dependencies"
```

---

### Task 4: `POST /submit/preview` endpoint

**Files:**
- Modify: `thread-helper/backend/app.py` (new route + a small suspended-guard helper)
- Modify: `thread-helper/backend/tests/conftest.py` (add `submit_client` fixture)
- Test: `thread-helper/backend/tests/test_public_submit.py`

**Interfaces:**
- Consumes: `get_app_x_client`, `get_optional_user`, `parse_post_id`, `find_active_contest_thread_for_post`, `get_active_contest`, `score_post`, `PreviewSubmissionRequest`, `DEFAULT_TWEET_FIELDS`.
- Produces: `POST /submit/preview` → `{"status": "ok", "post": <tweet>, "estimated_score": <float>}` or `{"status": "duplicate", "existing_thread_id": <int>}`; `422` invalid URL; `403` suspended; `503` no app client.
- Produces (helper): `_reject_if_suspended(user: dict | None) -> None`.

- [ ] **Step 1: Add the `submit_client` fixture**

In `thread-helper/backend/tests/conftest.py`, add after the `admin_client` fixture:

```python
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
```

- [ ] **Step 2: Write the failing tests**

Add to `thread-helper/backend/tests/test_public_submit.py`:

```python
import database
from app import app, get_app_x_client


def test_preview_returns_post_and_estimated_score(submit_client):
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
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd thread-helper/backend && uv run pytest tests/test_public_submit.py -k preview -v`
Expected: FAIL with `404 Not Found` (route does not exist) for the first two, and the 503 test likely errors on missing route too.

- [ ] **Step 4: Implement the helper + route**

In `thread-helper/backend/app.py`, add a new section (e.g. after the existing `/submissions/confirm` block, before `# ── Individual post`):

```python
# ── Public submission (no login) ─────────────────────────────────────────────

def _reject_if_suspended(user: dict[str, Any] | None) -> None:
    """403 if an *authenticated* session belongs to a suspended user. Anonymous
    (user is None) passes through — there is no reliable IP→account mapping."""
    if user and user.get("participation_status") == "suspended":
        raise HTTPException(
            status_code=403,
            detail={"error": "suspended", "message": "This account is suspended from submitting."},
        )


@app.post("/submit/preview")
@limiter.limit(settings.rate_limit_submissions)
async def submit_preview(
    request: Request,
    body: PreviewSubmissionRequest,
    x_client: Annotated[Client, Depends(get_app_x_client)],
    optional_user: Annotated[dict | None, Depends(get_optional_user)],
) -> dict[str, Any]:
    """Public, no-login preview: fetch a post and estimate its score without storing
    anything. Returns a duplicate marker if the post already exists in the active contest."""
    post_id = parse_post_id(body.url)
    if not post_id:
        raise HTTPException(status_code=422, detail="Invalid X post URL or ID.")

    _reject_if_suspended(optional_user)

    existing = find_active_contest_thread_for_post(post_id)
    if existing is not None:
        return {"status": "duplicate", "existing_thread_id": existing}

    try:
        resp = x_client.posts.get_by_id(
            id=post_id,
            tweet_fields=DEFAULT_TWEET_FIELDS,
            expansions=["author_id"],
            user_fields=["id", "username", "public_metrics"],
        )
    except requests.HTTPError as e:
        raise HTTPException(status_code=502, detail="Failed to fetch post from X.") from e

    result = resp.model_dump() if hasattr(resp, "model_dump") else resp
    tweet = result.get("data") if isinstance(result, dict) else None
    if not tweet or not tweet.get("id"):
        raise HTTPException(status_code=404, detail="Post not found on X.")

    estimated_score, _ = score_post(tweet.get("public_metrics") or {}, None, get_active_contest())
    return {"status": "ok", "post": tweet, "estimated_score": estimated_score}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd thread-helper/backend && uv run pytest tests/test_public_submit.py -k preview -v`
Expected: PASS (3 passed).

- [ ] **Step 6: Commit**

```bash
git add thread-helper/backend/app.py thread-helper/backend/tests/conftest.py thread-helper/backend/tests/test_public_submit.py
git commit -m "feat(DEV-25): add public POST /submit/preview endpoint"
```

---

### Task 5: `POST /submit` endpoint

**Files:**
- Modify: `thread-helper/backend/app.py` (new route)
- Test: `thread-helper/backend/tests/test_public_submit.py`

**Interfaces:**
- Consumes: `get_app_x_client`, `get_optional_user`, `parse_post_id`, `registry.call(ON_SUBMISSION, ...)`, `find_active_contest_thread_for_post`, `analyze_post_engagement`, `upsert_post_data`, `get_active_contest`, `create_thread`, `_reject_if_suspended` (from Task 4).
- Produces: `POST /submit` → `{"status": "ok", "thread_id": <int>, "score": <float>}` or `{"status": "duplicate", "existing_thread_id": <int>}`; `422` invalid URL; `403` suspended or `ON_SUBMISSION` rejection; `503` no app client.

- [ ] **Step 1: Write the failing tests**

Add to `thread-helper/backend/tests/test_public_submit.py` (imports `database`, `app`, `get_app_x_client` already added in Task 4):

```python
from database import create_contest


def test_submit_creates_thread_and_returns_score(submit_client):
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


def test_submit_suspended_session_returns_403(submit_client):
    from auth import get_optional_user
    app.dependency_overrides[get_optional_user] = lambda: {
        "x_id": "user1", "participation_status": "suspended",
    }
    resp = submit_client.post("/submit", json={"url": "https://x.com/u/status/111"})
    assert resp.status_code == 403
    assert resp.json()["detail"]["error"] == "suspended"


def test_submit_low_follower_failure_falls_back_to_none(submit_client, monkeypatch):
    import app as app_module
    monkeypatch.setattr(app_module, "analyze_post_engagement", lambda c, pid: None)
    resp = submit_client.post("/submit", json={"url": "https://x.com/u/status/111"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd thread-helper/backend && uv run pytest tests/test_public_submit.py -k "submit and not preview" -v`
Expected: FAIL with `404 Not Found` (route does not exist).

- [ ] **Step 3: Implement the route**

In `thread-helper/backend/app.py`, add directly after `submit_preview`:

```python
@app.post("/submit")
@limiter.limit(settings.rate_limit_submissions)
async def submit(
    request: Request,
    body: PreviewSubmissionRequest,
    x_client: Annotated[Client, Depends(get_app_x_client)],
    optional_user: Annotated[dict | None, Depends(get_optional_user)],
) -> dict[str, Any]:
    """Public, no-login submission: validate, fire ON_SUBMISSION, dedupe, fetch the
    post, score it against the active contest, store it, and create a single-post thread."""
    post_id = parse_post_id(body.url)
    if not post_id:
        raise HTTPException(status_code=422, detail="Invalid X post URL or ID.")

    _reject_if_suspended(optional_user)

    allowed = registry.call(ON_SUBMISSION, [post_id], {"ip": request.client.host})
    if not allowed:
        raise HTTPException(
            status_code=403,
            detail={"error": "submission_rejected", "message": "Submission was rejected."},
        )

    existing = find_active_contest_thread_for_post(post_id)
    if existing is not None:
        return {"status": "duplicate", "existing_thread_id": existing}

    try:
        resp = x_client.posts.get_by_id(
            id=post_id,
            tweet_fields=DEFAULT_TWEET_FIELDS,
            expansions=["author_id"],
            user_fields=["id", "username", "public_metrics"],
        )
    except requests.HTTPError as e:
        raise HTTPException(status_code=502, detail="Failed to fetch post from X.") from e

    result = resp.model_dump() if hasattr(resp, "model_dump") else resp
    tweet = result.get("data") if isinstance(result, dict) else None
    if not tweet or not tweet.get("id"):
        raise HTTPException(status_code=404, detail="Post not found on X.")

    low = analyze_post_engagement(x_client, post_id)
    upsert_post_data(tweet, low_follower_engagements=low, weights=get_active_contest())
    thread = create_thread([tweet["id"]])

    return {"status": "ok", "thread_id": thread["thread_id"], "score": thread["total_score"]}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd thread-helper/backend && uv run pytest tests/test_public_submit.py -v`
Expected: PASS (all public-submit tests). Then run the full backend suite:

Run: `cd thread-helper/backend && uv run pytest -q`
Expected: PASS (no regressions in the existing auth-gated `/submissions/*` tests).

- [ ] **Step 5: Commit**

```bash
git add thread-helper/backend/app.py thread-helper/backend/tests/test_public_submit.py
git commit -m "feat(DEV-25): add public POST /submit endpoint with duplicate detection"
```

---

### Task 6: Frontend — public SubmitPage + routing + nav + proxy

No JS test harness exists in this repo, so this task's gate is a clean `npm run build` plus a manual smoke check.

**Files:**
- Modify: `thread-helper/frontend/src/api.js`
- Create: `thread-helper/frontend/src/pages/SubmitPage.jsx`
- Modify: `thread-helper/frontend/src/App.jsx`
- Modify: `thread-helper/frontend/src/components/Layout.jsx`
- Modify: `thread-helper/frontend/vite.config.js`

**Interfaces:**
- Consumes: `submitPreview(url)`, `submitThread(url)` from `api.js`; `TweetPreviewCard`, `Spinner`.
- Produces: `SubmitPage` default export; public `/submit` route; nav entry.

- [ ] **Step 1: Add API helpers**

In `thread-helper/frontend/src/api.js`, add after `confirmSubmission`:

```javascript
export async function submitPreview(url) {
  return apiFetch('/submit/preview', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url }),
  });
}

export async function submitThread(url) {
  return apiFetch('/submit', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url }),
  });
}
```

- [ ] **Step 2: Add the Vite proxy entry**

In `thread-helper/frontend/vite.config.js`, add `'/submit': backendTarget,` to the `proxy` object (e.g. after the `'/submissions'` line).

- [ ] **Step 3: Create `SubmitPage.jsx`**

Create `thread-helper/frontend/src/pages/SubmitPage.jsx`:

```jsx
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { submitPreview, submitThread } from '../api';
import Spinner from '../components/Spinner';
import TweetPreviewCard from '../components/TweetPreviewCard';

// state: idle | previewing | preview | submitting | done
export default function SubmitPage() {
  const [url, setUrl] = useState('');
  const [phase, setPhase] = useState('idle');
  const [preview, setPreview] = useState(null);      // {post, estimated_score}
  const [duplicate, setDuplicate] = useState(null);  // existing_thread_id
  const [result, setResult] = useState(null);        // {thread_id, score}
  const [error, setError] = useState(null);

  const handlePreview = async e => {
    e.preventDefault();
    if (!url.trim()) return;
    setPhase('previewing');
    setError(null);
    setDuplicate(null);
    try {
      const data = await submitPreview(url.trim());
      if (data.status === 'duplicate') {
        setDuplicate(data.existing_thread_id);
        setPhase('idle');
        return;
      }
      setPreview(data);
      setPhase('preview');
    } catch (err) {
      setError(err.message);
      setPhase('idle');
    }
  };

  const handleSubmit = async () => {
    setPhase('submitting');
    setError(null);
    try {
      const data = await submitThread(url.trim());
      if (data.status === 'duplicate') {
        setDuplicate(data.existing_thread_id);
        setPreview(null);
        setPhase('idle');
        return;
      }
      setResult(data);
      setUrl('');
      setPreview(null);
      setPhase('done');
    } catch (err) {
      setError(err.message);
      setPhase('preview');
    }
  };

  const handleReset = () => {
    setPhase('idle');
    setPreview(null);
    setResult(null);
    setDuplicate(null);
    setError(null);
  };

  const spinning = phase === 'previewing' || phase === 'submitting';

  return (
    <div className="space-y-4">
      <h2 className="text-white font-semibold text-lg">Submit a Thread</h2>
      <p className="text-zinc-500 text-sm">Paste an X post URL — no login required.</p>

      {(phase === 'idle' || phase === 'previewing') && (
        <form onSubmit={handlePreview} className="space-y-3">
          <input
            type="text"
            value={url}
            onChange={e => setUrl(e.target.value)}
            placeholder="https://x.com/user/status/123..."
            disabled={spinning}
            className="w-full bg-zinc-900 border border-zinc-700 focus:border-sky-500 text-white text-sm rounded-xl px-4 py-3 placeholder-zinc-600 focus:outline-none transition-colors disabled:opacity-50"
          />
          <button
            type="submit"
            disabled={spinning || !url.trim()}
            className="w-full bg-sky-500 hover:bg-sky-400 active:bg-sky-600 disabled:opacity-40 disabled:cursor-not-allowed text-white font-semibold py-3 rounded-xl transition-colors text-sm flex items-center justify-center gap-2"
          >
            {spinning ? <><Spinner size={16} /> Fetching preview…</> : 'Preview'}
          </button>
        </form>
      )}

      {duplicate != null && (
        <div className="text-yellow-300 text-sm bg-yellow-950/30 border border-yellow-800 rounded-xl p-3">
          This post was already submitted.{' '}
          <Link to={`/?thread=${duplicate}`} className="underline text-sky-400">View the existing thread</Link>.
        </div>
      )}

      {phase === 'preview' && preview && (
        <div className="space-y-3">
          <TweetPreviewCard
            post={preview.post}
            author={{ name: null, x_username: null, profile_image_url: null }}
          />
          <p className="text-zinc-400 text-sm">
            Estimated score:{' '}
            <span className="text-white font-semibold">{preview.estimated_score?.toFixed(1)}</span>
          </p>
          <div className="flex gap-3 pt-1">
            <button
              onClick={handleSubmit}
              className="flex-1 bg-sky-500 hover:bg-sky-400 text-white font-semibold py-3 rounded-xl text-sm transition-colors"
            >
              Confirm & Submit
            </button>
            <button
              onClick={handleReset}
              className="flex-1 bg-zinc-800 hover:bg-zinc-700 text-zinc-300 font-semibold py-3 rounded-xl text-sm transition-colors"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {phase === 'submitting' && (
        <div className="flex flex-col items-center gap-3 py-10">
          <Spinner size={32} />
          <p className="text-zinc-400 text-sm">Submitting…</p>
        </div>
      )}

      {phase === 'done' && result && (
        <div className="space-y-3">
          <div className="text-green-400 text-sm bg-green-950/40 border border-green-800 rounded-xl p-4">
            <p className="font-medium">Thread submitted!</p>
            <p className="text-green-300 text-xs mt-1">Score {result.score?.toFixed(1)}</p>
            <Link to={`/?thread=${result.thread_id}`} className="underline text-sky-400 text-xs">
              View on leaderboard
            </Link>
          </div>
          <button
            onClick={handleReset}
            className="w-full bg-zinc-800 hover:bg-zinc-700 text-zinc-300 font-medium py-2.5 rounded-xl text-sm transition-colors"
          >
            Submit another
          </button>
        </div>
      )}

      {error && (
        <div className="text-red-400 text-sm bg-red-950/40 border border-red-800 rounded-xl p-3">{error}</div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Add the public route in `App.jsx`**

In `thread-helper/frontend/src/App.jsx`:
- Add import: `import SubmitPage from './pages/SubmitPage';`
- Add a public route inside `<Routes>` (after the `/` route):

```jsx
          <Route path="/submit" element={<SubmitPage />} />
```

(Leave `/add` as the authenticated route — it stays gated.)

- [ ] **Step 5: Add the nav entry in `Layout.jsx`**

In `thread-helper/frontend/src/components/Layout.jsx`:
- Change the lucide import to include `Send`: `import { Trophy, PlusCircle, Settings, User, Send } from 'lucide-react';`
- Add to the `nav` array, after the Leaderboard entry:

```javascript
    { to: '/submit', label: 'Submit', Icon: Send, always: true },
```

- [ ] **Step 6: Build and smoke-test**

Run: `cd thread-helper/frontend && npm install && npm run build`
Expected: build completes with no errors.

Manual smoke (optional, needs backend with a stored token + `npm run dev`): visit `/submit` while logged out → paste a URL → see preview card + estimated score → Confirm → see confirmed score; submit the same URL again → "already submitted" message.

- [ ] **Step 7: Commit**

```bash
git add thread-helper/frontend/src/api.js thread-helper/frontend/src/pages/SubmitPage.jsx thread-helper/frontend/src/App.jsx thread-helper/frontend/src/components/Layout.jsx thread-helper/frontend/vite.config.js
git commit -m "feat(DEV-25): public SubmitPage with preview→confirm flow"
```

---

## Final verification

- [ ] `cd core && uv run pytest` → all pass.
- [ ] `cd thread-helper/backend && uv run pytest` → all pass.
- [ ] `cd thread-helper/frontend && npm run build` → succeeds.
- [ ] Confirm against DEV-25 acceptance criteria (below).

## Acceptance criteria mapping

- Anyone (no login) can paste an X URL and submit → Task 5 (`POST /submit`, no auth dep) + Task 6 (public page).
- `ON_SUBMISSION` fires before storage; extensions can reject → Task 5 (rejection → 403, tested).
- Duplicate post IDs detected and returned gracefully → Task 2 + Tasks 4/5 (`status: duplicate`, not re-stored, tested).
- Rate limiting per IP → Tasks 4/5 (`@limiter.limit(settings.rate_limit_submissions)`).
- Full post object with `public_metrics` fetched via app X client → Tasks 3–5.
- `analyze_post_engagement()` called; `None` fallback → Task 5 (tested).
- `upsert_post_data(tweet, low, weights=contest_weights)` called → Task 5.
- End-to-end URL→thread→score→response → Task 5 (tested).
- Authenticated suspended users → 403; anonymous not blocked → Tasks 3–5 (`get_optional_user` + `_reject_if_suspended`, tested).
- Old auth-gated endpoints remain; `/submit` is the public default → `/submissions/*` untouched; full suite stays green.

# DEV-25 — Public paste-URL submission form + basic duplicate detection

**Linear:** [DEV-25](https://linear.app/jird-labs/issue/DEV-25/public-paste-url-submission-form-basic-duplicate-detection)
**Branch:** `jird/dev-25-public-paste-url-submission-form-basic-duplicate-detection`
**Date:** 2026-06-25

## Goal

Let anyone — with no X login — paste an X post URL and submit it as a thread into
the active contest. Detect duplicate post IDs and return the existing thread
instead of re-storing. Authenticated submission (participants connecting their own
X account for private metrics) remains a separate premium flow (DEV-31) and is left
untouched.

## Context

- **Foundation library** `core/src/shilljudge_core/` and **app backend**
  `thread-helper/backend/` keep *duplicate copies* of `database.py` / `models.py` /
  `hooks.py`. Every DB-layer change here is mirrored in both.
- Blockers are already satisfied in-repo: rate limiting (DEV-18,
  `settings.rate_limit_submissions`, slowapi), `participation_status` on `users`
  (DEV-21), active contest + per-metric weights (DEV-22).
- The existing submission endpoints `POST /submissions/preview` and
  `POST /submissions/confirm` are **auth-gated** (require X OAuth login and only
  allow submitting your *own* posts). They stay as-is for the premium flow.
- The background poller already builds an app-level X client from a *stored* token
  without a logged-in request: `_select_poller_x_id()` (prefer admin, else most
  recently refreshed) + `_poll_client()` (builds client, persists refreshed token
  on exit). The public endpoints reuse this.

## Decisions (resolved during brainstorming)

1. **Two-call flow**: `POST /submit/preview` (read-only, returns post + estimated
   score, no thread created) followed by `POST /submit` (authoritative, creates the
   thread). Chosen over single-shot to support "preview before final submit".
2. **New `SubmitPage.jsx`** mounted on a public route; `App.jsx` adjusted so
   leaderboard + submit are reachable without login. The existing authenticated
   `AddPostsPage.jsx` is left unchanged.

## Architecture

### 1. App-level X client dependency

Add a FastAPI dependency `get_app_x_client()` in `app.py` that reuses the poller's
token selection:

- Pick a stored token via the same query as `_select_poller_x_id()` (admin first,
  else most recently refreshed).
- Build the client with `build_user_client(settings, token)`; persist a refreshed
  token on exit (mirrors `_poll_client` / `get_x_client_for_user`).
- If no usable token is stored → raise `HTTPException(503, ...)` — "submission
  temporarily unavailable (no connected X app credentials)".

Refactor `_poll_client()` and this dependency to share one selection/persistence
helper to avoid divergence.

### 2. Backend endpoints

Both take body `{ "url": "..." }` (reuse existing `PreviewSubmissionRequest`), both
decorated `@limiter.limit(settings.rate_limit_submissions)` (default 10/min per IP),
both anonymous-friendly (no `Depends(get_current_user)`).

**`POST /submit/preview`** — read-only, never stores:

1. `post_id = parse_post_id(body.url)`; `422` if `None`.
2. Suspended guard (§4).
3. Duplicate check (§3): if found, return
   `{ "status": "duplicate", "existing_thread_id": <id> }`.
4. Fetch the post via the app client
   (`x_client.posts.get_by_id(id=post_id, tweet_fields=DEFAULT_TWEET_FIELDS,
   expansions=["author_id"], user_fields=["id","username","public_metrics"])`);
   `404` if the post is missing, `502` on X HTTP error.
5. Compute an **estimated score** with `score_post(metrics, low=None,
   weights=active_contest_weights)` (the low-follower analysis is skipped here to
   keep preview cheap — the estimate is a base figure).
6. Return `{ "status": "ok", "post": <tweet>, "estimated_score": <float> }`.

**`POST /submit`** — authoritative, creates the thread:

1. `post_id = parse_post_id(body.url)`; `422` if `None`.
2. Suspended guard (§4).
3. `result = registry.call(ON_SUBMISSION, [post_id], {"ip": request.client.host})`.
   `ON_SUBMISSION` is a pipeline hook threading arg 0 (the id list). If `result` is
   empty/falsy, a premium extension rejected the submission → `403`
   `{ "error": "submission_rejected" }`. Open-core has no handler, so this is a
   pass-through returning `[post_id]`.
4. Duplicate check (§3): if found, return
   `{ "status": "duplicate", "existing_thread_id": <id> }` (authoritative — also
   guards the preview→submit race).
5. Fetch the full post via the app client (same call as preview).
   `low = analyze_post_engagement(x_client, post_id)` → `int | None` (falls back to
   `None` on any API failure).
6. `upsert_post_data(tweet_dict, low, weights=active_contest_weights)` then
   `create_thread([post_id])`.
7. Return `{ "status": "ok", "thread_id": <id>, "score": <float> }` (score read back
   via `get_thread_score`/the created thread's total).

`active_contest_weights` is `get_active_contest()` (the contest dict carries the
`weight_*` keys, consistent with the existing confirm endpoint).

### 3. Duplicate detection — new DB function (mirrored in both copies)

```python
def find_active_contest_thread_for_post(post_id: str) -> int | None:
    """Return the thread_id of a thread in the *active* contest that already
    contains post_id, or None. Used to detect duplicate submissions."""
```

Query joins `thread_posts → threads` where `threads.contest_id` is the active
contest id and `thread_posts.post_id = ?`; returns the first `thread_id` or `None`.
Added to both `core/src/shilljudge_core/database.py` and
`thread-helper/backend/database.py` and exported.

### 4. Suspended-session guard

Best-effort, applies only when an optional X session exists (no reliable IP→user
mapping for anonymous traffic):

```python
x_id = request.session.get("x_id")
if x_id:
    u = get_user(x_id)
    if u and u.get("participation_status") == "suspended":
        raise HTTPException(403, {"error": "suspended", ...})
```

Applied to **both** endpoints so a suspended user is rejected at preview, not only at
submit. Fully anonymous submissions pass through.

### 5. Pure scoring helper (small refactor, mirrored in both copies)

Extract the scoring formula currently inline in `upsert_post_data` into:

```python
def score_post(metrics: dict, low_follower_engagements: int | None,
               weights: dict | None) -> tuple[float, float]:
    """Return (score, ratio) for a post's public_metrics under the given contest
    weights. Pure: no DB access, no hook dispatch."""
```

`upsert_post_data` calls `score_post(...)` and keeps its existing
`CALCULATE_SCORE` hook dispatch and persistence — observable behavior unchanged
(guarded by the existing `test_default_weights_match_base_formula` and
`test_calculate_score_hook_applied`). `/submit/preview` calls `score_post` directly
for the estimate, so preview and confirm scoring stay identical.

### 6. Frontend

- **`SubmitPage.jsx`** (new): single URL paste box. `submitPreview(url)` →
  - `status: "ok"` → render a `TweetPreviewCard` (reused) + estimated score, with a
    "Confirm & submit" button.
  - `status: "duplicate"` → message + link to the existing thread.
  - On confirm, `submitThread(url)` → show confirmed score (and link to the new
    thread). Handle `422` (invalid URL), `503` (unavailable), `403`
    (suspended/rejected), `429` (rate limit) with friendly messages.
- **`api.js`**: add `submitPreview(url)` → `POST /submit/preview`, `submitThread(url)`
  → `POST /submit`.
- **`App.jsx`**: leaderboard + submit reachable without login (no AuthPage wall for
  these routes). Login remains required for the authenticated/premium pages.
- **`Layout.jsx`**: add a nav entry for the public submit page. Vite proxy already
  forwards `/threads`/`/post`; add `/submit` to the proxied prefixes.
- `AddPostsPage.jsx` unchanged.

## Testing (TDD)

**core (`cd core && uv run pytest`):**

- `score_post` returns the base formula at default (all-1.0) weights and matches
  prior `upsert_post_data` outputs; weighted inputs scale correctly; `low=None`
  treated as 0.
- `find_active_contest_thread_for_post` returns the thread id for a post in the
  active contest, `None` for an unknown post or a post only in a non-active contest.

**thread-helper backend (`cd backend && uv run pytest`):**

- `POST /submit` happy path: URL in → post stored → thread created → score returned.
- Invalid URL → `422`.
- Duplicate post id → `{status: "duplicate", existing_thread_id}` and **not**
  re-stored (no second thread).
- Suspended authenticated session → `403`; anonymous → allowed.
- No stored app token → `503`.
- `ON_SUBMISSION` rejection (test-registered handler returning `[]`) → `403`.
- `analyze_post_engagement` failure → `low=None`, submission still succeeds.
- `POST /submit/preview`: returns post + estimated_score; duplicate short-circuit;
  invalid URL `422`. X API calls are mocked/stubbed (no live network).

## Out of scope

- Authenticated participant portal / private metrics (DEV-31).
- Self-reply chain concatenation / multi-post threads (DEV-23) — `/submit` handles a
  single post id.
- Any change to the existing auth-gated `/submissions/*` endpoints.

## Acceptance criteria (from DEV-25)

- [ ] Anyone (no login) can paste an X URL and submit a thread.
- [ ] `ON_SUBMISSION` fires before storage; extensions can validate/reject.
- [ ] Duplicate post IDs detected and returned gracefully (not re-stored).
- [ ] Rate limiting enforced per IP.
- [ ] Full post object (with `public_metrics`) fetched via the app's X client.
- [ ] `analyze_post_engagement()` called; falls back to `None` on failure.
- [ ] `upsert_post_data(tweet_dict, low_count, weights=contest_weights)` called.
- [ ] End-to-end: URL in → thread stored → score computed → response returned.
- [ ] Authenticated suspended users get `403`; anonymous not blocked.
- [ ] Old auth-gated endpoints remain; `POST /submit` is the public default.

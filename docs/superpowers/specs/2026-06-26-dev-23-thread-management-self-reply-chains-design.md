# DEV-23 — Manual thread/post management + self-reply chain concatenation — Design

**Date:** 2026-06-26
**Status:** Approved (design); decisions locked
**Linear:** DEV-23 (blocked-by DEV-25, which is complete)

## Context: the issue predates the monorepo migration

The DEV-23 issue was written against the old `thread-helper/backend` layout and references routes that no longer exist (`POST /posts/preview`, `POST /threads`, `DELETE /posts/{post_id}`). After the unify-monorepo migration the backend lives in `app/` and imports `shilljudge_core`. Mapping the issue onto current code, several items are **already done**:

- `DELETE /posts/{post_id}` → exists as `DELETE /manage/post/{post_id}` backed by `delete_post()`.
- Delete-Post button in `ManagePage.jsx` → exists (per-post trash in the `UserThreads` panel).
- "create thread from a list of post IDs" → `POST /submissions/confirm` already concatenates a list into a single thread and already collects per-post X errors gracefully.
- `parse_post_id` → already in core.

## Locked decisions

1. **ENRICH_THREAD dispatch lives inside core `create_thread()`** — every thread-creation path is enriched exactly once, mirroring how `CALCULATE_SCORE` already lives inside core's `upsert_post_data`. (Q1 = A)
2. **Self-reply chains are detected client-side in `AddPostsPage.jsx`** — the backend only exposes reply metadata on the preview payload; the frontend (which already holds every preview) groups parent→reply, indents the reply, and orders parent-first. `/submissions/confirm` already turns the list into one thread. (Q2 = A)
3. **Deleted-post graceful handling is scoped to the authenticated `/submissions/preview`** (the multi-paste flow) so one dead tweet does not abort the whole batch. Public single-post `/submit` + `/submit/preview` keep their `404` (a single dead post there is terminal). `/submissions/confirm` already tolerates batch errors. (Q3 = A)
4. **Admin thread-delete route is `DELETE /manage/thread/{thread_id}`** — follows the existing `/manage/*` admin convention (`/manage/post`, `/manage/user`, `/manage/contests`), not the issue's literal `/threads/{thread_id}`.

## X API reality (corrects the issue)

The issue's chain logic references an `in_reply_to_post_id` field. **That field does not exist** in the X v2 API. `in_reply_to_user_id` is a real tweet field; the replied-to *post* id is only available via the `referenced_tweets` array (the entry whose `type == "replied_to"`). Therefore:

- Add both `in_reply_to_user_id` and `referenced_tweets` to `DEFAULT_TWEET_FIELDS`.
- Derive `in_reply_to_post_id` from `referenced_tweets` in a small pure helper, and surface `in_reply_to_user_id` + the derived `in_reply_to_post_id` on the preview payload.

Chain rule (unchanged in spirit): posts **A** and **B** form one chain when B's `in_reply_to_user_id == B.author_id` (self-reply) and B's `in_reply_to_post_id == A.id`.

## Work breakdown

### 1. core — `enrich_thread` + `delete_thread`
- `create_thread()` returns `registry.call(ENRICH_THREAD, thread_dict)` so the assembled thread runs through the hook. Default behavior unchanged when no handler is registered (pipeline passthrough). The community meme-scorer ext registers an `enrich_thread` handler, giving an end-to-end test.
- Add `delete_thread(thread_id: int) -> bool` (deletes `thread_posts` + `thread_scores` + `threads`; returns whether a thread row was removed). Distinct from `delete_post()`.

### 2. app — reply metadata, deleted marker, admin thread delete
- `x_client.DEFAULT_TWEET_FIELDS` += `in_reply_to_user_id`, `referenced_tweets`.
- Pure helper `reply_meta(tweet) -> {in_reply_to_user_id, in_reply_to_post_id}` (derives parent id from `referenced_tweets`).
- `/submissions/preview`: include reply metadata on the returned `post`; when X returns no data for the id, return `{"status": "deleted", "post_id": …}` (+ `logger.warning`) instead of 404.
- `DELETE /manage/thread/{thread_id}` (admin-gated) → `delete_thread()`, 404 when absent.

### 3. frontend — chain visual + admin thread delete
- `api.js`: `deleteThread(threadId)`; preview already returns the post with the new fields.
- `AddPostsPage.jsx`: detect self-reply chains among previews, order parent-first, render the reply with a `↳ reply` indicator and indentation; handle `status: "deleted"` previews (show a "deleted" card, exclude from submission).
- `ManagePage.jsx`: thread-level Delete button (with confirm) in `UserThreads`, removing the thread from state.

## Out of scope
- Real premium enrich handlers (DeepSeek AI review, bot filter) — those are separate premium-repo extensions; this only guarantees the hook fires.
- Auto-fetching a chain's missing parent posts the user didn't paste.

## Verification
- `cd core && uv run pytest` — green (new `delete_thread` + `enrich_thread` dispatch tests).
- `cd app && uv run python -m pytest` — green (reply-meta, deleted-marker, thread-delete tests).
- `cd frontend && npm run build` — succeeds.

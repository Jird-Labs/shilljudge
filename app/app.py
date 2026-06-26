from __future__ import annotations

import copy
import logging
import os
import time
from collections.abc import Generator
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timezone
from itertools import batched
from typing import Annotated, Any

import requests
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.middleware.sessions import SessionMiddleware
from xdk import Client
from xdk.oauth2_auth import OAuth2PKCEAuth

from auth import get_current_user, get_optional_user, get_x_client_for_user, require_admin
from config import get_settings
from shilljudge_core.database import (
    clear_thread_score_override,
    create_contest,
    create_thread,
    delete_contest,
    delete_post,
    delete_user_data,
    find_active_contest_thread_for_post,
    get_active_contest,
    get_all_contests,
    get_all_users,
    get_connection,
    get_contest,
    get_contest_thread_ids,
    get_leaderboard,
    get_thread,
    get_thread_post_ids,
    get_thread_score,
    get_unenriched_user_ids,
    get_user,
    get_user_threads,
    init_db,
    insert_metric_snapshot,
    recompute_thread_total_score,
    score_post,
    set_thread_score_override,
    set_user_admin,
    set_user_participation,
    set_wallet,
    update_contest,
    upsert_post_data,
    upsert_user_data,
    upsert_user_profile,
    WEIGHT_COLUMNS,
)
from engagement import analyze_post_engagement
from shilljudge_core.hooks import ENRICH_LEADERBOARD, ON_SUBMISSION, registry
from shilljudge_core.models import (
    ConfirmSubmissionRequest,
    CreateContestRequest,
    PreviewSubmissionRequest,
    UpdateContestRequest,
    WalletRequest,
)
from schemas import OverrideScoreRequest, UpdateUserRequest
from scheduler import get_poll_status, start_scheduler, stop_scheduler
from solana_client import SolanaCheckError, check_wallet_staked
from shilljudge_core.token_storage import load_user_token, save_user_token
from shilljudge_core.utils import parse_post_id
from x_client import DEFAULT_TWEET_FIELDS, DEFAULT_USER_FIELDS, build_user_client, _tokens_differ

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO").upper())
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _settings = get_settings()
    missing = [v for v in ("X_CLIENT_ID", "X_CLIENT_SECRET", "SESSION_SECRET") if not getattr(_settings, v.lower(), None)]
    if missing:
        raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")
    init_db()
    if os.environ.get("SEED_DB") == "1":
        try:
            from shilljudge_core.seed import seed_db
            seed_db()
        except ImportError:
            pass
    # Deferred import: keeps extension loading out of module-level import scope and avoids loading the loader until startup.
    from extensions_loader import load_app_extensions
    loaded = load_app_extensions()
    logger.info("Loaded %d extension(s): %s", len(loaded), [m.get("name") for m in loaded])
    interval = max(_settings.poll_interval_seconds, 300)
    start_scheduler(_poll_client, interval)
    try:
        yield
    finally:
        stop_scheduler()


app = FastAPI(title="thread-helper backend", lifespan=lifespan)

settings = get_settings()

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    same_site="lax",
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - start) * 1000
    logger.info("%s %s %d %.1fms", request.method, request.url.path, response.status_code, duration_ms)
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    if isinstance(exc, HTTPException):
        raise exc
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


def _select_poller_x_id() -> str | None:
    """Pick whose stored token the background poller should use: prefer an admin,
    else the most recently refreshed token. Returns None if no token is stored."""
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT t.x_id
            FROM oauth_tokens t
            JOIN users u ON t.x_id = u.x_id
            ORDER BY u.is_admin DESC, t.updated_at DESC
            LIMIT 1
            """
        ).fetchone()
        return row["x_id"] if row else None


@contextmanager
def _poll_client():
    """Yield an authenticated X client for the background poller, or None when no
    usable token exists yet. Persists a refreshed token on exit (mirrors
    get_x_client_for_user)."""
    x_id = _select_poller_x_id()
    token = load_user_token(x_id) if x_id else None
    if not x_id or not token or not token.get("access_token"):
        yield None
        return
    client = build_user_client(settings, token)
    token_before = copy.deepcopy(client.token)
    try:
        yield client
    finally:
        token_after = client.token
        if _tokens_differ(token_before, token_after) and token_after:
            save_user_token(x_id, token_after)


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


def _enrich_users(x_client: Client) -> None:
    ids = get_unenriched_user_ids()
    if not ids:
        return
    for chunk in batched(ids, 100):
        try:
            resp = x_client.users.get_by_ids(ids=list(chunk), user_fields=DEFAULT_USER_FIELDS)
        except requests.HTTPError:
            return
        if not getattr(resp, "data", None):
            continue
        for user in resp.data:
            data = user.model_dump() if hasattr(user, "model_dump") else user
            if isinstance(data, dict) and data.get("id"):
                upsert_user_data(data)


def _enforce_stake_gate(user: dict[str, Any]) -> None:
    contest = get_active_contest()
    if not contest or not contest.get("must_stake_token"):
        return
    wallet = user.get("wallet_address")
    if not wallet:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "wallet_required",
                "message": "This contest requires staking. Set your Solana wallet address in your profile first.",
            },
        )
    try:
        staked = check_wallet_staked(wallet)
    except SolanaCheckError as e:
        raise HTTPException(
            status_code=503,
            detail={"error": "stake_check_unavailable", "message": str(e)},
        ) from e
    if not staked:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "stake_required",
                "message": "This contest requires staking the contest token.",
            },
        )
    # Update cached stake status
    now = datetime.now(timezone.utc).isoformat()
    set_wallet(user["x_id"], wallet, True, now)


def _contest_weights(contest: dict[str, Any] | None) -> dict[str, Any]:
    """Extract the weight_* keys from a contest row (empty dict → base scoring)."""
    if not contest:
        return {}
    return {k: v for k, v in contest.items() if k.startswith("weight_")}


def _rescore_thread(x_client: Client, thread_id: int, weights: dict[str, Any]) -> float:
    """Re-fetch every post in a thread from X (same two-step fetch as the poller),
    re-score with ``weights``, append a metric-history snapshot, then recompute and
    return the thread's new total score."""
    now = datetime.now(timezone.utc).isoformat()
    for post_id in get_thread_post_ids(thread_id):
        try:
            resp = x_client.posts.get_by_id(
                id=post_id,
                tweet_fields=DEFAULT_TWEET_FIELDS,
                expansions=["author_id"],
                user_fields=["id", "username", "public_metrics"],
            )
        except requests.HTTPError as e:
            raise HTTPException(status_code=502, detail=f"Failed to fetch post {post_id} from X.") from e
        result = resp.model_dump() if hasattr(resp, "model_dump") else resp
        tweet = result.get("data") if isinstance(result, dict) else None
        if not tweet or not tweet.get("id"):
            continue
        low = analyze_post_engagement(x_client, post_id)
        upsert_post_data(tweet, low, weights=weights)
        insert_metric_snapshot(tweet, now)
    return recompute_thread_total_score(thread_id)


# ── Health ──────────────────────────────────────────────────────────────────

@app.get("/status")
async def poll_status() -> dict[str, Any]:
    """Background poller health (public). Returns status, rate_limited_until, last_poll_at."""
    return get_poll_status()


# ── Auth ─────────────────────────────────────────────────────────────────────

@app.get("/auth/status")
async def auth_status(request: Request) -> dict[str, Any]:
    x_id = request.session.get("x_id")
    if not x_id:
        return {"authenticated": False, "x_id": None, "x_username": None, "is_admin": False,
                "wallet_address": None, "stake_verified": False}
    user = get_user(x_id)
    if not user:
        request.session.clear()
        return {"authenticated": False, "x_id": None, "x_username": None, "is_admin": False,
                "wallet_address": None, "stake_verified": False}
    return {
        "authenticated": True,
        "x_id": x_id,
        "x_username": user.get("x_username"),
        "is_admin": bool(user.get("is_admin")),
        "wallet_address": user.get("wallet_address"),
        "stake_verified": bool(user.get("stake_verified")),
    }


@app.post("/auth/logout")
async def auth_logout(request: Request) -> dict[str, bool]:
    request.session.clear()
    return {"ok": True}


@app.get("/oauth/login")
@limiter.limit(settings.rate_limit_auth)
async def oauth_login(request: Request) -> RedirectResponse:
    auth = OAuth2PKCEAuth(
        client_id=settings.x_client_id,
        client_secret=settings.x_client_secret,
        redirect_uri=settings.x_redirect_uri,
        scope=settings.oauth_scope_list,
    )
    auth_url = auth.get_authorization_url()
    verifier = auth.get_code_verifier()
    if not verifier:
        raise HTTPException(status_code=500, detail="PKCE verifier missing after get_authorization_url()")
    request.session["x_oauth_code_verifier"] = verifier
    return RedirectResponse(auth_url, status_code=302)


@app.get("/oauth/callback")
async def oauth_callback(
    request: Request,
    code: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    if error:
        raise HTTPException(status_code=400, detail={"error": error})
    if not code:
        raise HTTPException(status_code=400, detail="Missing code query parameter")

    verifier = request.session.pop("x_oauth_code_verifier", None)
    if not verifier:
        raise HTTPException(
            status_code=400,
            detail=(
                "Missing OAuth session (PKCE verifier). "
                "Visit /oauth/login in this same browser first."
            ),
        )

    auth = OAuth2PKCEAuth(
        client_id=settings.x_client_id,
        client_secret=settings.x_client_secret,
        redirect_uri=settings.x_redirect_uri,
        scope=settings.oauth_scope_list,
    )
    auth.set_pkce_parameters(verifier)
    try:
        token = auth.exchange_code(code)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    client = build_user_client(settings, token)
    try:
        me_resp = client.users.get_me(user_fields=DEFAULT_USER_FIELDS)
    except requests.HTTPError as e:
        raise HTTPException(status_code=502, detail="Failed to fetch user profile from X.") from e

    me = me_resp.data
    me_data = me.model_dump() if hasattr(me, "model_dump") else me
    x_id = me_data.get("id") or (me_data.get("data", {}) or {}).get("id")
    if not x_id:
        raise HTTPException(status_code=502, detail="Could not determine X user ID from token.")

    # Flatten nested data if necessary
    if "data" in me_data and isinstance(me_data["data"], dict):
        me_data = me_data["data"]

    me_data["id"] = x_id
    upsert_user_profile(me_data)
    if len(get_all_users()) == 1:
        set_user_admin(x_id, True)
    save_user_token(x_id, client.token or token)
    request.session["x_id"] = x_id
    return RedirectResponse(settings.frontend_url, status_code=302)


# ── Leaderboard (public) ──────────────────────────────────────────────────────

@app.get("/leaderboard")
@limiter.limit(settings.rate_limit_leaderboard)
async def leaderboard(
    request: Request,
    sort: str = "score",
    dir: str = "desc",
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    """Public, rate-limited leaderboard. The threads rail is sortable (``sort`` +
    ``dir``) and paginated (``limit`` capped at 100, ``offset``); each thread row
    is routed through the ENRICH_LEADERBOARD hook so premium extensions can append
    columns (no-op when none are loaded)."""
    data = get_leaderboard(sort_by=sort, sort_dir=dir, limit=min(limit, 100), offset=offset)
    data["threads"] = registry.call(ENRICH_LEADERBOARD, data["threads"])
    return data


# ── Profile / wallet ──────────────────────────────────────────────────────────

@app.put("/me/wallet")
async def update_wallet(
    body: WalletRequest,
    user: Annotated[dict, Depends(get_current_user)],
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    staked = False
    check_error = None
    try:
        staked = check_wallet_staked(body.wallet_address)
    except SolanaCheckError as e:
        check_error = str(e)
    set_wallet(user["x_id"], body.wallet_address, staked, now)
    result: dict[str, Any] = {
        "wallet_address": body.wallet_address,
        "stake_verified": staked,
        "stake_checked_at": now,
    }
    if check_error:
        result["check_error"] = check_error
    return result


@app.post("/me/wallet/recheck")
async def recheck_wallet(
    user: Annotated[dict, Depends(get_current_user)],
) -> dict[str, Any]:
    wallet = user.get("wallet_address")
    if not wallet:
        raise HTTPException(status_code=400, detail={"error": "no_wallet", "message": "No wallet address on file."})
    now = datetime.now(timezone.utc).isoformat()
    staked = False
    check_error = None
    try:
        staked = check_wallet_staked(wallet)
    except SolanaCheckError as e:
        check_error = str(e)
    set_wallet(user["x_id"], wallet, staked, now)
    result: dict[str, Any] = {
        "wallet_address": wallet,
        "stake_verified": staked,
        "stake_checked_at": now,
    }
    if check_error:
        result["check_error"] = check_error
    return result


# ── Submissions (preview + confirm) ──────────────────────────────────────────

@app.post("/submissions/preview")
@limiter.limit(settings.rate_limit_submissions)
async def preview_submission(
    request: Request,
    body: PreviewSubmissionRequest,
    user: Annotated[dict, Depends(get_current_user)],
    x_client: Annotated[Client, Depends(get_x_client_for_user)],
) -> dict[str, Any]:
    post_id = parse_post_id(body.url)
    if not post_id:
        raise HTTPException(status_code=422, detail="Invalid X post URL or ID.")

    try:
        resp = x_client.posts.get_by_id(id=post_id, tweet_fields=DEFAULT_TWEET_FIELDS)
    except requests.HTTPError as e:
        raise HTTPException(status_code=502, detail="Failed to fetch post from X.") from e

    result = resp.model_dump() if hasattr(resp, "model_dump") else resp
    tweet = result.get("data") if isinstance(result, dict) else None
    if not tweet or not tweet.get("id"):
        raise HTTPException(status_code=404, detail="Post not found on X.")

    if tweet.get("author_id") != user["x_id"]:
        raise HTTPException(
            status_code=403,
            detail={"error": "not_your_post", "message": "You can only submit your own posts."},
        )

    author = {
        "x_id": user["x_id"],
        "x_username": user.get("x_username"),
        "name": user.get("name"),
        "profile_image_url": user.get("profile_image_url"),
    }
    return {"post": tweet, "author": author}


@app.post("/submissions/confirm")
@limiter.limit(settings.rate_limit_submissions)
async def confirm_submission(
    request: Request,
    body: ConfirmSubmissionRequest,
    user: Annotated[dict, Depends(get_current_user)],
    x_client: Annotated[Client, Depends(get_x_client_for_user)],
) -> dict[str, Any]:
    _enforce_stake_gate(user)

    seen: set[str] = set()
    unique_ids: list[str] = []
    for pid in body.post_ids:
        if pid not in seen:
            seen.add(pid)
            unique_ids.append(pid)

    all_data: list[Any] = []
    all_errors: list[Any] = []

    try:
        for chunk in batched(unique_ids, 100):
            resp = x_client.posts.get_by_ids(ids=list(chunk), tweet_fields=DEFAULT_TWEET_FIELDS)
            if getattr(resp, "data", None):
                for item in resp.data:
                    all_data.append(item.model_dump() if hasattr(item, "model_dump") else item)
            if getattr(resp, "errors", None):
                for err in resp.errors:
                    all_errors.append(err.model_dump() if hasattr(err, "model_dump") else err)
    except requests.HTTPError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e

    for tweet in all_data:
        if isinstance(tweet, dict) and tweet.get("author_id") != user["x_id"]:
            raise HTTPException(
                status_code=403,
                detail={"error": "not_your_post", "message": f"Post {tweet.get('id')} does not belong to you."},
            )

    # Score against the active contest's metric weights (the contest dict carries weight_* keys).
    weights = get_active_contest()

    unanalyzed: list[str] = []
    for tweet in all_data:
        if isinstance(tweet, dict) and tweet.get("id"):
            low = analyze_post_engagement(x_client, tweet["id"])
            if low is None:
                unanalyzed.append(tweet["id"])
            upsert_post_data(tweet, low_follower_engagements=low, weights=weights)

    _enrich_users(x_client)
    fetched_ids = [t["id"] for t in all_data if isinstance(t, dict) and t.get("id")]

    if not fetched_ids:
        raise HTTPException(status_code=422, detail="None of the provided posts could be fetched from X.")

    thread = create_thread(fetched_ids)

    return {
        "thread_id": thread["thread_id"],
        "post_count": thread["post_count"],
        "total_score": thread["total_score"],
        "fetched": len(fetched_ids),
        "errors": all_errors,
        "unanalyzed": unanalyzed,
    }


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

    contest = get_active_contest()
    if contest is None:
        raise HTTPException(
            status_code=409,
            detail={"error": "no_active_contest", "message": "No active contest is accepting submissions right now."},
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
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail="Failed to fetch post from X.") from e

    result = resp.model_dump() if hasattr(resp, "model_dump") else resp
    tweet = result.get("data") if isinstance(result, dict) else None
    if not tweet or not tweet.get("id"):
        raise HTTPException(status_code=404, detail="Post not found on X.")

    estimated_score, _ = score_post(tweet.get("public_metrics") or {}, None, contest)
    return {"status": "ok", "post": tweet, "estimated_score": estimated_score}


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

    contest = get_active_contest()
    if contest is None:
        raise HTTPException(
            status_code=409,
            detail={"error": "no_active_contest", "message": "No active contest is accepting submissions right now."},
        )

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
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail="Failed to fetch post from X.") from e

    result = resp.model_dump() if hasattr(resp, "model_dump") else resp
    tweet = result.get("data") if isinstance(result, dict) else None
    if not tweet or not tweet.get("id"):
        raise HTTPException(status_code=404, detail="Post not found on X.")

    low = analyze_post_engagement(x_client, post_id)
    upsert_post_data(tweet, low_follower_engagements=low, weights=contest)
    thread = create_thread([tweet["id"]])

    return {"status": "ok", "thread_id": thread["thread_id"], "score": thread["total_score"]}


# ── Individual post (authenticated) ──────────────────────────────────────────

@app.get("/post/{post_id}")
async def get_post(
    post_id: str,
    user: Annotated[dict, Depends(get_current_user)],
    x_client: Annotated[Client, Depends(get_x_client_for_user)],
) -> dict[str, Any]:
    try:
        post = x_client.posts.get_by_id(id=post_id, tweet_fields=DEFAULT_TWEET_FIELDS)
    except requests.HTTPError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    result = post.model_dump() if hasattr(post, "model_dump") else post
    tweet = result.get("data") if isinstance(result, dict) else None
    if tweet and tweet.get("id"):
        # Recompute against the current active contest's weights, not whatever they were at submission.
        upsert_post_data(tweet, weights=get_active_contest())
        _enrich_users(x_client)
    return result  # type: ignore[return-value]


# ── Admin: contests ───────────────────────────────────────────────────────────

@app.get("/manage/contests")
async def manage_contests(
    admin: Annotated[dict, Depends(require_admin)],
) -> list[dict]:
    return get_all_contests()


@app.post("/manage/contests")
async def manage_create_contest(
    body: CreateContestRequest,
    admin: Annotated[dict, Depends(require_admin)],
) -> dict[str, Any]:
    try:
        return create_contest(
            body.title, body.description, body.start_date, body.end_date,
            body.must_stake_token, body.prize, body.thread_length, body.status,
            weights={col: getattr(body, col) for col in WEIGHT_COLUMNS},
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@app.put("/manage/contests/{contest_id}")
async def manage_update_contest(
    contest_id: int,
    body: UpdateContestRequest,
    admin: Annotated[dict, Depends(require_admin)],
) -> dict[str, Any]:
    fields = body.model_dump(exclude_none=True)
    if "must_stake_token" in fields:
        fields["must_stake_token"] = int(fields["must_stake_token"])
    try:
        result = update_contest(contest_id, fields)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    if result is None:
        raise HTTPException(status_code=404, detail="Contest not found.")
    return result


@app.delete("/manage/contests/{contest_id}")
async def manage_delete_contest(
    contest_id: int,
    admin: Annotated[dict, Depends(require_admin)],
) -> dict[str, bool]:
    deleted = delete_contest(contest_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Contest not found.")
    return {"ok": True}


# ── Admin: users ──────────────────────────────────────────────────────────────

@app.get("/manage/users")
async def manage_users(
    admin: Annotated[dict, Depends(require_admin)],
    q: str | None = None,
) -> list[dict]:
    return get_all_users(q)


@app.patch("/manage/user/{x_id}")
async def manage_update_user(
    x_id: str,
    body: UpdateUserRequest,
    admin: Annotated[dict, Depends(require_admin)],
) -> dict[str, Any]:
    if x_id == admin["x_id"] and body.is_admin is False:
        raise HTTPException(
            status_code=403,
            detail={"error": "self_demotion", "message": "Cannot revoke your own admin status."},
        )
    if not get_user(x_id):
        raise HTTPException(status_code=404, detail="User not found")
    if body.is_admin is not None:
        set_user_admin(x_id, body.is_admin)
    if body.participation_status is not None:
        set_user_participation(x_id, body.participation_status)
    return get_user(x_id)  # type: ignore[return-value]


@app.delete("/manage/user/{x_id}")
async def manage_delete_user(
    x_id: str,
    admin: Annotated[dict, Depends(require_admin)],
) -> dict[str, Any]:
    deleted = delete_user_data(x_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="User not found")
    return {"ok": True, "deleted_x_id": x_id}


@app.get("/manage/user/{x_id}/threads")
async def manage_user_threads(
    x_id: str,
    admin: Annotated[dict, Depends(require_admin)],
) -> list[dict]:
    return get_user_threads(x_id)


@app.delete("/manage/post/{post_id}")
async def manage_delete_post(
    post_id: str,
    admin: Annotated[dict, Depends(require_admin)],
) -> dict[str, bool]:
    deleted = delete_post(post_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Post not found.")
    return {"ok": True}


# ── Admin: scoring (rescore + manual override) ────────────────────────────────

@app.post("/threads/{thread_id}/rescore")
async def rescore_thread(
    thread_id: int,
    admin: Annotated[dict, Depends(require_admin)],
    x_client: Annotated[Client, Depends(get_x_client_for_user)],
) -> dict[str, Any]:
    """Re-fetch fresh X metrics for every post in a thread and recompute its score
    using the thread's contest weights. Returns the new total score."""
    thread = get_thread(thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found.")
    contest = get_contest(thread["contest_id"]) if thread["contest_id"] else None
    new_score = _rescore_thread(x_client, thread_id, _contest_weights(contest))
    return {"thread_id": thread_id, "new_score": new_score}


@app.post("/contests/{contest_id}/rescore-all")
async def rescore_all(
    contest_id: int,
    admin: Annotated[dict, Depends(require_admin)],
    x_client: Annotated[Client, Depends(get_x_client_for_user)],
) -> dict[str, Any]:
    """Rescore every thread in a contest in sequence (reflects current contest weights)."""
    contest = get_contest(contest_id)
    if not contest:
        raise HTTPException(status_code=404, detail="Contest not found.")
    weights = _contest_weights(contest)
    thread_ids = get_contest_thread_ids(contest_id)
    for tid in thread_ids:
        _rescore_thread(x_client, tid, weights)
    return {"rescored": len(thread_ids), "contest_id": contest_id}


@app.patch("/threads/{thread_id}/score")
async def override_thread_score(
    thread_id: int,
    body: OverrideScoreRequest,
    admin: Annotated[dict, Depends(require_admin)],
) -> dict[str, Any]:
    """Set or clear a manual admin score override for a thread. ``override_score=null``
    clears the override and reverts to the computed score. Returns the effective score."""
    if not get_thread(thread_id):
        raise HTTPException(status_code=404, detail="Thread not found.")
    if body.override_score is None:
        clear_thread_score_override(thread_id)
    else:
        set_thread_score_override(thread_id, body.override_score, body.note, admin["x_id"])
    return get_thread_score(thread_id)


import os as _os
from pathlib import Path as _Path
from fastapi.staticfiles import StaticFiles

_dist = _Path(_os.environ.get("FRONTEND_DIST", _Path(__file__).resolve().parent.parent / "frontend" / "dist"))
if _dist.is_dir():
    # html=True serves index.html for unknown paths (SPA client routing).
    app.mount("/", StaticFiles(directory=str(_dist), html=True), name="spa")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8080, reload=True)
"""Core database layer: schema, migrations, public scoring, contests, leaderboard, user/thread ops.

This module is the heart of the open-core foundation. All scoring math and contest/leaderboard
queries live here so they are identical for self-hosted and premium consumers.

Public scoring formula (preserved exactly):
    interactions = retweets + replies + likes + quotes + bookmarks
    valid = interactions - low_follower_engagements
    ratio = max((valid - low) / impressions, 0) if impressions > 0 else 0
    score = max(valid + 300.0 * ratio, 0.0)
Thread total_score = sum of its posts' scores.

Tables:
  thread_contests  — contest definitions (pk: contest_id)
  users            — X user profiles (pk: x_id)
  posts            — individual X posts + latest metrics (pk: post_id, fk: x_id → users)
  threads          — a contestant's submission (pk: thread_id, fk: x_id → users, contest_id → thread_contests)
  thread_posts     — posts belonging to a thread (pk: id, fk: thread_id → threads, post_id → posts)
  thread_scores    — per-post score rows (pk: id, fk: post_id → posts)
  oauth_tokens     — stored X OAuth2 tokens (pk: x_id, fk: x_id → users)
  post_metric_snapshots — timestamped metric history (pk: id, fk: post_id → posts) [added in DEV-26]

See also: feature_flags (for future premium branching around scoring/contests).
"""
import json
import os
import sqlite3
from pathlib import Path
from typing import Any

from .hooks import CALCULATE_SCORE, registry

DB_PATH = Path(os.environ.get("DB_PATH", str(Path(__file__).parent / "shilljudge_core.db")))

# Per-contest weights applied to each public metric before the (fixed) scoring formula.
# Order matters for INSERT/SELECT column lists; all default to 1.0 (no change to base scoring).
WEIGHT_COLUMNS = (
    "weight_likes", "weight_retweets", "weight_replies",
    "weight_quotes", "weight_bookmarks", "weight_impressions",
)


def _validate_weights(weights: dict[str, Any]) -> None:
    """Reject any weight < 0. Unknown keys are ignored (only WEIGHT_COLUMNS are persisted)."""
    for col in WEIGHT_COLUMNS:
        if col in weights and weights[col] is not None and float(weights[col]) < 0:
            raise ValueError(f"{col} must be >= 0 (no negative weighting)")


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _add_missing_columns(conn: sqlite3.Connection, table: str, columns: list[tuple[str, str]]) -> None:
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    for col, col_type in columns:
        if col not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")


def _fix_threads_contest_fk(conn: sqlite3.Connection) -> None:
    """Heal databases where threads or thread_posts were created/added with REFERENCES to a
    temporary *_old table during contest feature migration (the source of all "no such table: main.*_old" 500s
    on thread submission, contest delete, and user delete).
    Rebuilds affected tables in-place preserving data.
    """
    def _needs_fix(table: str, bad: str) -> bool:
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        return bool(row and row["sql"] and bad in row["sql"])

    fixes = []
    if _needs_fix("threads", "thread_contests_old"):
        fixes.append(("threads", """
            CREATE TABLE threads (
                thread_id   INTEGER PRIMARY KEY AUTOINCREMENT,
                x_id        TEXT NOT NULL REFERENCES users(x_id),
                created_at  TEXT NOT NULL DEFAULT (datetime('now')),
                total_score REAL DEFAULT 0.0,
                post_count  INTEGER DEFAULT 0,
                contest_id  INTEGER REFERENCES thread_contests(contest_id)
            );
        """))
    if _needs_fix("thread_posts", "threads_old"):
        fixes.append(("thread_posts", """
            CREATE TABLE thread_posts (
                thread_id INTEGER NOT NULL REFERENCES threads(thread_id),
                post_id   TEXT    NOT NULL REFERENCES posts(post_id),
                PRIMARY KEY (thread_id, post_id)
            );
        """))

    if not fixes:
        return

    conn.executescript("PRAGMA foreign_keys = OFF;")
    for table, create_sql in fixes:
        conn.executescript(f"""
            ALTER TABLE {table} RENAME TO {table}_old;
            {create_sql}
            INSERT INTO {table} SELECT * FROM {table}_old;
            DROP TABLE {table}_old;
        """)
    conn.executescript("PRAGMA foreign_keys = ON;")


def init_db() -> None:
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS thread_contests (
                contest_id        INTEGER PRIMARY KEY AUTOINCREMENT,
                title             TEXT NOT NULL,
                description       TEXT,
                start_date        TEXT NOT NULL,
                end_date          TEXT NOT NULL,
                created_at        TEXT DEFAULT (datetime('now')),
                must_stake_token  INTEGER DEFAULT 0,
                metadata          TEXT NOT NULL DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS users (
                x_id                 TEXT PRIMARY KEY,
                x_username           TEXT UNIQUE,
                name                 TEXT,
                description          TEXT,
                location             TEXT,
                created_at           TEXT,
                profile_image_url    TEXT,
                profile_banner_url   TEXT,
                url                  TEXT,
                verified             INTEGER,
                verified_type        TEXT,
                is_identity_verified INTEGER,
                protected            INTEGER,
                followers_count      INTEGER,
                following_count      INTEGER,
                tweet_count          INTEGER,
                listed_count         INTEGER,
                wallet_address       TEXT,
                stake_verified       INTEGER DEFAULT 0,
                stake_checked_at     TEXT,
                is_admin             BOOLEAN NOT NULL DEFAULT 0,
                participation_status TEXT NOT NULL DEFAULT 'active',
                metadata             TEXT NOT NULL DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS posts (
                post_id                   TEXT PRIMARY KEY,
                x_id                      TEXT NOT NULL REFERENCES users(x_id),
                retweets                  INTEGER,
                replies                   INTEGER,
                likes                     INTEGER,
                quotes                    INTEGER,
                bookmarks                 INTEGER,
                impressions               INTEGER,
                created_at                TEXT,
                text                      TEXT,
                low_follower_engagements  INTEGER,
                engagement_checked        INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS thread_scores (
                score_id   INTEGER PRIMARY KEY AUTOINCREMENT,
                post_id    TEXT NOT NULL REFERENCES posts(post_id),
                x_username TEXT REFERENCES users(x_username),
                ratio      REAL,
                score      REAL,
                metadata   TEXT NOT NULL DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS threads (
                thread_id   INTEGER PRIMARY KEY AUTOINCREMENT,
                x_id        TEXT NOT NULL REFERENCES users(x_id),
                created_at  TEXT NOT NULL DEFAULT (datetime('now')),
                total_score REAL DEFAULT 0.0,
                post_count  INTEGER DEFAULT 0,
                contest_id  INTEGER REFERENCES thread_contests(contest_id),
                metadata    TEXT NOT NULL DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS thread_posts (
                thread_id INTEGER NOT NULL REFERENCES threads(thread_id),
                post_id   TEXT    NOT NULL REFERENCES posts(post_id),
                PRIMARY KEY (thread_id, post_id)
            );

            CREATE TABLE IF NOT EXISTS oauth_tokens (
                x_id        TEXT PRIMARY KEY REFERENCES users(x_id),
                token_json  TEXT NOT NULL,
                updated_at  TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS post_metric_snapshots (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                post_id     TEXT NOT NULL,
                polled_at   TEXT NOT NULL,
                retweets    INTEGER,
                replies     INTEGER,
                likes       INTEGER,
                quotes      INTEGER,
                bookmarks   INTEGER,
                impressions INTEGER
            );
        """)
        # Migrate existing databases that predate column additions
        _add_missing_columns(conn, "thread_contests", [
            ("must_stake_token", "INTEGER DEFAULT 0"),
            ("metadata", "TEXT NOT NULL DEFAULT '{}'"),
            ("prize", "TEXT"),
            ("thread_length", "INTEGER NOT NULL DEFAULT 1"),
            ("status", "TEXT NOT NULL DEFAULT 'active'"),
            ("weight_likes", "REAL NOT NULL DEFAULT 1.0"),
            ("weight_retweets", "REAL NOT NULL DEFAULT 1.0"),
            ("weight_replies", "REAL NOT NULL DEFAULT 1.0"),
            ("weight_quotes", "REAL NOT NULL DEFAULT 1.0"),
            ("weight_bookmarks", "REAL NOT NULL DEFAULT 1.0"),
            ("weight_impressions", "REAL NOT NULL DEFAULT 1.0"),
        ])
        _add_missing_columns(conn, "users", [
            ("name", "TEXT"), ("description", "TEXT"), ("location", "TEXT"),
            ("created_at", "TEXT"), ("profile_image_url", "TEXT"), ("profile_banner_url", "TEXT"),
            ("url", "TEXT"), ("verified", "INTEGER"), ("verified_type", "TEXT"),
            ("is_identity_verified", "INTEGER"), ("protected", "INTEGER"),
            ("followers_count", "INTEGER"), ("following_count", "INTEGER"),
            ("tweet_count", "INTEGER"), ("listed_count", "INTEGER"),
            ("wallet_address", "TEXT"), ("stake_verified", "INTEGER DEFAULT 0"),
            ("stake_checked_at", "TEXT"), ("is_admin", "BOOLEAN NOT NULL DEFAULT 0"),
            ("participation_status", "TEXT NOT NULL DEFAULT 'active'"),
            ("metadata", "TEXT NOT NULL DEFAULT '{}'"),
        ])
        _add_missing_columns(conn, "posts", [
            ("low_follower_engagements", "INTEGER"),
            ("engagement_checked", "INTEGER DEFAULT 0"),
        ])
        _add_missing_columns(conn, "threads", [
            ("contest_id", "INTEGER"),
            ("metadata", "TEXT NOT NULL DEFAULT '{}'"),
        ])
        _add_missing_columns(conn, "thread_scores", [
            ("metadata", "TEXT NOT NULL DEFAULT '{}'"),
        ])
        _fix_threads_contest_fk(conn)


def get_metadata(conn: sqlite3.Connection, table: str, pk_col: str, pk_val: Any, namespace: str) -> dict:
    """Read one namespace from a row's metadata JSON. Returns {} if absent."""
    row = conn.execute(f"SELECT metadata FROM {table} WHERE {pk_col} = ?", (pk_val,)).fetchone()
    if not row:
        return {}
    try:
        meta = json.loads(row["metadata"] or "{}")
    except (json.JSONDecodeError, TypeError):
        return {}
    return meta.get(namespace, {})


def set_metadata(conn: sqlite3.Connection, table: str, pk_col: str, pk_val: Any, namespace: str, data: dict) -> None:
    """Merge data into namespace key of the row's metadata JSON. Never overwrites sibling namespaces."""
    row = conn.execute(f"SELECT metadata FROM {table} WHERE {pk_col} = ?", (pk_val,)).fetchone()
    if not row:
        return
    try:
        meta = json.loads(row["metadata"] or "{}")
    except (json.JSONDecodeError, TypeError):
        meta = {}
    meta[namespace] = data
    conn.execute(f"UPDATE {table} SET metadata = ? WHERE {pk_col} = ?", (json.dumps(meta), pk_val))


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


def upsert_post_data(
    tweet: dict[str, Any],
    low_follower_engagements: int | None = None,
    weights: dict[str, Any] | None = None,
) -> None:
    """Store a post + its public score. ``weights`` (the active contest's metric weights)
    scales each public metric before the fixed formula; absent/all-1.0 weights reproduce the
    unweighted score exactly. The base score is then routed through the CALCULATE_SCORE hook so
    premium extensions can adjust it."""
    author_id: str = tweet["author_id"]
    post_id: str = tweet["id"]
    metrics: dict[str, Any] = tweet.get("public_metrics") or {}

    score, ratio = score_post(metrics, low_follower_engagements, weights)
    score = registry.call(CALCULATE_SCORE, tweet, score)

    engagement_checked = 1 if low_follower_engagements is not None else 0

    with get_connection() as conn:
        conn.execute(
            "INSERT INTO users (x_id, x_username) VALUES (?, NULL) ON CONFLICT(x_id) DO NOTHING",
            (author_id,),
        )
        conn.execute(
            """
            INSERT INTO posts (
                post_id, x_id, retweets, replies, likes,
                quotes, bookmarks, impressions, created_at, text,
                low_follower_engagements, engagement_checked
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(post_id) DO UPDATE SET
                x_id                     = excluded.x_id,
                retweets                 = excluded.retweets,
                replies                  = excluded.replies,
                likes                    = excluded.likes,
                quotes                   = excluded.quotes,
                bookmarks                = excluded.bookmarks,
                impressions              = excluded.impressions,
                created_at               = excluded.created_at,
                text                     = excluded.text,
                low_follower_engagements = excluded.low_follower_engagements,
                engagement_checked       = excluded.engagement_checked
            """,
            (
                post_id, author_id,
                metrics.get("retweet_count"), metrics.get("reply_count"),
                metrics.get("like_count"), metrics.get("quote_count"),
                metrics.get("bookmark_count"), metrics.get("impression_count"),
                tweet.get("created_at"), tweet.get("text"),
                low_follower_engagements, engagement_checked,
            ),
        )
        conn.execute("DELETE FROM thread_scores WHERE post_id = ?", (post_id,))
        conn.execute(
            "INSERT INTO thread_scores (post_id, x_username, ratio, score) VALUES (?, NULL, ?, ?)",
            (post_id, ratio, score),
        )


def upsert_user_data(user: dict[str, Any]) -> None:
    """Populate public profile fields for a stub user (x_username IS NULL). Leaves enriched rows untouched."""
    x_id = user.get("id")
    if not x_id:
        return
    metrics: dict[str, Any] = user.get("public_metrics") or {}
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO users (x_id) VALUES (?) ON CONFLICT(x_id) DO NOTHING",
            (x_id,),
        )
        conn.execute(
            """
            UPDATE users SET
                x_username           = ?,
                name                 = ?,
                description          = ?,
                location             = ?,
                created_at           = ?,
                profile_image_url    = ?,
                profile_banner_url   = ?,
                url                  = ?,
                verified             = ?,
                verified_type        = ?,
                is_identity_verified = ?,
                protected            = ?,
                followers_count      = ?,
                following_count      = ?,
                tweet_count          = ?,
                listed_count         = ?
            WHERE x_id = ? AND x_username IS NULL
            """,
            (
                user.get("username"), user.get("name"), user.get("description"),
                user.get("location"), user.get("created_at"), user.get("profile_image_url"),
                user.get("profile_banner_url"), user.get("url"),
                int(bool(user.get("verified"))), user.get("verified_type"),
                int(bool(user.get("is_identity_verified"))), int(bool(user.get("protected"))),
                metrics.get("followers_count"), metrics.get("following_count"),
                metrics.get("tweet_count"), metrics.get("listed_count"),
                x_id,
            ),
        )


def upsert_user_profile(user: dict[str, Any]) -> None:
    """Force-update all profile fields for a logged-in user (no x_username IS NULL guard)."""
    x_id = user.get("id")
    if not x_id:
        return
    metrics: dict[str, Any] = user.get("public_metrics") or {}
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO users (x_id) VALUES (?) ON CONFLICT(x_id) DO NOTHING",
            (x_id,),
        )
        conn.execute(
            """
            UPDATE users SET
                x_username           = ?,
                name                 = ?,
                description          = ?,
                location             = ?,
                created_at           = ?,
                profile_image_url    = ?,
                profile_banner_url   = ?,
                url                  = ?,
                verified             = ?,
                verified_type        = ?,
                is_identity_verified = ?,
                protected            = ?,
                followers_count      = ?,
                following_count      = ?,
                tweet_count          = ?,
                listed_count         = ?
            WHERE x_id = ?
            """,
            (
                user.get("username"), user.get("name"), user.get("description"),
                user.get("location"), user.get("created_at"), user.get("profile_image_url"),
                user.get("profile_banner_url"), user.get("url"),
                int(bool(user.get("verified"))), user.get("verified_type"),
                int(bool(user.get("is_identity_verified"))), int(bool(user.get("protected"))),
                metrics.get("followers_count"), metrics.get("following_count"),
                metrics.get("tweet_count"), metrics.get("listed_count"),
                x_id,
            ),
        )


def get_user(x_id: str) -> dict[str, Any] | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM users WHERE x_id = ?", (x_id,)).fetchone()
        return dict(row) if row else None


def set_wallet(x_id: str, wallet_address: str, stake_verified: bool, stake_checked_at: str) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE users SET wallet_address = ?, stake_verified = ?, stake_checked_at = ?
            WHERE x_id = ?
            """,
            (wallet_address, int(stake_verified), stake_checked_at, x_id),
        )


def get_unenriched_user_ids() -> list[str]:
    with get_connection() as conn:
        rows = conn.execute("SELECT x_id FROM users WHERE x_username IS NULL").fetchall()
        return [row["x_id"] for row in rows]


def create_thread(post_ids: list[str]) -> dict[str, Any]:
    if not post_ids:
        raise ValueError("post_ids cannot be empty")

    with get_connection() as conn:
        first = conn.execute(
            "SELECT x_id FROM posts WHERE post_id = ?", (post_ids[0],)
        ).fetchone()
        if not first:
            raise ValueError(f"Post {post_ids[0]} not found in database")

        contest_id = _get_active_contest_id(conn)
        cursor = conn.execute(
            "INSERT INTO threads (x_id, contest_id) VALUES (?, ?)", (first["x_id"], contest_id)
        )
        thread_id = cursor.lastrowid

        conn.executemany(
            "INSERT OR IGNORE INTO thread_posts (thread_id, post_id) VALUES (?, ?)",
            [(thread_id, pid) for pid in post_ids],
        )

        conn.execute(
            """
            UPDATE threads
            SET
                post_count  = (SELECT COUNT(*) FROM thread_posts WHERE thread_id = ?),
                total_score = (
                    SELECT COALESCE(SUM(ts.score), 0.0)
                    FROM thread_posts tp
                    JOIN thread_scores ts ON tp.post_id = ts.post_id
                    WHERE tp.thread_id = ?
                )
            WHERE thread_id = ?
            """,
            (thread_id, thread_id, thread_id),
        )

        row = conn.execute(
            "SELECT thread_id, x_id, created_at, total_score, post_count FROM threads WHERE thread_id = ?",
            (thread_id,),
        ).fetchone()
        return dict(row)


def get_thread(thread_id: int) -> dict[str, Any] | None:
    """Return a single thread row (incl. contest_id) or None if it does not exist."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT thread_id, x_id, created_at, total_score, post_count, contest_id FROM threads WHERE thread_id = ?",
            (thread_id,),
        ).fetchone()
        return dict(row) if row else None


def get_thread_post_ids(thread_id: int) -> list[str]:
    """Return the post IDs belonging to a thread (in insertion order)."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT post_id FROM thread_posts WHERE thread_id = ?", (thread_id,)
        ).fetchall()
        return [row["post_id"] for row in rows]


def get_contest_thread_ids(contest_id: int) -> list[int]:
    """Return all thread IDs belonging to a contest (oldest first)."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT thread_id FROM threads WHERE contest_id = ? ORDER BY thread_id ASC",
            (contest_id,),
        ).fetchall()
        return [row["thread_id"] for row in rows]


def recompute_thread_total_score(thread_id: int) -> float:
    """Recompute ``threads.total_score`` (and post_count) from the current per-post
    ``thread_scores`` rows and return the new total. Call this after re-scoring a
    thread's posts via ``upsert_post_data``."""
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE threads
            SET
                post_count  = (SELECT COUNT(*) FROM thread_posts WHERE thread_id = ?),
                total_score = (
                    SELECT COALESCE(SUM(ts.score), 0.0)
                    FROM thread_posts tp
                    JOIN thread_scores ts ON tp.post_id = ts.post_id
                    WHERE tp.thread_id = ?
                )
            WHERE thread_id = ?
            """,
            (thread_id, thread_id, thread_id),
        )
        row = conn.execute(
            "SELECT total_score FROM threads WHERE thread_id = ?", (thread_id,)
        ).fetchone()
        return row["total_score"] if row else 0.0


def set_thread_score_override(thread_id: int, override_score: float, note: str, by: str) -> None:
    """Store an admin manual score override for a thread in the ``admin`` metadata
    namespace, alongside the audit note and the overriding admin's x_id."""
    with get_connection() as conn:
        set_metadata(conn, "threads", "thread_id", thread_id, "admin", {
            "override_score": override_score,
            "note": note,
            "by": by,
        })


def clear_thread_score_override(thread_id: int) -> None:
    """Remove a thread's admin override (resets to the computed score) by writing an
    empty ``admin`` namespace."""
    with get_connection() as conn:
        set_metadata(conn, "threads", "thread_id", thread_id, "admin", {})


def _effective_score(total_score: float, admin_meta: dict) -> tuple[float, bool]:
    """Return (effective_score, is_overridden) given a thread's computed total and its
    admin metadata namespace. An override of 0.0 is honored (presence, not truthiness)."""
    is_overridden = bool(admin_meta) and "override_score" in admin_meta
    score = admin_meta["override_score"] if is_overridden else total_score
    return score, is_overridden


def get_thread_score(thread_id: int) -> dict[str, Any] | None:
    """Return a thread's effective score view: computed total, any override, and the
    effective score (override when present, else computed). None if no such thread."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT thread_id, total_score FROM threads WHERE thread_id = ?", (thread_id,)
        ).fetchone()
        if not row:
            return None
        admin_meta = get_metadata(conn, "threads", "thread_id", thread_id, "admin")
        score, is_overridden = _effective_score(row["total_score"], admin_meta)
        return {
            "thread_id": thread_id,
            "total_score": row["total_score"],
            "override_score": admin_meta.get("override_score") if is_overridden else None,
            "is_overridden": is_overridden,
            "score": score,
        }


def _get_active_contest_id(conn: sqlite3.Connection) -> int | None:
    row = conn.execute(
        "SELECT contest_id FROM thread_contests WHERE status = 'active' LIMIT 1"
    ).fetchone()
    return row["contest_id"] if row else None


def get_active_contest() -> dict[str, Any] | None:
    with get_connection() as conn:
        row = conn.execute(
            f"""
            SELECT contest_id, title, must_stake_token, {", ".join(WEIGHT_COLUMNS)}
            FROM thread_contests
            WHERE status = 'active'
            LIMIT 1
            """
        ).fetchone()
        return dict(row) if row else None


def get_active_contest_post_ids() -> list[str]:
    """Return all post IDs belonging to threads in the active contest.

    Used by the polling engine to know which posts to re-fetch. Returns an empty
    list when there is no active contest.
    """
    with get_connection() as conn:
        contest_id = _get_active_contest_id(conn)
        if not contest_id:
            return []
        rows = conn.execute(
            """
            SELECT DISTINCT tp.post_id
            FROM thread_posts tp
            JOIN threads t ON tp.thread_id = t.thread_id
            WHERE t.contest_id = ?
            """,
            (contest_id,),
        ).fetchall()
        return [row["post_id"] for row in rows]


def insert_metric_snapshot(tweet: dict[str, Any], polled_at: str) -> None:
    """Append a timestamped metric snapshot for a post (history of each poll).

    Unlike ``upsert_post_data`` (which overwrites the latest values used for
    scoring), this never replaces prior rows — it builds a time series.
    """
    metrics: dict[str, Any] = tweet.get("public_metrics") or {}
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO post_metric_snapshots (
                post_id, polled_at, retweets, replies, likes, quotes, bookmarks, impressions
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                tweet["id"], polled_at,
                metrics.get("retweet_count"), metrics.get("reply_count"),
                metrics.get("like_count"), metrics.get("quote_count"),
                metrics.get("bookmark_count"), metrics.get("impression_count"),
            ),
        )


def _get_leaderboard_contest(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute(
        """
        SELECT contest_id, title, description, start_date, end_date, created_at, must_stake_token, status
        FROM thread_contests
        WHERE status = 'active'
        LIMIT 1
        """
    ).fetchone()
    if row:
        return dict(row)
    row = conn.execute(
        """
        SELECT contest_id, title, description, start_date, end_date, created_at, must_stake_token, status
        FROM thread_contests
        WHERE status = 'ended'
        ORDER BY end_date DESC
        LIMIT 1
        """
    ).fetchone()
    return dict(row) if row else None


# Public sort keys for the paginated threads rail. Maps each accepted ``sort_by``
# value to the thread-row field used for ordering. "score" is the override-aware
# effective score. Anything outside this allowlist falls back to "score" — caller
# input never reaches SQL or a row lookup unvalidated.
LEADERBOARD_SORT_KEYS = {
    "score": "score",
    "total_score": "total_score",
    "post_count": "post_count",
    "created": "created_at",
    "created_at": "created_at",
    "likes": "likes",
    "retweets": "retweets",
    "replies": "replies",
    "quotes": "quotes",
    "bookmarks": "bookmarks",
    "impressions": "impressions",
    "views": "impressions",
}


def _leaderboard_sort_key(value: Any):
    """Total-orderable key for one thread-row field. None sorts smallest; numbers
    and strings keep their natural order (all rows share a type for a given field)."""
    if value is None:
        return (0, 0)
    if isinstance(value, str):
        return (1, value)
    return (2, value)


def get_leaderboard(
    sort_by: str = "score",
    sort_dir: str = "desc",
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    """Active-contest (or most-recent ended) leaderboard.

    ``users`` and ``posts`` stay fixed top-20 supplementary rails; ``threads`` is
    sortable + paginated. ``sort_by`` is validated against ``LEADERBOARD_SORT_KEYS``
    (invalid → "score"); ``sort_dir`` must be "asc"/"desc" (invalid → "desc").
    ``limit`` is clamped to [0, 100] and ``offset`` to >= 0. The threads rail is
    override-aware (DEV-27): each row's effective ``score`` prefers a manual
    override over the computed total, and the rail is ordered by the effective value.
    """
    sort_field = LEADERBOARD_SORT_KEYS.get(sort_by)
    if sort_field is None:
        sort_by, sort_field = "score", "score"
    if sort_dir not in ("asc", "desc"):
        sort_dir = "desc"
    limit = max(0, min(int(limit), 100))
    offset = max(0, int(offset))

    with get_connection() as conn:
        contest = _get_leaderboard_contest(conn)
        cid = contest["contest_id"] if contest else None

        user_rows = conn.execute("""
            WITH user_stats AS (
                SELECT
                    u.x_id,
                    u.x_username,
                    COUNT(p.post_id) AS post_count,
                    SUM(
                        COALESCE(p.retweets, 0) + COALESCE(p.replies, 0) +
                        COALESCE(p.likes, 0) + COALESCE(p.quotes, 0) +
                        COALESCE(p.bookmarks, 0)
                    ) AS total_interactions,
                    COALESCE(SUM(p.impressions), 0) AS total_impressions,
                    SUM(COALESCE(p.low_follower_engagements, 0)) AS total_low
                FROM users u
                JOIN posts p ON u.x_id = p.x_id
                WHERE (:cid IS NULL OR p.post_id IN (
                    SELECT tp.post_id FROM thread_posts tp
                    JOIN threads t ON tp.thread_id = t.thread_id
                    WHERE t.contest_id = :cid
                ))
                GROUP BY u.x_id
            )
            SELECT
                x_id,
                x_username,
                post_count,
                total_interactions,
                total_impressions,
                total_low,
                CASE WHEN total_impressions = 0 THEN 0.0
                     ELSE MAX(CAST(total_interactions - total_low - total_low AS REAL) / total_impressions, 0.0)
                END AS ratio,
                MAX(
                    (total_interactions - total_low) + 300.0 *
                    CASE WHEN total_impressions = 0 THEN 0.0
                         ELSE MAX(CAST(total_interactions - total_low - total_low AS REAL) / total_impressions, 0.0)
                    END,
                    0.0
                ) AS score
            FROM user_stats
            ORDER BY score DESC
            LIMIT 20
        """, {"cid": cid}).fetchall()

        post_rows = conn.execute("""
            SELECT
                ts.post_id,
                p.text,
                p.created_at,
                u.x_id,
                u.x_username,
                ts.ratio,
                ts.score
            FROM thread_scores ts
            JOIN posts p ON ts.post_id = p.post_id
            JOIN users u ON p.x_id = u.x_id
            WHERE (:cid IS NULL OR ts.post_id IN (
                SELECT tp.post_id FROM thread_posts tp
                JOIN threads t ON tp.thread_id = t.thread_id
                WHERE t.contest_id = :cid
            ))
            ORDER BY ts.score DESC
            LIMIT 20
        """, {"cid": cid}).fetchall()

        thread_rows = conn.execute("""
            SELECT
                t.thread_id,
                t.x_id,
                u.x_username,
                t.total_score,
                t.post_count,
                t.created_at,
                COALESCE(SUM(p.likes), 0)       AS likes,
                COALESCE(SUM(p.retweets), 0)    AS retweets,
                COALESCE(SUM(p.replies), 0)     AS replies,
                COALESCE(SUM(p.quotes), 0)      AS quotes,
                COALESCE(SUM(p.bookmarks), 0)   AS bookmarks,
                COALESCE(SUM(p.impressions), 0) AS impressions,
                (
                    SELECT p2.text
                    FROM thread_posts tp2
                    JOIN posts p2 ON tp2.post_id = p2.post_id
                    WHERE tp2.thread_id = t.thread_id
                    ORDER BY p2.created_at ASC
                    LIMIT 1
                ) AS top_text
            FROM threads t
            JOIN users u ON t.x_id = u.x_id
            LEFT JOIN thread_posts tp ON tp.thread_id = t.thread_id
            LEFT JOIN posts p ON tp.post_id = p.post_id
            WHERE (:cid IS NULL OR t.contest_id = :cid)
            GROUP BY t.thread_id
        """, {"cid": cid}).fetchall()

        # Apply admin overrides: each thread's effective ``score`` prefers a manual
        # override (DEV-27) over the computed total. Sort the full rail by the
        # requested field (validated above) before paginating, so an override can
        # change leaderboard position and the page reflects the true ordering.
        threads_all = []
        for r in thread_rows:
            d = dict(r)
            admin_meta = get_metadata(conn, "threads", "thread_id", d["thread_id"], "admin")
            d["score"], d["is_overridden"] = _effective_score(d["total_score"], admin_meta)
            threads_all.append(d)
        threads_all.sort(
            key=lambda t: _leaderboard_sort_key(t.get(sort_field)),
            reverse=(sort_dir == "desc"),
        )
        total_count = len(threads_all)
        threads_page = threads_all[offset:offset + limit] if limit else []

        return {
            "contest": contest,
            "users": [dict(r) for r in user_rows],
            "posts": [dict(r) for r in post_rows],
            "threads": threads_page,
            "total_count": total_count,
            "sort_by": sort_by,
            "sort_dir": sort_dir,
            "limit": limit,
            "offset": offset,
        }


def get_all_contests() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(f"""
            SELECT contest_id, title, description, start_date, end_date, created_at, must_stake_token,
                   prize, thread_length, status, {", ".join(WEIGHT_COLUMNS)}
            FROM thread_contests
            ORDER BY start_date DESC
        """).fetchall()
        return [dict(r) for r in rows]


def get_contest(contest_id: int) -> dict[str, Any] | None:
    with get_connection() as conn:
        row = conn.execute(
            f"""
            SELECT contest_id, title, description, start_date, end_date, created_at, must_stake_token,
                   prize, thread_length, status, {", ".join(WEIGHT_COLUMNS)}
            FROM thread_contests WHERE contest_id = ?
            """,
            (contest_id,),
        ).fetchone()
        return dict(row) if row else None


def create_contest(
    title: str, description: str | None, start_date: str, end_date: str,
    must_stake_token: bool = False,
    prize: str | None = None,
    thread_length: int = 1,
    status: str = "active",
    weights: dict[str, Any] | None = None,
) -> dict:
    w = weights or {}
    _validate_weights(w)
    weight_values = [float(w.get(col, 1.0)) for col in WEIGHT_COLUMNS]
    weight_cols_sql = ", ".join(WEIGHT_COLUMNS)
    weight_placeholders = ", ".join("?" for _ in WEIGHT_COLUMNS)
    with get_connection() as conn:
        if status == "active":
            existing = conn.execute(
                "SELECT contest_id FROM thread_contests WHERE status = 'active' LIMIT 1"
            ).fetchone()
            if existing:
                raise ValueError("An active contest already exists. Archive it before creating a new active one.")
        cursor = conn.execute(
            f"""
            INSERT INTO thread_contests
                (title, description, start_date, end_date, must_stake_token, prize, thread_length, status,
                 {weight_cols_sql})
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, {weight_placeholders})
            """,
            (title, description, start_date, end_date, int(must_stake_token), prize, thread_length, status,
             *weight_values),
        )
        row = conn.execute(
            f"""
            SELECT contest_id, title, description, start_date, end_date, created_at, must_stake_token,
                   prize, thread_length, status, {weight_cols_sql}
            FROM thread_contests WHERE contest_id = ?
            """,
            (cursor.lastrowid,),
        ).fetchone()
        return dict(row)


def update_contest(contest_id: int, fields: dict[str, Any]) -> dict[str, Any] | None:
    allowed = {"title", "description", "start_date", "end_date", "must_stake_token", "prize", "thread_length", "status"}
    allowed.update(WEIGHT_COLUMNS)
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return get_contest(contest_id)
    _validate_weights(updates)
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    with get_connection() as conn:
        if updates.get("status") == "active":
            existing = conn.execute(
                "SELECT contest_id FROM thread_contests WHERE status = 'active' AND contest_id != ? LIMIT 1",
                (contest_id,),
            ).fetchone()
            if existing:
                raise ValueError("An active contest already exists. Archive it before activating this one.")
        conn.execute(
            f"UPDATE thread_contests SET {set_clause} WHERE contest_id = ?",
            (*updates.values(), contest_id),
        )
    return get_contest(contest_id)


def delete_contest(contest_id: int) -> bool:
    with get_connection() as conn:
        result = conn.execute(
            "UPDATE thread_contests SET status = 'archived' WHERE contest_id = ?",
            (contest_id,),
        )
        return result.rowcount > 0


def get_user_threads(x_id: str) -> list[dict[str, Any]]:
    with get_connection() as conn:
        threads = conn.execute(
            "SELECT thread_id, created_at, total_score, post_count FROM threads WHERE x_id = ? ORDER BY created_at DESC",
            (x_id,),
        ).fetchall()
        result = []
        for t in threads:
            posts = conn.execute(
                """
                SELECT p.post_id, p.text, p.created_at, p.likes, p.retweets, p.impressions,
                       ts.score
                FROM thread_posts tp
                JOIN posts p ON tp.post_id = p.post_id
                LEFT JOIN thread_scores ts ON tp.post_id = ts.post_id
                WHERE tp.thread_id = ?
                ORDER BY p.created_at ASC
                """,
                (t["thread_id"],),
            ).fetchall()
            entry = dict(t)
            entry["posts"] = [dict(p) for p in posts]
            result.append(entry)
        return result


def delete_post(post_id: str) -> bool:
    with get_connection() as conn:
        row = conn.execute("SELECT post_id FROM posts WHERE post_id = ?", (post_id,)).fetchone()
        if not row:
            return False
        affected_threads = conn.execute(
            "SELECT DISTINCT thread_id FROM thread_posts WHERE post_id = ?", (post_id,)
        ).fetchall()
        conn.execute("DELETE FROM thread_posts WHERE post_id = ?", (post_id,))
        conn.execute("DELETE FROM thread_scores WHERE post_id = ?", (post_id,))
        conn.execute("DELETE FROM posts WHERE post_id = ?", (post_id,))
        for t in affected_threads:
            tid = t["thread_id"]
            conn.execute(
                """
                UPDATE threads SET
                    post_count  = (SELECT COUNT(*) FROM thread_posts WHERE thread_id = ?),
                    total_score = (
                        SELECT COALESCE(SUM(ts.score), 0.0)
                        FROM thread_posts tp
                        JOIN thread_scores ts ON tp.post_id = ts.post_id
                        WHERE tp.thread_id = ?
                    )
                WHERE thread_id = ?
                """,
                (tid, tid, tid),
            )
        return True


def get_all_users(q: str | None = None) -> list[dict]:
    """List all users with post counts. Optional ``q`` filters by x_username LIKE '%q%'."""
    where = "WHERE u.x_username LIKE :q" if q else ""
    params = {"q": f"%{q}%"} if q else {}
    with get_connection() as conn:
        rows = conn.execute(f"""
            SELECT u.x_id, u.x_username, u.profile_image_url, u.created_at,
                   u.wallet_address, u.stake_verified, u.is_admin, u.participation_status,
                   COUNT(p.post_id) AS post_count
            FROM users u
            LEFT JOIN posts p ON u.x_id = p.x_id
            {where}
            GROUP BY u.x_id
        """, params).fetchall()
        return [dict(row) for row in rows]


def set_user_admin(x_id: str, is_admin: bool) -> None:
    with get_connection() as conn:
        conn.execute("UPDATE users SET is_admin = ? WHERE x_id = ?", (int(is_admin), x_id))


def set_user_participation(x_id: str, status: str) -> None:
    """Set a user's participation_status ('active' or 'suspended')."""
    with get_connection() as conn:
        conn.execute("UPDATE users SET participation_status = ? WHERE x_id = ?", (status, x_id))


def delete_user_data(x_id: str) -> bool:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT x_id, x_username FROM users WHERE x_id = ?", (x_id,)
        ).fetchone()
        if not row:
            return False
        x_username = row["x_username"]
        conn.execute(
            "DELETE FROM thread_posts WHERE post_id IN (SELECT post_id FROM posts WHERE x_id = ?)",
            (x_id,),
        )
        conn.execute("DELETE FROM threads WHERE x_id = ?", (x_id,))
        conn.execute(
            "DELETE FROM thread_scores WHERE post_id IN (SELECT post_id FROM posts WHERE x_id = ?)",
            (x_id,),
        )
        if x_username:
            conn.execute("DELETE FROM thread_scores WHERE x_username = ?", (x_username,))
        conn.execute("DELETE FROM posts WHERE x_id = ?", (x_id,))
        conn.execute("DELETE FROM oauth_tokens WHERE x_id = ?", (x_id,))
        conn.execute("DELETE FROM users WHERE x_id = ?", (x_id,))
        return True

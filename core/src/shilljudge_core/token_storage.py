"""OAuth token persistence (DB backed).

Used by auth flows. Moved to core so any consumer app shares the same token table owned by the foundation schema.
"""
import json
from typing import Any

from .database import get_connection


def load_user_token(x_id: str) -> dict[str, Any] | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT token_json FROM oauth_tokens WHERE x_id = ?", (x_id,)
        ).fetchone()
        if not row:
            return None
        data = json.loads(row["token_json"])
        return data if isinstance(data, dict) else None


def save_user_token(x_id: str, token: dict[str, Any]) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO oauth_tokens (x_id, token_json, updated_at)
            VALUES (?, ?, datetime('now'))
            ON CONFLICT(x_id) DO UPDATE SET
                token_json = excluded.token_json,
                updated_at = excluded.updated_at
            """,
            (x_id, json.dumps(token)),
        )


def delete_user_token(x_id: str) -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM oauth_tokens WHERE x_id = ?", (x_id,))

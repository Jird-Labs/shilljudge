"""User-context X API client (OAuth2). build_user_client is the entry point;
get_x_client_for_user (per-user, session-backed) lives in auth.py."""

from __future__ import annotations

import json
from typing import Any

from xdk import Client

from config import Settings

DEFAULT_TWEET_FIELDS: list[str] = [
    "author_id",
    "text",
    "created_at",
    "public_metrics",
]

DEFAULT_USER_FIELDS: list[str] = [
    "id",
    "username",
    "name",
    "description",
    "location",
    "created_at",
    "profile_image_url",
    "profile_banner_url",
    "url",
    "verified",
    "verified_type",
    "is_identity_verified",
    "protected",
    "public_metrics",
]


def _tokens_differ(a: dict[str, Any] | None, b: dict[str, Any] | None) -> bool:
    if a is None and b is None:
        return False
    if a is None or b is None:
        return True
    return json.dumps(a, sort_keys=True) != json.dumps(b, sort_keys=True)


def build_user_client(settings: Settings, token: dict[str, Any]) -> Client:
    """OAuth2 user-context client with refresh support."""
    return Client(
        client_id=settings.x_client_id,
        client_secret=settings.x_client_secret,
        redirect_uri=settings.x_redirect_uri,
        token=token,
        scope=settings.oauth_scope_list,
    )

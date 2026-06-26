from __future__ import annotations

import copy
import json
from collections.abc import Generator
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request
from xdk import Client

from config import get_settings
from database import get_user
from token_storage import load_user_token, save_user_token
from x_client import build_user_client, _tokens_differ


def get_current_user(request: Request) -> dict[str, Any]:
    x_id = request.session.get("x_id")
    if not x_id:
        raise HTTPException(
            status_code=401,
            detail={"error": "auth_required", "message": "Sign in with X to continue."},
        )
    user = get_user(x_id)
    if not user:
        request.session.clear()
        raise HTTPException(
            status_code=401,
            detail={"error": "auth_required", "message": "Session expired. Sign in again."},
        )
    return user


def get_optional_user(request: Request) -> dict[str, Any] | None:
    """Return the logged-in user dict if a valid session exists, else None. Unlike
    ``get_current_user`` this never raises — for public endpoints that allow anonymous
    access but still want an optional session check (e.g. the suspended-user guard)."""
    x_id = request.session.get("x_id")
    if not x_id:
        return None
    return get_user(x_id)


def require_admin(user: Annotated[dict, Depends(get_current_user)]) -> dict[str, Any]:
    if not user.get("is_admin"):
        raise HTTPException(
            status_code=403,
            detail={"error": "forbidden", "message": "Admin access required."},
        )
    return user


def get_x_client_for_user(
    user: Annotated[dict, Depends(get_current_user)],
) -> Generator[Client, None, None]:
    x_id = user["x_id"]
    token = load_user_token(x_id)
    if not token or not token.get("access_token"):
        raise HTTPException(
            status_code=401,
            detail={
                "error": "x_oauth_required",
                "message": "X OAuth token missing. Sign in again.",
                "login_path": "/oauth/login",
            },
        )
    settings = get_settings()
    client = build_user_client(settings, token)
    token_before = copy.deepcopy(client.token)
    try:
        yield client
    finally:
        token_after = client.token
        if _tokens_differ(token_before, token_after) and token_after:
            save_user_token(x_id, token_after)
"""Auth primitives for the foundation (user identity + admin gate).

These are framework-agnostic. FastAPI Depends wrappers live in the concrete app
(the ShillJudge app (`app/`)) so that core has no hard dependency on FastAPI or xdk.

Consumers typically do:

    from fastapi import Depends, Request, HTTPException
    from shilljudge_core.auth import get_current_user_from_session, require_admin

    def get_current_user(request: Request):
        user = get_current_user_from_session(request.session)
        if not user:
            raise HTTPException(...)
        return user

    def require_admin_user(user=Depends(get_current_user)):
        return require_admin(user)
"""
from __future__ import annotations

from typing import Any

from .database import get_user


def get_current_user_from_session(session: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return the user dict for the x_id in the session, or None if missing/expired."""
    if not session:
        return None
    x_id = session.get("x_id")
    if not x_id:
        return None
    user = get_user(x_id)
    if not user:
        # Signal to caller that session should be cleared
        return None
    return user


def require_admin(user: dict[str, Any]) -> dict[str, Any]:
    """Raise or return user if the is_admin DB flag is set."""
    if not user.get("is_admin"):
        raise PermissionError("Admin access required.")
    return user


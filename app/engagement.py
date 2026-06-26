"""Analyze post engagement: count likes + reposts from accounts with <100 followers.

analyze_post_engagement() is called at submission confirm time. It returns the
low-follower engagement count (int) or None if the API call failed (rate limit,
scope error, etc.) — the caller falls back to base scoring in that case.
"""

from __future__ import annotations

import logging

import requests
from xdk import Client

from database import upsert_user_data

logger = logging.getLogger(__name__)

LOW_FOLLOWER_THRESHOLD = 100
MAX_PAGES_PER_ENDPOINT = 3  # 100 users/page → cap at 300 engagers per endpoint
ENGAGEMENT_USER_FIELDS = ["id", "username", "public_metrics"]


def analyze_post_engagement(client: Client, post_id: str) -> int | None:
    """Return count of engagements (likes + reposts) from users with <100 followers.

    Side effect: upserts every engaging user into the users table so their
    follower counts are available for leaderboard context.
    Returns None on any API error (rate limit, scope issue, etc.).
    """
    low = 0
    try:
        for fetch_fn in (client.posts.get_liking_users, client.posts.get_reposted_by):
            for page_num, page in enumerate(
                fetch_fn(id=post_id, max_results=100, user_fields=ENGAGEMENT_USER_FIELDS)
            ):
                for u in page.data or []:
                    d = u.model_dump() if hasattr(u, "model_dump") else u
                    if isinstance(d, dict) and d.get("id"):
                        upsert_user_data(d)
                        followers = (d.get("public_metrics") or {}).get("followers_count", 0) or 0
                        if followers < LOW_FOLLOWER_THRESHOLD:
                            low += 1
                if page_num + 1 >= MAX_PAGES_PER_ENDPOINT:
                    break
    except (requests.HTTPError, Exception):
        logger.debug("Engagement analysis failed for post %s", post_id, exc_info=True)
        return None
    return low

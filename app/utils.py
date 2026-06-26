from __future__ import annotations

import re

_STATUS_RE = re.compile(r"status/(\d+)")


def parse_post_id(text: str) -> str | None:
    """Extract a numeric post ID from an X/Twitter URL, or return the value if it's already a bare numeric ID."""
    m = _STATUS_RE.search(text)
    if m:
        return m.group(1)
    stripped = text.strip()
    if stripped.isdigit():
        return stripped
    return None
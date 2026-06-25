"""Local-dev seed helper. Not called by core itself — invoked by apps or the CLI entry point."""
from datetime import date, timedelta

from shilljudge_core.database import create_contest, get_all_contests


def seed_db() -> None:
    """Insert a default contest if none exists. Idempotent."""
    if get_all_contests():
        return
    create_contest(
        title="Test Contest",
        description="Auto-seeded for local dev",
        start_date=date.today().isoformat(),
        end_date=(date.today() + timedelta(days=30)).isoformat(),
    )

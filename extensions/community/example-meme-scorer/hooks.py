from shilljudge_core.hooks import ENRICH_LEADERBOARD, ENRICH_THREAD


def _handle_enrich_thread(thread: dict) -> dict:
    thread.setdefault("metadata", {})["meme_scorer"] = {"checked": True}
    return thread


def _handle_enrich_leaderboard(rows: list) -> list:
    for row in rows:
        row["meme_bonus"] = 0
    return rows


def register(registry) -> None:
    registry.register(ENRICH_THREAD, _handle_enrich_thread, priority=50)
    registry.register(ENRICH_LEADERBOARD, _handle_enrich_leaderboard, priority=50)

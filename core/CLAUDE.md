# CLAUDE.md (core)

shilljudge-core is the **open-core foundation** library.

## What belongs here
- SQLite schema + migrations (`init_db`, table fixes)
- Public scoring formula + `upsert_post_data` / `thread_scores`
- Contest mgmt (create/update/delete, active status, must_stake_token)
- Leaderboard computation (3-rail + contest scoping)
- Shared Pydantic models for the foundation surface
- `parse_post_id`
- Auth/user primitives + token storage (DB)
- Feature flags (always from day 1)

## What does NOT belong here (stay in apps like thread-helper)
- FastAPI app + route definitions + middlewares
- Full X OAuth PKCE dance + redirects + xdk Client construction
- `engagement.analyze_post_engagement` (X-specific calls)
- Solana staking RPC checks
- Any React / frontend code
- Per-app config (X creds, admin list, frontend URLs, Solana RPC)

## Running
```bash
uv sync
uv run pytest
```

Preserve the exact public scoring math (and its tests) forever:
`score = max(valid + 300.0 * (valid / impressions or 0), 0)`
where valid = interactions - low_follower_engagements.

# CLAUDE.md — ShillJudge monorepo

Open-core tool for AI-scored X (Twitter) thread contests & leaderboards. One self-contained public repo: a free self-hostable app + a premium-extension system. (The old standalone `thread-helper` repo was folded in and retired — don't reference it.)

## Layout

- `core/` — `shilljudge_core`, the open-core **library** (SQLite schema/migrations, public scoring, contests, leaderboard, models, `parse_post_id`, auth/token primitives, feature flags, hook registry). Pure library. See `core/CLAUDE.md`.
- `app/` — the **FastAPI app** (routes, OAuth PKCE, X client, scheduler, Solana, config). Imports `shilljudge_core` via the uv workspace; serves the built SPA. See `app/CLAUDE.md`.
- `frontend/` — React/Vite SPA.
- `extensions/` — `loader.py` + `community/` (full impls) + `premium/` (stub manifests only; real premium code is in a separate private repo). Loaded into the app at startup.
- root `compose.yaml` + `pyproject.toml` (uv workspace: members `core`, `app`).

## Commands

```bash
cd core && uv run pytest               # core library tests
cd app  && uv run python -m pytest     # app tests — NOT bare `pytest` (shim resolves wrong here)
cd frontend && npm install && npm run build   # build the SPA
docker compose up --build              # run the whole app (SPA + API on :8080)
```

Dev: `cd app && uv run fastapi dev app.py --port 8080` + `cd frontend && npm run dev` (Vite :5173 proxies to :8080).

## Architecture rules

- `core/` is a pure library — never add FastAPI/X/React/Solana/app-config code to it.
- `app/` imports `shilljudge_core`; there are NO vendored copies. Edit shared DB/scoring/models/auth in `core/` only.
- ONE shared hook registry (`shilljudge_core.hooks.registry`): app + extensions register into it; core's `upsert_post_data` dispatches `CALCULATE_SCORE` through it.
- Preserve the scoring math exactly: `score = max(valid + 300.0*(valid/impressions or 0), 0)`, `valid = interactions − low_follower_engagements`. `core/tests/test_database.py` must stay green.

## Gotchas

- Use `uv run python -m pytest` for the app (bare `pytest` resolves to the wrong interpreter here).
- The app serves the SPA from `../frontend/dist` (build it first); override with `FRONTEND_DIST`.
- `extensions/premium/` are stub manifests only — real premium code is out-of-repo.

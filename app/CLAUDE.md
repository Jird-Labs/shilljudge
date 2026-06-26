# CLAUDE.md (app)

`app/` is the **FastAPI application layer** for ShillJudge. It imports `shilljudge_core` for all database operations, scoring logic, contest management, and auth primitives — the app itself owns only routes, middleware, OAuth PKCE dance, X API calls (via `xdk`), and extension loading.

## Run commands

```bash
# From the repo root (workspace-aware):
cd app
uv run python -m pytest       # run tests — use `python -m pytest`, NOT bare `pytest` (shim resolves wrong here)
uv run fastapi dev app.py     # start the dev server (default port 8000)
uv run fastapi dev app.py --port 8080  # use 8080 to match the Vite dev proxy (frontend: `cd frontend && npm run dev`)
```

## Key files

- `app.py` — FastAPI app, all route definitions, middleware, lifespan
- `auth.py` — FastAPI `Depends` wrappers around `shilljudge_core.auth`
- `config.py` — `pydantic-settings` config (reads from `.env`)
- `scheduler.py` — APScheduler background metric-polling loop
- `extensions_loader.py` — loads extensions from `../extensions/` at startup
- `engagement.py` — low-follower engagement analysis (X API calls)
- `solana_client.py` — Solana RPC stake verification
- `schemas.py` — app-local Pydantic models (not in core)

## Extension loader + SPA serving

At startup, `extensions_loader.load_app_extensions()` discovers and loads any extensions present in `../extensions/`. Extensions register hooks via `shilljudge_core.hooks.registry`.

The built React frontend (`../frontend/dist/`) is mounted at `/` via `StaticFiles(html=True)` so the FastAPI server also serves the SPA. Set `FRONTEND_DIST` env var to override the dist path.

## Environment

Copy `app/.env.example` to `app/.env` and fill in `X_CLIENT_ID`, `X_CLIENT_SECRET`, and `SESSION_SECRET`. `DB_PATH=shilljudge.db` is set by default.

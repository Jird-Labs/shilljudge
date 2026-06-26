# Unify into a self-contained ShillJudge monorepo (retire thread-helper) — Design

**Date:** 2026-06-26
**Status:** Approved (design); pending implementation plan
**Related Linear:** Phase 0/1 of the ShillJudge project. Effectively the unfinished other half of **DEV-7** (whose dedup acceptance was never met). Subsumes completion of **DEV-25**. A new Linear issue should track this migration.

## Goal

Turn the repository into a **single, self-contained, ShillJudge-branded, runnable open-source application** with **no external git repos** and **no "thread-helper" references**. Anyone can clone the repo and run the full free product with one command. Premium features remain out of scope here — they are stub-only extensions whose real code lives in a separate private repo (`shilljudge-premium`) and are loaded at runtime.

## Decisions (locked)

1. **One public repo for the free app.** Premium distribution is deferred; premium = runtime extensions, worthless without the core app. (Q1 = C)
2. **Keep the internal library boundary.** `core/` stays an importable library; the app is a thin layer on top. (Q2 = A)
3. **Clean-start git history.** Copy current working files into the monorepo as a fresh ShillJudge baseline; archive + delete the standalone `thread-helper` repo. (Q3 = A)
4. **Full scope.** The migration includes the library dedup, extension-loader wiring, and a production run path — not just relocate + rebrand.

## Current state (what we are migrating from)

- **`thread-helper/` is a separate nested git repo** (own `.git`, remote `github.com/Jird-Labs/thread-helper.git`), untracked by the monorepo. It holds **~42 uncommitted/untracked changes** across many in-flight issues (DEV-25, DEV-27, polling engine, Solana, etc.). None of this may be lost.
- **The root monorepo tracks only `core/` + `docs/`.** `extensions/` exists on disk but is **untracked**.
- **`core/`** is the `shilljudge_core` library; `core/CLAUDE.md` forbids FastAPI/X/React code in it.
- **DEV-7 was never actually completed:** `app/` (thread-helper/backend) still keeps **local duplicate** copies of `database.py`, `models.py`, `token_storage.py`, `utils.py`, diverged from core in both directions (see Findings).

## Target structure

```
shilljudge/                      the one public repo
├── core/                        shilljudge_core library (unchanged home)
│   └── src/shilljudge_core/     scoring, DB schema, contests, leaderboard,
│                                models, parse_post_id, auth primitives, hooks
├── app/                         FastAPI backend  ← thread-helper/backend
│   ├── app.py (main)            routes, OAuth, /submit, admin, scheduler, lifespan
│   ├── schemas.py               app-only request models (UpdateUserRequest, OverrideScoreRequest)
│   ├── x_client.py, engagement.py, solana_client.py, auth.py, config.py, hooks.py
│   ├── Containerfile            multi-stage: build frontend, serve via FastAPI
│   └── tests/
├── frontend/                    React/Vite UI    ← thread-helper/frontend
├── extensions/                  community + premium plugins (now TRACKED)
│   ├── loader.py                load_extensions(registry, enable_premium)
│   ├── community/               full impl examples (MIT)
│   └── premium/                 STUB manifests only (real code in shilljudge-premium)
├── docs/
├── compose.yaml                 root: builds + runs the whole app
├── pyproject.toml               uv workspace (members: core, app)
├── README.md                    ShillJudge-branded "run your first contest in 10 minutes"
└── LICENSE (MIT)
```

- **`app` imports `shilljudge_core`** via a **uv workspace** at the repo root (members: `core`, `app`). The library boundary stays intact so extensions hook into a clean core surface.
- **`extensions/` becomes tracked** — the loader + community examples + premium *stubs* are all safe to publish.
- The standalone `thread-helper` repo and its remote are **archived and deleted**.

## Migration route (ordered for zero data loss)

### A — Capture & branch
- Commit the entire current `thread-helper/` working tree to **its own repo** and push to its remote — an archival snapshot so all in-flight work (DEV-25 verified, DEV-27, polling, Solana) is recoverable. (`.env`, `*.db`, tokens stay gitignored and are not pushed.)
- Create a fresh migration branch in the monorepo off `main`.

### B — Relocate (allowlist copy)
- Copy `thread-helper/backend → app/` and `thread-helper/frontend → frontend/`, **excluding**: `.git`, `.env`, `*.db`, `x_oauth_tokens.json`, `uvicorn_*.txt`, `node_modules`, `.venv`, `__pycache__`, `dist`, `mcps/`, `terminals/`, editor/runtime junk.
- Bring `.env.example` (templated, empty values) and the relevant `.gitignore` rules into the monorepo.
- Start tracking `extensions/`.

### C — Library dedup (finish DEV-7) — test-gated
- Delete `app/`'s copies of `utils.py` (identical), `token_storage.py` (trivial import-style diff), `database.py`, and the shared portion of `models.py`.
- Switch ~20 import sites from `from database import …` / `from models import …` / `from utils import …` / `from token_storage import …` to `from shilljudge_core import …`.
- **Reconciliation rule — core must be a superset.** Before deleting `app/database.py`, diff it against `core/src/shilljudge_core/database.py` and confirm core contains every function/behavior the app relies on:
  - Core *re-introduces* `CALCULATE_SCORE` hook dispatch and the `thread_scores` metadata migration that the app copy currently lacks — both are safe/desirable.
  - DEV-25's `score_post` + `find_active_contest_thread_for_post` are already byte-identical in both copies.
  - Verify no app-only DB function (e.g. anything from DEV-27 weighted scoring / admin override) is lost; if any exists only in the app copy, land it in core first.
- Move the two app-only request models (`UpdateUserRequest`, `OverrideScoreRequest`) into `app/schemas.py`.
- **Gate:** the `app` test suite stays green. The re-enabled `CALCULATE_SCORE` dispatch is a no-op passthrough when no scorer hook is registered, so default behavior is unchanged.

### D — Wire the extension loader
- Call `load_extensions(registry, enable_premium=False)` in the app's `lifespan` startup so `extensions/community/*` auto-register their hooks and missing premium stubs are skipped gracefully (the loader is designed for this).
- Add a test proving a community extension's hook fires through the running app.
- `enable_premium` is driven by a setting/env (default `False` for the free self-host app).

### E — Production run path
- Multi-stage `app/Containerfile`: build the frontend (`npm run build` → `dist/`), then have **FastAPI serve the built `dist/` as static files**. API routes take precedence; the SPA is served same-origin, so no proxy is needed in production.
- Dev keeps the existing vite dev server + proxy.
- **Consolidate to a single root `compose.yaml`.** The two existing compose files — root `docker-compose.yml` (untracked) and `thread-helper/compose.yaml` (marked deprecated) — are removed in favor of one canonical root `compose.yaml`. `docker compose up` builds and runs the app and yields a real runnable product.

### F — Rebrand (~35–40 edits)
- `thread_helper.db → shilljudge.db` default (DB_PATH still overridable via env).
- `pyproject.toml` name → `shilljudge-app`; `frontend/package.json` name → `shilljudge-frontend` (regenerate lockfile).
- FastAPI `title`, HTML `<title>`, `AuthPage` `<h1>`, `Layout` nav label → **ShillJudge**.
- `compose.yaml` volume names + build context paths (`./thread-helper/backend` → `./app`, `./thread-helper/frontend` → `./frontend`).
- Both `CLAUDE.md` files (a new `app/CLAUDE.md` replacing thread-helper's; update `core/CLAUDE.md`'s "stay in apps like thread-helper" wording).
- READMEs: root README becomes the ShillJudge "run your first contest in 10 minutes" guide; update core-doc references to "thread-helper".

### G — Remove & finalize
- Delete the `thread-helper/` directory (archival snapshot already pushed in Step A).
- Remove any root `.gitignore` entry excluding `thread-helper`/`app`.
- **Verification gates:**
  - `cd core && uv run pytest` → all pass
  - `cd app && uv run python -m pytest` → all pass
  - `cd frontend && npm run build` → succeeds
  - `docker compose up` → app starts and serves the UI (smoke)
  - `grep -ri "thread.helper"` → returns nothing but intentional historical notes

## Findings that shaped this design (from completeness audit)

### De-risked
- **No premium code leak.** `extensions/premium/*` are stub manifests only (`requires_license: true`, implementation pointer to private `shilljudge-premium`). Safe to publish `extensions/` wholesale.
- **Licenses clean** (root + thread-helper both MIT, identical). **No CI** referencing the old repo. Only external-repo reference is `thread-helper/.git/config`, which disappears on deletion.

### Must-do operational
- **Real secrets live in `thread-helper/` working tree** (not git-tracked): `.env` (live X OAuth client id/secret), `x_oauth_tokens.json` (live access/refresh tokens), `thread_helper.db` (user data), `uvicorn_*.txt`. The allowlist copy (Step B) must exclude these. **Recommendation: rotate the X app secret + tokens** — they have been in plaintext on disk.
- Root `docker-compose.yml` hardcodes `./thread-helper/...` paths — repoint to `./app` / `./frontend`.
- Test `conftest.py` `sys.path.insert(...parent.parent)` hacks break on the move — fix paths or rely on workspace imports.

### Newly surfaced (now in scope, "Full")
1. **DEV-7 dedup never done** — handled by Step C.
2. **Extension loader inert** (`load_extensions()` never called) — handled by Step D.
3. **No production run path** (dev servers only) — handled by Step E.

## Risks & mitigations

| Risk | Mitigation |
| --- | --- |
| Data loss of uncommitted in-flight work | Archival commit + push of `thread-helper/` before any move (Step A) |
| Secret/token/DB leak into clean repo | Allowlist copy (Step B) + pre-commit `git status`/grep check for `.env`, tokens, `*.db` |
| Behavior drift from library dedup | Superset diff of `database.py` + green `app` suite as the gate (Step C) |
| Lost app-only logic (override/weighted) | Confirm core superset; land any app-only DB function in core before deleting app copy |
| Production serving regression | `docker compose up` smoke test (Step G) |

## Out of scope

- Building real premium modules (separate private repo / Phase 2 issues).
- Finishing the half-done Phase 1 feature issues beyond DEV-25 (they continue from their new `app/` location).
- Hosted/SaaS multi-tenant backend (Phase 3).

## Verification summary (definition of done)

- One self-contained public repo: `core/` + `app/` + `frontend/` + `extensions/`, no `thread-helper/`, no external-repo references.
- `app` imports `shilljudge_core` (no duplicate library files).
- Extension loader wired; a community extension hook demonstrably fires through the app.
- `docker compose up` runs the full ShillJudge app (production static serving).
- All test suites green; frontend builds; no residual "thread-helper" branding.

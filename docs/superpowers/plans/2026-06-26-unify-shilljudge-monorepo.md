# Unify into a self-contained ShillJudge monorepo (retire thread-helper) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fold the standalone `thread-helper` app into the monorepo as a self-contained, ShillJudge-branded, runnable open-source product (`core/` + `app/` + `frontend/` + `extensions/`) with no external git repos and no "thread-helper" references.

**Architecture:** A uv workspace at the repo root makes the FastAPI `app/` import the `shilljudge_core` library instead of vendoring copies of it. The app wires the extension loader at startup and serves the built React SPA as static files, so `docker compose up` runs the whole free product. The old `thread-helper/` nested repo is archived and deleted.

**Tech Stack:** Python 3.14 / FastAPI / slowapi / APScheduler / SQLite / xdk / uv (workspace); React / Vite / Tailwind; Docker/Podman compose.

## Global Constraints

- **Preserve the public scoring math exactly:** `score = max(valid + 300.0 * ratio, 0.0)` where `valid = interactions - low_follower_engagements`, `ratio = max((valid - low) / impressions, 0)` (0 when impressions ≤ 0). Core's `core/tests/test_database.py` must stay green.
- **Core stays a pure library:** no FastAPI/X/React/Solana code added to `core/` (per `core/CLAUDE.md`). This migration only *consumes* core from `app/`; it does not move app-layer code into core.
- **One shared hook registry:** `app/` and extensions must use `shilljudge_core.hooks.registry` (the same instance core's `database.py` dispatches `CALCULATE_SCORE` through). No local `hooks.py` mirror survives.
- **Never copy secrets/runtime junk into the monorepo:** exclude `.env`, `*.db`, `x_oauth_tokens.json`, `uvicorn_*.txt`, `node_modules`, `.venv`, `dist`, `__pycache__`, `mcps/`, `terminals/`, and the nested `.git`.
- **Run tests:** core → `cd core && uv run pytest`; app → `cd app && uv run python -m pytest` (the bare `pytest` shim resolves wrong on this machine — always use `python -m pytest`); frontend → `cd frontend && npm run build`.
- **Branding:** all user-visible strings and package names are "ShillJudge", never "thread-helper".

---

## File Structure

- `pyproject.toml` (root, NEW) — uv workspace declaring members `core`, `app`.
- `app/` (NEW, ← `thread-helper/backend/`) — FastAPI app: `app.py`, `auth.py`, `config.py`, `engagement.py`, `scheduler.py`, `solana_client.py`, `x_client.py`, `schemas.py` (NEW, app-only request models), `pyproject.toml`, `Containerfile`, `tests/`. No `database.py`/`models.py`/`utils.py`/`token_storage.py`/`hooks.py` (deleted — imported from core).
- `app/extensions_loader.py` (NEW) — locates the `extensions/` dir and calls `load_extensions`.
- `frontend/` (NEW, ← `thread-helper/frontend/`) — React SPA; `vite.config.js`, `Containerfile`, `index.html`, `src/`.
- `extensions/` (now TRACKED) — `loader.py`, `community/`, `premium/` (stubs), `tests/`.
- `compose.yaml` (root) — single canonical compose; builds `app` (multi-stage incl. frontend), serves SPA + API.
- `core/` — unchanged except a one-line `CLAUDE.md` wording tweak (Task 7).
- Deleted at the end: `thread-helper/`, root `docker-compose.yml`.

---

### Task 1: Archive the thread-helper snapshot and create the migration branch

Safety first: capture all uncommitted in-flight work (DEV-25 verified, DEV-27, polling, Solana) to the old repo's remote so nothing is recoverable-only-locally, then branch the monorepo.

**Files:** none in the monorepo yet (procedural).

- [ ] **Step 1: Snapshot + push the thread-helper working tree to its own remote**

```bash
cd thread-helper
git add -A
git commit -m "chore: archival snapshot before monorepo migration (DEV-25/27 + in-flight work)"
git push origin HEAD
git rev-parse HEAD   # record this archive SHA
```

Expected: a new commit pushed to `github.com/Jird-Labs/thread-helper`. `.env`, `*.db`, `x_oauth_tokens.json` stay untracked (gitignored) and are NOT pushed — verify with `git status --short` showing them still untracked/ignored.

- [ ] **Step 2: Create the migration branch in the monorepo**

```bash
cd ..
git checkout main
git pull --ff-only || true
git checkout -b jird/unify-shilljudge-monorepo
git branch --show-current
```

Expected: on branch `jird/unify-shilljudge-monorepo`.

- [ ] **Step 3: Verify the archive is complete**

```bash
cd thread-helper && git status --short && cd ..
```

Expected: only ignored junk (`.env`, `*.db`, `x_oauth_tokens.json`, `uvicorn_*.txt`) remains uncommitted; all source/tests are committed. Do not commit anything in the monorepo in this task.

---

### Task 2: Relocate backend→`app/` and frontend→`frontend/` (allowlist copy); track `extensions/`

Pure relocation. App keeps its local `database.py`/etc. for now (dedup is Task 4), so imports are unchanged and tests pass against the moved files.

**Files:**
- Create: `app/**` (from `thread-helper/backend/**`), `frontend/**` (from `thread-helper/frontend/**`)
- Track: `extensions/**`

- [ ] **Step 1: Copy backend → `app/` excluding secrets/junk**

```bash
mkdir -p app
# source files
cp thread-helper/backend/*.py app/
cp thread-helper/backend/pyproject.toml thread-helper/backend/uv.lock app/
cp thread-helper/backend/.env.example thread-helper/backend/.python-version app/
cp thread-helper/backend/.containerignore thread-helper/backend/Containerfile thread-helper/backend/README.md app/
mkdir -p app/tests
cp thread-helper/backend/tests/*.py app/tests/
# EXCLUDE: .env, *.db, x_oauth_tokens.json, uvicorn_*.txt, .venv, __pycache__
rm -f app/uvicorn_out.txt app/uvicorn_err.txt
ls app
```

Expected: `app/` contains `app.py auth.py config.py database.py engagement.py hooks.py models.py scheduler.py solana_client.py token_storage.py utils.py x_client.py pyproject.toml uv.lock Containerfile README.md .env.example` and `app/tests/`. No `.env`, `.db`, `x_oauth_tokens.json`, or `uvicorn_*` files.

- [ ] **Step 2: Copy frontend → `frontend/` excluding node_modules/dist**

```bash
mkdir -p frontend
cp -r thread-helper/frontend/src frontend/src
cp thread-helper/frontend/index.html frontend/package.json frontend/package-lock.json frontend/
cp thread-helper/frontend/vite.config.js frontend/postcss.config.js frontend/tailwind.config.js frontend/Containerfile frontend/
ls frontend
```

Expected: `frontend/` has `src/ index.html package.json package-lock.json vite.config.js postcss.config.js tailwind.config.js Containerfile`. No `node_modules/` or `dist/`.

- [ ] **Step 3: Verify the relocated app still passes (local files, unchanged imports)**

```bash
cd app && uv sync && uv run python -m pytest -q; cd ..
```

Expected: PASS (105+ tests). The app still imports its local `database.py` etc.; nothing wired to core yet.

- [ ] **Step 4: Verify the relocated frontend builds**

```bash
cd frontend && npm install && npm run build; cd ..
```

Expected: build succeeds, `frontend/dist/` produced.

- [ ] **Step 5: Stage and commit (track app/, frontend/, extensions/)**

```bash
printf '\ndist/\nnode_modules/\n.venv/\n__pycache__/\n*.db\n.env\nx_oauth_tokens.json\nuvicorn_*.txt\n' >> .gitignore
git add .gitignore app frontend extensions
git status --short | grep -E "\.env$|\.db$|x_oauth_tokens|uvicorn_" && echo "SECRET LEAK — ABORT" || echo "no secrets staged"
git commit -m "feat: relocate thread-helper into app/ + frontend/; track extensions/"
```

Expected: "no secrets staged"; commit succeeds with `app/`, `frontend/`, `extensions/` added.

---

### Task 3: Root uv workspace; make `shilljudge_core` importable from `app/`

**Files:**
- Create: `pyproject.toml` (root)
- Modify: `app/pyproject.toml`

**Interfaces:**
- Produces: `shilljudge_core` importable in the `app` environment (enables Task 4's import rewrite).

- [ ] **Step 1: Create the root workspace `pyproject.toml`**

```toml
[tool.uv.workspace]
members = ["core", "app"]
```

- [ ] **Step 2: Add `shilljudge-core` as a workspace dependency of the app**

In `app/pyproject.toml`, add `"shilljudge-core"` to `dependencies` and a workspace source. Result:

```toml
[project]
name = "thread-helper-backend"
version = "0.1.0"
description = "Add your description here"
readme = "README.md"
requires-python = ">=3.14"
dependencies = [
    "apscheduler>=3.10",
    "fastapi[standard]>=0.136.3",
    "itsdangerous>=2.2.0",
    "pydantic-settings>=2.0.0",
    "shilljudge-core",
    "slowapi>=0.1.9",
    "xdk>=0.9.0",
]

[tool.uv.sources]
shilljudge-core = { workspace = true }

[dependency-groups]
dev = [
    "httpx>=0.27.0",
    "pytest>=8.0.0",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

(The `name` field is rebranded later in Task 7.)

- [ ] **Step 3: Sync and verify core is importable**

```bash
uv sync
cd app && uv run python -c "import shilljudge_core; print('core OK', shilljudge_core.__file__)"; cd ..
```

Expected: prints "core OK …/core/src/shilljudge_core/__init__.py".

- [ ] **Step 4: Confirm app tests still green**

```bash
cd app && uv run python -m pytest -q; cd ..
```

Expected: PASS (still using local dup files; this task only made core *available*).

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml app/pyproject.toml app/uv.lock uv.lock
git commit -m "build: uv workspace; app depends on shilljudge-core"
```

---

### Task 4: Library dedup — delete app's vendored copies, import from `shilljudge_core`

The risky, test-gated core of the migration. Core is a verified **superset** of the app copies (it adds `metadata` columns + migrations and the `CALCULATE_SCORE` dispatch; DEV-25/DEV-27 functions are identical in both). Switching imports re-enables the (currently absent) scoring-hook dispatch — a no-op when no scorer hook is registered.

**Files:**
- Create: `app/schemas.py`
- Delete: `app/database.py`, `app/models.py`, `app/utils.py`, `app/token_storage.py`, `app/hooks.py`, `app/tests/test_database.py`, `app/tests/test_url_parsing.py`
- Modify (imports): `app/app.py`, `app/auth.py`, `app/engagement.py`, `app/tests/conftest.py`, `app/tests/test_api.py`, `app/tests/test_public_submit.py`, `app/tests/test_rescore_override.py`, `app/tests/test_scheduler.py`

**Interfaces:**
- Consumes: `shilljudge_core.database.*`, `shilljudge_core.models.*`, `shilljudge_core.utils.parse_post_id`, `shilljudge_core.token_storage.*`, `shilljudge_core.hooks.{registry, ON_SUBMISSION, ENRICH_LEADERBOARD, CALCULATE_SCORE}`.
- Produces: `app.schemas.UpdateUserRequest`, `app.schemas.OverrideScoreRequest`.

- [ ] **Step 1: Pre-flight superset check (must show core lacks nothing the app needs)**

```bash
diff core/src/shilljudge_core/database.py app/database.py
diff core/src/shilljudge_core/models.py app/models.py
```

Expected: `database.py` diff shows ONLY core-additions (docstring, `from .hooks import CALCULATE_SCORE, registry`, `metadata` columns + `_add_missing_columns` for them, the `registry.call(CALCULATE_SCORE, ...)` line, DB_PATH default `shilljudge_core.db` vs `thread_helper.db`, EOF newline). `models.py` diff shows ONLY app-additions `UpdateUserRequest` + `OverrideScoreRequest`. If any *app-only* function appears in `database.py`, STOP and land it in core first.

- [ ] **Step 2: Create `app/schemas.py` with the two app-only request models**

```python
"""App-layer request models not part of the shilljudge-core foundation surface."""
from typing import Literal

from pydantic import BaseModel, Field


class UpdateUserRequest(BaseModel):
    is_admin: bool | None = None
    participation_status: Literal["active", "suspended"] | None = None


class OverrideScoreRequest(BaseModel):
    """Admin manual score override. ``override_score=None`` clears the override and
    reverts the thread to its computed score."""
    override_score: float | None = None
    note: str = Field(default="", max_length=500, description="Audit reason for the override")
```

- [ ] **Step 3: Delete the vendored duplicates and the core-duplicating tests**

```bash
git rm app/database.py app/models.py app/utils.py app/token_storage.py app/hooks.py
git rm app/tests/test_database.py app/tests/test_url_parsing.py
```

(The DB layer and URL parsing are covered by `core/tests/test_database.py` and `core/tests/test_url_parsing.py`.)

- [ ] **Step 4: Rewrite imports in `app/app.py`**

Replace the import block (current lines 24–76) module paths:
- `from database import (` → `from shilljudge_core.database import (` (keep the exact symbol list lines 27–59 unchanged).
- `from hooks import ENRICH_LEADERBOARD, ON_SUBMISSION, registry` → `from shilljudge_core.hooks import ENRICH_LEADERBOARD, ON_SUBMISSION, registry`
- `from token_storage import load_user_token, save_user_token` → `from shilljudge_core.token_storage import load_user_token, save_user_token`
- `from utils import parse_post_id` → `from shilljudge_core.utils import parse_post_id`
- Split the models import. Replace:
  ```python
  from models import (
      ConfirmSubmissionRequest,
      CreateContestRequest,
      OverrideScoreRequest,
      PreviewSubmissionRequest,
      UpdateContestRequest,
      UpdateUserRequest,
      WalletRequest,
  )
  ```
  with:
  ```python
  from shilljudge_core.models import (
      ConfirmSubmissionRequest,
      CreateContestRequest,
      PreviewSubmissionRequest,
      UpdateContestRequest,
      WalletRequest,
  )
  from schemas import OverrideScoreRequest, UpdateUserRequest
  ```
- Leave the optional seed shim (lines ~89–94 `from shilljudge_core.seed import seed_db` in try/except) as-is: core ships `shilljudge_core.seed` (see `core/pyproject.toml`'s `shilljudge-seed` script), so the import now succeeds when `SEED_DB=1` and is a harmless no-op otherwise.

- [ ] **Step 5: Rewrite imports in `app/auth.py` and `app/engagement.py`**

- `app/auth.py:12` `from database import get_user` → `from shilljudge_core.database import get_user`
- `app/auth.py:13` `from token_storage import load_user_token, save_user_token` → `from shilljudge_core.token_storage import load_user_token, save_user_token`
- `app/engagement.py:15` `from database import upsert_user_data` → `from shilljudge_core.database import upsert_user_data`

- [ ] **Step 6: Rewrite imports in the remaining app tests**

In each file, repoint `database`/`hooks` to core:
- `app/tests/conftest.py:9` `import database` → `from shilljudge_core import database`
- `app/tests/test_api.py` lines 7–8 → `from shilljudge_core import database` and `from shilljudge_core.database import create_contest`. Any `from hooks import ...` → `from shilljudge_core.hooks import ...`.
- `app/tests/test_public_submit.py` lines 6,8 → `from shilljudge_core import database`, `from shilljudge_core.database import create_contest`. Any `from hooks import registry, ON_SUBMISSION` → `from shilljudge_core.hooks import registry, ON_SUBMISSION`.
- `app/tests/test_rescore_override.py:7` `import database` → `from shilljudge_core import database`
- `app/tests/test_scheduler.py` lines 13,15 → `from shilljudge_core import database`, `from shilljudge_core.database import create_contest, create_thread, upsert_post_data`

- [ ] **Step 7: Run app tests (gate)**

```bash
cd app && uv run python -m pytest -q; cd ..
```

Expected: PASS. If a test registers a `CALCULATE_SCORE` handler it would now actually fire — verify any such test still asserts correctly; with no handler registered, scores are unchanged.

- [ ] **Step 8: Run core tests (must remain green)**

```bash
cd core && uv run pytest -q; cd ..
```

Expected: PASS (104+).

- [ ] **Step 9: Commit**

```bash
git add app/ && git commit -m "refactor: app imports shilljudge_core; delete vendored db/models/utils/token_storage/hooks (finishes DEV-7)"
```

---

### Task 5: Wire the extension loader into app startup

`extensions/loader.py` exists but is never called. Wire it so `extensions/community/*` hooks auto-register into the shared `shilljudge_core.hooks.registry` at startup, with premium gated by the core feature flag.

**Files:**
- Create: `app/extensions_loader.py`, `app/tests/test_extensions_wiring.py`
- Modify: `app/app.py` (lifespan)

**Interfaces:**
- Consumes: `shilljudge_core.hooks.registry`, `shilljudge_core.feature_flags.get_feature_flags`, `extensions/loader.py:load_extensions`.
- Produces: `app.extensions_loader.load_app_extensions() -> list[dict]`.

- [ ] **Step 1: Write the failing test**

`app/tests/test_extensions_wiring.py`:

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def test_community_extension_hook_registers(test_db, monkeypatch, tmp_path):
    from shilljudge_core.hooks import registry, ENRICH_LEADERBOARD
    import extensions_loader

    # Point the loader at a temp extensions dir with one community extension.
    ext = tmp_path / "extensions" / "community" / "demo"
    ext.mkdir(parents=True)
    (ext / "manifest.json").write_text(
        '{"name":"demo","version":"1.0.0","hooks":["enrich_leaderboard"],"requires_license":false}',
        encoding="utf-8",
    )
    (ext / "hooks.py").write_text(
        "def register(reg):\n    reg.register('enrich_leaderboard', lambda rows, ctx=None: rows)\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("EXTENSIONS_DIR", str(tmp_path / "extensions"))

    before = len(registry._handlers.get(ENRICH_LEADERBOARD, []))
    loaded = extensions_loader.load_app_extensions()
    after = len(registry._handlers.get(ENRICH_LEADERBOARD, []))
    assert any(m["name"] == "demo" for m in loaded)
    assert after == before + 1
```

(`HookRegistry` stores handlers in the private `_handlers` dict — there is no public introspection method; counting `_handlers[name]` is the supported way in tests.)

- [ ] **Step 2: Run it to verify it fails**

```bash
cd app && uv run python -m pytest tests/test_extensions_wiring.py -q; cd ..
```

Expected: FAIL — `ModuleNotFoundError: No module named 'extensions_loader'`.

- [ ] **Step 3: Implement `app/extensions_loader.py`**

```python
"""Locate the repo's extensions/ directory and load its community hooks into core's
shared registry. Premium stubs are surfaced only when the premium feature flag is on."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from typing import Any

from shilljudge_core.feature_flags import get_feature_flags
from shilljudge_core.hooks import registry


def _extensions_dir() -> Path:
    override = os.environ.get("EXTENSIONS_DIR")
    if override:
        return Path(override)
    return Path(__file__).resolve().parent.parent / "extensions"


def load_app_extensions() -> list[dict[str, Any]]:
    ext_dir = _extensions_dir()
    loader_path = ext_dir / "loader.py"
    if not loader_path.exists():
        return []
    spec = importlib.util.spec_from_file_location("_shilljudge_ext_loader", loader_path)
    if spec is None or spec.loader is None:
        return []
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.load_extensions(registry, enable_premium=get_feature_flags().enable_premium)
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd app && uv run python -m pytest tests/test_extensions_wiring.py -q; cd ..
```

Expected: PASS.

- [ ] **Step 5: Call it from the app lifespan**

In `app/app.py`'s `lifespan`, after `init_db()` and before `start_scheduler(...)`, add:

```python
    from extensions_loader import load_app_extensions
    loaded = load_app_extensions()
    logger.info("Loaded %d extension(s): %s", len(loaded), [m.get("name") for m in loaded])
```

- [ ] **Step 6: Full app suite + commit**

```bash
cd app && uv run python -m pytest -q; cd ..
git add app/ && git commit -m "feat: wire extension loader into app startup (community hooks auto-register)"
```

Expected: PASS.

---

### Task 6: Production run path — FastAPI serves the built SPA; multi-stage image

Make `docker compose up` yield a real product: build the frontend and serve `dist/` from FastAPI (same origin → no proxy in prod). Dev keeps the vite proxy.

**Files:**
- Modify: `app/app.py` (mount static, SPA fallback), `app/Containerfile`, root `compose.yaml`
- Create: `app/tests/test_static_serving.py`

- [ ] **Step 1: Write the failing test (SPA served at `/` when dist exists)**

`app/tests/test_static_serving.py`:

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def test_root_serves_spa_when_dist_present(monkeypatch, tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><title>ShillJudge</title>", encoding="utf-8")
    monkeypatch.setenv("FRONTEND_DIST", str(dist))

    from fastapi.testclient import TestClient
    import importlib, app as app_module
    importlib.reload(app_module)  # re-evaluate the static mount with FRONTEND_DIST set
    # No `with` block: we exercise routing/static only, not the lifespan/scheduler.
    resp = TestClient(app_module.app).get("/")
    assert resp.status_code == 200
    assert "ShillJudge" in resp.text
```

(Module import does not require env or DB — `settings = get_settings()` only constructs defaults; the env checks live in `lifespan`, which a bare `TestClient` request does not trigger.)

- [ ] **Step 2: Run it to verify it fails**

```bash
cd app && uv run python -m pytest tests/test_static_serving.py -q; cd ..
```

Expected: FAIL (root returns 404 / no static mount).

- [ ] **Step 3: Mount static SPA in `app/app.py`**

After all API routes are registered (near the end of the module, after the last `@app.<method>` route), add:

```python
import os as _os
from pathlib import Path as _Path
from fastapi.staticfiles import StaticFiles

_dist = _Path(_os.environ.get("FRONTEND_DIST", _Path(__file__).resolve().parent.parent / "frontend" / "dist"))
if _dist.is_dir():
    # html=True serves index.html for unknown paths (SPA client routing).
    app.mount("/", StaticFiles(directory=str(_dist), html=True), name="spa")
```

This must come AFTER API routes so `/leaderboard`, `/submit`, etc. win over the catch-all mount.

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd app && uv run python -m pytest tests/test_static_serving.py -q && uv run python -m pytest -q; cd ..
```

Expected: PASS (the static test and the full suite — API routes still resolve because they're registered before the mount).

- [ ] **Step 5: Rewrite `app/Containerfile` as a multi-stage prod image**

```dockerfile
# ---- frontend build ----
FROM node:20-slim AS frontend
WORKDIR /fe
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build           # -> /fe/dist

# ---- python runtime ----
FROM ghcr.io/astral-sh/uv:latest AS uv-source
FROM python:3.14-slim
COPY --from=uv-source /uv /uvx /bin/
WORKDIR /app
# workspace: core + app
COPY pyproject.toml uv.lock ./
COPY core/ ./core/
COPY app/ ./app/
RUN uv sync --frozen --no-dev --project app
COPY extensions/ ./extensions/
COPY --from=frontend /fe/dist ./frontend/dist
ENV FRONTEND_DIST=/app/frontend/dist
ENV EXTENSIONS_DIR=/app/extensions
WORKDIR /app/app
RUN mkdir -p /app/data
CMD ["uv", "run", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
```

Note: this Containerfile's build context is the **repo root** (it copies `core/`, `app/`, `extensions/`, `frontend/`). The compose `build.context` is set accordingly in Step 6.

- [ ] **Step 6: Replace root compose with a single canonical `compose.yaml`**

Create `compose.yaml` at repo root (one service; SPA + API same origin):

```yaml
# ShillJudge — self-hostable open-core app (core + community extensions).
# Premium extensions require a licensed host — see extensions/premium/.
services:
  shilljudge:
    build:
      context: .
      dockerfile: app/Containerfile
    ports:
      - "8080:8080"
    volumes:
      - shilljudge-data:/app/data
    env_file: ./app/.env
    environment:
      DB_PATH: /app/data/shilljudge.db
      X_TOKEN_PATH: /app/data/x_oauth_tokens.json
      FRONTEND_URL: http://localhost:8080
      CORE_ENABLE_PREMIUM: "0"
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8080/')"]
      interval: 10s
      timeout: 5s
      retries: 5

volumes:
  shilljudge-data:
```

Delete the old root dev compose:

```bash
git rm docker-compose.yml
```

- [ ] **Step 7: Commit**

```bash
git add app/app.py app/Containerfile app/tests/test_static_serving.py compose.yaml
git commit -m "feat: production run path — FastAPI serves built SPA; multi-stage image; single compose.yaml"
```

(Manual smoke — optional, needs an `app/.env`: `docker compose up --build` then open `http://localhost:8080/`.)

---

### Task 7: Rebrand thread-helper → ShillJudge

**Files:** `app/pyproject.toml`, `app/app.py`, `frontend/package.json`, `frontend/index.html`, `frontend/src/pages/AuthPage.jsx`, `frontend/src/components/Layout.jsx`, `app/.env.example`, `app/README.md`, `core/CLAUDE.md`, `core/README.md`, `core/src/shilljudge_core/auth.py`, root `README.md`, new `app/CLAUDE.md`.

- [ ] **Step 1: Backend identifiers**

- `app/pyproject.toml:2` `name = "thread-helper-backend"` → `name = "shilljudge-app"`.
- `app/app.py:103` `FastAPI(title="thread-helper backend", ...)` → `FastAPI(title="ShillJudge", ...)`.

- [ ] **Step 2: Frontend identifiers + visible branding**

- `frontend/package.json:2` `"name": "thread-helper-frontend"` → `"shilljudge-frontend"`, then `cd frontend && npm install` to regenerate the lockfile name.
- `frontend/index.html:6` `<title>thread-helper</title>` → `<title>ShillJudge</title>`.
- `frontend/src/pages/AuthPage.jsx:11` `<h1>thread-helper</h1>` → `<h1>ShillJudge</h1>`.
- `frontend/src/components/Layout.jsx:31` nav `<span>thread-helper</span>` → `<span>ShillJudge</span>`.

- [ ] **Step 3: DB default filename**

In `app/.env.example`, set/append `DB_PATH=shilljudge.db` (so a bare `uv run` uses a ShillJudge-named DB rather than core's `shilljudge_core.db` default). Confirm no remaining `thread_helper.db` literals: `grep -rn "thread_helper.db" app/ frontend/`.

- [ ] **Step 4: Docs + CLAUDE.md**

- `core/CLAUDE.md`: change "stay in apps like thread-helper" → "stay in the app layer (`app/`)".
- `core/README.md` + `core/src/shilljudge_core/auth.py`: replace "thread-helper" example references with "the ShillJudge app (`app/`)".
- Replace `app/README.md` heading "# thread-helper backend" → "# ShillJudge App (backend)".
- Create `app/CLAUDE.md` (short): describes `app/` as the FastAPI layer that imports `shilljudge_core`, lists run commands (`cd app && uv run python -m pytest`, `uv run fastapi dev app.py`), and notes the extension loader + static-SPA serving.
- Rewrite root `README.md` as the ShillJudge "run your first contest in 10 minutes" guide referencing `compose.yaml`, `core/`, `app/`, `frontend/`, `extensions/`.

- [ ] **Step 5: Verify no stray branding remains, suites green**

```bash
grep -rin "thread.helper" --include='*.py' --include='*.js' --include='*.jsx' --include='*.json' --include='*.toml' --include='*.html' --include='*.md' --include='*.yaml' --include='*.yml' app frontend core compose.yaml README.md | grep -v node_modules
```

Expected: no matches except intentional historical notes in `docs/` (which we are not grepping). Then:

```bash
cd app && uv run python -m pytest -q; cd ../frontend && npm run build; cd ../core && uv run pytest -q; cd ..
```

Expected: all PASS / build OK.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "chore: rebrand thread-helper → ShillJudge across app, frontend, docs"
```

---

### Task 8: Remove `thread-helper/` and final verification

**Files:** delete `thread-helper/`.

- [ ] **Step 1: Confirm the archive exists on the remote (from Task 1) before deleting**

```bash
cd thread-helper && git log --oneline -1 && git status --short && cd ..
```

Expected: the archival commit is the latest; only ignored junk uncommitted. (Its remote push happened in Task 1.)

- [ ] **Step 2: Delete the nested repo directory**

```bash
rm -rf thread-helper
ls | grep thread-helper && echo "STILL PRESENT" || echo "removed"
```

Expected: "removed".

- [ ] **Step 3: Final verification gates**

```bash
cd core && uv run pytest -q; cd ..
cd app && uv run python -m pytest -q; cd ..
cd frontend && npm run build; cd ..
grep -rin "thread.helper" --include='*.py' --include='*.js' --include='*.jsx' --include='*.json' --include='*.toml' --include='*.html' --include='*.yaml' --include='*.yml' . | grep -v node_modules | grep -v '/docs/'
```

Expected: core PASS, app PASS, frontend build OK, and the grep returns nothing (no residual branding outside `docs/`).

- [ ] **Step 4: Manual compose smoke (optional but recommended)**

```bash
cp app/.env.example app/.env   # fill X creds if exercising OAuth
docker compose up --build -d
curl -fsS http://localhost:8080/ | grep -qi shilljudge && echo "SPA served" || echo "check serving"
docker compose down
```

Expected: the app starts and `/` serves the ShillJudge SPA.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "chore: remove thread-helper/ — monorepo is now self-contained"
```

---

## Self-review — spec coverage map

- "One public repo, `core/` + `app/` + `frontend/` + `extensions/`" → Tasks 2, 3 (structure + workspace).
- "`app` imports `shilljudge_core`, no duplicate library files" → Task 4.
- "Extension loader wired; community hook fires through the app" → Task 5.
- "Production run path; `docker compose up` runs the app (static SPA serving)" → Task 6.
- "Full ShillJudge rebrand, no thread-helper references" → Task 7 + Task 8 grep gate.
- "Clean-start git; archive + delete the standalone repo" → Task 1 (archive) + Task 8 (delete).
- "Exclude secrets/junk" → Task 2 allowlist copy + Task 2 Step 5 secret-leak guard.
- "Consolidate to one root `compose.yaml`" → Task 6 Step 6.
- "No premium leak" → premium stays stub-only; `extensions/premium/` already stubs (no code change needed).

## Out of scope (per spec)

- Building real premium modules (separate private repo).
- Finishing other half-done Phase 1 feature issues (they continue from `app/`).
- Hosted/SaaS multi-tenant backend (Phase 3).

## Non-code follow-ups (do separately, not part of this plan's commits)

- Create a Linear issue for this migration; note it completes the unfinished dedup half of **DEV-7** and folds in **DEV-25**. Correct DEV-7's status if its acceptance is now truly met.
- Rotate the X OAuth app secret + tokens that were found in plaintext in the old `thread-helper/` working tree.

# ShillJudge

Open-core platform for X (Twitter) thread contest judging and leaderboards. Self-host for free under MIT. The hosted platform adds DeepSeek AI review, private metrics, advanced bot filtering, and $NRSE/SOL access gating.

## Run your first contest in 10 minutes

```bash
# 1. Clone and configure
git clone https://github.com/jird-labs/shilljudge.git
cd shilljudge

cp app/.env.example app/.env
# Fill in X_CLIENT_ID, X_CLIENT_SECRET, SESSION_SECRET
# (from the X Developer Portal → your app → OAuth 2.0 settings)

# 2. Start everything with Docker Compose
docker compose up
```

Open **http://localhost:8080** — the first account that logs in becomes admin.

Create a contest via **Manage → Contests**, share the submission URL with participants, and watch the leaderboard update in real time.

## Monorepo layout

```
shilljudge/
├── core/          # Open-core library (MIT) — scoring, contests, DB, leaderboard
├── app/           # FastAPI backend — routes, X OAuth, extension loader, SPA serving
├── frontend/      # React + Vite SPA — leaderboard, submission form, admin UI
├── extensions/
│   ├── community/ # Open-source community extensions (any self-hosted instance)
│   └── premium/   # Manifests only (implementations in shilljudge-premium)
└── compose.yaml   # One-command self-hosted stack
```

## Development (without Docker)

**Backend + core:**

```bash
# Install workspace deps (from repo root)
uv sync

# Run backend in dev mode
cd app
uv run fastapi dev app.py --port 8080

# Run app tests
uv run python -m pytest

# Run core tests
cd ../core
uv run pytest
```

**Frontend:**

```bash
cd frontend
npm install
npm run dev      # Vite dev server on :5173, proxies /oauth → :8080
npm run build    # Production build → frontend/dist/ (served by FastAPI)
```

For local dev with X OAuth, set `X_REDIRECT_URI=http://localhost:5173/oauth/callback` and `FRONTEND_URL=http://localhost:5173` in `app/.env`, register the same callback URI in the X Developer Portal, and use the Vite proxy (the default setup).

## Feature flags

All premium surfaces default to off. Set via environment variables or `app/.env`.

| Variable | Default | Description |
|---|---|---|
| `CORE_ENABLE_PREMIUM` | `0` | Master switch for any premium surface |
| `CORE_ENABLE_PRIVATE_CONTESTS` | `0` | Private/hidden contests |
| `CORE_ENABLE_ADVANCED_BOT_FILTER` | `0` | ML-based bot filtering |
| `CORE_ENABLE_AI_SCORING` | `0` | DeepSeek LLM scoring pass |
| `CORE_ENABLE_TOKEN_GATING` | `1` | Wallet + $NRSE stake gating |

## Extensions

Community extensions in `extensions/community/` are fully open-source. Premium extension manifests in `extensions/premium/` declare hooks and license requirements — real implementations live in the private `shilljudge-premium` repository.

See `extensions/` for the loader API and example community extension.

## License

MIT — see [LICENSE](LICENSE).

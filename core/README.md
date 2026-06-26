# shilljudge-core

Open-core foundation (MIT) for X/Twitter thread contest judging and leaderboards.

This package provides the reusable data layer, public scoring, contest management, leaderboard computation, auth primitives, and feature flags used by the ShillJudge app (`app/`) and the premium hosted product.

See root [README.md](../README.md) for the overall project vision (open-core + premium hosted with AI, private metrics, advanced bot filtering, $NRSE/SOL access).

## Usage (from a consumer app)

```python
from shilljudge_core.database import init_db, get_leaderboard, create_contest
from shilljudge_core.feature_flags import get_feature_flags
from shilljudge_core.utils import parse_post_id

init_db()
flags = get_feature_flags()
print("premium enabled?", flags.enable_premium)
lb = get_leaderboard()
...
```

## Feature Flags (Phase 0)

All flags default safe for pure open-core public usage. Set `CORE_ENABLE_*=1` (or via .env) to opt into premium paths in consuming apps or future core-premium layers.

Current flags (see feature_flags.py):
- `enable_premium`
- `enable_private_contests`
- `enable_advanced_bot_filter`
- `enable_ai_scoring`
- `enable_token_gating`

## Development

```bash
cd core
uv sync
uv run pytest
```

The scoring formula, contest lifecycle, and leaderboard queries are owned here so they stay identical across all consumers.

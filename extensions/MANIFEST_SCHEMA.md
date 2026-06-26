# Extension Manifest Schema

Every extension — community or premium — must include a `manifest.json` at its directory root. The loader validates this file before importing any code.

---

## Required fields

| Field | Type | Description |
|---|---|---|
| `name` | string | Kebab-case unique identifier (e.g. `my-scorer`). Must match the directory name under `community/` or `premium/`. |
| `version` | string | Semantic version string (e.g. `1.0.0`). |
| `hooks` | array of strings | Hook names this extension handles. Community extensions must use names from the 8 core hooks (see below). Premium manifests may declare platform-specific hook names not in that set. |
| `requires_license` | boolean | `false` for community (MIT) extensions; `true` for premium. |

A missing or wrong-typed required field causes the extension to be skipped with a warning log — no exception is raised.

---

## Optional fields

| Field | Type | Description |
|---|---|---|
| `description` | string | Human-readable one-line summary. Recommended. |
| `author` | string | Author name or username. |
| `license` | string | SPDX license identifier (e.g. `MIT`). |
| `min_tier` | string | Minimum deployment tier. Only meaningful when `requires_license` is `true`. Allowed values: `hosted`, `enterprise`. |
| `config` | object | Declares user-configurable parameters. Each key is a parameter name; its value is an object with `type`, `default`, and `description`. The loader does not validate or inject these values — extensions read them from environment variables or a config block passed by the host app. |
| `implementation` | string | Informational hint for premium extensions pointing to the private implementation (e.g. `shilljudge-premium/deepseek-review-engine`). The loader never acts on this field. |

---

## Annotated example

```json
{
  "name": "my-scorer",
  "version": "1.0.0",
  "description": "Community example: boosts threads with high engagement.",
  "author": "community",
  "license": "MIT",
  "hooks": ["enrich_thread", "calculate_score"],
  "requires_license": false,
  "config": {
    "engagement_weight": {
      "type": "float",
      "default": 0.2,
      "description": "Fraction of base score added as engagement bonus."
    }
  }
}
```

---

## The 8 core hooks

Community extension manifests must only declare names from this set (enforced by the loader). Premium manifests are not hook-name-validated.

| Constant | Name string | Dispatch | Threaded argument |
|---|---|---|---|
| `ON_SUBMISSION` | `on_submission` | pipeline | `post_ids` (arg 0) — filter or transform the list before processing |
| `ENRICH_THREAD` | `enrich_thread` | pipeline | `thread` dict (arg 0) — augment metadata; return modified dict |
| `CALCULATE_SCORE` | `calculate_score` | pipeline | `score` (arg 1) — adjust final numeric score; return new value |
| `ENRICH_LEADERBOARD` | `enrich_leaderboard` | pipeline | `rows` list (arg 0) — add or modify columns; return modified list |
| `FORMAT_EXPORT` | `format_export` | pipeline | `data` (arg 0) — transform export payload; return modified value |
| `UI_SLOT` | `ui_slot` | collect | All returned dicts are merged; later handlers overwrite earlier keys |
| `WEBHOOK_SLOT` | `webhook_slot` | fire-and-forget | Return value ignored; one failure does not stop other handlers |
| `EVENT_BUS` | `event_bus` | fire-and-forget | Return value ignored; one failure does not stop other handlers |

**Pipeline hooks** pass the threaded argument through each handler in priority order — the output of one handler becomes the input of the next. A handler that raises is logged and skipped; the value at that point continues through remaining handlers.

**Core degrades cleanly**: if no handlers are registered for a hook, pipeline hooks return their threaded argument unchanged, collect hooks return `{}`, and fire-and-forget hooks are a no-op.

---

## Validation rules

- **Community extensions** (`requires_license: false`): every name in `hooks` must be one of the 8 core hook strings listed above. An unrecognised hook name causes the entire extension to be skipped.
- **Premium extensions** (`requires_license: true`): hook names are *not* validated — platform-specific names such as `on_stake_check` or `on_leaderboard_query` are permitted.
- The loader **never** imports a premium extension's `hooks.py` from this repository. The real implementation is loaded by the licensed host platform.

---

## `hooks.py` interface

Every community extension that registers handlers must define a top-level `register` function:

```python
from shilljudge_core.hooks import ENRICH_THREAD

def _handle_enrich_thread(thread: dict) -> dict:
    thread.setdefault("metadata", {})["my_ext"] = {"checked": True}
    return thread

def register(registry) -> None:
    registry.register(ENRICH_THREAD, _handle_enrich_thread, priority=50)
```

- `priority` controls handler ordering: lower values run first. The default is `0`; community extensions should use `50` to leave room for high-priority core handlers.
- Providing no `hooks.py` is valid — the manifest is still surfaced to the host app, but no handlers are wired.

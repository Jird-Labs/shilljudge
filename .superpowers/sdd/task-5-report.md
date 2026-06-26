# Task 5 Report: Wire Extension Loader into App Startup

## Status: DONE

## Commit

SHA: `0365c6f`
Subject: `feat: wire extension loader into app startup (community hooks auto-register)`

---

## TDD Evidence

### RED (Step 2)

Command:
```
cd app && uv run python -m pytest tests/test_extensions_wiring.py -q
```

Output:
```
FAILED tests/test_extensions_wiring.py::test_community_extension_hook_registers
ModuleNotFoundError: No module named 'extensions_loader'
1 failed, 7 warnings in 0.17s
```

### GREEN (Step 4)

Command:
```
cd app && uv run python -m pytest tests/test_extensions_wiring.py -q
```

Output:
```
1 passed, 7 warnings in 0.07s
```

---

## Implementation Notes

### Brief deviation (required to make test pass)

The brief's `load_app_extensions()` uses `loader_path = ext_dir / "loader.py"` where
`ext_dir = _extensions_dir()` (which respects the `EXTENSIONS_DIR` override). The test sets
`EXTENSIONS_DIR` to `tmp_path / "extensions"` — a temp dir that contains `community/demo/`
but NOT `loader.py`. The brief's code would return `[]` and fail the test.

Fix: always load `loader.py` from the canonical path relative to `extensions_loader.py`'s own
location (`Path(__file__).resolve().parent.parent / "extensions" / "loader.py"`), then patch
`module._EXTENSIONS_DIR = ext_dir` so community discovery respects the env override. In
production `ext_dir` equals the canonical dir so behaviour is identical. The deviation is
one line added and one path changed.

### Lifespan wiring diff (`app/app.py`)

```python
-    interval = max(_settings.poll_interval_seconds, 300)
-    start_scheduler(_poll_client, interval)
+    from extensions_loader import load_app_extensions
+    loaded = load_app_extensions()
+    logger.info("Loaded %d extension(s): %s", len(loaded), [m.get("name") for m in loaded])
+    interval = max(_settings.poll_interval_seconds, 300)
+    start_scheduler(_poll_client, interval)
```

Placed after `init_db()` (and the optional SEED_DB block), before `start_scheduler`.

---

## Full App Suite Result

Command:
```
cd app && uv run python -m pytest -q
```

Output:
```
81 passed, 7 warnings in 3.24s
```

No regressions. The real `extensions/community/example-meme-scorer` extension is now loaded
on every lifespan startup. It registers idempotent handlers (`ENRICH_LEADERBOARD` adds
`meme_bonus: 0`; `ENRICH_THREAD` tags metadata). No existing test asserts the absence of
`meme_bonus` or checks global handler counts, so all 81 pass.

One informational note: `test_leaderboard_base_response_has_no_premium_columns` has the
docstring "With no extensions loaded the hook is a no-op" — stale now (extensions ARE loaded),
but the assertion (`assert all("premium_flag" not in r ...)`) still holds because
`example-meme-scorer` adds `meme_bonus`, not `premium_flag`. Docstring is misleading; the
assertion is correct. Not reported as DONE_WITH_CONCERNS because no assertion fails.

---

## Files Created/Modified

- Created: `app/extensions_loader.py`
- Created: `app/tests/test_extensions_wiring.py`
- Modified: `app/app.py` (lifespan, +3 lines)

---

## Task 5 fix

### Changes applied (code review fixes)

1. **`app/extensions_loader.py` line 35** — Added assert guard immediately after `module._EXTENSIONS_DIR = ext_dir` and before `return module.load_extensions(...)`. Fails loudly if `loader.py` is refactored to no longer expose `_EXTENSIONS_DIR` as a patchable module global.

2. **`app/tests/test_api.py` line 315** — Updated stale docstring on `test_leaderboard_base_response_has_no_premium_columns`. Old: "With no extensions loaded the hook is a no-op; rows are unchanged." New: accurately notes extensions load at startup but no premium column (e.g. `premium_flag`) should appear; community extensions may add their own columns. Assertion logic unchanged.

3. **`app/app.py` line 94** — Added one-line comment on the `from extensions_loader import load_app_extensions` deferred import inside `lifespan` explaining why it is function-local.

### Commands run and output

```
cd app && uv run python -m pytest tests/test_extensions_wiring.py "tests/test_api.py::test_leaderboard_base_response_has_no_premium_columns" -v
```
Result: **2 passed, 7 warnings in 0.12s**

```
cd app && uv run python -m pytest -q
```
Result: **81 passed, 7 warnings in 3.13s**

No regressions.

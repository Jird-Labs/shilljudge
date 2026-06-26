"""Tests for the manifest-based extension loader."""

import json
import logging
from pathlib import Path

import pytest

from shilljudge_core.hooks import ENRICH_LEADERBOARD, ENRICH_THREAD, HookRegistry


@pytest.fixture
def registry():
    return HookRegistry()


def _write_community_ext(base: Path, name: str, hooks: list, requires_license: bool = False) -> Path:
    ext_dir = base / "community" / name
    ext_dir.mkdir(parents=True, exist_ok=True)
    (ext_dir / "manifest.json").write_text(
        json.dumps({"name": name, "version": "0.1.0", "hooks": hooks, "requires_license": requires_license}),
        encoding="utf-8",
    )
    return ext_dir


def _write_premium_ext(base: Path, name: str, hooks: list) -> Path:
    ext_dir = base / "premium" / name
    ext_dir.mkdir(parents=True, exist_ok=True)
    (ext_dir / "manifest.json").write_text(
        json.dumps({"name": name, "version": "0.1.0", "hooks": hooks, "requires_license": True}),
        encoding="utf-8",
    )
    return ext_dir


# ---------------------------------------------------------------------------
# End-to-end: real example-meme-scorer
# ---------------------------------------------------------------------------


def test_example_meme_scorer_end_to_end():
    """The real example-meme-scorer wires correctly and enriches threads."""
    import loader

    r = HookRegistry()
    manifests = loader.load_extensions(r, enable_premium=False)
    assert any(m["name"] == "example-meme-scorer" for m in manifests)
    result = r.call(ENRICH_THREAD, {})
    assert result == {"metadata": {"meme_scorer": {"checked": True}}}


def test_example_meme_scorer_both_hooks_end_to_end():
    """Both hook implementations produce correct output and core degrades cleanly without the extension."""
    import loader

    # 1. Fresh registry, load extensions
    r = HookRegistry()
    manifests = loader.load_extensions(r, enable_premium=False)
    assert any(m["name"] == "example-meme-scorer" for m in manifests)

    # 2. enrich_thread pipeline: metadata is populated
    thread = r.call(ENRICH_THREAD, {"id": "t1"})
    assert thread["metadata"]["meme_scorer"]["checked"] is True

    # 3. enrich_leaderboard pipeline: meme_bonus column added to each row
    rows = r.call(ENRICH_LEADERBOARD, [{"score": 100}])
    assert rows[0]["meme_bonus"] == 0

    # 4. Clean degradation: a registry with no extensions loaded returns input unchanged
    bare = HookRegistry()
    assert bare.call(ENRICH_THREAD, {"id": "t1"}) == {"id": "t1"}
    assert bare.call(ENRICH_LEADERBOARD, [{"score": 100}]) == [{"score": 100}]


# ---------------------------------------------------------------------------
# Valid community extension loads and wires
# ---------------------------------------------------------------------------


def test_valid_community_extension_wires(tmp_path, registry, monkeypatch):
    import loader

    ext_dir = _write_community_ext(tmp_path, "test-ext", ["enrich_thread"])
    (ext_dir / "hooks.py").write_text(
        "from shilljudge_core.hooks import ENRICH_THREAD\n"
        "def register(r): r.register(ENRICH_THREAD, lambda t: {**t, 'wired': True})\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(loader, "_EXTENSIONS_DIR", tmp_path)

    manifests = loader.load_extensions(registry)

    assert len(manifests) == 1
    assert manifests[0]["name"] == "test-ext"
    assert manifests[0]["_source"] == "community"
    assert manifests[0]["_available"] is True
    assert registry.call(ENRICH_THREAD, {}).get("wired") is True


def test_community_extension_without_hooks_py_is_still_loaded(tmp_path, registry, monkeypatch):
    import loader

    _write_community_ext(tmp_path, "manifest-only-ext", ["enrich_thread"])
    monkeypatch.setattr(loader, "_EXTENSIONS_DIR", tmp_path)

    manifests = loader.load_extensions(registry)

    assert len(manifests) == 1
    assert manifests[0]["name"] == "manifest-only-ext"


# ---------------------------------------------------------------------------
# Broken hooks.py skipped; others still load
# ---------------------------------------------------------------------------


def test_broken_hooks_py_skipped_with_warning_others_load(tmp_path, registry, monkeypatch, caplog):
    import loader

    good_dir = _write_community_ext(tmp_path, "good-ext", ["enrich_thread"])
    (good_dir / "hooks.py").write_text(
        "from shilljudge_core.hooks import ENRICH_THREAD\n"
        "def register(r): r.register(ENRICH_THREAD, lambda t: {**t, 'good': True})\n",
        encoding="utf-8",
    )
    bad_dir = _write_community_ext(tmp_path, "zzz-bad-ext", ["enrich_thread"])
    (bad_dir / "hooks.py").write_text("raise RuntimeError('broken')\n", encoding="utf-8")

    monkeypatch.setattr(loader, "_EXTENSIONS_DIR", tmp_path)

    with caplog.at_level(logging.WARNING, logger="loader"):
        manifests = loader.load_extensions(registry)

    assert len(manifests) == 1
    assert manifests[0]["name"] == "good-ext"
    assert "zzz-bad-ext" in caplog.text


def test_hooks_py_missing_register_function_skipped(tmp_path, registry, monkeypatch, caplog):
    import loader

    ext_dir = _write_community_ext(tmp_path, "no-register-ext", ["enrich_thread"])
    (ext_dir / "hooks.py").write_text("# no register function\n", encoding="utf-8")
    monkeypatch.setattr(loader, "_EXTENSIONS_DIR", tmp_path)

    with caplog.at_level(logging.WARNING, logger="loader"):
        manifests = loader.load_extensions(registry)

    assert manifests == []
    assert "no-register-ext" in caplog.text


# ---------------------------------------------------------------------------
# Premium extension stubs: discovered but not wired
# ---------------------------------------------------------------------------


def test_premium_hooks_py_never_imported(tmp_path, registry, monkeypatch):
    import loader

    _write_community_ext(tmp_path, "community-ext", ["enrich_thread"])
    p_dir = _write_premium_ext(tmp_path, "premium-ext", ["on_leaderboard_query"])
    (p_dir / "hooks.py").write_text(
        "def register(r): raise RuntimeError('premium hooks must not run')\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(loader, "_EXTENSIONS_DIR", tmp_path)

    manifests = loader.load_extensions(registry, enable_premium=True)

    premium = [m for m in manifests if m["_source"] == "premium"]
    assert len(premium) == 1
    assert premium[0]["_available"] is False


def test_enable_premium_false_excludes_premium_manifests(tmp_path, registry, monkeypatch):
    import loader

    _write_community_ext(tmp_path, "community-ext", ["enrich_thread"])
    _write_premium_ext(tmp_path, "premium-ext", ["on_leaderboard_query"])
    monkeypatch.setattr(loader, "_EXTENSIONS_DIR", tmp_path)

    manifests = loader.load_extensions(registry, enable_premium=False)

    assert all(m["_source"] == "community" for m in manifests)
    assert len(manifests) == 1


# ---------------------------------------------------------------------------
# Manifest validation
# ---------------------------------------------------------------------------


def test_invalid_manifest_missing_field_skipped(tmp_path, registry, monkeypatch, caplog):
    import loader

    ext_dir = tmp_path / "community" / "bad-manifest"
    ext_dir.mkdir(parents=True)
    # Missing requires_license
    (ext_dir / "manifest.json").write_text(
        json.dumps({"name": "bad-manifest", "version": "0.1.0", "hooks": ["enrich_thread"]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(loader, "_EXTENSIONS_DIR", tmp_path)

    with caplog.at_level(logging.WARNING, logger="loader"):
        manifests = loader.load_extensions(registry)

    assert manifests == []
    assert "bad-manifest" in caplog.text


def test_invalid_manifest_wrong_field_type_skipped(tmp_path, registry, monkeypatch, caplog):
    import loader

    ext_dir = tmp_path / "community" / "wrong-type-ext"
    ext_dir.mkdir(parents=True)
    # hooks should be a list, not a string
    (ext_dir / "manifest.json").write_text(
        json.dumps({"name": "wrong-type-ext", "version": "0.1.0", "hooks": "enrich_thread", "requires_license": False}),
        encoding="utf-8",
    )
    monkeypatch.setattr(loader, "_EXTENSIONS_DIR", tmp_path)

    with caplog.at_level(logging.WARNING, logger="loader"):
        manifests = loader.load_extensions(registry)

    assert manifests == []


def test_unknown_hook_in_community_manifest_skipped(tmp_path, registry, monkeypatch, caplog):
    import loader

    _write_community_ext(tmp_path, "bad-hook-ext", ["on_unknown_hook"])
    monkeypatch.setattr(loader, "_EXTENSIONS_DIR", tmp_path)

    with caplog.at_level(logging.WARNING, logger="loader"):
        manifests = loader.load_extensions(registry)

    assert manifests == []
    assert "bad-hook-ext" in caplog.text


def test_unknown_hook_not_validated_for_premium(tmp_path, registry, monkeypatch):
    """Premium manifests use platform-specific hooks outside core's known set — must not reject them."""
    import loader

    _write_premium_ext(tmp_path, "premium-with-platform-hook", ["on_stake_check"])
    monkeypatch.setattr(loader, "_EXTENSIONS_DIR", tmp_path)

    manifests = loader.load_extensions(registry, enable_premium=True)

    assert len(manifests) == 1
    assert manifests[0]["name"] == "premium-with-platform-hook"

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

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

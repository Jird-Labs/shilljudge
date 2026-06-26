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
    # loader.py always lives in the canonical extensions/ dir next to the repo root,
    # regardless of EXTENSIONS_DIR (which only redirects where community/ is discovered).
    loader_path = Path(__file__).resolve().parent.parent / "extensions" / "loader.py"
    if not loader_path.exists():
        return []
    spec = importlib.util.spec_from_file_location("_shilljudge_ext_loader", loader_path)
    if spec is None or spec.loader is None:
        return []
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # Allow tests (and deployment overrides) to redirect community/premium discovery.
    module._EXTENSIONS_DIR = ext_dir
    return module.load_extensions(registry, enable_premium=get_feature_flags().enable_premium)

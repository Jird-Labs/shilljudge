"""Public extension loader for ShillJudge.

Discovers and surfaces extension manifests from community/ and premium/.
Community extensions are fully usable. Premium extensions are stub manifests only —
real implementations live in shilljudge-premium (private, licensed).
"""
from __future__ import annotations

import importlib.util
import json
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_EXTENSIONS_DIR = Path(__file__).parent

_REQUIRED_FIELDS: dict[str, type] = {
    "name": str,
    "version": str,
    "hooks": list,
    "requires_license": bool,
}


def _load_manifest(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        log.warning("Failed to load manifest %s: %s", path, exc)
        return None


def _validate_manifest(
    manifest: dict[str, Any],
    known_hooks: frozenset,
    check_hook_names: bool,
) -> bool:
    ext_name = manifest.get("name", "<unknown>")
    for field, expected_type in _REQUIRED_FIELDS.items():
        value = manifest.get(field)
        if value is None or not isinstance(value, expected_type):
            log.warning("Extension %r: invalid or missing manifest field %r", ext_name, field)
            return False
    if check_hook_names:
        for hook_name in manifest["hooks"]:
            if hook_name not in known_hooks:
                log.warning(
                    "Extension %r: manifest declares unrecognised hook %r",
                    ext_name,
                    hook_name,
                )
                return False
    return True


def _wire_hooks(ext_dir: Path, ext_name: str, registry: Any) -> bool:
    hooks_path = ext_dir / "hooks.py"
    if not hooks_path.exists():
        return True
    try:
        module_name = f"_shilljudge_ext_{ext_name.replace('-', '_')}_hooks"
        spec = importlib.util.spec_from_file_location(module_name, hooks_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Could not create module spec for {hooks_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.register(registry)
        return True
    except Exception as exc:
        log.warning("Extension %r: failed to load or register hooks: %s", ext_name, exc)
        return False


def load_extensions(registry: Any, enable_premium: bool = False) -> list[dict[str, Any]]:
    """Return extension manifests available in this environment and wire community hooks.

    Community extensions are validated, and their hooks.py (if present) is imported and
    registered into ``registry``. Premium extension manifests are surfaced for
    introspection but hooks are never wired from this loader — they require a licensed
    implementation from shilljudge-premium loaded by the host platform.

    Args:
        registry: A ``HookRegistry`` instance to register community handlers into.
        enable_premium: pass ``get_feature_flags().enable_premium`` from the calling app.

    Returns:
        List of manifest dicts, each annotated with ``_source`` and ``_available``.
    """
    known_hooks: frozenset = registry.known_hooks
    loaded: list[dict[str, Any]] = []

    community_dir = _EXTENSIONS_DIR / "community"
    if community_dir.exists():
        for manifest_path in sorted(community_dir.glob("*/manifest.json")):
            manifest = _load_manifest(manifest_path)
            if manifest is None:
                continue
            if not _validate_manifest(manifest, known_hooks, check_hook_names=True):
                continue
            ext_dir = manifest_path.parent
            ext_name = manifest["name"]
            if not _wire_hooks(ext_dir, ext_name, registry):
                continue
            manifest["_source"] = "community"
            manifest["_available"] = True
            manifest["_path"] = str(ext_dir)
            loaded.append(manifest)
            log.info("Loaded community extension: %s", ext_name)

    if enable_premium:
        premium_dir = _EXTENSIONS_DIR / "premium"
        if premium_dir.exists():
            for manifest_path in sorted(premium_dir.glob("*/manifest.json")):
                manifest = _load_manifest(manifest_path)
                if manifest is None:
                    continue
                if not _validate_manifest(manifest, known_hooks, check_hook_names=False):
                    continue
                manifest["_source"] = "premium"
                manifest["_available"] = False  # Real impl loaded by licensed host only
                manifest["_path"] = str(manifest_path.parent)
                log.info(
                    "Discovered premium extension stub: %s (real impl not in this repo)",
                    manifest.get("name"),
                )
                loaded.append(manifest)

    return loaded

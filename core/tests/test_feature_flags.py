"""Phase 0 feature flag tests."""
import os
from unittest.mock import patch

import pytest

from shilljudge_core.feature_flags import FeatureFlags, get_feature_flags


def test_defaults_are_open_core_safe():
    # Fresh instance bypasses lru for test isolation
    flags = FeatureFlags(_env_file=None)
    assert flags.enable_premium is False
    assert flags.enable_private_contests is False
    assert flags.enable_advanced_bot_filter is False
    assert flags.enable_ai_scoring is False
    assert flags.enable_token_gating is True  # current foundation behavior


def test_env_prefix_core_enable_premium(monkeypatch):
    monkeypatch.setenv("CORE_ENABLE_PREMIUM", "1")
    # Clear cache so new settings are read
    get_feature_flags.cache_clear()
    flags = get_feature_flags()
    assert flags.enable_premium is True
    get_feature_flags.cache_clear()


def test_env_prefix_core_enable_token_gating_off(monkeypatch):
    monkeypatch.setenv("CORE_ENABLE_TOKEN_GATING", "0")
    get_feature_flags.cache_clear()
    flags = get_feature_flags()
    assert flags.enable_token_gating is False
    get_feature_flags.cache_clear()

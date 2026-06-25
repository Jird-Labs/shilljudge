"""Feature flags for core vs premium behavior (DEV-6).

Env vars are prefixed with CORE_ (e.g. CORE_ENABLE_PREMIUM=1).
All flags default to safe open-core / public behavior.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class FeatureFlags(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CORE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Phase 0 flags (enable future premium work without breaking self-host open-core)
    enable_premium: bool = Field(default=False, description="Master switch for any premium surface")
    enable_private_contests: bool = Field(default=False, description="Allow private/hidden contests")
    enable_advanced_bot_filter: bool = Field(
        default=False, description="Stricter or ML-based bot/low-follower filtering (beyond current engagement analysis)"
    )
    enable_ai_scoring: bool = Field(default=False, description="DeepSeek / LLM augmented scoring pass")
    enable_token_gating: bool = Field(
        default=True, description="Respect must_stake_token on contests + wallet gates (foundation today)"
    )


@lru_cache(maxsize=1)
def get_feature_flags() -> FeatureFlags:
    return FeatureFlags()

import re
from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_OAUTH1_USER_TOKEN_CLIENT_ID = re.compile(r"^\d{10,22}-[A-Za-z0-9_-]+$")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    x_client_id: str = Field(validation_alias="X_CLIENT_ID")
    x_client_secret: str = Field(validation_alias="X_CLIENT_SECRET")
    x_redirect_uri: str = Field(
        default="http://127.0.0.1:8080/oauth/callback",
        validation_alias="X_REDIRECT_URI",
    )
    # like.read is required for liking_users engagement analysis
    x_oauth_scopes: str = Field(
        default="tweet.read users.read like.read offline.access",
        validation_alias="X_OAUTH_SCOPES",
    )
    session_secret: str = Field(
        default="change-me-in-production-use-openssl-rand-hex-32",
        validation_alias="SESSION_SECRET",
    )
    frontend_url: str = Field(
        default="http://localhost:5173",
        validation_alias="FRONTEND_URL",
    )
    # Helius (or other) Solana RPC endpoint for stake checks
    solana_rpc_url: str = Field(
        default="",
        validation_alias="SOLANA_RPC_URL",
    )

    # Background metric-polling interval (seconds). Clamped to a 300s minimum at startup.
    poll_interval_seconds: int = Field(
        default=3600,
        validation_alias="POLL_INTERVAL_SECONDS",
    )

    rate_limit_submissions: str = Field(
        default="10/minute",
        validation_alias="RATE_LIMIT_SUBMISSIONS",
    )
    rate_limit_leaderboard: str = Field(
        default="60/minute",
        validation_alias="RATE_LIMIT_LEADERBOARD",
    )
    rate_limit_auth: str = Field(
        default="5/minute",
        validation_alias="RATE_LIMIT_AUTH",
    )

    @field_validator("x_client_id")
    @classmethod
    def oauth2_client_id_not_oauth1_token(cls, v: str) -> str:
        s = v.strip()
        if _OAUTH1_USER_TOKEN_CLIENT_ID.fullmatch(s):
            raise ValueError(
                "X_CLIENT_ID looks like an OAuth 1.0a *user access token* (digits-hyphen-secret), "
                "not an OAuth 2.0 Client ID. In the X Developer Portal open your app → "
                "User authentication settings (OAuth 2.0) and copy the OAuth 2.0 "
                '"Client ID" (often a short base64-like value), not keys from "Access token & secret".'
            )
        return s

    @property
    def oauth_scope_list(self) -> list[str]:
        return [s for s in self.x_oauth_scopes.split() if s]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

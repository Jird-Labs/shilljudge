from typing import Literal

from pydantic import BaseModel, Field


class CreateContestRequest(BaseModel):
    title: str = Field(..., min_length=1)
    description: str | None = Field(default=None)
    start_date: str = Field(..., description="YYYY-MM-DD")
    end_date: str = Field(..., description="YYYY-MM-DD")
    must_stake_token: bool = False
    prize: str | None = None
    thread_length: Literal[1, 3, 5, 7] = 1
    status: Literal["active", "ended", "archived"] = "active"
    # Per-metric weights feeding the base engagement count; non-negative, default 1.0 (no change).
    weight_likes: float = Field(default=1.0, ge=0)
    weight_retweets: float = Field(default=1.0, ge=0)
    weight_replies: float = Field(default=1.0, ge=0)
    weight_quotes: float = Field(default=1.0, ge=0)
    weight_bookmarks: float = Field(default=1.0, ge=0)
    weight_impressions: float = Field(default=1.0, ge=0)


class UpdateContestRequest(BaseModel):
    title: str | None = None
    description: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    must_stake_token: bool | None = None
    prize: str | None = None
    thread_length: Literal[1, 3, 5, 7] | None = None
    status: Literal["active", "ended", "archived"] | None = None
    weight_likes: float | None = Field(default=None, ge=0)
    weight_retweets: float | None = Field(default=None, ge=0)
    weight_replies: float | None = Field(default=None, ge=0)
    weight_quotes: float | None = Field(default=None, ge=0)
    weight_bookmarks: float | None = Field(default=None, ge=0)
    weight_impressions: float | None = Field(default=None, ge=0)


class PreviewSubmissionRequest(BaseModel):
    url: str = Field(..., min_length=1)


class ConfirmSubmissionRequest(BaseModel):
    post_ids: list[str] = Field(..., min_length=1, max_length=100)


class WalletRequest(BaseModel):
    wallet_address: str = Field(..., min_length=32, max_length=44)

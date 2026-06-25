"""Foundation Pydantic model tests — contest metric weight validation (DEV-24)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest
from pydantic import ValidationError

from shilljudge_core.models import CreateContestRequest, UpdateContestRequest


def test_create_contest_weights_default_to_one():
    req = CreateContestRequest(title="T", start_date="2025-01-01", end_date="2025-01-31")
    assert req.weight_likes == 1.0
    assert req.weight_impressions == 1.0


def test_create_contest_accepts_custom_weights():
    req = CreateContestRequest(
        title="T", start_date="2025-01-01", end_date="2025-01-31",
        weight_likes=2.5, weight_impressions=0.0,
    )
    assert req.weight_likes == 2.5
    assert req.weight_impressions == 0.0


def test_create_contest_rejects_negative_weight():
    with pytest.raises(ValidationError):
        CreateContestRequest(
            title="T", start_date="2025-01-01", end_date="2025-01-31",
            weight_likes=-0.1,
        )


def test_update_contest_rejects_negative_weight():
    with pytest.raises(ValidationError):
        UpdateContestRequest(weight_bookmarks=-1.0)

"""Tests for parse_post_id (extracted into shilljudge-core as a pure utility)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from shilljudge_core.utils import parse_post_id


def test_full_x_url_with_query_params():
    assert parse_post_id("https://x.com/testuser/status/1234567890123456789?s=20") == "1234567890123456789"


def test_full_x_url_without_query_params():
    assert parse_post_id("https://x.com/user/status/123456789") == "123456789"


def test_twitter_com_url():
    assert parse_post_id("https://twitter.com/user/status/987654321") == "987654321"


def test_mobile_twitter_url():
    assert parse_post_id("https://mobile.twitter.com/user/status/111222333") == "111222333"


def test_bare_numeric_id():
    assert parse_post_id("1234567890123456789") == "1234567890123456789"


def test_short_numeric_id():
    assert parse_post_id("123") == "123"


def test_invalid_text_returns_none():
    assert parse_post_id("not-a-url") is None


def test_empty_string_returns_none():
    assert parse_post_id("") is None


def test_non_status_url_returns_none():
    assert parse_post_id("https://example.com/page/123") is None


def test_url_with_trailing_whitespace():
    assert parse_post_id("  https://x.com/user/status/999888777  ") == "999888777"


def test_bare_id_with_whitespace():
    assert parse_post_id("  123456  ") == "123456"

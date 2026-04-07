"""Tests for normalize_event_id."""

import pytest

from unifi_protect_backup.utils import normalize_event_id


@pytest.mark.parametrize(
    "input_id, expected",
    [
        # Plain UUID — unchanged
        ("f9f5a34b-867d-4001-9b42-c3429c1785df", "f9f5a34b-867d-4001-9b42-c3429c1785df"),
        # Plain 24-char hex — unchanged
        ("69be9ae203c9f503e4357080", "69be9ae203c9f503e4357080"),
        # UUID with camera suffix — UUID only
        (
            "f9f5a34b-867d-4001-9b42-c3429c1785df-69be9ae203c9f503e4357080",
            "f9f5a34b-867d-4001-9b42-c3429c1785df",
        ),
        # Hex ID with suffix — hex only
        ("69be9ae203c9f503e4357080-abcdef", "69be9ae203c9f503e4357080"),
        # Already-truncated ID (old bug artifact) — passed through unchanged
        ("f9f5a34b", "f9f5a34b"),
        # Empty string — passed through unchanged
        ("", ""),
        # Garbage — passed through unchanged
        ("not-a-valid-id", "not-a-valid-id"),
        # Uppercase UUID — normalized correctly
        ("F9F5A34B-867D-4001-9B42-C3429C1785DF", "F9F5A34B-867D-4001-9B42-C3429C1785DF"),
    ],
)
def test_normalize_event_id(input_id, expected):
    assert normalize_event_id(input_id) == expected

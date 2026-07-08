"""Tests for the JSON-parsing helper in vision.py.

The Claude API call itself is not tested here (that requires an API key and
network). What we can and should test is the response-parsing tolerance:
the model occasionally wraps its output in a code fence or a stray sentence,
and we don't want that to crash extraction.
"""

import pytest

from app.vision import _parse_json


def test_parse_bare_json():
    raw = '{"brand_name": "Old Tom"}'
    assert _parse_json(raw) == {"brand_name": "Old Tom"}


def test_parse_fenced_json():
    raw = '```json\n{"brand_name": "Old Tom"}\n```'
    assert _parse_json(raw) == {"brand_name": "Old Tom"}


def test_parse_json_with_preamble():
    raw = 'Here is the extraction:\n{"brand_name": "Old Tom"}\nHope this helps!'
    assert _parse_json(raw) == {"brand_name": "Old Tom"}


def test_parse_no_json_raises():
    with pytest.raises(ValueError):
        _parse_json("Sorry, I can't help with that.")

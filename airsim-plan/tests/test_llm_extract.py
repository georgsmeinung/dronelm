"""Tests for JSON extraction helpers."""
from __future__ import annotations

from airsim_plan.llm import extract_json_object, looks_like_manifest


def test_extract_clean_json() -> None:
    raw = '{"mission_id": "FOO", "waypoints": []}'
    out = extract_json_object(raw)
    assert out == {
        "mission_id": "FOO",
        "waypoints": [],
    }


def test_extract_markdown_fenced_json() -> None:
    raw = (
        "```json\n"
        '{"mission_id": "FOO", "waypoints": []}\n'
        "```"
    )
    out = extract_json_object(raw)
    assert out["mission_id"] == "FOO"


def test_extract_with_preamble() -> None:
    raw = (
        "Aqui va el manifesto:\n"
        '{"mission_id": "FOO", "waypoints": []}\n'
        "Espero que sirva."
    )
    out = extract_json_object(raw)
    assert out is not None
    assert out["mission_id"] == "FOO"


def test_extract_unparseable_returns_none() -> None:
    assert extract_json_object("nada de nada") is None
    assert extract_json_object("") is None
    assert extract_json_object("[1, 2, 3]") is None  # not an object


def test_extract_picks_first_balanced_object() -> None:
    raw = '{"a": 1} bla bla {"mission_id": "FOO", "waypoints": []}'
    out = extract_json_object(raw)
    assert out is not None
    # The first balanced object that json.loads accepts is `{a:1}` which
    # is not a manifest, but looks_like_manifest is the caller's concern.
    assert out == {"a": 1}


def test_looks_like_manifest() -> None:
    assert looks_like_manifest({"mission_id": "X", "waypoints": []})
    assert not looks_like_manifest({"mission_id": "X"})
    assert not looks_like_manifest([])
    assert not looks_like_manifest(None)

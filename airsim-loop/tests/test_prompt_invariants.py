"""F2.1: la cantidad de etiquetas de fotograma ([Fotograma t-N]) en el mensaje

enviado al VLM debe ser siempre igual a la cantidad de imagenes efectivamente
adjuntadas. La version original afirmaba una historia temporal de 4 frames
([t-3]..[t]) mientras `frame_history` nunca se poblaba y solo se enviaba 1.
"""
from __future__ import annotations

from types import SimpleNamespace

import src.agents.deliberative as deliberative


class _FakeCompletions:
    def __init__(self, capture):
        self._capture = capture

    def create(self, **kwargs):
        self._capture.append(kwargs)
        msg = SimpleNamespace(content='{"macro_action": "MANTENER_RUMBO", "rationale": "ok"}')
        choice = SimpleNamespace(message=msg)
        return SimpleNamespace(choices=[choice])


class _FakeChat:
    def __init__(self, capture):
        self.completions = _FakeCompletions(capture)


class _FakeOpenAIClient:
    def __init__(self, *a, **k):
        self.chat = _FakeChat(_captured_calls)


_captured_calls: list = []


def _count_frame_labels(user_content) -> int:
    return sum(
        1 for item in user_content
        if isinstance(item, dict) and item.get("type") == "text" and "[Fotograma" in item.get("text", "")
    )


def _count_images(user_content) -> int:
    return sum(1 for item in user_content if isinstance(item, dict) and item.get("type") == "image_url")


def test_single_frame_has_no_temporal_labels(monkeypatch):
    global _captured_calls
    _captured_calls = []
    monkeypatch.setattr(deliberative, "OpenAI", _FakeOpenAIClient)
    monkeypatch.setattr(deliberative, "VLM_VISION_ENABLED", True)
    monkeypatch.setattr(deliberative, "VLM_USE_JSON_SCHEMA", False)

    deliberative._query_slm_impl({"prompt": "test", "images_b64": ["deadbeef"]})

    assert len(_captured_calls) == 1
    user_content = _captured_calls[0]["messages"][1]["content"]
    assert _count_images(user_content) == 1
    assert _count_frame_labels(user_content) == 0


def test_multi_frame_label_count_matches_image_count(monkeypatch):
    global _captured_calls
    _captured_calls = []
    monkeypatch.setattr(deliberative, "OpenAI", _FakeOpenAIClient)
    monkeypatch.setattr(deliberative, "VLM_VISION_ENABLED", True)
    monkeypatch.setattr(deliberative, "VLM_USE_JSON_SCHEMA", False)

    images = ["a", "b", "c"]
    deliberative._query_slm_impl({"prompt": "test", "images_b64": images})

    user_content = _captured_calls[0]["messages"][1]["content"]
    assert _count_images(user_content) == len(images)
    assert _count_frame_labels(user_content) == len(images)

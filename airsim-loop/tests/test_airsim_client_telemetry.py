# bug-fix 2026-0903: `cosysairsim` no expone `to_eularian_angles`
# (hasattr(airsim, "to_eularian_angles") da False), asi que
# `_state_to_telemetry` caia siempre en el fallback manual -- que hasta
# ahora solo calculaba `yaw` y dejaba pitch/roll hardcodeados en 0.0 para
# SIEMPRE con este backend. Encontrado al revisar por que el prompt del VLM
# mostraba "pitch=+0.0°, roll=+0.0°" en cada deliberacion de un vuelo real.
from __future__ import annotations

import math
from dataclasses import dataclass

import pytest

from src.hardware.airsim_client import _quaternion_to_euler


@dataclass
class _FakeQuaternion:
    w_val: float
    x_val: float
    y_val: float
    z_val: float


def test_pure_roll_quaternion_recovers_roll_not_zero():
    angle = math.radians(90.0)
    q = _FakeQuaternion(w_val=math.cos(angle / 2), x_val=math.sin(angle / 2), y_val=0.0, z_val=0.0)
    pitch, roll, yaw = _quaternion_to_euler(q)
    assert roll == pytest.approx(angle, abs=1e-6)
    assert pitch == pytest.approx(0.0, abs=1e-6)
    assert yaw == pytest.approx(0.0, abs=1e-6)


def test_pure_pitch_quaternion_recovers_pitch_not_zero():
    angle = math.radians(30.0)
    q = _FakeQuaternion(w_val=math.cos(angle / 2), x_val=0.0, y_val=math.sin(angle / 2), z_val=0.0)
    pitch, roll, yaw = _quaternion_to_euler(q)
    assert pitch == pytest.approx(angle, abs=1e-6)
    assert roll == pytest.approx(0.0, abs=1e-6)
    assert yaw == pytest.approx(0.0, abs=1e-6)


def test_pure_yaw_quaternion_still_correct():
    angle = math.radians(45.0)
    q = _FakeQuaternion(w_val=math.cos(angle / 2), x_val=0.0, y_val=0.0, z_val=math.sin(angle / 2))
    pitch, roll, yaw = _quaternion_to_euler(q)
    assert yaw == pytest.approx(angle, abs=1e-6)
    assert pitch == pytest.approx(0.0, abs=1e-6)
    assert roll == pytest.approx(0.0, abs=1e-6)


def test_identity_quaternion_is_level():
    q = _FakeQuaternion(w_val=1.0, x_val=0.0, y_val=0.0, z_val=0.0)
    pitch, roll, yaw = _quaternion_to_euler(q)
    assert (pitch, roll, yaw) == (0.0, 0.0, 0.0)

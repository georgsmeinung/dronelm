import math

import pytest

from src.agents.action_map import VALID_ACTIONS, action_to_command

REQUIRED_KEYS = {"macro_action", "vx", "vy", "vz", "yaw_rate", "target_yaw"}


@pytest.mark.parametrize("action", sorted(VALID_ACTIONS))
def test_every_valid_action_maps_to_bounded_command(action):
    cmd = action_to_command(action, guidance={}, telemetry={})
    assert REQUIRED_KEYS.issubset(cmd.keys())
    for key in ("vx", "vy", "vz", "yaw_rate"):
        val = cmd[key]
        assert isinstance(val, (int, float))
        assert not math.isnan(val)
        assert abs(val) < 30.0  # ninguna macro-accion produce velocidades desbocadas


def test_unknown_action_falls_back_to_frenar():
    cmd = action_to_command("ACCION_INEXISTENTE")
    assert cmd["macro_action"] == "FRENAR"
    assert cmd["vx"] == 0.0 and cmd["vy"] == 0.0 and cmd["vz"] == 0.0 and cmd["yaw_rate"] == 0.0


def test_evadir_derecha_snaps_to_manhattan_grid():
    cmd = action_to_command("EVADIR_DERECHA", telemetry={"orientation": {"yaw": 0.0}})
    assert cmd["target_yaw"] == pytest.approx(90.0)


def test_evadir_izquierda_snaps_to_manhattan_grid():
    cmd = action_to_command("EVADIR_IZQUIERDA", telemetry={"orientation": {"yaw": 0.0}})
    assert cmd["target_yaw"] == pytest.approx(-90.0)


def test_mantener_rumbo_uses_guidance_velocity():
    cmd = action_to_command("MANTENER_RUMBO", guidance={"vx": 3.3, "vz": -0.1, "yaw_rate": 2.0})
    assert cmd["vx"] == pytest.approx(3.3)
    assert cmd["vz"] == pytest.approx(-0.1)
    assert cmd["yaw_rate"] == pytest.approx(2.0)


def test_close_structural_reduces_lateral_speed():
    fast = action_to_command("EVADIR_DERECHA", close_structural=False)
    slow = action_to_command("EVADIR_DERECHA", close_structural=True)
    assert slow["vx"] < fast["vx"]

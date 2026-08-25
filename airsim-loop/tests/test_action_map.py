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


def test_ganar_altura_has_no_lateral_drift_and_keeps_aligning():
    """Regresion 2026-0824: GANAR_ALTURA llevaba `vy=0.5` (deriva lateral
    constante en una macro-accion de ascenso) y `yaw_rate=0`. En vuelo real
    eso ALEJABA el waypoint en el plano XY -- la misma metrica que decide si
    el atasco se resolvio -- y congelaba el rumbo a 60 grados del objetivo,
    de modo que el escape se alimentaba a si mismo.
    """
    cmd = action_to_command("GANAR_ALTURA", guidance={"yaw_rate": -12.0})
    assert cmd["vy"] == 0.0
    assert cmd["vx"] == 0.0
    assert cmd["vz"] < 0.0  # NED: sube
    assert cmd["yaw_rate"] == pytest.approx(-12.0)  # sigue alineando al waypoint


def test_girar_90_turns_toward_the_waypoint_side():
    """El giro de exploracion elige el lado por el error de rumbo, en vez de
    girar siempre a la derecha (que en vuelo mando al dron en contra del
    waypoint).
    """
    telemetry = {"orientation": {"yaw": 0.0}}
    left = action_to_command("GIRAR_90", guidance={"bearing_err_deg": -68.0}, telemetry=telemetry)
    right = action_to_command("GIRAR_90", guidance={"bearing_err_deg": 40.0}, telemetry=telemetry)
    default = action_to_command("GIRAR_90", telemetry=telemetry)

    assert left["yaw_rate"] < 0 and left["target_yaw"] == pytest.approx(-90.0)
    assert right["yaw_rate"] > 0 and right["target_yaw"] == pytest.approx(90.0)
    assert default["yaw_rate"] > 0  # sin guidance: comportamiento historico


def test_close_structural_reduces_lateral_speed():
    fast = action_to_command("EVADIR_DERECHA", close_structural=False)
    slow = action_to_command("EVADIR_DERECHA", close_structural=True)
    assert slow["vx"] < fast["vx"]

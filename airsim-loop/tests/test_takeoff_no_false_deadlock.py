"""Falso deadlock al despegar (2026-0930).

Secuencia real de citysim_pilot seed 99 173724Z c1-c20: el guiado ordena subir (vz=-0.8) y girar en
el lugar hacia el WP (vx=0) durante 15 ciclos. El contador de "detenido" llegaba a 15 y, al cruzar el
piso optico (4.5 m), stopped_prolonged disparaba el deadlock en c17.
"""
from __future__ import annotations

from src.agents.stall_detector import StallDetector


def _st(z, cmd_vx, act_v=0.0, vz=-0.8, yaw_rate=-30.0):
    return {
        "telemetry": {"position": {"x": 0.0, "y": 0.0, "z": z}, "velocity": {"vx": act_v, "vy": 0.0, "vz": vz},
                      "imu_linear_acceleration": {"ax": 0.0, "ay": 0.0}},
        "velocity_command": {"vx": cmd_vx, "vy": 0.0, "vz": vz, "yaw_rate": yaw_rate},
        "waypoint_guidance": {"dist_xy": 82.6, "ceiling_z": None},
        "current_wp_index": 0, "slm_request_id": None,
    }


def test_takeoff_climb_and_rotation_is_not_a_stall():
    det = StallDetector()
    # c1-c15: subiendo de 1.5 a 4.0 m, girando, vx=0
    for i in range(15):
        det.update(_st(-1.5 - i * 0.17, cmd_vx=0.0))
    # c16-c20: ya sobre el piso optico, sigue girando/terminando de subir con vx=0
    for i in range(5):
        det.update(_st(-4.6 - i * 0.2, cmd_vx=0.0))
        assert not det.stopped_prolonged


def test_rotation_in_place_at_cruise_is_not_a_stall():
    det = StallDetector()
    for _ in range(40):
        det.update(_st(-10.0, cmd_vx=0.0, vz=0.0, yaw_rate=20.0))
    assert not det.stopped_prolonged and det.stopped_cycles == 0


def test_commanded_forward_without_motion_still_counts():
    det = StallDetector()
    for _ in range(10):
        det.update(_st(-10.0, cmd_vx=1.5, act_v=0.0, vz=0.0, yaw_rate=0.0))
    assert det.stopped_prolonged


def test_no_progress_counter_ignores_takeoff_and_restarts_on_new_subgoal():
    det = StallDetector()
    for _ in range(60):                                              # despegue: no cuenta
        det.update(_st(-3.0, cmd_vx=0.0))
    assert not det.wp_no_progress
    st = _st(-10.0, cmd_vx=1.0, act_v=1.0, vz=0.0)
    st["waypoint_guidance"]["target_wp"] = {"x": 80.0, "y": 0.0, "label": "WP_1"}
    for _ in range(40):
        det.update(st)
    sub = _st(-10.0, cmd_vx=1.0, act_v=1.0, vz=0.0)                 # sub-meta del VLM en el mismo indice
    sub["waypoint_guidance"].update({"target_wp": {"x": 5.0, "y": 15.0, "label": "VLM_SUBGOAL"}, "dist_xy": 95.0})
    det.update(sub)
    assert det._wp_no_progress_cycles == 0                           # objetivo nuevo: arranca de cero

"""Regresion de la deriva de altitud durante FRENAR prolongado (CHANGELOG

2026-0824, opcion 3). moveByVelocityBodyFrameAsync(vz=0,...) reemitido cada
ciclo es un controlador de VELOCIDAD, no de altitud -- pedir "velocidad
cero" repetidamente no sostiene la posicion (~9m de deriva medidos en 120s
de FRENAR sostenido). motor_node() ancla la altitud al primer ciclo de
FRENAR y corrige vz si la altitud medida se aleja del ancla.
"""
from __future__ import annotations

from src.agents.graph import _build_nodes


class _StubAirSimClient:
    def __init__(self):
        self.loop_hz = 5.0
        self.commands = []

    def execute_velocity(self, vx, vy, vz, yaw_rate=0.0, target_yaw=None):
        self.commands.append((vx, vy, vz, yaw_rate, target_yaw))
        return True


def _frenar_state(z: float) -> dict:
    return {
        "telemetry": {"position": {"x": 0.0, "y": 0.0, "z": z}},
        "velocity_command": {"macro_action": "FRENAR", "vx": 0.0, "vy": 0.0, "vz": 0.0, "yaw_rate": 0.0},
        "deliberations": [],
    }


def test_motor_node_corrects_altitude_drift_during_sustained_frenar():
    client = _StubAirSimClient()
    nodes = _build_nodes(client)
    motor_node = nodes["motor"]
    try:
        # Primer ciclo de FRENAR a -10.0m: ancla la altitud, sin drift todavia.
        state = _frenar_state(-10.0)
        state = motor_node(state)
        assert client.commands[-1][2] == 0.0  # vz sin corregir, todavia en el ancla
        assert state["_hover_alt_anchor"] == -10.0

        # La altitud derivo 1m hacia abajo (z mas cerca de 0, NED) mientras
        # se sigue frenando -- motor_node debe corregir vz para volver al
        # ancla (subir: vz negativo en NED).
        state["telemetry"] = {"position": {"x": 0.0, "y": 0.0, "z": -9.0}}
        state = motor_node(state)
        assert client.commands[-1][2] < 0.0
    finally:
        nodes["_deliberation_service"].stop()


def test_motor_node_resets_altitude_anchor_when_not_frenar():
    client = _StubAirSimClient()
    nodes = _build_nodes(client)
    motor_node = nodes["motor"]
    try:
        state = _frenar_state(-10.0)
        state = motor_node(state)
        assert state["_hover_alt_anchor"] == -10.0

        state["velocity_command"] = {"macro_action": "MANTENER_RUMBO", "vx": 2.0, "vy": 0.0, "vz": 0.0, "yaw_rate": 0.0}
        state = motor_node(state)
        assert state["_hover_alt_anchor"] is None
    finally:
        nodes["_deliberation_service"].stop()


def test_motor_node_no_correction_within_deadzone():
    client = _StubAirSimClient()
    nodes = _build_nodes(client)
    motor_node = nodes["motor"]
    try:
        state = _frenar_state(-10.0)
        state = motor_node(state)

        # Deriva de 0.1m: por debajo de HOVER_ALT_DEADZONE_M (0.3m default) -- no corrige.
        state["telemetry"] = {"position": {"x": 0.0, "y": 0.0, "z": -9.9}}
        state = motor_node(state)
        assert client.commands[-1][2] == 0.0
    finally:
        nodes["_deliberation_service"].stop()

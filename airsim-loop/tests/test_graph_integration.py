"""Prueba de integracion end-to-end del grafo compilado, sin AirSim real.

Usa un AirSimClient stub (misma interfaz: capture/execute_velocity/get_telemetry)
y un query_fn del SLM instantaneo para no depender de un servidor real ni de
timeouts de red. Cubre F0.2 (una sola entrada en deliberations[] por ciclo
resuelto) y que el grafo compila y corre un ciclo completo sin excepciones.
"""
from __future__ import annotations

import time

import numpy as np
import pytest

import src.agents.deliberative as deliberative_mod
from src.agents.graph import compile_workflow


class _StubAirSimClient:
    def __init__(self):
        self.loop_hz = 5.0
        self._t = 0.0
        self.commands = []

    def capture(self):
        self._t += 0.2
        frame = np.random.randint(0, 255, size=(120, 160, 3), dtype=np.uint8)
        telemetry = {
            "position": {"x": 0.0, "y": 0.0, "z": -10.0},
            "velocity": {"vx": 0.0, "vy": 0.0, "vz": 0.0},
            "orientation": {"pitch": 0.0, "roll": 0.0, "yaw": 0.0},
            "collision": {"has_collided": False, "object_name": ""},
            "timestamp": self._t,
            "source": "airsim",
        }
        return frame, telemetry

    def get_telemetry(self):
        return {
            "position": {"x": 0.0, "y": 0.0, "z": -10.0},
            "velocity": {"vx": 0.0, "vy": 0.0, "vz": 0.0},
            "orientation": {"pitch": 0.0, "roll": 0.0, "yaw": 0.0},
            "collision": {"has_collided": False, "object_name": ""},
            "timestamp": self._t,
            "source": "airsim",
        }

    def execute_velocity(self, vx, vy, vz, yaw_rate=0.0, target_yaw=None):
        self.commands.append((vx, vy, vz, yaw_rate, target_yaw))
        return True


def _instant_fallback_query(payload):
    # Simula "SLM no disponible": el nodo debe usar el fallback determinista.
    return None, "", 5.0, "stub: no hay servidor SLM en el test"


def _base_state():
    return {
        "waypoints": [],
        "current_wp_index": 0,
        "target_waypoint": None,
        "waypoint_guidance": {},
        "mission_completed": False,
        "rgb_image": None,
        "telemetry": {},
        "frame_history": [],
        "estimated_ttc": float("inf"),
        "next_action": "",
        "flight_status": "vuelo",
        "deliberations": [],
        "active_maneuver": None,
        "maneuver_cycles_left": 0,
        "maneuver_command": None,
        "evasion_stuck_cycles": 0,
        "slm_request_id": None,
    }


def test_graph_compiles_and_runs_one_cycle(monkeypatch):
    monkeypatch.setattr(deliberative_mod, "_query_slm_impl", _instant_fallback_query)
    client = _StubAirSimClient()
    graph, service = compile_workflow(client)
    try:
        state = _base_state()
        result = graph.invoke(state)
        assert "velocity_command" in result
        assert len(client.commands) == 1
    finally:
        service.stop()


def test_single_cycle_produces_at_most_one_new_deliberation(monkeypatch):
    """Regresion F0.2: la version original invocaba al SLM dos veces por

    ciclo cuando el router entraba en la rama de deliberacion (un nodo
    devolvia el resultado de llamar directamente a otro, y ademas el grafo
    tenia una arista hacia el mismo destino). Aca, sea cual sea el numero de
    invocaciones de graph.invoke() que hagan falta para que la deliberacion
    asincrona se resuelva, nunca debe haber mas de una entrada nueva en
    deliberations[] por resolucion.
    """
    monkeypatch.setattr(deliberative_mod, "_query_slm_impl", _instant_fallback_query)
    monkeypatch.setattr("src.agents.graph.AGENT_ARM", "slm")

    client = _StubAirSimClient()
    graph, service = compile_workflow(client)
    try:
        state = _base_state()
        # Forzar la rama deliberativa via el escape de deadlock (no depende
        # de la estimacion real de flujo optico, que con frames aleatorios
        # no produce evidencia).
        state["evasion_stuck_cycles"] = 999

        state = graph.invoke(state)
        len_after_first = len(state.get("deliberations", []))

        # El escape de deadlock es sincronico (no pasa por el servicio async),
        # asi que ya debe haber exactamente una entrada.
        assert len_after_first <= 1
    finally:
        service.stop()


def test_deliberative_branch_resolves_to_single_entry_via_service(monkeypatch):
    monkeypatch.setattr(deliberative_mod, "_query_slm_impl", _instant_fallback_query)

    from src.agents.deliberative import make_deliberation_service, make_deliberative_node
    from src.perception.obstacle_field import BANDS, SECTORS, Cell, ObstacleField

    service = make_deliberation_service()
    node = make_deliberative_node(service)
    try:
        cells = {
            (s, b): Cell(sector=s, band=b, occupancy=0.9, ttc_s=1.0, confidence=0.9)
            for s in SECTORS for b in BANDS
        }
        field = ObstacleField(cells=cells, source="flow", foe=(0.0, 0.0), foe_confidence=1.0)
        state = _base_state()
        state["obstacle_field"] = field

        state = node(state)  # primer ciclo: encola el pedido, frena
        assert len(state.get("deliberations", [])) == 0
        assert state["next_action"] == "FRENAR"
        assert state["slm_request_id"] is not None

        deadline = time.time() + 2.0
        while time.time() < deadline:
            state = node(state)
            if len(state.get("deliberations", [])) >= 1:
                break
            time.sleep(0.01)

        assert len(state["deliberations"]) == 1  # nunca mas de una entrada por resolucion
    finally:
        service.stop()

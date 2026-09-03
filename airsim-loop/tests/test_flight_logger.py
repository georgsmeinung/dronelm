# Auditoria VLM (2026-0901, pedido explicito): fotogramas enviados al VLM
# guardados a PNG (photo-<timestamp_ISO>.png, junto al .jsonl/.csv de la
# corrida, uno por cada capture_timestamp REAL -- no el instante de
# resolucion de la deliberacion) y referenciados en el CSV; prompt +
# respuesta completos en el JSONL.
from __future__ import annotations

import csv
import json

import numpy as np
import pytest

from src.logging.flight_logger import FlightLogger, _format_ts_for_filename


def _state_with_deliberation(delib_id: int, prompt: str, raw_response: str) -> dict:
    return {
        "telemetry": {
            "position": {"x": 0.0, "y": 0.0, "z": -10.0},
            "velocity": {"vx": 0.0, "vy": 0.0, "vz": 0.0},
            "orientation": {"yaw": 0.0},
            "collision": {"has_collided": False, "object_name": ""},
        },
        "waypoint_guidance": {"distance": 10.0},
        "obstacle_field": None,
        "route": "deliberative",
        "next_action": "MANTENER_RUMBO",
        "current_wp_index": 0,
        "degraded": False,
        "deliberations": [
            {
                "id": delib_id,
                "arm": "slm",
                "macro_action": "MANTENER_RUMBO",
                "rationale": "sin obstaculos",
                "is_fallback": False,
                "timeout": False,
                "adherent": True,
                "used_json_schema": True,
                "latency_ms": 123.4,
                "prompt": prompt,
                "raw_response": raw_response,
            }
        ],
    }


def test_log_cycle_saves_vlm_frames_named_by_own_capture_timestamp(tmp_path):
    run_dir = tmp_path / "TEST_RUN-20260901T120000Z"
    out_path = run_dir / "TEST_RUN-20260901T120000Z.jsonl"
    logger = FlightLogger(str(out_path), scenario="test", seed=1, arm="slm")
    try:
        frame = np.zeros((20, 20, 3), dtype=np.uint8)
        capture_ts = 1735689045.123
        state = _state_with_deliberation(1, "prompt de prueba", '{"macro_action": "MANTENER_RUMBO"}')

        logger.log_cycle(state, latency_ms={"graph": 5.0}, delib_frames=[(frame, capture_ts)])

        expected_name = f"photo-{_format_ts_for_filename(capture_ts)}.png"
        assert logger.frames_dir == run_dir
        saved = list(run_dir.glob("*.png"))
        assert len(saved) == 1
        assert saved[0].name == expected_name
    finally:
        logger.close()

    with open(logger.csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    assert rows[0]["slm_delib_id"] == "1"
    assert rows[0]["slm_frame_paths"] == expected_name  # junto al csv: solo el nombre de archivo
    # Prompt y respuesta COMPLETOS tienen que estar en el CSV, no solo en el
    # JSONL (2026-0903, pedido explicito -- sin esto no se puede analizar un
    # vuelo mirando solo el CSV).
    assert rows[0]["slm_prompt"] == "prompt de prueba"
    assert rows[0]["slm_raw_response"] == '{"macro_action": "MANTENER_RUMBO"}'

    with open(out_path, encoding="utf-8") as f:
        record = json.loads(f.readline())
    assert record["slm"]["prompt"] == "prompt de prueba"
    assert record["slm"]["raw_response"] == '{"macro_action": "MANTENER_RUMBO"}'
    assert record["slm"]["frame_paths"] == [expected_name]


def test_log_cycle_does_not_resave_frames_for_the_same_stale_deliberation(tmp_path):
    """Mientras route sigue en 'deliberative' esperando la proxima resolucion,

    last_deliberation puede repetirse varios ciclos (ver TOWNSIM_INI,
    2026-0901): solo el ciclo que trae delib_frames debe escribir el PNG;
    los ciclos de repeticion deben seguir referenciando la misma ruta ya
    guardada, sin volver a llamar a cv2.imwrite.
    """
    run_dir = tmp_path / "TEST_RUN2-20260901T120000Z"
    out_path = run_dir / "TEST_RUN2-20260901T120000Z.jsonl"
    logger = FlightLogger(str(out_path), scenario="test", seed=1, arm="slm")
    try:
        frame = np.zeros((20, 20, 3), dtype=np.uint8)
        capture_ts = 1735689045.5
        state = _state_with_deliberation(7, "prompt", "respuesta")

        logger.log_cycle(state, latency_ms={"graph": 5.0}, delib_frames=[(frame, capture_ts)])
        logger.log_cycle(state, latency_ms={"graph": 5.0}, delib_frames=None)
        logger.log_cycle(state, latency_ms={"graph": 5.0}, delib_frames=None)

        saved = list(run_dir.glob("*.png"))
        assert len(saved) == 1  # nunca duplicado
    finally:
        logger.close()

    expected_name = f"photo-{_format_ts_for_filename(capture_ts)}.png"
    with open(logger.csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 3
    for row in rows:
        assert row["slm_frame_paths"] == expected_name


def test_slm_invocations_count_once_per_deliberation_not_per_repeated_cycle(tmp_path):
    """Bug encontrado 2026-0903: last_deliberation puede repetirse varios

    ciclos mientras el brazo sigue en ruta 'deliberative' esperando la
    proxima resolucion (ver TOWNSIM_INI, 2026-0901) -- summary.json debe
    reportar cuantas deliberaciones REALES hubo (una por id nuevo), no
    cuantos ciclos las mostraron en pantalla.
    """
    run_dir = tmp_path / "TEST_RUN5-20260901T120000Z"
    out_path = run_dir / "TEST_RUN5-20260901T120000Z.jsonl"
    logger = FlightLogger(str(out_path), scenario="test", seed=1, arm="slm")

    state1 = _state_with_deliberation(1, "prompt 1", "respuesta 1")
    # 3 ciclos repiten la misma deliberacion #1 (esperando la #2).
    logger.log_cycle(state1, latency_ms={"graph": 5.0})
    logger.log_cycle(state1, latency_ms={"graph": 5.0})
    logger.log_cycle(state1, latency_ms={"graph": 5.0})

    state2 = _state_with_deliberation(2, "prompt 2", "respuesta 2")
    logger.log_cycle(state2, latency_ms={"graph": 5.0})

    summary = logger.close()

    assert logger._cycle == 4  # 4 ciclos totales
    assert summary["slm_invocations"] == 2  # pero solo 2 deliberaciones reales
    assert summary["deliberation_rate"] == 0.5


def test_deep_scan_frames_use_their_own_capture_timestamp_not_resolution_time(tmp_path):
    """Los fotogramas del barrido del escaneo profundo (H2) se toman en

    rumbos/ciclos DISTINTOS, varios segundos antes de que el VLM resuelva
    -- cada uno debe llevar SU PROPIO timestamp real, nunca el instante
    compartido en que se resolvio la deliberacion (2026-0901: asi estaban
    "mal numerados" antes de este fix)."""
    run_dir = tmp_path / "TEST_RUN4-20260901T120000Z"
    out_path = run_dir / "TEST_RUN4-20260901T120000Z.jsonl"
    logger = FlightLogger(str(out_path), scenario="test", seed=1, arm="slm")
    try:
        capture_timestamps = [1735689050.0, 1735689053.4, 1735689057.9]
        frames_with_ts = [(np.zeros((20, 20, 3), dtype=np.uint8), ts) for ts in capture_timestamps]
        state = _state_with_deliberation(2, "prompt escaneo", "respuesta escaneo")

        logger.log_cycle(state, latency_ms={"graph": 5.0}, delib_frames=frames_with_ts)

        saved = sorted(p.name for p in run_dir.glob("*.png"))
        expected = sorted(f"photo-{_format_ts_for_filename(ts)}.png" for ts in capture_timestamps)
        assert saved == expected
    finally:
        logger.close()


def test_log_cycle_without_frames_leaves_csv_column_empty(tmp_path):
    run_dir = tmp_path / "TEST_RUN3-20260901T120000Z"
    out_path = run_dir / "TEST_RUN3-20260901T120000Z.jsonl"
    logger = FlightLogger(str(out_path), scenario="test", seed=1, arm="reactive")
    try:
        state = {
            "telemetry": {
                "position": {"x": 0.0, "y": 0.0, "z": -10.0},
                "velocity": {"vx": 1.0, "vy": 0.0, "vz": 0.0},
                "orientation": {"yaw": 0.0},
                "collision": {"has_collided": False, "object_name": ""},
            },
            "waypoint_guidance": {"distance": 10.0},
            "obstacle_field": None,
            "route": "reactive",
            "next_action": "MANTENER_RUMBO",
            "current_wp_index": 0,
            "degraded": False,
            "deliberations": [],
        }
        logger.log_cycle(state, latency_ms={"graph": 5.0})
        assert list(run_dir.glob("*.png")) == []
    finally:
        logger.close()

    with open(logger.csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["slm_frame_paths"] == ""
    assert rows[0]["slm_delib_id"] == ""


def test_csv_velocity_columns_read_the_right_telemetry_keys(tmp_path):
    """bug-fix 2026-0903: telemetry["velocity"] siempre usa vx/vy/vz (ver

    AirSimClient._state_to_telemetry), nunca x/y/z -- con las claves
    equivocadas vel_x/vel_y/vel_z quedaban vacias en TODO el historial de
    corridas desde que existe el CSV (2026-0828). Encontrado analizando en
    vivo el CSV de TOWNSIM_INI.
    """
    run_dir = tmp_path / "TEST_RUN6-20260901T120000Z"
    out_path = run_dir / "TEST_RUN6-20260901T120000Z.jsonl"
    logger = FlightLogger(str(out_path), scenario="test", seed=1, arm="reactive")
    state = {
        "telemetry": {
            "position": {"x": 1.0, "y": 2.0, "z": -10.0},
            "velocity": {"vx": 3.5, "vy": -1.5, "vz": 0.25},
            "orientation": {"yaw": 0.0},
            "collision": {"has_collided": False, "object_name": ""},
        },
        "waypoint_guidance": {"distance": 10.0},
        "obstacle_field": None, "route": "reactive", "next_action": "MANTENER_RUMBO",
        "current_wp_index": 0, "degraded": False, "deliberations": [],
    }
    logger.log_cycle(state, latency_ms={"graph": 5.0})
    logger.close()

    with open(logger.csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert float(rows[0]["vel_x"]) == 3.5
    assert float(rows[0]["vel_y"]) == -1.5
    assert float(rows[0]["vel_z"]) == 0.25


def test_csv_logs_full_three_axis_orientation(tmp_path):
    """2026-0903, pedido explicito: antes solo se guardaba yaw_deg -- para

    analizar el momento de inercia rotacional hace falta pitch/roll tambien,
    no solo el rumbo horizontal.
    """
    import math

    run_dir = tmp_path / "TEST_RUN7-20260901T120000Z"
    out_path = run_dir / "TEST_RUN7-20260901T120000Z.jsonl"
    logger = FlightLogger(str(out_path), scenario="test", seed=1, arm="reactive")
    state = {
        "telemetry": {
            "position": {"x": 0.0, "y": 0.0, "z": -10.0},
            "velocity": {"vx": 0.0, "vy": 0.0, "vz": 0.0},
            "orientation": {"yaw": math.radians(30.0), "pitch": math.radians(-5.0), "roll": math.radians(8.0)},
            "collision": {"has_collided": False, "object_name": ""},
        },
        "waypoint_guidance": {"distance": 10.0},
        "obstacle_field": None, "route": "reactive", "next_action": "MANTENER_RUMBO",
        "current_wp_index": 0, "degraded": False, "deliberations": [],
    }
    logger.log_cycle(state, latency_ms={"graph": 5.0})
    logger.close()

    with open(logger.csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert float(rows[0]["yaw_deg"]) == pytest.approx(30.0, abs=0.01)
    assert float(rows[0]["pitch_deg"]) == pytest.approx(-5.0, abs=0.01)
    assert float(rows[0]["roll_deg"]) == pytest.approx(8.0, abs=0.01)


def test_per_waypoint_summary_csv(tmp_path):
    """2026-0903, pedido explicito: un CSV de resumen que muestre ciclos

    consumidos por waypoint y uso del nodo deliberativo/escaneo profundo,
    para identificar de un vistazo cual tramo concentra la dificultad (ver
    hallazgo de WP_0_ASCENSO en TOWNSIM_INI).
    """
    run_dir = tmp_path / "TEST_RUN8-20260901T120000Z"
    out_path = run_dir / "TEST_RUN8-20260901T120000Z.jsonl"
    logger = FlightLogger(str(out_path), scenario="test", seed=1, arm="slm")

    def _state(wp_index, wp_label, route):
        return {
            "telemetry": {
                "position": {"x": 0.0, "y": 0.0, "z": -10.0},
                "velocity": {"vx": 0.0, "vy": 0.0, "vz": 0.0},
                "orientation": {"yaw": 0.0},
                "collision": {"has_collided": False, "object_name": ""},
            },
            "waypoint_guidance": {"distance": 10.0},
            "obstacle_field": None, "route": route, "next_action": "MANTENER_RUMBO",
            "current_wp_index": wp_index, "target_waypoint": {"label": wp_label},
            "degraded": False, "deliberations": [],
        }

    # WP 0: 3 ciclos, 1 deliberativo, 1 evento de escaneo profundo.
    logger.log_cycle(_state(0, "WP_0", "reactive"), latency_ms={"graph": 5.0})
    logger.log_cycle(
        _state(0, "WP_0", "deliberative"), latency_ms={"graph": 5.0},
        deadlock_event={"strategy": "deep_vlm", "resolved_by_scan": True, "cycles_to_resolve": 1, "fell_back_to_blind": False},
    )
    logger.log_cycle(_state(0, "WP_0", "reactive"), latency_ms={"graph": 5.0})
    # WP 1: 2 ciclos, sin deliberacion.
    logger.log_cycle(_state(1, "WP_1", "reactive"), latency_ms={"graph": 5.0})
    logger.log_cycle(_state(1, "WP_1", "reactive"), latency_ms={"graph": 5.0})

    logger.close()

    wp_summary_path = out_path.with_name(out_path.stem + ".summary_by_wp.csv")
    with open(wp_summary_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    assert len(rows) == 2
    assert rows[0]["wp_index"] == "0"
    assert rows[0]["wp_label"] == "WP_0"
    assert rows[0]["cycles"] == "3"
    assert rows[0]["deliberative_cycles"] == "1"
    assert rows[0]["deep_scan_events"] == "1"

    assert rows[1]["wp_index"] == "1"
    assert rows[1]["wp_label"] == "WP_1"
    assert rows[1]["cycles"] == "2"
    assert rows[1]["deliberative_cycles"] == "0"
    assert rows[1]["deep_scan_events"] == "0"

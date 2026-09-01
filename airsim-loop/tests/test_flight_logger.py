# Auditoria VLM (2026-0901, pedido explicito): fotogramas enviados al VLM
# guardados a PNG (photo-<timestamp_ISO>.png, junto al .jsonl/.csv de la
# corrida, uno por cada capture_timestamp REAL -- no el instante de
# resolucion de la deliberacion) y referenciados en el CSV; prompt +
# respuesta completos en el JSONL.
from __future__ import annotations

import csv
import json

import numpy as np

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

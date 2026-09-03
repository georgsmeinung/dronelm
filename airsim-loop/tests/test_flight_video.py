# 2026-0903, pedido explicito: grabar un .webm (VP8) de la corrida
# sincronizado con el timeline del log (un frame por ciclo, a fps=LOOP_HZ).
# VP8/webm en vez de mp4v/mp4 o avc1/mp4 -- ver flight_video.py para el
# porque (mp4v no lo decodifica ningun navegador, avc1/H264 requiere una DLL
# que este entorno no tiene instalada).
from __future__ import annotations

import numpy as np

from src.logging.flight_video import FlightVideoRecorder


def test_records_frames_and_reports_count(tmp_path):
    out_path = tmp_path / "run" / "flight.mp4"
    recorder = FlightVideoRecorder(str(out_path), frame_size=(64, 48), fps=5.0)

    for _ in range(5):
        frame = np.zeros((48, 64, 3), dtype=np.uint8)
        recorder.write_frame(frame)

    n_frames = recorder.close()
    assert n_frames == 5
    assert recorder.out_path.suffix == ".webm"
    assert recorder.out_path.exists()
    assert recorder.out_path.stat().st_size > 0


def test_skips_none_frames_without_error(tmp_path):
    out_path = tmp_path / "run2" / "flight.mp4"
    recorder = FlightVideoRecorder(str(out_path), frame_size=(64, 48), fps=5.0)

    recorder.write_frame(None)
    recorder.write_frame(np.zeros((48, 64, 3), dtype=np.uint8))
    recorder.write_frame(None)

    n_frames = recorder.close()
    assert n_frames == 1


def test_resizes_mismatched_frame_size(tmp_path):
    """Un frame de tamano distinto al declarado no debe tirar excepcion --

    se reescala al tamano fijo del video (cv2.VideoWriter no admite tamano
    variable entre frames).
    """
    out_path = tmp_path / "run3" / "flight.mp4"
    recorder = FlightVideoRecorder(str(out_path), frame_size=(64, 48), fps=5.0)

    mismatched = np.zeros((120, 160, 3), dtype=np.uint8)
    recorder.write_frame(mismatched)

    n_frames = recorder.close()
    assert n_frames == 1

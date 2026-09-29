# Video de la camara externa "FollowCam" (2026-0929), sincronizado con el frontal.
#
# Un frame por ciclo, igual que el video frontal, para que ambos compartan el indice de
# ciclo (el visor mapea fila -> tiempo por indice). Si en algun ciclo no llega imagen se
# repite el ultimo frame (o negro antes del primero) en vez de saltarlo: saltar un frame
# desalinearia el resto del video respecto de las filas del CSV.
#
# Solo auditoria: este modulo nunca toca el DroneState ni la percepcion.
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

import numpy as np

from .flight_video import FlightVideoRecorder


def follow_video_path(front_video_path: str) -> str:
    """<stem>.webm -> <stem>.follow.webm"""
    p = Path(front_video_path).with_suffix("")
    return str(p.with_name(p.name + ".follow")) + ".webm"


def annotate_follow_frame(frame: Any, final_state: dict, cycle: int, elapsed_s: float) -> Any:
    """Banner minimo sobre una COPIA del frame de FollowCam (ciclo, tiempo, ruta y accion)."""
    # pyrefly: ignore [missing-import]
    import cv2

    out = frame.copy()
    h, w = out.shape[:2]
    cv2.rectangle(out, (0, 0), (w, 34), (10, 10, 15), -1)
    route = str(final_state.get("route", "") or "").upper() or "DIRECT"
    action = final_state.get("next_action", "") or ""
    pos = (final_state.get("telemetry") or {}).get("position", {}) or {}
    cv2.putText(
        out,
        f"FollowCam  cy={cycle}  t={elapsed_s:6.1f}s  [{route}] {action}  "
        f"z={pos.get('z', 0.0):+.1f}",
        (10, 23), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 1, cv2.LINE_AA,
    )
    return out


class FollowCamRecorder:
    """Escribe `<stem>.follow.webm` con un frame por ciclo (creacion diferida)."""

    def __init__(self, front_video_path: str, fps: float, scale: Optional[float] = None) -> None:
        self.out_path = Path(follow_video_path(front_video_path))
        self._fps = fps
        self._scale = scale
        self._rec: Optional[FlightVideoRecorder] = None
        self._last: Optional[np.ndarray] = None
        self._blank_pending = 0
        self.frames_written = 0

    def _open(self, frame: np.ndarray) -> None:
        h, w = frame.shape[:2]
        self._rec = FlightVideoRecorder(str(self.out_path), (w, h), self._fps, scale=self._scale)

    def write(self, frame: Optional[np.ndarray]) -> None:
        """Encola el frame de este ciclo (o rellena si no hay)."""
        if frame is not None:
            if self._rec is None:
                self._open(frame)
                black = np.zeros_like(frame)
                for _ in range(self._blank_pending):  # ciclos previos al primer frame real
                    self._rec.write_frame(black)
                    self.frames_written += 1
                self._blank_pending = 0
            self._last = frame
        elif self._last is not None and self._rec is not None:
            frame = self._last
        else:
            self._blank_pending += 1
            return
        self._rec.write_frame(frame)  # type: ignore[union-attr]
        self.frames_written += 1

    def close(self) -> int:
        n = self._rec.close() if self._rec is not None else 0
        return n


def follow_cam_config() -> Optional[str]:
    """Nombre de la camara externa a grabar (env AIRSIM_FOLLOW_CAMERA); '' o 'none' = desactivada."""
    name = os.getenv("AIRSIM_FOLLOW_CAMERA", "FollowCam").strip()
    return None if name.lower() in ("", "none", "false", "off") else name

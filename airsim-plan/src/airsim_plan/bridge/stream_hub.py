from __future__ import annotations

import threading
import time
from typing import Any, Dict, Optional, Generator
import cv2
import numpy as np


class StreamHub:
    """Singleton para compartir frames de video anotados y telemetría en tiempo real

    entre el bucle de navegación (airsim-loop) y el servidor web (WebDCS / FastAPI).
    """

    _instance: Optional["StreamHub"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "StreamHub":
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._init_hub()
            return cls._instance

    def _init_hub(self) -> None:
        self._frame_lock = threading.Condition()
        self._latest_jpeg: Optional[bytes] = None
        self._latest_telemetry: Dict[str, Any] = {
            "connected": False,
            "status": "idle",
            "decision": "MANTENER_RUMBO",
            "flight_status": "en_espera",
            "estimated_ttc": None,
            "xor_change_ratio": 0.0,
            "detections": [],
            "detected_obstacles": [],
            "scene_summary": "",
            "velocity": {"vx": 0.0, "vy": 0.0, "vz": 0.0, "yaw_rate": 0.0},
            "timestamp": 0.0,
        }
        self._last_update = 0.0
        self._placeholder_jpeg = self._create_placeholder_frame("WebDCS - Esperando video...")

    def _create_placeholder_frame(self, text: str) -> bytes:
        img = np.zeros((480, 640, 3), dtype=np.uint8)
        # Gradient background
        img[:, :] = (18, 14, 10)
        cv2.putText(
            img,
            text,
            (40, 240),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (160, 160, 160),
            2,
            cv2.LINE_AA,
        )
        cv2.putText(
            img,
            "Inicie una mision para recibir el feed en vivo",
            (40, 275),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (90, 90, 90),
            1,
            cv2.LINE_AA,
        )
        _, encoded = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])
        return encoded.tobytes()

    def publish(
        self,
        frame: Optional[np.ndarray],
        telemetry: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Publica un nuevo cuadro (numpy array) y/o telemetría."""
        jpeg_bytes = None
        if frame is not None:
            try:
                # Asegurar formato BGR para OpenCV
                success, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                if success:
                    jpeg_bytes = encoded.tobytes()
            except Exception as e:
                print(f"[StreamHub] Error codificando JPEG: {e}")

        with self._frame_lock:
            if jpeg_bytes is not None:
                self._latest_jpeg = jpeg_bytes
            if telemetry is not None:
                self._latest_telemetry = telemetry
            self._last_update = time.time()
            self._frame_lock.notify_all()

    def get_telemetry(self) -> Dict[str, Any]:
        with self._frame_lock:
            data = dict(self._latest_telemetry)
            data["active"] = (time.time() - self._last_update) < 3.0
            return data

    def generate_mjpeg(self) -> Generator[bytes, None, None]:
        """Generador para StreamingResponse de FastAPI (multipart/x-mixed-replace)."""
        while True:
            with self._frame_lock:
                # Esperar hasta 0.5s por un nuevo frame
                self._frame_lock.wait(timeout=0.5)
                # Si el feed está inactivo hace más de 3 segundos, enviar placeholder
                is_active = (time.time() - self._last_update) < 3.0
                frame_bytes = self._latest_jpeg if (is_active and self._latest_jpeg is not None) else self._placeholder_jpeg

            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" + frame_bytes + b"\r\n"
            )
            time.sleep(0.04)  # ~25 FPS max rate


# Instancia global
stream_hub = StreamHub()

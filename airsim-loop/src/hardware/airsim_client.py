# Paso 1 y 5: Conexion con la API nativa de AirSim.
# Encapsula la captura sensorial (imagen RGB + telemetria) y el envio de
# comandos de velocidad hacia el simulador. Si la libreria cosys-airsim
# no esta disponible o el simulador no responde, se degrada a modo
# "simulado" para que el grafo pueda ejecutarse en entornos de prueba.
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover
    pass

try:
    import airsim  # type: ignore
except Exception:  # pragma: no cover - dependencia opcional en tiempo de import
    airsim = None  # type: ignore

import numpy as np


DEFAULT_IP = os.getenv("AIRSIM_IP", "127.0.0.1")
DEFAULT_PORT = int(os.getenv("AIRSIM_PORT", "41451"))
DEFAULT_VEHICLE = os.getenv("AIRSIM_VEHICLE_NAME", "Drone1")
DEFAULT_CAMERA = os.getenv("AIRSIM_CAMERA_NAME", "0")
DEFAULT_FRAME_WIDTH = int(os.getenv("DEFAULT_FRAME_WIDTH", "256"))
DEFAULT_FRAME_HEIGHT = int(os.getenv("DEFAULT_FRAME_HEIGHT", "144"))


@dataclass
class AirSimClient:
    """Cliente ligero para AirSim (modo Drone por defecto).

    Permite capturar imagen RGB + telemetria basica y enviar comandos de
    velocidad (``moveByVelocityAsync``). Cuando no hay simulador disponible
    o no se puede conectar, devuelve datos simulados para que el pipeline
    pueda ejercitarse sin un entorno grafico.
    """

    ip: str = DEFAULT_IP
    port: int = DEFAULT_PORT
    vehicle_name: str = DEFAULT_VEHICLE
    camera_name: str = DEFAULT_CAMERA
    frame_width: int = DEFAULT_FRAME_WIDTH
    frame_height: int = DEFAULT_FRAME_HEIGHT
    timeout_seconds: float = 5.0
    _client: Any = field(default=None, init=False, repr=False)
    _connected: bool = field(default=False, init=False, repr=False)

    # ------------------------------------------------------------------ #
    # Conexion                                                          #
    # ------------------------------------------------------------------ #
    def connect(self) -> bool:
        """Inicializa el cliente nativo de AirSim. Devuelve True si conecta."""
        if airsim is None:
            print("[AirSimClient] Libreria cosys-airsim no disponible. Modo simulado.")
            self._connected = False
            return False
        try:
            self._client = airsim.MultirotorClient(ip=self.ip, port=self.port)
            self._client.confirmConnection()
            try:
                self._client.enableApiControl(True, vehicle_name=self.vehicle_name)
                self._client.armDisarm(True, vehicle_name=self.vehicle_name)
                self._client.takeoffAsync(vehicle_name=self.vehicle_name).join()
            except Exception as exc:  # pragma: no cover - depende del entorno
                print(f"[AirSimClient] No se pudo armar/despegar ({exc}).")
            self._connected = True
            return True
        except Exception as exc:
            print(f"[AirSimClient] No se pudo conectar a {self.ip}:{self.port} ({exc}).")
            self._client = None
            self._connected = False
            return False

    def disconnect(self) -> None:
        if self._client is None:
            return
        try:
            self._client.armDisarm(False, vehicle_name=self.vehicle_name)
            self._client.enableApiControl(False, vehicle_name=self.vehicle_name)
        except Exception:  # pragma: no cover
            pass
        self._connected = False

    # ------------------------------------------------------------------ #
    # Paso 1: captura sensorial                                         #
    # ------------------------------------------------------------------ #
    def capture(self) -> Tuple[Optional[np.ndarray], Dict[str, Any]]:
        """Devuelve (imagen_rgb, telemetria).

        La imagen es un ``numpy.ndarray`` con shape ``(H, W, 3)`` o ``None``
        si el simulador no esta disponible. La telemetria siempre trae al
        menos ``position``, ``velocity`` y ``orientation`` en el marco NED.
        """
        if not self._connected or self._client is None:
            return self._simulated_frame(), self._simulated_telemetry()
        try:
            responses = self._client.simGetImages(
                [
                    airsim.ImageRequest(
                        self.camera_name,
                        airsim.ImageType.Scene,
                        False,
                        False,
                    )
                ],
                vehicle_name=self.vehicle_name,
            )
            response = responses[0] if responses else None
            image = None
            if response is not None and response.width > 0 and response.height > 0:
                img_1d = np.frombuffer(response.image_data_uint8, dtype=np.uint8)
                image = img_1d.reshape(response.height, response.width, 3)
                if (
                    image.shape[1] != self.frame_width
                    or image.shape[0] != self.frame_height
                ):
                    image = _resize_frame(image, self.frame_width, self.frame_height)
            state = self._client.getMultirotorState(vehicle_name=self.vehicle_name)
            telemetry = _state_to_telemetry(state)
            return image, telemetry
        except Exception as exc:
            print(f"[AirSimClient] Error capturando datos: {exc}")
            return self._simulated_frame(), self._simulated_telemetry()

    # ------------------------------------------------------------------ #
    # Paso 5: ejecucion motriz                                          #
    # ------------------------------------------------------------------ #
    def execute_velocity(
        self, vx: float, vy: float, vz: float, yaw_rate: float = 0.0
    ) -> bool:
        """Envia un comando de velocidad al dron (marco NED)."""
        if not self._connected or self._client is None:
            print(
                f"[AirSimClient][simulado] vx={vx:.2f} vy={vy:.2f} vz={vz:.2f} "
                f"yaw={yaw_rate:.2f}"
            )
            return True
        try:
            self._client.moveByVelocityAsync(
                vx,
                vy,
                vz,
                duration=1.0,
                drivetrain=airsim.DrivetrainType.MaxDegreeOfFreedom,
                yaw_mode=airsim.YawMode(is_rate=True, yaw_or_rate=yaw_rate),
                vehicle_name=self.vehicle_name,
            )
            return True
        except Exception as exc:
            print(f"[AirSimClient] No se pudo enviar velocidad: {exc}")
            return False

    # ------------------------------------------------------------------ #
    # Helpers / modo simulado                                           #
    # ------------------------------------------------------------------ #
    def _simulated_frame(self) -> np.ndarray:
        """Devuelve un frame sintetico con un obstaculo central cuando aplica."""
        rng = np.random.default_rng(int(time.time()) % 100000)
        frame = rng.integers(
            20, 60, size=(self.frame_height, self.frame_width, 3), dtype=np.uint8
        )
        # Pinta un cuadrado "obstaculo" en el centro para que YOLO tenga algo
        central_pad = int(self.frame_width * 0.12)
        cy = self.frame_height // 2
        frame[
            cy - 20 : cy + 20,
            self.frame_width // 2 - central_pad : self.frame_width // 2 + central_pad,
        ] = (180, 90, 40)
        return frame

    def _simulated_telemetry(self) -> Dict[str, Any]:
        return {
            "position": {"x": 0.0, "y": 0.0, "z": 0.0},
            "velocity": {"vx": 0.0, "vy": 0.0, "vz": 0.0},
            "orientation": {"pitch": 0.0, "roll": 0.0, "yaw": 0.0},
            "timestamp": time.time(),
            "source": "simulated",
        }


def _resize_frame(image: np.ndarray, width: int, height: int) -> np.ndarray:
    """Reescala con nearest-neighbor para evitar dependencias de OpenCV."""
    src_h, src_w = image.shape[:2]
    if src_h == height and src_w == width:
        return image
    y_idx = (np.linspace(0, src_h - 1, height)).astype(int)
    x_idx = (np.linspace(0, src_w - 1, width)).astype(int)
    return image[np.ix_(y_idx, x_idx)]


def _state_to_telemetry(state: Any) -> Dict[str, Any]:
    """Adapta un MultirotorState de AirSim a un dict simple en marco NED."""
    kin = getattr(state, "kinematics_estimated", None)
    pos = getattr(kin, "position", None)
    vel = getattr(kin, "linear_velocity", None)
    orient = getattr(kin, "orientation", None)
    return {
        "position": {
            "x": getattr(pos, "x_val", 0.0),
            "y": getattr(pos, "y_val", 0.0),
            "z": getattr(pos, "z_val", 0.0),
        },
        "velocity": {
            "vx": getattr(vel, "x_val", 0.0),
            "vy": getattr(vel, "y_val", 0.0),
            "vz": getattr(vel, "z_val", 0.0),
        },
        "orientation": {
            "pitch": getattr(orient, "x_val", 0.0),
            "roll": getattr(orient, "y_val", 0.0),
            "yaw": getattr(orient, "w_val", 0.0),
        },
        "timestamp": time.time(),
        "source": "airsim",
    }

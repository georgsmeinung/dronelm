# Paso 1 y 5: Conexion con la API nativa de AirSim.
# Encapsula la captura sensorial (imagen RGB + telemetria) y el envio de
# comandos de velocidad hacia el simulador. Si la libreria cosys-airsim
# no esta disponible o el simulador no responde, se degrada a modo
# "simulado" para que el grafo pueda ejecutarse en entornos de prueba.
from __future__ import annotations

import math
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
    import cosysairsim as airsim  # type: ignore
except Exception:
    try:
        import airsim  # type: ignore
    except Exception:  # pragma: no cover - dependencia opcional en tiempo de import
        airsim = None  # type: ignore

import numpy as np


DEFAULT_IP = os.getenv("AIRSIM_IP", "127.0.0.1")
DEFAULT_PORT = int(os.getenv("AIRSIM_PORT", "41451"))
DEFAULT_VEHICLE = os.getenv("AIRSIM_VEHICLE_NAME", "Drone1")
DEFAULT_CAMERA = os.getenv("AIRSIM_CAMERA_NAME", "0")
DEFAULT_FRAME_WIDTH = int(os.getenv("DEFAULT_FRAME_WIDTH", "1080"))
DEFAULT_FRAME_HEIGHT = int(os.getenv("DEFAULT_FRAME_HEIGHT", "720"))


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
    # Conexión                                                           #
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
    # Paso 1: captura sensorial                                          #
    # ------------------------------------------------------------------ #
    def capture(
        self, return_depth: bool = False
    ) -> Tuple[Optional[np.ndarray], Dict[str, Any]] | Tuple[Optional[np.ndarray], Optional[np.ndarray], Dict[str, Any]]:
        """Devuelve (imagen_rgb, telemetria) o (imagen_rgb, imagen_depth, telemetria) si return_depth es True.

        La imagen es un ``numpy.ndarray`` con shape ``(H, W, 3)`` o ``None``
        si el simulador no esta disponible. La telemetria siempre trae al
        menos ``position``, ``velocity`` y ``orientation`` en el marco NED.
        """
        if not self._connected or self._client is None:
            if return_depth:
                return self._simulated_frame(), self._simulated_depth(), self._simulated_telemetry()
            return self._simulated_frame(), self._simulated_telemetry()
        try:
            camera_id = int(self.camera_name) if self.camera_name.isdigit() else self.camera_name
            requests = [
                airsim.ImageRequest(
                    camera_id,
                    airsim.ImageType.Scene,
                    False,
                    False,
                )
            ]
            if return_depth:
                depth_type = getattr(airsim.ImageType, "DepthPlanar", getattr(airsim.ImageType, "DepthPlanner", None))
                requests.append(
                    airsim.ImageRequest(
                        camera_id,
                        depth_type,
                        True,
                        False,
                    )
                )

            responses = self._client.simGetImages(requests, vehicle_name=self.vehicle_name)
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

            depth = None
            if return_depth and len(responses) > 1:
                depth_response = responses[1]
                if depth_response is not None and depth_response.width > 0 and depth_response.height > 0:
                    depth_1d = np.array(depth_response.image_data_float, dtype=np.float32)
                    depth = depth_1d.reshape(depth_response.height, depth_response.width)
                    if (
                        depth.shape[1] != self.frame_width
                        or depth.shape[0] != self.frame_height
                    ):
                        depth = _resize_depth(depth, self.frame_width, self.frame_height)

            state = self._client.getMultirotorState(vehicle_name=self.vehicle_name)
            telemetry = _state_to_telemetry(state)
            
            if return_depth:
                return image, depth, telemetry
            return image, telemetry
        except Exception as exc:
            print(f"[AirSimClient] Error capturando datos: {exc}")
            if return_depth:
                return self._simulated_frame(), self._simulated_depth(), self._simulated_telemetry()
            return self._simulated_frame(), self._simulated_telemetry()

    def get_telemetry(self) -> Dict[str, Any]:
        """Obtiene la telemetria de posicion, velocidad y orientacion actual del dron."""
        if not self._connected or self._client is None:
            return self._simulated_telemetry()
        try:
            state = self._client.getMultirotorState(vehicle_name=self.vehicle_name)
            return _state_to_telemetry(state)
        except Exception as exc:
            print(f"[AirSimClient] Error obteniendo telemetria: {exc}")
            return self._simulated_telemetry()

    # ------------------------------------------------------------------ #
    # Paso 5: comando motriz                                             #
    # ------------------------------------------------------------------ #
    def execute_velocity(
        self,
        vx: float,
        vy: float,
        vz: float,
        yaw_rate: float = 0.0,
        target_yaw: Optional[float] = None,
    ) -> bool:
        """Envia un comando de velocidad al dron en marco Body Frame.

        Si yaw_rate != 0.0, usa MaxDegreeOfFreedom con YawMode(is_rate=True) para girar la
        proa proporcionalmente mientras avanza de frente (Estrategia Car-like).
        Si vy != 0.0 y yaw_rate == 0.0 (evasión lateral), usa ForwardOnly para orientar la cámara a la maniobra.
        """
        if not self._connected or self._client is None:
            mode_str = f"yaw_rate={yaw_rate:+.1f}°/s" if abs(yaw_rate) > 0.01 else "ForwardOnly"
            print(
                f"[AirSimClient][simulado] vx={vx:.2f} vy={vy:.2f} vz={vz:.2f} "
                f"({mode_str})"
            )
            return True
        try:
            # Si todas las velocidades y giro son nulos, activar hover de seguridad
            if abs(vx) < 0.05 and abs(vy) < 0.05 and abs(vz) < 0.05 and abs(yaw_rate) < 0.01:
                self._client.hoverAsync(vehicle_name=self.vehicle_name)
                return True

            if abs(yaw_rate) > 0.01:
                drivetrain = airsim.DrivetrainType.MaxDegreeOfFreedom
                yaw_mode = airsim.YawMode(is_rate=True, yaw_or_rate=float(yaw_rate))
            elif target_yaw is not None:
                drivetrain = airsim.DrivetrainType.MaxDegreeOfFreedom
                yaw_mode = airsim.YawMode(is_rate=False, yaw_or_rate=float(target_yaw))
            else:
                drivetrain = airsim.DrivetrainType.ForwardOnly
                yaw_mode = airsim.YawMode(is_rate=False, yaw_or_rate=0.0)

            self._client.moveByVelocityBodyFrameAsync(
                vx,
                vy,
                vz,
                duration=2.0,
                drivetrain=drivetrain,
                yaw_mode=yaw_mode,
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

    def _simulated_depth(self) -> np.ndarray:
        """Devuelve un depth map sintetico de la misma resolucion."""
        depth = np.full((self.frame_height, self.frame_width), 20.0, dtype=np.float32)
        central_pad = int(self.frame_width * 0.12)
        cy = self.frame_height // 2
        depth[
            cy - 20 : cy + 20,
            self.frame_width // 2 - central_pad : self.frame_width // 2 + central_pad,
        ] = 5.0
        return depth


def _resize_frame(image: np.ndarray, width: int, height: int) -> np.ndarray:
    """Reescala con nearest-neighbor para evitar dependencias de OpenCV."""
    src_h, src_w = image.shape[:2]
    if src_h == height and src_w == width:
        return image
    y_idx = (np.linspace(0, src_h - 1, height)).astype(int)
    x_idx = (np.linspace(0, src_w - 1, width)).astype(int)
    return image[np.ix_(y_idx, x_idx)]


def _resize_depth(image: np.ndarray, width: int, height: int) -> np.ndarray:
    """Reescala con nearest-neighbor."""
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

    # Conversión exacta de Cuaternión a ángulos de Euler (pitch, roll, yaw) en radianes
    pitch, roll, yaw = 0.0, 0.0, 0.0
    if orient is not None:
        try:
            if airsim is not None and hasattr(airsim, "to_eularian_angles"):
                pitch, roll, yaw = airsim.to_eularian_angles(orient)
            else:
                w = getattr(orient, "w_val", 1.0)
                x = getattr(orient, "x_val", 0.0)
                y = getattr(orient, "y_val", 0.0)
                z = getattr(orient, "z_val", 0.0)
                siny_cosp = 2.0 * (w * z + x * y)
                cosy_cosp = 1.0 - 2.0 * (y * y + z * z)
                yaw = math.atan2(siny_cosp, cosy_cosp)
        except Exception:
            w = getattr(orient, "w_val", 1.0)
            x = getattr(orient, "x_val", 0.0)
            y = getattr(orient, "y_val", 0.0)
            z = getattr(orient, "z_val", 0.0)
            siny_cosp = 2.0 * (w * z + x * y)
            cosy_cosp = 1.0 - 2.0 * (y * y + z * z)
            yaw = math.atan2(siny_cosp, cosy_cosp)

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
            "pitch": float(pitch),
            "roll": float(roll),
            "yaw": float(yaw),
        },
        "timestamp": time.time(),
        "source": "airsim",
    }

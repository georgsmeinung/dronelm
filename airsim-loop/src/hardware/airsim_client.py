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

# pyrefly: ignore [missing-import]
import numpy as np


DEFAULT_IP = os.getenv("AIRSIM_IP", "127.0.0.1")
DEFAULT_PORT = int(os.getenv("AIRSIM_PORT", "41451"))
DEFAULT_VEHICLE = os.getenv("AIRSIM_VEHICLE_NAME", "Drone1")
DEFAULT_CAMERA = os.getenv("AIRSIM_CAMERA_NAME", "0")
DEFAULT_FRAME_WIDTH = int(os.getenv("DEFAULT_FRAME_WIDTH", "1080"))
DEFAULT_FRAME_HEIGHT = int(os.getenv("DEFAULT_FRAME_HEIGHT", "720"))
# F0.6: en modo estricto (default en vuelo), si AirSim no responde, capture()
# devuelve None en lugar de un frame sintetico. Los frames simulados quedan
# disponibles solo para tests (AIRSIM_STRICT=false).
AIRSIM_STRICT = os.getenv("AIRSIM_STRICT", "true").lower() == "true"
# Reintento 2026-0826 (v2, ver CHANGELOG.md) del fix de cabeceo. El primer
# intento (revertido) atava la vigencia del comando a un multiplo del periodo
# del lazo (0.5s a 5Hz, ver F0.1 original) con un margen de reemision al 30%: en la practica igual
# reemitia cada ~2 ciclos aunque el setpoint no hubiera cambiado, sin dejarle
# tiempo real al PID interno de SimpleFlight para asentarse -- enfoque
# equivocado, no la idea en si. Un operador humano no retoca el stick cada
# 200ms "porque puede": lo retoca cuando cambia el rumbo o aparece un
# obstaculo. Este enfoque separa las dos duraciones:
#   - CMD_DURATION_S: duracion real del comando en AirSim, mucho mayor que el
#     periodo del lazo -- el comando queda vigente varios segundos en vez de
#     medio segundo.
#   - Solo se cancela/reemite cuando el comando difiere del ultimo enviado
#     mas alla de las tolerancias, o cuando a ese comando le queda menos del
#     30% de vigencia (refresco de seguridad).
# Un cambio real (obstaculo, nuevo rumbo) sigue tomando efecto en el ciclo
# siguiente: cancelLastTask() no cambia, solo deja de dispararse sin motivo.
#
# Primer valor probado para CMD_DURATION_S (3.0s) mostro el problema real:
# el refresco de seguridad (cada ~2.1s con margen 30%) seguia produciendo un
# bache de -0.2/-0.25 m/s en vx cada vez que disparaba, IDENTICO en forma al
# cabeceo original -- prueba directa de que reemitir el comando (incluso sin
# cambiar el setpoint) es en si mismo lo que perturba a SimpleFlight, no la
# frecuencia con la que se hacia antes. Se subio a 120s para que el refresco
# de seguridad practicamente nunca dispare durante un tramo normal de vuelo;
# sigue acotando el riesgo de un proceso colgado (no crasheado) a minutos en
# vez de indefinido.
CMD_DURATION_S = float(os.getenv("CMD_DURATION_S", "120.0"))
CMD_VELOCITY_TOLERANCE_MPS = float(os.getenv("CMD_VELOCITY_TOLERANCE_MPS", "0.1"))
CMD_YAW_RATE_TOLERANCE_DPS = float(os.getenv("CMD_YAW_RATE_TOLERANCE_DPS", "1.0"))
CMD_REISSUE_MARGIN_FRACTION = float(os.getenv("CMD_REISSUE_MARGIN_FRACTION", "0.3"))


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
    # Timeout en segundos para las llamadas RPC al servidor de AirSim.
    # Configurable vía AIRSIM_RPC_TIMEOUT para evitar bloqueos silenciosos de simGetImages.
    timeout_seconds: float = float(os.getenv("AIRSIM_RPC_TIMEOUT", "8"))
    # Frecuencia del lazo de control: determina la duración de cada comando de
    # velocidad emitido (ver execute_velocity). Configurable para que main.py
    # pueda propagar LOOP_HZ sin tocar código.
    loop_hz: float = float(os.getenv("LOOP_HZ", "5.0"))
    _client: Any = field(default=None, init=False, repr=False)
    _connected: bool = field(default=False, init=False, repr=False)
    # Último Future de movimiento activo; se guarda solo para poder cancelarlo
    # en el apagado (disconnect/land), nunca se espera (.join()) en el ciclo
    # de control: eso es lo que fijaba el período del lazo en 2s.
    _last_move_future: Any = field(default=None, init=False, repr=False)
    # Ultimo comando de velocidad efectivamente enviado a AirSim (no cada
    # llamada a execute_velocity(), solo las que de verdad reemitieron):
    # (vx, vy, vz, yaw_rate, target_yaw). Ver CMD_DURATION_S mas arriba.
    _last_cmd: Optional[Tuple[float, float, float, float, Optional[float]]] = field(
        default=None, init=False, repr=False
    )
    _last_cmd_sent_at: float = field(default=0.0, init=False, repr=False)

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
            # timeout_value limita cada llamada RPC individual (simGetImages, getMultirotorState, etc.)
            # a timeout_seconds segundos; si AirSim no responde, lanza excepción en lugar de bloquearse.
            self._client = airsim.MultirotorClient(
                ip=self.ip, port=self.port, timeout_value=int(self.timeout_seconds)
            )
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

    def reset(self) -> bool:
        """Reinicia el vehiculo a su pose original y limpia estado fisico

        residual (colision, velocidad, integradores del controlador interno
        de SimpleFlight) antes de una nueva corrida. Necesario para que
        corridas sucesivas en el mismo proceso de AirSim (experiments/
        runner.py, N corridas por semilla/escenario/brazo) no arrastren
        estado de la corrida anterior -- simSetVehiclePose() por si solo
        solo teletransporta posicion/orientacion, no reinicia esto.

        client.reset() de AirSim desarma el vehiculo y deshabilita el
        control por API como efecto secundario (comportamiento documentado);
        por eso se re-habilitan y se despega de nuevo antes de devolver.
        """
        if not self._connected or self._client is None:
            print("[AirSimClient][simulado] Reiniciando vehículo...")
            return True
        try:
            self._client.reset()
            self._client.enableApiControl(True, vehicle_name=self.vehicle_name)
            self._client.armDisarm(True, vehicle_name=self.vehicle_name)
            self._client.takeoffAsync(vehicle_name=self.vehicle_name).join()
            # El estado fisico se reinicio; el ultimo comando "recordado" ya
            # no describe nada vigente, forzar reemision inmediata.
            self._last_cmd = None
            return True
        except Exception as exc:
            print(f"[AirSimClient] Error al reiniciar el vehículo: {exc}")
            return False

    def land(self) -> bool:
        """Ejecuta el aterrizaje autónomo y desarma los motores."""
        if not self._connected or self._client is None:
            print("[AirSimClient][simulado] Aterrizando dron y desarmando motores...")
            return True
        try:
            print(f"[AirSimClient] Aterrizando vehículo '{self.vehicle_name}'...")
            self._client.landAsync(vehicle_name=self.vehicle_name).join()
            self._client.armDisarm(False, vehicle_name=self.vehicle_name)
            print(f"[AirSimClient] Vehículo '{self.vehicle_name}' aterrizado y desarmado con éxito.")
            return True
        except Exception as exc:
            print(f"[AirSimClient] Error durante el aterrizaje: {exc}")
            return False

    def set_vehicle_pose(self, x: float, y: float, z: float, yaw_deg: float = 0.0) -> bool:
        """Posiciona / teletransporta el vehículo en coordenadas NED ignorando colisiones."""
        if not self._connected or self._client is None:
            return True
        try:
            yaw_rad = math.radians(yaw_deg)
            qz = math.sin(yaw_rad * 0.5)
            qw = math.cos(yaw_rad * 0.5)
            orientation = airsim.Quaternionr(0.0, 0.0, float(qz), float(qw))
            pos = airsim.Vector3r(float(x), float(y), float(z))
            pose = airsim.Pose(pos, orientation)
            self._client.simSetVehiclePose(pose, ignore_collision=True, vehicle_name=self.vehicle_name)
            time.sleep(0.2)
            return True
        except Exception as exc:
            print(f"[AirSimClient] Error al posicionar vehículo: {exc}")
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
            return self._unavailable_capture(return_depth)
        try:
            t_start = time.time()
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

            t_before_images = time.time()
            # Log previo: si el proceso muere aquí sin imprimir el timing posterior,
            # es señal inequívoca de que simGetImages bloqueó el hilo.
            print(f"[AirSimClient] simGetImages: solicitando {len(requests)} imagen(es)...")
            responses = self._client.simGetImages(requests, vehicle_name=self.vehicle_name)
            t_after_images = time.time()
            
            response = responses[0] if responses else None
            # Timestamp de captura real de la imagen, del reloj del propio
            # simulador (nanosegundos, AirSim). Se usa para telemetry["timestamp"]
            # en lugar de time.time() tomado despues de getMultirotorState():
            # ver CHANGELOG.md 2026-0826 para el bug que esto corrige (dt/derotacion
            # en flow_ttc.py contaminados por el jitter del round-trip RPC del
            # lado del cliente, en vez de reflejar el intervalo real entre frames).
            image_timestamp_s = (
                float(response.time_stamp) / 1e9
                if response is not None and getattr(response, "time_stamp", 0)
                else None
            )
            image = None
            t_before_resize = time.time()
            if response is not None and response.width > 0 and response.height > 0:
                img_1d = np.frombuffer(response.image_data_uint8, dtype=np.uint8)
                image = img_1d.reshape(response.height, response.width, 3)
                if (
                    image.shape[1] != self.frame_width
                    or image.shape[0] != self.frame_height
                ):
                    # Usar OpenCV si está disponible para máxima velocidad, si no fallback a numpy
                    try:
                        # pyrefly: ignore [missing-import]
                        import cv2
                        image = cv2.resize(image, (self.frame_width, self.frame_height), interpolation=cv2.INTER_NEAREST)
                    except Exception:
                        image = _resize_frame(image, self.frame_width, self.frame_height)
            t_after_resize = time.time()

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
                        try:
                            # pyrefly: ignore [missing-import]
                            import cv2
                            depth = cv2.resize(depth, (self.frame_width, self.frame_height), interpolation=cv2.INTER_NEAREST)
                        except Exception:
                            depth = _resize_depth(depth, self.frame_width, self.frame_height)

            t_before_state = time.time()
            state = self._client.getMultirotorState(vehicle_name=self.vehicle_name)
            t_after_state = time.time()
            telemetry = _state_to_telemetry(state, timestamp_s=image_timestamp_s)
            
            t_total = time.time() - t_start
            dt_images = (t_after_images - t_before_images) * 1000.0
            dt_resize = (t_after_resize - t_before_resize) * 1000.0
            dt_state = (t_after_state - t_before_state) * 1000.0
            print(f"[AirSimClient] Capture timing: total={t_total*1000.0:.1f}ms (simGetImages={dt_images:.1f}ms, resize={dt_resize:.1f}ms, getMultirotorState={dt_state:.1f}ms)")
            
            if return_depth:
                return image, depth, telemetry
            return image, telemetry
        except Exception as exc:
            print(f"[AirSimClient] Error capturando datos: {exc}")
            return self._unavailable_capture(return_depth)

    def _unavailable_capture(
        self, return_depth: bool
    ) -> Tuple[Optional[np.ndarray], Dict[str, Any]] | Tuple[Optional[np.ndarray], Optional[np.ndarray], Dict[str, Any]]:
        """Respuesta cuando AirSim no está disponible.

        En modo estricto (default en vuelo) NO se inventa un frame: el
        pipeline de percepción y deliberación debe degradarse explícitamente
        (ver main.py) en lugar de "volar" sobre datos ficticios. Los frames
        simulados solo se usan en tests con AIRSIM_STRICT=false.
        """
        if AIRSIM_STRICT:
            telem = self._simulated_telemetry()
            if return_depth:
                return None, None, telem
            return None, telem
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
            now = time.time()

            # No retocar el comando en curso si el nuevo es esencialmente
            # igual al ultimo enviado y todavia le queda vigencia real (ver
            # CMD_DURATION_S mas arriba): un cambio de rumbo o un obstaculo
            # sigue tomando efecto de inmediato mas abajo, esto solo evita
            # reemitir "lo mismo" sin motivo.
            if self._last_cmd is not None:
                lvx, lvy, lvz, lyaw_rate, ltarget_yaw = self._last_cmd
                same_velocity = (
                    abs(vx - lvx) < CMD_VELOCITY_TOLERANCE_MPS
                    and abs(vy - lvy) < CMD_VELOCITY_TOLERANCE_MPS
                    and abs(vz - lvz) < CMD_VELOCITY_TOLERANCE_MPS
                    and abs(yaw_rate - lyaw_rate) < CMD_YAW_RATE_TOLERANCE_DPS
                )
                same_target_yaw = (target_yaw is None and ltarget_yaw is None) or (
                    target_yaw is not None
                    and ltarget_yaw is not None
                    and abs(target_yaw - ltarget_yaw) < CMD_YAW_RATE_TOLERANCE_DPS
                )
                time_left = CMD_DURATION_S - (now - self._last_cmd_sent_at)
                still_valid = time_left > CMD_DURATION_S * CMD_REISSUE_MARGIN_FRACTION
                if same_velocity and same_target_yaw and still_valid:
                    return True

            # moveByVelocityBodyFrameAsync es "last-command-wins" en el servidor
            # de AirSim: no hace falta esperar (join) al comando anterior para
            # emitir el siguiente. Antes, cada ciclo bloqueaba hasta 2s
            # esperando ese join, lo cual fijaba el período del lazo en vez de
            # ser su consecuencia. cancelLastTask() descarta cualquier
            # comando en curso sin bloquear, permitiendo abortar una maniobra
            # a mitad de ejecución.
            try:
                self._client.cancelLastTask(vehicle_name=self.vehicle_name)
            except Exception:
                pass

            self._last_cmd = (vx, vy, vz, yaw_rate, target_yaw)
            self._last_cmd_sent_at = now
            duration = CMD_DURATION_S

            # Si todas las velocidades y giro son nulos, mantener el mismo
            # comando de velocidad-cero (no usar hoverAsync().join(), que
            # bloquea): un vx=vy=vz=0 con duration acotada logra el mismo
            # efecto sin detener el lazo.
            if abs(vx) < 0.05 and abs(vy) < 0.05 and abs(vz) < 0.05 and abs(yaw_rate) < 0.01 and target_yaw is None:
                self._last_move_future = self._client.moveByVelocityBodyFrameAsync(
                    0.0, 0.0, 0.0, duration=duration,
                    drivetrain=airsim.DrivetrainType.ForwardOnly,
                    yaw_mode=airsim.YawMode(is_rate=False, yaw_or_rate=0.0),
                    vehicle_name=self.vehicle_name,
                )
                return True

            # Giro puro en el lugar (vx=vy=0, sin target_yaw absoluto): en vez
            # de simular la rotacion embebiendola en moveByVelocityBodyFrameAsync
            # (que sigue siendo, ante todo, un comando de TRASLACION), usar el
            # primitivo nativo de AirSim para esto (2026-0826, ver CHANGELOG.md).
            # rotateByYawRateAsync es la maniobra que el propio firmware de
            # SimpleFlight ya sabe ejecutar manteniendo posicion/altitud
            # mientras gira -- no tiene sentido reimplementarla a mano
            # combinando ejes de traslacion en cero con yaw_rate. Coincide
            # exactamente con la fase de pivot-en-el-lugar de
            # waypoint_tracker.py (_sharp_turn_active/settle).
            if abs(vx) < 0.05 and abs(vy) < 0.05 and abs(yaw_rate) > 0.01 and target_yaw is None:
                self._last_move_future = self._client.rotateByYawRateAsync(
                    float(yaw_rate), duration, vehicle_name=self.vehicle_name,
                )
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

            self._last_move_future = self._client.moveByVelocityBodyFrameAsync(
                vx,
                vy,
                vz,
                duration=duration,
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


def _state_to_telemetry(state: Any, timestamp_s: Optional[float] = None) -> Dict[str, Any]:
    """Adapta un MultirotorState de AirSim a un dict simple en marco NED.

    ``timestamp_s`` es el instante real de captura (del reloj del simulador,
    via ``ImageResponse.time_stamp``) cuando esta telemetria acompania un
    frame; si no se provee (p. ej. ``get_telemetry()`` sin imagen asociada)
    se cae a ``time.time()`` como antes.
    """
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

    collision_info = getattr(state, "collision", None)
    has_collided = False
    collision_object = ""
    if collision_info is not None:
        has_collided = getattr(collision_info, "has_collided", False)
        collision_object = getattr(collision_info, "object_name", "")

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
        "collision": {
            "has_collided": bool(has_collided),
            "object_name": str(collision_object),
        },
        "timestamp": timestamp_s if timestamp_s is not None else time.time(),
        "source": "airsim",
    }

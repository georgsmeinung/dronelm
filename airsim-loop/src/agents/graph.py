# Definición del flujo de LangGraph y el Bucle de Control Jerárquico.
#
# Cambios de fondo respecto de la version original (ver PLAN-MEJORAS.md):
#   - El cliente de AirSim se inyecta (F0.3): un solo cliente conectado por
#     proceso, en vez de que get_airsim_client() reconstruyera el grafo entero.
#   - La ruta hacia el SLM es unica (F0.2): policy_router decide en un solo
#     paso hacia donde va el ciclo (antes habia un nodo + un router encadenado
#     que terminaba invocando al SLM dos veces por ciclo).
#   - El SLM corre en un hilo aparte (F0.5): el nodo deliberativo nunca
#     bloquea el lazo, ver deliberation_service.py.
#   - La percepcion produce un unico ObstacleField (F1.1): reemplaza a
#     detected_obstacles (que quedaba siempre en [] desde que se retiro YOLO)
#     y a la mascara del IPM retirado.
#   - Router de arma (F3.1): AGENT_ARM selecciona entre el brazo SLM (default,
#     comportamiento historico), un brazo FSM determinista, y un brazo
#     puramente reactivo (guiado a waypoint sin evasion, cota inferior).
from __future__ import annotations

import math
import os
import time
from typing import Any, Dict, List, Optional, TypedDict

try:
    from pathlib import Path
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[3] / "config" / ".env")
except Exception:  # pragma: no cover
    pass

# pyrefly: ignore [missing-import]
from langgraph.graph import END, StateGraph

from src.navigation.waypoint_tracker import effective_stall_threshold, hard_stall_threshold
from src.perception.obstacle_field import ObstacleField, empty_field, has_open_corridor

AGENT_ARM = os.getenv("AGENT_ARM", "slm")  # "slm" | "fsm" | "reactive"

# V3-VLM-REFINEMENT: umbrales IMU para detección de contacto/jitter.
_IMU_JITTER_ELEVATED_MPS2 = float(os.getenv("IMU_JITTER_ELEVATED_MPS2", "3.0"))
_IMU_JITTER_CRITICAL_MPS2 = float(os.getenv("IMU_JITTER_CRITICAL_MPS2", "8.0"))
_IMU_CONTACT_THRESHOLD_MPS2 = float(os.getenv("IMU_CONTACT_THRESHOLD_MPS2", "5.0"))
# V3b-VLM-REFINEMENT: detección de "pared invisible" por divergencia cmd/real.
_CMD_BLIND_FWD_MIN_MPS = float(os.getenv("CMD_BLIND_FWD_MIN_MPS", "0.45"))
_CMD_BLIND_ACT_MAX_MPS = float(os.getenv("CMD_BLIND_ACT_MAX_MPS", "0.30"))
# BF_MAX subido a 0.25: follaje UE5 dentro del convex hull produce bf=0-0.222;
# con 0.15 esos ciclos rompían la cuenta consecutiva. 0.25 deja pasar el rango
# real del árbol sin confundirse con obstáculos legítimos (bf > 0.5 en pasillo).
_CMD_BLIND_BF_MAX      = float(os.getenv("CMD_BLIND_BF_MAX",       "0.25"))
# 2 ciclos consecutivos (0.4s a 5Hz): reduce la ventana donde bf puede fluctuar.
_CMD_BLIND_CYCLES      = int(os.getenv("CMD_BLIND_CYCLES",          "2"))
# V3c-VLM-REFINEMENT: drone parado sin razón (obstáculo no visto por flujo óptico).
# 15 ciclos = 3 s: por encima del watchdog normal de VLM (1.5 s), por debajo del
# freeze observado (130 s). Independiente de cmd_vx → captura el caso ESCANEO.
_STOPPED_CYCLES_THRESHOLD = int(os.getenv("STOPPED_CYCLES_THRESHOLD", "15"))
# V4-VLM-REFINEMENT: profundidad monocular estimada (Depth Anything V2 Metric).
# Activa solo cuando flujo óptico dice "corredor libre" y drone avanza (ver
# perception_node). cmd_vx mínimo para disparar la inferencia; bf máximo por
# encima del cual el flujo óptico tiene control y no se necesita profundidad.
_DEPTH_CMD_VX_MIN      = float(os.getenv("DEPTH_CMD_VX_MIN",      "0.30"))
_DEPTH_BF_ACTIVATE     = float(os.getenv("DEPTH_BF_ACTIVATE",     "0.25"))
_DEPTH_BRAKE_M         = float(os.getenv("DEPTH_BRAKE_M",         "5.00"))
_DEPTH_MAX_AGE_MS      = float(os.getenv("DEPTH_MAX_AGE_MS",      "3000.0"))
# V4b: requiere N ciclos consecutivos de depth < umbral antes de disparar
# deliberative. Un falso positivo aislado (modelo Depth Anything V2 Metric
# sobre renders sintéticos de AirSim) no dispara; solo profundidad sostenida.
# El contador se bloquea durante evasive/deliberative para evitar el re-trigger
# inmediato al volver a reactive (ver perception_node).
_DEPTH_BELOW_THRESHOLD = int(os.getenv("DEPTH_BELOW_THRESHOLD",   "2"))
# V4c: altitud mínima (m AGL) para confiar en flujo óptico.
# Por debajo de OPTICAL_MIN_ALT_M el sensor ve suelo en movimiento y produce
# TTC falsos; la misma lógica que SLM_MIN_ALT_M pero para evasion reactiva.
_OPTICAL_MIN_ALT_M     = float(os.getenv("OPTICAL_MIN_ALT_M",     "4.5"))
# D1 (Zona 2): GIRAR_90 con historia de zonas — si el lado del waypoint tiene
# stall rate >= umbral con suficientes intentos, girar al lado contrario en vez de
# seguir hacia una zona ya conocida como bloqueada.
_GIRAR90_STALL_THRESHOLD = float(os.getenv("GIRAR90_STALL_THRESHOLD", "0.70"))
_GIRAR90_MIN_ATTEMPTS    = int(os.getenv("GIRAR90_MIN_ATTEMPTS",    "3"))

# Correccion activa de altitud durante FRENAR prolongado (2026-0824, opcion 3
# de CHANGELOG.md): moveByVelocityBodyFrameAsync(vz=0,...) reemitido cada
# ciclo no sostiene la altitud perfectamente durante ventanas largas (~9m de
# deriva medidos en 120s durante un FRENAR sostenido) -- es un controlador de
# VELOCIDAD, no de altitud, y pedir "velocidad cero" repetidamente no es lo
# mismo que pedir "quedate en esta altura". motor_node ancla la altitud al
# primer ciclo de FRENAR y corrige vz (mismo patron que la correccion de
# altitud de WaypointTracker.compute_guidance()) mientras dure el freno.
HOVER_ALT_DEADZONE_M = float(os.getenv("HOVER_ALT_DEADZONE_M", "0.3"))
HOVER_ALT_KP = float(os.getenv("HOVER_ALT_KP", "0.35"))
HOVER_ALT_MAX_VZ = float(os.getenv("HOVER_ALT_MAX_VZ", "0.8"))


# ---------------------------------------------------------------------------
# Estado del grafo (DroneState)
# ---------------------------------------------------------------------------
class DroneState(TypedDict, total=False):
    """Estado que circula entre los nodos del grafo."""

    rgb_image: Any
    prev_image: Any
    prev_telemetry: Dict[str, Any]
    frame_history: List[Any]  # Ring buffer real de los ultimos N frames para el VLM (F2.1)
    # Timestamp REAL de captura (reloj del simulador, no el de resolucion de
    # la deliberacion) de cada frame de frame_history, mismo indice a indice
    # -- 2026-0901, pedido explicito para poder nombrar los .png de auditoria
    # VLM con el instante en que se tomaron, no con cuando el VLM contesto
    # (pueden diferir varios segundos, mas en el barrido del escaneo profundo).
    frame_history_ts: List[float]
    telemetry: Dict[str, Any]
    degraded: bool  # True si AirSim no respondio este ciclo (F0.6)
    obstacle_field: ObstacleField  # F1.1: unico contrato de percepcion
    estimated_ttc: float  # derivado de obstacle_field.min_ttc(), para display/logging
    scene_summary: str
    next_action: str
    velocity_command: Dict[str, Any]
    route: str
    flight_status: str
    deliberations: List[Dict[str, Any]]
    last_deliberation: Optional[Dict[str, Any]]
    slm_request_id: Optional[int]
    waypoints: List[Dict[str, Any]]
    current_wp_index: int
    target_waypoint: Optional[Dict[str, Any]]
    waypoint_guidance: Dict[str, Any]
    mission_completed: bool
    active_maneuver: Optional[str]
    maneuver_cycles_left: int
    maneuver_command: Optional[Dict[str, Any]]
    evasion_stuck_cycles: int
    _delib_outcomes: List[Dict[str, Any]]
    # Corrigen el bug de escape por altura descontrolado (ver CHANGELOG.md
    # 2026-0824). _deliberation_pending: True mientras se espera al SLM
    # dentro del watchdog -- el caller se salta record_progress() para que
    # esperar una respuesta no cuente como "atascado". _consecutive_escapes:
    # cuenta disparos seguidos del escape sincrono (GANAR_ALTURA/CLIMB); al
    # superar MAX_CONSECUTIVE_ESCAPES se frena en el lugar en vez de seguir
    # subiendo sin techo.
    _deliberation_pending: bool
    _consecutive_escapes: int
    _hover_alt_anchor: Optional[float]  # altitud anclada durante FRENAR prolongado (corrige deriva, ver motor_node)
    # IMPORTANTE (2026-0824): LangGraph construye los canales del grafo a
    # partir de ESTE esquema y descarta en silencio cualquier clave que un
    # nodo escriba y no este declarada aca. Las cuatro de abajo se escribian
    # sin declarar, asi que nunca sobrevivian a `graph.invoke()`:
    #   - _escape_reset: el nodo deliberativo lo marca para que el lazo llame
    #     a WaypointTracker.reset_progress(). Al perderse, el contador de
    #     atasco NUNCA se reiniciaba: crecia monotono (5, 6, 8, 9, 11, ...
    #     medidos en vuelo), el router quedaba clavado en "deliberative" y el
    #     nodo deliberativo en su rama de escape -- el SLM no se consultaba
    #     ni una vez en 76 ciclos. Este era el deadlock duro.
    #   - _escape_locked: enclavamiento del escape agotado (ver deliberative).
    #   - _delib_baseline / _delib_last_baselined_id: memoria corta de
    #     resultados (F2.2), que por lo mismo nunca llego a acumular nada.
    #   - inject_corner: inyeccion de sub-waypoints de esquina (Manhattan).
    # Regla: toda clave que cruce la frontera nodo <-> lazo va declarada aca.
    _escape_reset: bool
    _escape_locked: bool
    _escape_baseline_dist: Optional[float]
    _delib_baseline: Optional[Dict[str, Any]]
    _delib_last_baselined_id: Optional[int]
    inject_corner: Optional[Dict[str, Any]]
    # H2 (PLAN-MEJORAS-3): escaneo espacial profundo en atasco duro
    # (DEADLOCK_STRATEGY=deep_vlm, ver src/agents/deep_scan.py). Mismo motivo
    # que el bloque de arriba: cruzan la frontera nodo <-> lazo via multiples
    # invocaciones de graph.invoke() (el barrido dura varios ciclos), asi que
    # van declaradas aca o LangGraph las descarta en silencio.
    _scan_phase: Optional[str]  # "rotando" | "asentando" | "capturado" | None
    _scan_heading_index: int
    _scan_frames: List[Any]
    _scan_start_yaw_deg: Optional[float]
    _scan_settle_left: int
    _deep_scan_request_id: Optional[int]
    _deadlock_cycles: int
    _deadlock_event: Optional[Dict[str, Any]]  # H3.2: metricas de resolucion, consumido por main.py/flight_logger
    # Instrumentacion de auditoria VLM (2026-0901, pedido explicito para
    # analisis): _pending_delib_prompt/_pending_delib_frames se fijan al
    # encolar un pedido (deliberative.py/deep_scan.py) y se leen al
    # resolverlo -- sobreviven entre invocaciones de graph.invoke() mientras
    # dura la espera asincrona al SLM/VLM, por eso van declaradas aca.
    # _pending_delib_frames/_last_delib_frames son listas de tuplas
    # (frame, capture_timestamp) -- cada frame lleva SU PROPIO timestamp real
    # de captura (frame_history_ts), no el instante en que el VLM contesto
    # (pueden diferir varios segundos, mas en el barrido del escaneo
    # profundo). _last_delib_frames es un canal de UNA sola pasada (igual que
    # _deadlock_event/_escape_reset): solo lleva contenido en el ciclo EXACTO
    # en que una deliberacion se resuelve, y FlightLogger lo consume via
    # pop() en main.py/runner.py -- nunca se acumulan frames RAW dentro de
    # `deliberations` (que vive toda la mision) para no inflar memoria.
    _pending_delib_prompt: Optional[str]
    _pending_delib_frames: Optional[List[Any]]
    _last_delib_frames: Optional[List[Any]]
    # C1 (Zona 2): stall rates publicados por capture_node para policy_router y
    # evasive_node. _traj_frente_* se leen en policy_router (TRAJ_STALL path);
    # _traj_izq/_der_* en evasive_node para desempate de direccion.
    # IMPORTANTE: si no estan declarados aqui LangGraph los descarta en silencio.
    _traj_frente_stall_rate: float
    _traj_frente_attempts: int
    _traj_izq_stall_rate: float
    _traj_izq_attempts: int
    _traj_der_stall_rate: float
    _traj_der_attempts: int
    # S1 (PLAN-SLAM): distancia al waypoint del ciclo anterior, para calcular
    # delta_wp_m en FlightTrajectory.record() al inicio del siguiente ciclo.
    # Estado del grafo (no del proceso): sobrevive entre graph.invoke() calls.
    _prev_wp_distance: Optional[float]
    # V1-VLM-REFINEMENT: sub-meta semántica reactiva del VLM.
    # vlm_goal: VlmGoal actual (confianza >= VLM_GOAL_MIN_CONFIDENCE).
    # _vlm_goal_history: últimas 3 metas + trigger_type, para contexto del prompt.
    # _vlm_proactive_request_id: ID de la consulta proactiva en vuelo (None si libre).
    vlm_goal: Optional[Dict[str, Any]]
    _vlm_goal_history: List[Dict[str, Any]]
    # V3-VLM-REFINEMENT: señales IMU (linear acceleration) para detección de contacto.
    # imu_jitter_level: "normal" | "elevado" | "crítico" (RMS aceleración transversal).
    # imu_contact_event: True si jitter alto por 2+ ciclos consecutivos con cmd > 0.3 m/s.
    # _imu_contact_cycles: contador interno de ciclos consecutivos de contacto.
    imu_jitter_level: str
    imu_contact_event: bool
    _imu_contact_cycles: int
    # V3b-VLM-REFINEMENT: "pared invisible" — velocidad comandada vs. real.
    # Señal pura cinemática: el drone manda velocidad frontal pero la física lo
    # detiene mientras el flujo óptico reporta corredor libre. Captura colisiones
    # con convex hulls opacos (árboles UE5, muros sin textura) sin requerir sensor
    # de profundidad. Equivalente real: comando motor vs. velocidad medida por IMU.
    # _blind_wall_cycles: ciclos consecutivos de condición activa.
    # blind_wall_event: True cuando _blind_wall_cycles >= CMD_BLIND_CYCLES (default 3).
    blind_wall_event: bool
    _blind_wall_cycles: int
    # V3c-VLM-REFINEMENT: ciclos consecutivos con velocidad real ≈ 0, sin importar
    # la acción comandada. Detecta el freeze del árbol (cmd_vx=0 en ESCANEO, donde
    # blind_wall_event nunca dispara). Se resetea sólo cuando el drone se mueve
    # (act_spd > 0.1 m/s); un RETROCEDER fallido mantiene la cuenta activa.
    _stopped_cycles: int
    # Señal unificada de obstáculo invisible (simplificación Zona 1): True cuando
    # cualquiera de V3/V3b/V3c está activa. policy_router usa este campo en lugar
    # de acceder directamente al contador _stopped_cycles; imu_contact_event y
    # blind_wall_event se mantienen como sub-campos para evasive_node y deliberative.
    stuck_invisible: bool
    # NUNCA agregar aca una clave de profundidad RAW del sensor AirSim
    # (depth/depth_image/min_obstacle_dist_m ni el tipo imagen planar/depth,
    # ver PLAN-MEJORAS-3.md §0.2). El test test_no_depth_in_flight_path.py
    # verifica esos patrones específicos.
    #
    # V4-VLM-REFINEMENT: EXCEPCIÓN EXPLÍCITA — profundidad INFERIDA por modelo
    # monocular (Depth Anything V2 Metric). Diferencia arquitectural: la entrada
    # es solo RGB (mismo frame del flujo óptico); el sensor de profundidad de
    # AirSim NO se invoca. Equivalente real: StereoNet/MiDaS en drone sin LiDAR.
    # Valor en metros del percentil-5 del sector frontal del mapa estimado.
    # None si el estimador no tiene resultado reciente (<= DEPTH_MAX_AGE_MS).
    _depth_proximity_m: Optional[float]
    _depth_below_cycles: int             # V4b: consecutive cycles with depth < BRAKE_M
    _depth_obstacle_type: Optional[str]  # E2: "follaje" | "superficie plana" | "desconocido" | None


# ---------------------------------------------------------------------------
# Lazy imports y construcción de nodos
# ---------------------------------------------------------------------------
def _build_nodes(airsim_client: Any) -> Dict[str, Any]:
    """Construye los callables de los nodos a partir de un AirSimClient YA

    conectado (F0.3: inyeccion de dependencia, un solo cliente por proceso).
    """
    from .reactive import reactive_node
    from .deliberative import (
        make_deliberation_service, make_deliberative_node,
        parse_vlm_goal, vlm_goal_to_inject_corner,
    )
    from .evasive import evasive_node
    from .fsm import fsm_node as _fsm_node_fn
    from .action_map import action_to_command
    from .spatial_history import FlightTrajectory, TrajectoryEvent, SLAM_STALL_THRESHOLD_M
    from src.perception import FlowTTCEstimator
    from src.perception.depth_estimator import DepthEstimator

    flow_ttc_estimator = FlowTTCEstimator()
    depth_estimator = DepthEstimator()  # V4: hilo background, inicia carga del modelo
    flight_trajectory = FlightTrajectory()  # S1: buffer de trayectoria (estado de proceso)
    deliberation_service = make_deliberation_service()
    deliberative_node = make_deliberative_node(deliberation_service, flight_trajectory)

    frame_history_size = int(os.getenv("VLM_FRAME_HISTORY_SIZE", "2"))  # 2026-0903: t y t-1, no solo t (pedido explicito)
    girar90_duration_s = float(os.getenv("GIRAR90_DURATION_S", "1.0"))

    # 1. Captura sensorial
    def capture_node(state: DroneState) -> DroneState:
        # S1 (PLAN-SLAM): registrar evento del ciclo ANTERIOR antes de sobreescribir
        # el estado. Usa la distancia al WP guardada del ciclo anterior (_prev_wp_distance)
        # vs la actual (waypoint_guidance.distance del ciclo que acaba de terminar).
        prev_telem = state.get("telemetry") or {}
        if prev_telem.get("source") == "airsim":
            curr_dist = float((state.get("waypoint_guidance") or {}).get("distance", 0.0))
            prev_dist = state.get("_prev_wp_distance")
            if prev_dist is not None:
                delta_wp = curr_dist - prev_dist  # positivo = retroceso, negativo = avance
                action_taken = state.get("next_action", "")
                # Stall = retroceso significativo O acción de escape (escape
                # implica que el camino estaba bloqueado ese ciclo, aunque la
                # distancia al WP no haya aumentado: p.ej. PERDER_ALTURA cerca
                # de un árbol no retrocede en distancia pero sí indica falla).
                _ESCAPE_STALL = {
                    "GANAR_ALTURA", "PERDER_ALTURA", "DESCENDER",
                    "FRENAR", "EVADIR_IZQUIERDA", "EVADIR_DERECHA", "GIRAR_90",
                }
                # ESCANEO = VLM procesando deadlock: dron quieto contra el obstáculo.
                # Si no avanzó más de 3 cm en ese ciclo, es improductivo → stall.
                _SCAN_NO_PROGRESS = 0.03
                stall = (
                    delta_wp > SLAM_STALL_THRESHOLD_M
                    or action_taken in _ESCAPE_STALL
                    or (action_taken == "ESCANEO" and delta_wp > -_SCAN_NO_PROGRESS)
                )
                pos = prev_telem.get("position") or {}
                orient_d = prev_telem.get("orientation") or {}
                had_evidence = (state.get("obstacle_field") or empty_field()).has_evidence()
                event = TrajectoryEvent(
                    timestamp=float(prev_telem.get("timestamp", 0.0)),
                    position=(
                        float(pos.get("x", 0.0)),
                        float(pos.get("y", 0.0)),
                        float(pos.get("z", 0.0)),
                    ),
                    heading_deg=math.degrees(float(orient_d.get("yaw", 0.0))),
                    action_taken=action_taken,
                    delta_wp_m=delta_wp,
                    stall=stall,
                    flow_had_evidence=had_evidence,
                )
                flight_trajectory.record(event)
                # Publicar frente_stall_rate en el estado para que policy_router
                # pueda activar slam_assess antes de llegar a hard_stall_threshold
                # cuando el campo óptico reporta corredor espurio (2026-0910).
                orient_now = prev_telem.get("orientation") or {}
                hdg_now = math.degrees(float(orient_now.get("yaw", 0.0)))
                _traj_stats = flight_trajectory.zone_stats(hdg_now)
                state["_traj_frente_stall_rate"] = _traj_stats["FRENTE"]["stall_rate"]
                state["_traj_frente_attempts"]   = _traj_stats["FRENTE"]["attempts"]
                state["_traj_izq_stall_rate"]    = _traj_stats["IZQUIERDA"]["stall_rate"]
                state["_traj_izq_attempts"]      = _traj_stats["IZQUIERDA"]["attempts"]
                state["_traj_der_stall_rate"]    = _traj_stats["DERECHA"]["stall_rate"]
                state["_traj_der_attempts"]      = _traj_stats["DERECHA"]["attempts"]
            state["_prev_wp_distance"] = curr_dist

        state["prev_image"] = state.get("rgb_image")
        state["prev_telemetry"] = state.get("telemetry", {}) or {}
        image, telemetry = airsim_client.capture()
        state["rgb_image"] = image
        state["telemetry"] = telemetry
        degraded = image is None or telemetry.get("source") != "airsim"
        state["degraded"] = degraded
        if not degraded:
            history = list(state.get("frame_history") or [])
            history_ts = list(state.get("frame_history_ts") or [])
            history.append(image)
            history_ts.append(float(telemetry.get("timestamp") or time.time()))
            state["frame_history"] = history[-frame_history_size:]
            state["frame_history_ts"] = history_ts[-frame_history_size:]

        # V3-VLM-REFINEMENT: jitter IMU desde aceleración lineal transversal.
        imu_la = (telemetry.get("imu_linear_acceleration") or {}) if isinstance(telemetry, dict) else {}
        ax = float(imu_la.get("ax", 0.0))
        ay = float(imu_la.get("ay", 0.0))
        jitter_rms = math.sqrt(ax * ax + ay * ay)
        if jitter_rms >= _IMU_JITTER_CRITICAL_MPS2:
            jitter_level = "crítico"
        elif jitter_rms >= _IMU_JITTER_ELEVATED_MPS2:
            jitter_level = "elevado"
        else:
            jitter_level = "normal"
        state["imu_jitter_level"] = jitter_level

        cmd_vel = state.get("velocity_command") or {}
        cmd_speed = math.hypot(float(cmd_vel.get("vx", 0.0)), float(cmd_vel.get("vy", 0.0)))
        contact_cycles = int(state.get("_imu_contact_cycles") or 0)
        if jitter_rms >= _IMU_CONTACT_THRESHOLD_MPS2 and cmd_speed > 0.3:
            contact_cycles += 1
        else:
            contact_cycles = 0
        state["_imu_contact_cycles"] = contact_cycles
        state["imu_contact_event"] = contact_cycles >= 2

        return state

    def degraded_hover_node(state: DroneState) -> DroneState:
        telemetry = state.get("telemetry", {}) or {}
        cmd = action_to_command("FRENAR", telemetry=telemetry)
        cmd["rationale"] = "AirSim no disponible: hover de seguridad, sin percepcion ni deliberacion (F0.6)."
        state["next_action"] = "FRENAR"
        state["velocity_command"] = cmd
        state["route"] = "degraded"
        state["flight_status"] = "degradado"
        return state

    # Percepcion (F1.1): un unico nodo que produce el ObstacleField completo.
    def perception_node(state: DroneState) -> DroneState:
        prev_image = state.get("prev_image")
        curr_image = state.get("rgb_image")
        prev_telemetry = state.get("prev_telemetry") or {}
        telemetry = state.get("telemetry") or {}
        field = flow_ttc_estimator.estimate(curr_image, prev_image, telemetry, prev_telemetry)
        state["obstacle_field"] = field
        state["estimated_ttc"] = field.min_ttc()
        state["scene_summary"] = field.summary_text()

        # V3b-VLM-REFINEMENT: detección de "pared invisible" por divergencia cmd/real.
        # El drone comanda velocidad frontal (vx > umbral) pero la física lo detiene
        # (velocidad real < umbral) mientras el flujo óptico reporta corredor libre.
        # Captura colisiones con convex hulls opacos (árboles, muros) sin sensor depth.
        # Equivalente real: comando motor vs. velocidad medida por IMU/barómetro/VIO.
        vel_cmd = state.get("velocity_command") or {}
        cmd_vx  = float(vel_cmd.get("vx", 0.0))
        vel_now = (state.get("telemetry") or {}).get("velocity") or {}
        act_spd = math.sqrt(
            float(vel_now.get("vx", 0.0)) ** 2 + float(vel_now.get("vy", 0.0)) ** 2
        )
        # prev_act_spd: velocidad del ciclo anterior — distingue "frenado por obstáculo"
        # (prev_spd > 0.20, luego act_spd cae) de "aceleración desde reposo"
        # (prev_spd ≈ 0, act_spd aún no subió). Sin esto, los primeros 2-3 ciclos
        # de cualquier despegue disparan blind_wall_event con CYCLES=2.
        prev_vel = (state.get("prev_telemetry") or {}).get("velocity") or {}
        prev_act_spd = math.sqrt(
            float(prev_vel.get("vx", 0.0)) ** 2 + float(prev_vel.get("vy", 0.0)) ** 2
        )
        blind_wall_cond = (
            cmd_vx >= _CMD_BLIND_FWD_MIN_MPS               # comandando hacia adelante
            and act_spd < _CMD_BLIND_ACT_MAX_MPS            # pero no se mueve ahora
            and field.blocked_fraction() < _CMD_BLIND_BF_MAX  # flujo óptico: corredor libre
            and (prev_act_spd >= 0.20 or int(state.get("_blind_wall_cycles") or 0) > 0)
            # ^^^: el drone YA estaba en movimiento antes de detenerse, O el contador
            # ya empezó (persistencia: un ciclo con bf ligeramente alta no rompe la cuenta).
        )
        prev_bw = int(state.get("_blind_wall_cycles") or 0)
        bw_cycles = (prev_bw + 1) if blind_wall_cond else 0
        state["_blind_wall_cycles"] = bw_cycles
        state["blind_wall_event"] = bw_cycles >= _CMD_BLIND_CYCLES

        # V3c-VLM-REFINEMENT: contador de "parado sin razón" en ruta deliberativa.
        # Solo acumula cuando el ciclo ANTERIOR fue "deliberative" (ESCANEO o
        # MANTENER_RUMBO de slam_assess) Y el VLM normal NO está procesando
        # (slm_request_id=None). Mientras el VLM espera respuesta, el freeze es
        # intencional — no contar. Se resetea cuando slm_request_id pasa a None
        # para evitar un disparo inmediato al terminar una deliberación normal.
        prev_stopped = int(state.get("_stopped_cycles") or 0)
        prev_route = state.get("route", "")
        slm_active = state.get("slm_request_id") is not None
        if act_spd > 0.10 or prev_route not in ("deliberative",) or slm_active:
            state["_stopped_cycles"] = 0
        else:
            # Techo de 200 para evitar overflow en corridas muy largas.
            state["_stopped_cycles"] = min(prev_stopped + 1, 200)

        # Señal unificada para policy_router: OR de las tres señales de obstáculo
        # invisible (V3/V3b/V3c). imu_contact y blind_wall tienen prioridad sobre
        # slm_request_id en el router; _stopped_cycles no (ver ordering en policy_router).
        state["stuck_invisible"] = (
            bool(state.get("imu_contact_event"))
            or bool(state.get("blind_wall_event"))
            or int(state.get("_stopped_cycles", 0)) >= _STOPPED_CYCLES_THRESHOLD
        )

        # V4 (A1): profundidad monocular inyectada en ObstacleField.
        # Trigger: flujo óptico reporta corredor libre (bf < umbral) y el drone
        # avanza. En esas condiciones foe_confidence es baja (malla del árbol);
        # Depth Anything V2 Metric detecta la superficie visual antes que el mesh.
        #
        # La profundidad NO se convierte en una señal de routing separada; se
        # inyecta como celdas bloqueadas en el sector centro del ObstacleField
        # (merge_depth_estimate). Así el router, el SLM y el logger ven un único
        # campo de percepción coherente sin lógica especial downstream.
        #
        # Guarda de N ciclos consecutivos (V4b): evita que un frame ruidoso
        # del modelo en renders sintéticos inyecte una señal falsa. Solo actúa
        # cuando depth < DEPTH_BRAKE_M durante _DEPTH_BELOW_THRESHOLD ciclos
        # seguidos sin interrupción por evasive o deliberative.
        bf_now = field.blocked_fraction()
        depth_trigger = (
            cmd_vx >= _DEPTH_CMD_VX_MIN
            and bf_now < _DEPTH_BF_ACTIVATE
            and prev_route not in ("evasive",)
        )
        if depth_trigger:
            depth_estimator.request(state.get("rgb_image"))
        depth_m, obstacle_type, depth_age_ms = depth_estimator.poll()

        prev_depth_cycles = int(state.get("_depth_below_cycles") or 0)
        depth_active = (
            depth_m is not None
            and depth_age_ms < _DEPTH_MAX_AGE_MS
            and depth_m < _DEPTH_BRAKE_M
            and depth_trigger
            and prev_route not in ("evasive", "deliberative")
        )
        if depth_active:
            new_depth_cycles = min(prev_depth_cycles + 1, 10)
        else:
            new_depth_cycles = 0
        state["_depth_below_cycles"] = new_depth_cycles

        if depth_active and new_depth_cycles >= _DEPTH_BELOW_THRESHOLD:
            # Inyectar en el ObstacleField: centro pasa a BLOQUEADO con TTC cinemático.
            field = field.merge_depth_estimate(depth_m, cmd_vx)
            state["obstacle_field"] = field
            state["estimated_ttc"] = field.min_ttc()
            state["scene_summary"] = field.summary_text()
            state["_depth_proximity_m"] = depth_m
            state["_depth_obstacle_type"] = obstacle_type
            # E2: añadir al prompt del SLM una pista táctica sobre el tipo de obstáculo.
            # "follaje" sugiere evasión diagonal / +1m; "superficie plana" sugiere
            # evasión amplia. La anotación complementa el source "flow+depth" del B1.
            _type_hints = {
                "follaje":         "Posibles huecos entre ramas — evasión diagonal o +1 m de altura puede ser viable.",
                "superficie plana": "Superficie compacta — evasión lateral amplia o ascenso significativo necesario.",
            }
            _hint = _type_hints.get(obstacle_type or "", "")
            if _hint:
                state["scene_summary"] = (
                    state["scene_summary"]
                    + f"\nObstáculo frontal (profundidad monocular): {obstacle_type}. {_hint}"
                )
        else:
            state["_depth_proximity_m"] = None
            state["_depth_obstacle_type"] = None

        # G1: Muro invisible por baja textura — contradiccion campo optico vs stall historico.
        # Cuando la tasa de stall frontal es significativa pero el campo optico reporta
        # corredor libre, es probable que haya un muro liso (edificio, pared de hormigon)
        # invisible al flujo optico. Inyectar aviso en scene_summary para que el SLM
        # no recomiende MANTENER_RUMBO y priorice un giro o evasion lateral.
        _g1_frente_stall = float(state.get("_traj_frente_stall_rate") or 0.0)
        _g1_frente_att   = int(state.get("_traj_frente_attempts") or 0)
        _G1_STALL_MIN = float(os.getenv("G1_STALL_MIN", "0.20"))
        _G1_ATT_MIN   = int(os.getenv("G1_ATT_MIN",    "3"))
        _G1_OCC_MAX   = float(os.getenv("G1_OCC_MAX",  "0.15"))
        if (_g1_frente_stall >= _G1_STALL_MIN
                and _g1_frente_att >= _G1_ATT_MIN
                and field.blocked_fraction() < _G1_OCC_MAX):
            state["scene_summary"] = (
                state.get("scene_summary", "")
                + f"\nAVISO [G1]: stall frontal {_g1_frente_stall:.0%}"
                  f" ({_g1_frente_att} intentos) con campo optico despejado"
                  f" — posible obstaculo invisible (muro liso, baja textura)."
                  f" MANTENER_RUMBO agravara el bloqueo."
                  f" Priorizar GIRAR_90 o evasion lateral amplia."
            )
        return state

    def girar_90_node(state: DroneState) -> DroneState:
        telemetry = state.get("telemetry", {}) or {}
        field: ObstacleField = state.get("obstacle_field") or empty_field()
        guidance = state.get("waypoint_guidance") or {}

        # D1 (Zona 2): antes de girar, consultar historia de stalls laterales.
        # action_map elige: bearing_err_deg < 0 → izquierda, >= 0 → derecha.
        # Si el lado preferido por bearing tiene >= THRESHOLD stall con >= MIN intentos
        # Y el lado contrario NO, negar el bearing para forzar el giro al otro lado.
        bearing_err = float(guidance.get("bearing_err_deg", 0.0))
        pref_key = "izq" if bearing_err < 0.0 else "der"
        opp_key  = "der" if pref_key == "izq" else "izq"
        pref_stall = float(state.get(f"_traj_{pref_key}_stall_rate") or 0.0)
        pref_att   = int(state.get(f"_traj_{pref_key}_attempts")    or 0)
        opp_stall  = float(state.get(f"_traj_{opp_key}_stall_rate") or 0.0)
        opp_att    = int(state.get(f"_traj_{opp_key}_attempts")     or 0)
        flip = (
            pref_stall >= _GIRAR90_STALL_THRESHOLD and pref_att >= _GIRAR90_MIN_ATTEMPTS
            and not (opp_stall >= _GIRAR90_STALL_THRESHOLD and opp_att >= _GIRAR90_MIN_ATTEMPTS)
        )
        if flip:
            # Negar el bearing (0.0 se desplaza levemente para que el signo cambie)
            flipped = -(bearing_err if bearing_err != 0.0 else 0.01)
            effective_guidance = {**guidance, "bearing_err_deg": flipped}
            flip_note = (
                f" [D1: lado {'izq' if pref_key=='izq' else 'der'} "
                f"{pref_stall:.0%}/{pref_att}int -> giro al lado contrario]"
            )
        else:
            effective_guidance = guidance
            flip_note = ""

        cmd = action_to_command("GIRAR_90", guidance=effective_guidance, telemetry=telemetry)
        side = "izquierda" if cmd["yaw_rate"] < 0 else "derecha"
        cmd["rationale"] = (
            f"FOV bloqueado ({field.blocked_fraction()*100:.0f}%). "
            f"Girando 90° hacia la {side} para buscar corredor.{flip_note}"
        )
        state["next_action"] = "GIRAR_90"
        state["velocity_command"] = cmd
        state["route"] = "girar_90"
        state["flight_status"] = "exploracion_yaw"
        loop_hz = float(os.getenv("LOOP_HZ", "5.0"))
        state["active_maneuver"] = "GIRAR_90"
        state["maneuver_cycles_left"] = max(1, round(girar90_duration_s * loop_hz))
        state["maneuver_command"] = cmd
        return state

    def motor_node(state: DroneState) -> DroneState:
        cmd = state.get("velocity_command") or {
            "macro_action": state.get("next_action", "MANTENER_RUMBO"),
            "vx": 0.0, "vy": 0.0, "vz": 0.0, "yaw_rate": 0.0,
        }

        telemetry = state.get("telemetry") or {}
        current_z = float((telemetry.get("position") or {}).get("z", 0.0))
        if cmd.get("macro_action") == "FRENAR":
            anchor = state.get("_hover_alt_anchor")
            if anchor is None:
                anchor = current_z
            dz = anchor - current_z  # NED: negativo si hay que subir para volver al ancla
            if abs(dz) > HOVER_ALT_DEADZONE_M:
                cmd = dict(cmd)
                cmd["vz"] = max(-HOVER_ALT_MAX_VZ, min(HOVER_ALT_MAX_VZ, HOVER_ALT_KP * dz))
            state["_hover_alt_anchor"] = anchor
        else:
            state["_hover_alt_anchor"] = None

        target_yaw = cmd.get("target_yaw")
        airsim_client.execute_velocity(
            vx=float(cmd.get("vx", 0.0)),
            vy=float(cmd.get("vy", 0.0)),
            vz=float(cmd.get("vz", 0.0)),
            yaw_rate=float(cmd.get("yaw_rate", 0.0)),
            target_yaw=float(target_yaw) if target_yaw is not None else None,
        )
        state["velocity_command"] = cmd
        deliberations = state.get("deliberations") or []
        if deliberations:
            state["last_deliberation"] = deliberations[-1]
        return state

    return {
        "capture": capture_node,
        "degraded_hover": degraded_hover_node,
        "perception": perception_node,
        "keep_going": reactive_node,
        "evasive": evasive_node,
        "deliberative": deliberative_node,
        "girar_90": girar_90_node,
        # H3.1 (PLAN-MEJORAS-3): el escaneo profundo es una capacidad compartida
        # entre slm y fsm; usan el mismo DeliberationService y FlightTrajectory.
        "fsm": lambda state: _fsm_node_fn(state, service=deliberation_service, trajectory=flight_trajectory),
        "motor": motor_node,
        "_airsim_client": airsim_client,
        "_deliberation_service": deliberation_service,
    }


# ---------------------------------------------------------------------------
# Routers Condicionales del Grafo
# ---------------------------------------------------------------------------
# NOTA sobre umbrales: calibrados con datos de vuelo real (F1.3, ver
# CHANGELOG.md 2026-0824). Los defaults de abajo solo aplican si .env no
# define la variable; los valores versionados en .env son los medidos.
TTC_EVASION_THRESHOLD = float(os.getenv("TTC_EVASION_THRESHOLD", "3.2"))
TTC_SAFE_THRESHOLD = float(os.getenv("TTC_SAFE_THRESHOLD", "4.6"))
FOV_BLOCKED_THRESHOLD = float(os.getenv("FOV_BLOCKED_THRESHOLD", "0.6"))
# Altitud mínima (m) por debajo de la cual los disparadores TTC/occupancy NO
# invocan el SLM — se desvían a "evasive" en su lugar.  Durante el ascenso
# inicial (WP_0 climb-first) el dron percibe suelo y ramas bajas como
# obstáculos y agotaba los timeouts del SLM antes de salir de los primeros 10m.
# El deep_scan de deadlock sigue activo a cualquier altitud.
SLM_MIN_ALT_M = float(os.getenv("SLM_MIN_ALT_M", "8.0"))


def degraded_router(state: DroneState) -> str:
    return "degraded_hover" if state.get("degraded") else "perception"


def policy_router(state: DroneState) -> str:
    """Router unico de politica (F0.2 + F1.1 + F3.1).

    Reemplaza a ttc_router + hover_before_slm_node + blind_wall_router_node
    de la version original: antes esos tres pasos (uno de ellos con una
    llamada directa a otro nodo dentro del cuerpo de la funcion) hacian que
    un mismo ciclo pudiera invocar al SLM dos veces. Aca la decision de arma
    (slm/fsm/reactive) y la decision tactica (keep_going/evasive/deliberative/
    girar_90) se resuelven en un unico paso, con un unico router condicional.
    """
    if AGENT_ARM == "reactive":
        return "keep_going"
    if AGENT_ARM == "fsm":
        return "fsm"

    # stuck_invisible: señal unificada de obstáculo invisible (V3/V3b/V3c),
    # computada en perception_node. Ver DroneState para descripción de sub-señales.
    # imu_contact y blind_wall tienen prioridad máxima (emergen antes que slm_request_id);
    # _stopped_cycles se evalúa después del check de slm_request_id (abajo) porque
    # el freeze puede ser intencional mientras el SLM procesa.
    if state.get("imu_contact_event") or state.get("blind_wall_event"):
        return "evasive"

    # No abandonar una deliberacion ya encolada (2026-0828, ver CHANGELOG.md):
    # si hay un pedido al LLM en vuelo (slm_request_id != None), seguir
    # enrutando a "deliberative" para que el poll se resuelva, sin importar
    # que el disparador puntual (p. ej. un TTC de un frame ruidoso) ya haya
    # desaparecido en el ciclo siguiente. Sin esto, el pedido queda huerfano:
    # nada vuelve a entrar a deliberative_node para resolverlo,
    # state["_deliberation_pending"] nunca vuelve a False, y el guard de
    # runner.py/main.py que salta record_progress() mientras se espera al SLM
    # queda activado para siempre -- desactivando el detector de atasco por
    # el resto de la mision. Confirmado con una corrida real de townsim_a
    # (replay offline de compute_guidance()/record_progress() contra las
    # posiciones reales del log): 528 ciclos seguidos de keep_going sin
    # escalar nunca, pese a que el dron no avanzaba.
    if state.get("slm_request_id") is not None:
        return "deliberative"

    # V3c (freeze): stuck_invisible cubre _stopped_cycles. Se evalúa DESPUÉS de
    # slm_request_id porque el freeze es intencional mientras el SLM procesa.
    if state.get("stuck_invisible"):
        return "evasive"

    # V4 (A1): la profundidad monocular ya está inyectada en obstacle_field
    # (merge_depth_estimate en perception_node). No hay routing especial aquí:
    # el campo con centro bloqueado activa los checks de TTC normales abajo.

    telem = state.get("telemetry") or {}
    pos = telem.get("position") or {}
    alt_m = abs(float(pos.get("z", 0.0)))
    below_slm_floor = alt_m < SLM_MIN_ALT_M
    # V4c: a baja altitud (ascenso inicial) el flujo óptico ve el suelo y genera
    # TTC falsos. Los checks TTC/occupancy quedan suspendidos hasta OPTICAL_MIN_ALT_M.
    # blind_wall / imu_contact (arriba) siguen activos a cualquier altitud.
    below_optical_floor = alt_m < _OPTICAL_MIN_ALT_M

    field: ObstacleField = state.get("obstacle_field") or empty_field()
    guidance = state.get("waypoint_guidance") or {}
    ttc = field.min_ttc()
    center_blocked = field.is_blocked("centro")
    center_ttc = field.sector_ttc("centro")

    # Persistencia de maniobra comprometida (anti flip-flop). Va ANTES del
    # escape de deadlock y del trigger TRAJ_STALL: una maniobra ya comprometida
    # (EVADIR_*, GANAR/PERDER_ALTURA, RETROCEDER, GIRAR_90) no debe ser
    # preemptada por ningún check downstream. Emergencias reales (blind_wall,
    # imu_contact) ya retornan "evasive" antes de llegar acá.
    active_man = state.get("active_maneuver")
    cycles_left = int(state.get("maneuver_cycles_left", 0))
    if active_man and cycles_left > 0:
        # Todos los escape maneuvers (EVADIR_*, GANAR/PERDER_ALTURA, RETROCEDER,
        # GIRAR_90) se ejecutan incondicionalmente: se mueven LEJOS del obstáculo,
        # así que TTC bajo es precisamente la razón por la que se comprometió el
        # escape. Si se deja caer al check de TTC, el trigger TRAJ_STALL (línea
        # siguiente) envía a "deliberative" y el SLM regular borra active_maneuver.
        return "evasive"

    # V4c: suprimir escapes de deadlock y triggers de trayectoria durante
    # la fase de ascenso inicial. El contador progress_stall_cycles se
    # incrementa cada ciclo que el drone no avanza hacia el waypoint en XY
    # — incluyendo los ciclos normales de subida donde vx=0 es intencional.
    # Tanto el escape de deadlock como el trigger de trayectoria se suprimen
    # hasta que el drone supere OPTICAL_MIN_ALT_M: la fase de ascenso genera
    # "atasco" ficticio porque el drone aún no está navegando en XY.
    # blind_wall / imu_contact (arriba) siguen activos a cualquier altitud.
    if below_optical_floor:
        return "keep_going"

    # Escape de deadlock: ya no cortocircuita la percepcion. Si el campo tiene
    # evidencia valida y ve un sector transitable, la decision tactica normal
    # (evasive / keep_going, mas abajo) es estrictamente mejor que forzar la
    # rama de escape -- en el vuelo del 2026-0824 el dron subio 12m mientras
    # la percepcion reportaba `DERECHA: DESPEJADO` porque este `return`
    # ocurria antes de mirar el campo. El bypass tiene techo (hard_stall_
    # threshold): un campo "despejado" espurio no desactiva el escape para
    # siempre.
    stuck = int(state.get("evasion_stuck_cycles", 0))
    if stuck >= effective_stall_threshold():
        if stuck >= hard_stall_threshold() or not has_open_corridor(field, guidance):
            return "deliberative"

    # Trigger por trayectoria (2026-0910): si el historial acumulado confirma
    # bloqueo frontal persistente, escalar a deliberative aunque el campo
    # óptico reportara corredor libre (optical flow no fiable cuando el drone
    # está embebido en la malla del árbol → foe_confidence baja → blocked=False
    # espurio). Umbral: >=70% stall FRENTE con >=10 eventos (2s a 5Hz).
    traj_stall = float(state.get("_traj_frente_stall_rate", 0.0))
    traj_att = int(state.get("_traj_frente_attempts", 0))
    _TRAJ_STALL_TRIGGER = float(os.getenv("TRAJ_STALL_TRIGGER_RATE", "0.70"))
    _TRAJ_ATT_TRIGGER = int(os.getenv("TRAJ_STALL_TRIGGER_MIN_ATT", "10"))
    if traj_stall >= _TRAJ_STALL_TRIGGER and traj_att >= _TRAJ_ATT_TRIGGER:
        return "deliberative"

    center_imminent = center_ttc <= TTC_EVASION_THRESHOLD
    if center_imminent or (center_blocked and center_ttc <= TTC_SAFE_THRESHOLD):
        if field.blocked_fraction() > FOV_BLOCKED_THRESHOLD:
            return "evasive" if below_slm_floor else "girar_90"
        return "evasive" if below_slm_floor else "deliberative"

    if center_blocked or ttc <= TTC_SAFE_THRESHOLD:
        return "evasive"

    return "keep_going"


# ---------------------------------------------------------------------------
# Construcción e Integración del Grafo
# ---------------------------------------------------------------------------
def build_workflow(airsim_client: Any) -> Any:
    """Construye el StateGraph. Requiere un AirSimClient ya conectado (F0.3)."""
    nodes = _build_nodes(airsim_client)
    workflow = StateGraph(DroneState)

    workflow.add_node("capture", nodes["capture"])
    workflow.add_node("degraded_hover", nodes["degraded_hover"])
    workflow.add_node("perception", nodes["perception"])
    workflow.add_node("keep_going", nodes["keep_going"])
    workflow.add_node("evasive", nodes["evasive"])
    workflow.add_node("deliberative", nodes["deliberative"])
    workflow.add_node("girar_90", nodes["girar_90"])
    workflow.add_node("fsm", nodes["fsm"])
    workflow.add_node("motor", nodes["motor"])

    workflow.set_entry_point("capture")
    workflow.add_conditional_edges("capture", degraded_router, {
        "degraded_hover": "degraded_hover",
        "perception": "perception",
    })
    workflow.add_conditional_edges("perception", policy_router, {
        "keep_going": "keep_going",
        "evasive": "evasive",
        "deliberative": "deliberative",
        "girar_90": "girar_90",
        "fsm": "fsm",
    })

    workflow.add_edge("degraded_hover", "motor")
    workflow.add_edge("keep_going", "motor")
    workflow.add_edge("evasive", "motor")
    workflow.add_edge("deliberative", "motor")
    workflow.add_edge("girar_90", "motor")
    workflow.add_edge("fsm", "motor")
    workflow.add_edge("motor", END)

    workflow._nodes_extra = nodes  # acceso a _airsim_client / _deliberation_service desde main.py
    return workflow


def compile_workflow(airsim_client: Any):
    """Compila el StateGraph. Devuelve (app_compilada, deliberation_service)."""
    workflow = build_workflow(airsim_client)
    app = workflow.compile()
    return app, workflow._nodes_extra["_deliberation_service"]


def get_airsim_client() -> Optional[Any]:
    """Deprecado (F0.3): antes reconstruia el grafo entero y creaba un

    SEGUNDO cliente de AirSim (con su propio takeoffAsync), mientras el grafo
    seguia usando el primero. main.py ahora crea un unico AirSimClient y lo
    inyecta en compile_workflow(). Esta funcion queda solo por compatibilidad
    hacia atras para llamadores externos; construye un cliente propio,
    desconectado del grafo real.
    """
    import warnings

    warnings.warn(
        "get_airsim_client() esta deprecado: crea un cliente AirSim "
        "independiente del que usa el grafo. Usar AirSimClient() + "
        "compile_workflow(client) directamente.",
        DeprecationWarning,
        stacklevel=2,
    )
    try:
        from src.hardware import AirSimClient

        client = AirSimClient()
        client.connect()
        return client
    except Exception:
        return None

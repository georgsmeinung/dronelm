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
from typing import Any, Dict, List, Optional, TypedDict

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover
    pass

# pyrefly: ignore [missing-import]
from langgraph.graph import END, StateGraph

from src.perception.obstacle_field import ObstacleField, empty_field

AGENT_ARM = os.getenv("AGENT_ARM", "slm")  # "slm" | "fsm" | "reactive"

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


# ---------------------------------------------------------------------------
# Lazy imports y construcción de nodos
# ---------------------------------------------------------------------------
def _build_nodes(airsim_client: Any) -> Dict[str, Any]:
    """Construye los callables de los nodos a partir de un AirSimClient YA

    conectado (F0.3: inyeccion de dependencia, un solo cliente por proceso).
    """
    from .reactive import reactive_node
    from .deliberative import make_deliberation_service, make_deliberative_node
    from .evasive import evasive_node
    from .fsm import fsm_node
    from .action_map import action_to_command
    from src.perception import FlowTTCEstimator

    flow_ttc_estimator = FlowTTCEstimator()
    deliberation_service = make_deliberation_service()
    deliberative_node = make_deliberative_node(deliberation_service)

    frame_history_size = int(os.getenv("VLM_FRAME_HISTORY_SIZE", "1"))
    girar90_duration_s = float(os.getenv("GIRAR90_DURATION_S", "1.0"))

    # 1. Captura sensorial
    def capture_node(state: DroneState) -> DroneState:
        state["prev_image"] = state.get("rgb_image")
        state["prev_telemetry"] = state.get("telemetry", {}) or {}
        image, telemetry = airsim_client.capture()
        state["rgb_image"] = image
        state["telemetry"] = telemetry
        degraded = image is None or telemetry.get("source") != "airsim"
        state["degraded"] = degraded
        if not degraded:
            history = list(state.get("frame_history") or [])
            history.append(image)
            state["frame_history"] = history[-frame_history_size:]
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
        return state

    def girar_90_node(state: DroneState) -> DroneState:
        telemetry = state.get("telemetry", {}) or {}
        field: ObstacleField = state.get("obstacle_field") or empty_field()
        cmd = action_to_command("GIRAR_90", telemetry=telemetry)
        cmd["rationale"] = f"FOV bloqueado ({field.blocked_fraction()*100:.0f}%). Girando 90° para buscar corredor."
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
        "fsm": fsm_node,
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

    stuck_threshold = int(os.getenv("EVASION_STUCK_THRESHOLD", "10"))
    stuck = int(state.get("evasion_stuck_cycles", 0))
    if stuck >= stuck_threshold:
        return "deliberative"

    field: ObstacleField = state.get("obstacle_field") or empty_field()
    ttc = field.min_ttc()
    center_blocked = field.is_blocked("centro")
    center_ttc = field.sector_ttc("centro")

    active_man = state.get("active_maneuver")
    cycles_left = int(state.get("maneuver_cycles_left", 0))
    if active_man and cycles_left > 0 and ttc > TTC_EVASION_THRESHOLD:
        return "evasive"

    center_imminent = center_ttc <= TTC_EVASION_THRESHOLD
    if center_imminent or (center_blocked and center_ttc <= TTC_SAFE_THRESHOLD):
        if field.blocked_fraction() > FOV_BLOCKED_THRESHOLD:
            return "girar_90"
        return "deliberative"

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

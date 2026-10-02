# Grafo de control (v2): capture -> perception -> navigate -> motor.
#
# Dos lazos desacoplados (ver vlm_strategic.py):
#   - Lazo rapido (5 Hz): guiado al waypoint + evasion por flujo optico. Es el unico que comanda
#     velocidades y el responsable de lo inminente.
#   - Lazo lento (VLM, ~0.3 Hz, asincrono): propone sub-metas en coordenadas del mundo ancladas a la
#     pose del frame que vio. Ante un deadlock, barrido panoramico + VLM (deep_scan.py).
#
# 2026-0930 -- simplificacion por evidencia (12 corridas citysim_pilot con este grafo):
#   - navigate_node: de ~15 reglas a 8. Se quitaron la consulta tactica por sector, el escape
#     vertical forzado, los eventos de "frentes bloqueados", el disparador por FlightTrajectory,
#     el contador de atasco del tracker como disparador, la deteccion de escaneo huerfano, el
#     freno por profundidad y la profundidad monocular (desactivada). Ver stall_detector.py.
#   - GIRAR_90 ya no inyecta una esquina determinista (74 esquinas: mediana 0.35 m de avance al WP
#     real en 20 s). En su lugar adelanta la consulta al VLM estrategico con el frame que ve el muro.
#   - Deadlock sin VLM (blind) o con el VLM fallando: GANAR_ALTURA, la unica maniobra que en las
#     corridas libero al dron de una estructura (RETROCEDER tuvo avance mediano negativo).
#   - policy_router (stub sin uso) y get_airsim_client (deprecado) eliminados.
from __future__ import annotations

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

from src.navigation.speed_governor import SpeedGovernor
from src.perception.obstacle_field import ObstacleField, empty_field

AGENT_ARM = os.getenv("AGENT_ARM", "slm")

TTC_EVASION_THRESHOLD = float(os.getenv("TTC_EVASION_THRESHOLD", "3.2"))
TTC_SAFE_THRESHOLD = float(os.getenv("TTC_SAFE_THRESHOLD", "4.6"))
FOV_BLOCKED_THRESHOLD = float(os.getenv("FOV_BLOCKED_THRESHOLD", "0.6"))

HOVER_ALT_DEADZONE_M = float(os.getenv("HOVER_ALT_DEADZONE_M", "0.3"))
HOVER_ALT_KP = float(os.getenv("HOVER_ALT_KP", "0.35"))
HOVER_ALT_MAX_VZ = float(os.getenv("HOVER_ALT_MAX_VZ", "0.8"))

_OPTICAL_MIN_ALT_M = float(os.getenv("OPTICAL_MIN_ALT_M", "4.5"))
# Techo del escape vertical determinista: por encima, girar hacia el WP en vez de seguir subiendo.
_MAX_ESCAPE_ALT_M = float(os.getenv("MAX_ESCAPE_ALT_M", "30.0"))


class DroneState(TypedDict, total=False):
    """Estado que circula entre nodos. Toda clave que cruce la frontera nodo <-> lazo externo
    DEBE estar declarada: LangGraph descarta en silencio las que no lo estan."""

    # Percepcion y sensores
    rgb_image: Any
    prev_image: Any
    prev_telemetry: Dict[str, Any]
    frame_history: List[Any]
    frame_history_ts: List[float]
    telemetry: Dict[str, Any]
    degraded: bool
    obstacle_field: ObstacleField
    estimated_ttc: float
    scene_summary: str
    # Mision y guiado (los escribe el lazo externo)
    waypoints: List[Dict[str, Any]]
    current_wp_index: int
    target_waypoint: Optional[Dict[str, Any]]
    waypoint_guidance: Dict[str, Any]
    mission_completed: bool
    evasion_stuck_cycles: int
    # Decision y actuacion
    next_action: str
    velocity_command: Dict[str, Any]
    route: str
    flight_status: str
    active_maneuver: Optional[str]
    maneuver_cycles_left: int
    maneuver_command: Optional[Dict[str, Any]]
    _hover_alt_anchor: Optional[float]
    _speed_cap: Optional[float]
    # VLM: auditoria y canales hacia el lazo externo
    deliberations: List[Dict[str, Any]]
    last_deliberation: Optional[Dict[str, Any]]
    slm_request_id: Optional[int]
    _deliberation_pending: bool
    _pending_delib_prompt: Optional[str]
    _pending_delib_frames: Optional[List[Any]]
    _last_delib_frames: Optional[List[Any]]
    _vlm_strategic: Optional[Dict[str, Any]]
    inject_corner: Optional[Dict[str, Any]]
    _clear_subgoals: bool
    # Deadlock / barrido panoramico (deep_scan.py)
    _escape_reset: bool
    _deadlock_cycles: int
    _deadlock_event: Optional[Dict[str, Any]]
    _scan_phase: Optional[str]
    _scan_heading_index: int
    _scan_frames: List[Any]
    _scan_start_yaw_deg: Optional[float]
    _scan_settle_left: int
    _scan_rot_stall: int
    _deep_scan_request_id: Optional[int]
    _deep_scan_request_ts: Optional[float]
    _scan_started_ts: Optional[float]
    # StallDetector (publicado para logging)
    imu_jitter_level: str
    imu_contact_event: bool
    blind_wall_event: bool
    _stopped_cycles: int
    _wp_no_progress_cycles: int
    _freeze_cycles: int


# Duracion de cada maniobra comprometida: (variable de entorno, default en s).
_MANEUVER_DURATION = {
    "GANAR_ALTURA": ("ESCAPE_MANEUVER_DURATION_S", 1.6),
    "PERDER_ALTURA": ("ESCAPE_MANEUVER_DURATION_S", 1.6),
    "GIRAR_90": ("GIRAR90_DURATION_S", 1.0),
    "EVADIR_IZQUIERDA": ("MANEUVER_DURATION_S", 1.0),
    "EVADIR_DERECHA": ("MANEUVER_DURATION_S", 1.0),
}
_STATUS = {
    "MANTENER_RUMBO": "vuelo_waypoint", "EVADIR_IZQUIERDA": "evasion_lateral",
    "EVADIR_DERECHA": "evasion_lateral", "GIRAR_90": "exploracion_yaw",
    "GANAR_ALTURA": "escape_altitud", "PERDER_ALTURA": "escape_altitud", "FRENAR": "frenado",
}


def _build_nodes(airsim_client: Any) -> Dict[str, Any]:
    """Construye los nodos sobre un AirSimClient ya conectado."""
    from .reactive import reactive_node
    from .evasive import evasive_node
    from .fsm import fsm_node as _fsm_node_fn
    from .action_map import action_to_command
    from .stall_detector import StallDetector
    from .vlm_client import make_deliberation_service
    from .vlm_strategic import StrategicLayer
    from .deep_scan import DEADLOCK_STRATEGY, deep_scan_cycle
    from src.perception import FlowTTCEstimator

    flow_ttc_estimator = FlowTTCEstimator()
    stall = StallDetector()
    governor = SpeedGovernor()
    deliberation_service = make_deliberation_service()
    strategic = StrategicLayer(deliberation_service)
    frame_history_size = int(os.getenv("VLM_FRAME_HISTORY_SIZE", "1"))
    loop_hz = float(os.getenv("LOOP_HZ", "5.0"))

    # ------------------------------------------------------------------ 1. captura
    def capture_node(state: DroneState) -> DroneState:
        state["prev_image"] = state.get("rgb_image")
        state["prev_telemetry"] = state.get("telemetry", {}) or {}
        image, telemetry = airsim_client.capture()
        state["rgb_image"] = image
        state["telemetry"] = telemetry
        degraded = image is None or telemetry.get("source") != "airsim"
        state["degraded"] = degraded
        if not degraded:
            history = list(state.get("frame_history") or []) + [image]
            history_ts = list(state.get("frame_history_ts") or []) + [float(telemetry.get("timestamp") or time.time())]
            state["frame_history"] = history[-frame_history_size:]
            state["frame_history_ts"] = history_ts[-frame_history_size:]
        return state

    def degraded_hover_node(state: DroneState) -> DroneState:
        cmd = action_to_command("FRENAR", telemetry=state.get("telemetry", {}) or {})
        cmd["rationale"] = "AirSim no disponible: hover de seguridad (F0.6)."
        state["next_action"] = "FRENAR"
        state["velocity_command"] = cmd
        state["route"] = "degraded"
        state["flight_status"] = "degradado"
        return state

    # ------------------------------------------------------------------ 2. percepcion
    def perception_node(state: DroneState) -> DroneState:
        field = flow_ttc_estimator.estimate(
            state.get("rgb_image"), state.get("prev_image"),
            state.get("telemetry") or {}, state.get("prev_telemetry") or {},
        )
        state["obstacle_field"] = field
        state["estimated_ttc"] = field.min_ttc()
        state["scene_summary"] = field.summary_text()
        return state

    # ------------------------------------------------------------------ 3. navegacion
    def _strategic_tick(state: DroneState) -> None:
        """VLM estrategico: no bloqueante, nunca comanda velocidades (ver vlm_strategic.py)."""
        audit = strategic.tick(state)
        state["_vlm_strategic"] = strategic.last_outcome
        if audit is None:
            return
        dl = list(state.get("deliberations") or [])
        dl.append({
            "id": len(dl) + 1,
            "timestamp": audit["timestamp"],
            "arm": audit["arm"],
            "prompt": audit["prompt"],
            "raw_response": audit["raw_response"],
            "macro_action": "SUBMETA" if audit["subgoal"] else None,
            "rationale": audit["reason"],
            "is_fallback": audit["parsed"] is None,
            "timeout": False,
            "adherent": audit["parsed"] is not None,
            "used_json_schema": bool((audit["parsed"] or {}).get("used_json_schema", False)),
            "latency_ms": audit["latency_ms"],
        })
        state["deliberations"] = dl
        if audit.get("frame") is not None:
            state["_last_delib_frames"] = [(audit["frame"], audit.get("frame_ts"))]

    def _dispatch(state: DroneState, macro: str, rationale: str, route: str) -> DroneState:
        cmd = action_to_command(macro, guidance=state.get("waypoint_guidance") or {},
                                telemetry=state.get("telemetry") or {})
        cmd["rationale"] = rationale
        state["velocity_command"] = cmd
        state["next_action"] = macro
        state["route"] = route
        state["flight_status"] = _STATUS.get(macro, "vuelo")
        if macro in _MANEUVER_DURATION:
            env, default = _MANEUVER_DURATION[macro]
            dur = float(os.getenv(env, str(default)))
            state["active_maneuver"] = macro
            state["maneuver_cycles_left"] = max(1, round(dur * loop_hz))
            state["maneuver_command"] = cmd
        return state

    def _deadlock_resolve(state: DroneState, field: ObstacleField, guidance: Dict, telem: Dict) -> DroneState:
        """Deadlock: barrido + VLM (deep_vlm) o, si no hay VLM / falla, escape vertical."""
        strategic.cancel("cancelado_por_deadlock")
        dc = int(state.get("_deadlock_cycles", 0)) + 1
        state["_deadlock_cycles"] = dc
        if DEADLOCK_STRATEGY == "deep_vlm":
            if deep_scan_cycle(state, deliberation_service, field, telem, guidance, AGENT_ARM, dc):
                if state.get("_escape_reset"):
                    stall.reset()
                return state
        # blind, o el barrido fallo (watchdog, formato invalido, rotacion imposible).
        stall.reset()
        state["_escape_reset"] = True
        state["_deadlock_cycles"] = 0
        alt_m = abs(float((telem.get("position") or {}).get("z", 0.0)))
        macro = "GANAR_ALTURA" if alt_m < _MAX_ESCAPE_ALT_M else "GIRAR_90"
        if not state.get("_deadlock_event"):
            state["_deadlock_event"] = {
                "strategy": DEADLOCK_STRATEGY, "arm": AGENT_ARM, "resolved_by_scan": False,
                "cycles_to_resolve": None, "fell_back_to_blind": True, "macro": macro,
            }
        return _dispatch(state, macro, f"Deadlock sin resolucion del VLM ({DEADLOCK_STRATEGY}): escape {macro}.",
                         "tactical")

    def navigate_node(state: DroneState) -> DroneState:
        stall.update(state)
        stall.publish(state)

        # Despegue vertical, comun a los tres brazos: el guiado sube en el lugar hasta la altitud del
        # primer objetivo. El flujo optico de un ascenso puro no es valido (FOE espurio), asi que
        # tampoco hay evasion basada en flujo. Ver WaypointTracker (TAKEOFF_VERTICAL).
        if (state.get("waypoint_guidance") or {}).get("takeoff"):
            return reactive_node(state)

        if AGENT_ARM == "reactive":
            return reactive_node(state)
        if AGENT_ARM == "fsm":
            return _fsm_node_fn(state, service=deliberation_service)

        telem = state.get("telemetry") or {}
        guidance = state.get("waypoint_guidance") or {}
        field: ObstacleField = state.get("obstacle_field") or empty_field()
        alt_m = abs(float((telem.get("position") or {}).get("z", 0.0)))

        # Lazo lento: el VLM estrategico corre siempre en segundo plano.
        _strategic_tick(state)

        # 1. Un barrido en curso es duenio del dron hasta resolver o fallar (sus watchdogs lo acotan).
        if state.get("_scan_phase") is not None or state.get("_deep_scan_request_id") is not None:
            return _deadlock_resolve(state, field, guidance, telem)

        # 2. Deadlock: trabado (avance ordenado sin movimiento) o ~10 s sin acercarse al objetivo.
        # Precede a toda otra regla salvo el barrido: en el piloto citysim_pilot seed 99 un
        # PERDER_ALTURA contra el parapeto de la autopista se repitio 220 ciclos sin que el deadlock
        # llegara a evaluarse, y con la velocidad medida las evasiones por blind_wall (regla 4) y la
        # maniobra comprometida (regla 3) lo tapaban igual. Una maniobra que no mueve al dron en 2 s
        # no es una decision en curso: es un atasco.
        if stall.stopped_prolonged or stall.wp_no_progress:
            return _deadlock_resolve(state, field, guidance, telem)

        # 3. Maniobra comprometida (anti flip-flop).
        active_man = state.get("active_maneuver")
        cycles_left = int(state.get("maneuver_cycles_left", 0))
        if active_man and cycles_left > 0:
            state["velocity_command"] = state.get("maneuver_command") or {}
            state["next_action"] = active_man
            state["maneuver_cycles_left"] = cycles_left - 1
            if cycles_left <= 1:
                state["active_maneuver"] = None
                state["maneuver_command"] = None
            state["route"] = "evasive"
            state["flight_status"] = f"maniobra_{active_man.lower()}"
            return state

        # 4. Contacto que el flujo optico no ve (IMU / avance ordenado sin movimiento).
        if stall.imu_contact or stall.blind_wall:
            return evasive_node(state)

        # 5. Despegue/aterrizaje: bajo el piso optico el flujo no es valido.
        under_ceiling = guidance.get("ceiling_z") is not None
        if alt_m < _OPTICAL_MIN_ALT_M and not under_ceiling:
            return reactive_node(state)

        # 6. El WP esta bajo un techo detectado: descender (z como dimension de navegacion).
        if guidance.get("z_path_blocked") and float(guidance.get("dz", 0.0)) > 1.0:
            return _dispatch(state, "PERDER_ALTURA", "Camino vertical bloqueado por techo.", "reactive")

        if alt_m < _OPTICAL_MIN_ALT_M:  # vuelo bajo un techo: sin evasion basada en flujo
            return reactive_node(state)

        # 7. Peligro frontal por flujo optico.
        center_ttc = field.sector_ttc("centro")
        center_blocked = field.is_blocked("centro")
        if center_ttc <= TTC_EVASION_THRESHOLD or (center_blocked and center_ttc <= TTC_SAFE_THRESHOLD):
            if field.blocked_fraction() > FOV_BLOCKED_THRESHOLD:
                # Muro de frente: girar hacia el lado del WP y adelantar la consulta al VLM con el
                # frame que ve el muro (el rodeo lo decide el modelo, no una esquina fija).
                strategic.expedite()
                _strategic_tick(state)
                return _dispatch(state, "GIRAR_90",
                                 f"FOV bloqueado ({field.blocked_fraction() * 100:.0f}%).", "girar_90")
            return evasive_node(state)
        if center_blocked or field.min_ttc() <= TTC_SAFE_THRESHOLD:
            return evasive_node(state)

        # 8. Camino despejado: guiado nominal.
        return reactive_node(state)

    # ------------------------------------------------------------------ 4. motor
    def motor_node(state: DroneState) -> DroneState:
        cmd = state.get("velocity_command") or {
            "macro_action": state.get("next_action", "MANTENER_RUMBO"),
            "vx": 0.0, "vy": 0.0, "vz": 0.0, "yaw_rate": 0.0,
        }
        current_z = float(((state.get("telemetry") or {}).get("position") or {}).get("z", 0.0))
        # Ancla de altitud en FRENAR: vz=0 reemitido es un controlador de velocidad, no de altura.
        if cmd.get("macro_action") == "FRENAR":
            anchor = state.get("_hover_alt_anchor")
            if anchor is None:
                anchor = current_z
            dz = anchor - current_z
            if abs(dz) > HOVER_ALT_DEADZONE_M:
                cmd = dict(cmd)
                cmd["vz"] = max(-HOVER_ALT_MAX_VZ, min(HOVER_ALT_MAX_VZ, HOVER_ALT_KP * dz))
            state["_hover_alt_anchor"] = anchor
        else:
            state["_hover_alt_anchor"] = None

        # Gobernador de velocidad (ver src/navigation/speed_governor.py).
        fld = state.get("obstacle_field")
        cap = governor.update(
            getattr(fld, "source", "none") if fld is not None else "none",
            fld.blocked_fraction() if fld is not None else 0.0,
            bool(state.get("active_maneuver")),
            str(state.get("next_action", "")),
        )
        state["_speed_cap"] = cap
        if cap is not None and cmd.get("macro_action") == "MANTENER_RUMBO" and float(cmd.get("vx", 0.0)) > cap:
            cmd = dict(cmd)
            cmd["vx"] = cap
            cmd["rationale"] = f"{cmd.get('rationale', '')} [tope {cap:.1f} m/s]".strip()

        target_yaw = cmd.get("target_yaw")
        airsim_client.execute_velocity(
            vx=float(cmd.get("vx", 0.0)),
            vy=float(cmd.get("vy", 0.0)),
            vz=float(cmd.get("vz", 0.0)),
            yaw_rate=float(cmd.get("yaw_rate", 0.0)),
            target_yaw=float(target_yaw) if target_yaw is not None else None,
        )
        state["velocity_command"] = cmd
        if state.get("deliberations"):
            state["last_deliberation"] = state["deliberations"][-1]
        return state

    return {
        "capture": capture_node,
        "degraded_hover": degraded_hover_node,
        "perception": perception_node,
        "navigate": navigate_node,
        "motor": motor_node,
        "_airsim_client": airsim_client,
        "_deliberation_service": deliberation_service,
    }


def degraded_router(state: DroneState) -> str:
    return "degraded_hover" if state.get("degraded") else "perception"


def build_workflow(airsim_client: Any) -> Any:
    nodes = _build_nodes(airsim_client)
    workflow = StateGraph(DroneState)
    workflow.add_node("capture", nodes["capture"])
    workflow.add_node("degraded_hover", nodes["degraded_hover"])
    workflow.add_node("perception", nodes["perception"])
    workflow.add_node("navigate", nodes["navigate"])
    workflow.add_node("motor", nodes["motor"])
    workflow.set_entry_point("capture")
    workflow.add_conditional_edges("capture", degraded_router, {
        "degraded_hover": "degraded_hover",
        "perception": "perception",
    })
    workflow.add_edge("perception", "navigate")
    workflow.add_edge("degraded_hover", "motor")
    workflow.add_edge("navigate", "motor")
    workflow.add_edge("motor", END)
    workflow._nodes_extra = nodes
    return workflow


def compile_workflow(airsim_client: Any):
    """Compila el StateGraph. Devuelve (app, deliberation_service)."""
    workflow = build_workflow(airsim_client)
    return workflow.compile(), workflow._nodes_extra["_deliberation_service"]

# Grafo de navegacion con arquitectura por capas (v2).
#
# Cambios fundamentales respecto de legacy/graph_v1.py:
#   - 4 nodos: capture -> perception -> navigate -> motor (no branching router)
#   - navigate_node combina reactive + evasive + tactical en un unico nodo
#   - VLM proactivo: se consulta ANTES del deadlock, no despues
#   - VLM nunca frena: si la respuesta no llego, capa reactiva guia al drone
#   - StallDetector: objeto de proceso (como FlightTrajectory), no campos en state
#   - FlightTrajectory como senal primaria de routing en deadlock
from __future__ import annotations

from collections import deque
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

from src.navigation.speed_governor import SpeedGovernor
from src.navigation.waypoint_tracker import effective_stall_threshold, hard_stall_threshold
from src.perception.obstacle_field import ObstacleField, empty_field, has_open_corridor

AGENT_ARM = os.getenv("AGENT_ARM", "slm")

TTC_EVASION_THRESHOLD = float(os.getenv("TTC_EVASION_THRESHOLD", "3.2"))
TTC_SAFE_THRESHOLD = float(os.getenv("TTC_SAFE_THRESHOLD", "4.6"))
FOV_BLOCKED_THRESHOLD = float(os.getenv("FOV_BLOCKED_THRESHOLD", "0.6"))
SLM_MIN_ALT_M = float(os.getenv("SLM_MIN_ALT_M", "8.0"))

HOVER_ALT_DEADZONE_M = float(os.getenv("HOVER_ALT_DEADZONE_M", "0.3"))
HOVER_ALT_KP = float(os.getenv("HOVER_ALT_KP", "0.35"))
HOVER_ALT_MAX_VZ = float(os.getenv("HOVER_ALT_MAX_VZ", "0.8"))

_OPTICAL_MIN_ALT_M = float(os.getenv("OPTICAL_MIN_ALT_M", "4.5"))
_GIRAR90_STALL_THRESHOLD = float(os.getenv("GIRAR90_STALL_THRESHOLD", "0.70"))
_GIRAR90_MIN_ATTEMPTS = int(os.getenv("GIRAR90_MIN_ATTEMPTS", "3"))
_TRAJ_STALL_TRIGGER = float(os.getenv("TRAJ_STALL_TRIGGER_RATE", "0.70"))
_TRAJ_ATT_TRIGGER = int(os.getenv("TRAJ_STALL_TRIGGER_MIN_ATT", "10"))
_STUCK_RETROCEDER_LIMIT = int(os.getenv("STUCK_RETROCEDER_LIMIT", "30"))
_DEEP_WATCHDOG_MS = float(os.getenv("SLM_DEEP_WATCHDOG_MS", "12000"))
# Escaneo huerfano: ciclos de navegacion sin que nadie lo sondee (la rama de deadlock dejo de llamarlo).
_ORPHAN_SCAN_IDLE_CYCLES = int(os.getenv("ORPHAN_SCAN_IDLE_CYCLES", "25"))
# Frente bloqueado repetido (2026-0929): N giros GIRAR_90 en una ventana de ciclos = deadlock, AUNQUE
# la distancia al WP siga bajando. En citysim_pilot seed 99 (02:32) el dron avanzo 30 m de frente contra
# una fachada con 6 GIRAR_90 y el detector de atasco (basado en progreso al WP) nunca disparo, porque
# acercarse a la pared TAMBIEN acerca al WP que esta detras.
_BLOCKED_EVENTS_TRIGGER = int(os.getenv("BLOCKED_EVENTS_TRIGGER", "3"))
_BLOCKED_EVENTS_WINDOW = int(os.getenv("BLOCKED_EVENTS_WINDOW", "60"))
# GIRAR_90 compromete un desvio: ademas de girar, inyecta una esquina en el rumbo del giro (antes el
# dron reanudaba MANTENER_RUMBO recto hacia el mismo muro al terminar el giro).
_DEPTH_BRAKE_SPEED_MPS = float(os.getenv("DEPTH_BRAKE_SPEED_MPS", "0.0"))
_GIRAR90_COMMIT_CORNER =os.getenv("GIRAR90_COMMIT_CORNER", "true").lower() == "true"
_GIRAR90_CORNER_OFFSET_M = float(os.getenv("GIRAR90_CORNER_OFFSET_M", os.getenv("CORNER_OFFSET_M", "15.0")))
# Escape vertical forzado (2026-0928): un escaneo cuenta como "futil" si entre
# dos resoluciones consecutivas el dron se desplazo menos de ESCAPE_MIN_DISP_M.
# Tras VERTICAL_ESCAPE_FUTILE_SCANS escaneos futiles seguidos, o con
# stuck_invisible + posicion congelada VERTICAL_ESCAPE_FREEZE_CYCLES ciclos,
# se fuerza GANAR_ALTURA/PERDER_ALTURA alternados (como hacia el grafo viejo).
_ESCAPE_MIN_DISP_M = float(os.getenv("ESCAPE_MIN_DISP_M", "2.0"))
_VERTICAL_ESCAPE_FUTILE_SCANS = int(os.getenv("VERTICAL_ESCAPE_FUTILE_SCANS", "2"))
_VERTICAL_ESCAPE_FREEZE_CYCLES = int(os.getenv("VERTICAL_ESCAPE_FREEZE_CYCLES", "50"))
_VERTICAL_ESCAPE_MAX_ALT_M = float(os.getenv("VERTICAL_ESCAPE_MAX_ALT_M", "25.0"))
_DEPTH_CMD_VX_MIN = float(os.getenv("DEPTH_CMD_VX_MIN", "0.30"))
_DEPTH_BF_ACTIVATE = float(os.getenv("DEPTH_BF_ACTIVATE", "0.25"))
_DEPTH_BRAKE_M = float(os.getenv("DEPTH_BRAKE_M", "5.00"))
_DEPTH_MAX_AGE_MS = float(os.getenv("DEPTH_MAX_AGE_MS", "3000.0"))
_DEPTH_BELOW_THRESHOLD = int(os.getenv("DEPTH_BELOW_THRESHOLD", "2"))
_G1_STALL_MIN = float(os.getenv("G1_STALL_MIN", "0.20"))
_G1_ATT_MIN = int(os.getenv("G1_ATT_MIN", "3"))
_G1_OCC_MAX = float(os.getenv("G1_OCC_MAX", "0.15"))

MAX_CONSECUTIVE_ESCAPES = int(os.getenv("MAX_CONSECUTIVE_ESCAPES", "3"))


# ---------------------------------------------------------------------------
# DroneState -- reduced from ~80 to ~60 fields
# ---------------------------------------------------------------------------
class DroneState(TypedDict, total=False):
    """State circulating between graph nodes."""

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
    _deliberation_pending: bool
    _consecutive_escapes: int
    _hover_alt_anchor: Optional[float]
    _escape_reset: bool
    _escape_locked: bool
    _escape_baseline_dist: Optional[float]
    inject_corner: Optional[Dict[str, Any]]
    scene_description: Optional[Dict[str, Any]]
    _deadlock_cycles: int
    _deadlock_event: Optional[Dict[str, Any]]
    # Deep scan state (multi-cycle rotation, used by deep_scan.py)
    _scan_phase: Optional[str]
    _scan_heading_index: int
    _scan_frames: List[Any]
    _scan_start_yaw_deg: Optional[float]
    _scan_settle_left: int
    _scan_rot_stall: int
    _deep_scan_request_id: Optional[int]
    _post_retroceder_corner_pending: bool
    _scan_last_evadir_dir: Optional[str]
    _scan_evadir_count: int
    _deep_scan_request_ts: Optional[float]
    _scan_started_ts: Optional[float]
    # VLM audit trail
    _pending_delib_prompt: Optional[str]
    _pending_delib_frames: Optional[List[Any]]
    _last_delib_frames: Optional[List[Any]]
    # Trajectory stats (published by capture_node)
    _traj_frente_stall_rate: float
    _traj_frente_attempts: int
    _traj_izq_stall_rate: float
    _traj_izq_attempts: int
    _traj_der_stall_rate: float
    _traj_der_attempts: int
    _prev_wp_distance: Optional[float]
    # VLM goal
    vlm_goal: Optional[Dict[str, Any]]
    _vlm_goal_history: List[Dict[str, Any]]
    # StallDetector signals (published for logging/compat)
    imu_jitter_level: str
    imu_contact_event: bool
    blind_wall_event: bool
    stuck_invisible: bool
    _stopped_cycles: int
    # Depth estimation
    _depth_proximity_m: Optional[float]
    _depth_below_cycles: int
    _depth_obstacle_type: Optional[str]
    # VLM intention (new in v2): last parsed VLM decision with timestamp
    _vlm_intention: Optional[Dict[str, Any]]
    _delib_baseline: Optional[Dict[str, Any]]
    # Auditoria (2026-0929): contadores internos publicados para el log.
    _scan_track: Dict[str, Any]
    _speed_cap: Optional[float]
    _depth_brake_left: int
    _blocked_events: int
    _freeze_cycles: int
    _pos_freeze_cycles: int
    _wp_no_progress_cycles: int


# ---------------------------------------------------------------------------
# Node construction
# ---------------------------------------------------------------------------
def _build_nodes(airsim_client: Any) -> Dict[str, Any]:
    """Build node callables from an already-connected AirSimClient."""
    from .reactive import reactive_node
    from .evasive import evasive_node
    from .fsm import fsm_node as _fsm_node_fn
    from .action_map import action_to_command, compute_corner_waypoint
    from .spatial_history import FlightTrajectory, TrajectoryEvent, SLAM_STALL_THRESHOLD_M
    from .stall_detector import StallDetector
    from .deliberative import (
        make_deliberation_service,
        _build_user_prompt,
        _encode_frame_base64,
        _parse_decision,
        _fallback_decision,
        parse_vlm_goal,
        vlm_goal_to_inject_corner,
    )
    from src.perception import FlowTTCEstimator
    from src.perception.depth_estimator import DepthEstimator

    flow_ttc_estimator = FlowTTCEstimator()
    depth_estimator = DepthEstimator()
    flight_trajectory = FlightTrajectory()
    stall = StallDetector()
    # Seguimiento de escaneos futiles / escapes verticales (ver constantes).
    scan_track: Dict[str, Any] = {"pos": None, "futile": 0, "vert_n": 0}
    governor = SpeedGovernor()
    nav_cycle = {"n": 0}
    last_scan_call = {"n": 0}
    blocked_events: "deque[int]" = deque()
    deliberation_service = make_deliberation_service()

    frame_history_size = int(os.getenv("VLM_FRAME_HISTORY_SIZE", "2"))
    girar90_duration_s = float(os.getenv("GIRAR90_DURATION_S", "1.0"))
    escape_duration_s = float(os.getenv("ESCAPE_MANEUVER_DURATION_S", "1.6"))
    maneuver_duration_s = float(os.getenv("MANEUVER_DURATION_S", "1.0"))
    loop_hz = float(os.getenv("LOOP_HZ", "5.0"))

    # ------------------------------------------------------------------
    # 1. Capture node
    # ------------------------------------------------------------------
    def capture_node(state: DroneState) -> DroneState:
        prev_telem = state.get("telemetry") or {}
        if prev_telem.get("source") == "airsim":
            curr_dist = float((state.get("waypoint_guidance") or {}).get("distance", 0.0))
            prev_dist = state.get("_prev_wp_distance")
            if prev_dist is not None:
                delta_wp = curr_dist - prev_dist
                action_taken = state.get("next_action", "")
                _ESCAPE_STALL = {
                    "GANAR_ALTURA", "PERDER_ALTURA", "DESCENDER",
                    "FRENAR", "EVADIR_IZQUIERDA", "EVADIR_DERECHA", "GIRAR_90",
                }
                _SCAN_NO_PROGRESS = 0.03
                stall_ev = (
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
                    stall=stall_ev,
                    flow_had_evidence=had_evidence,
                )
                flight_trajectory.record(event)
                orient_now = prev_telem.get("orientation") or {}
                hdg_now = math.degrees(float(orient_now.get("yaw", 0.0)))
                _ts = flight_trajectory.zone_stats(hdg_now)
                state["_traj_frente_stall_rate"] = _ts["FRENTE"]["stall_rate"]
                state["_traj_frente_attempts"] = _ts["FRENTE"]["attempts"]
                state["_traj_izq_stall_rate"] = _ts["IZQUIERDA"]["stall_rate"]
                state["_traj_izq_attempts"] = _ts["IZQUIERDA"]["attempts"]
                state["_traj_der_stall_rate"] = _ts["DERECHA"]["stall_rate"]
                state["_traj_der_attempts"] = _ts["DERECHA"]["attempts"]
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

        return state

    def degraded_hover_node(state: DroneState) -> DroneState:
        telemetry = state.get("telemetry", {}) or {}
        cmd = action_to_command("FRENAR", telemetry=telemetry)
        cmd["rationale"] = "AirSim no disponible: hover de seguridad (F0.6)."
        state["next_action"] = "FRENAR"
        state["velocity_command"] = cmd
        state["route"] = "degraded"
        state["flight_status"] = "degradado"
        return state

    # ------------------------------------------------------------------
    # 2. Perception node (no stall detection -- that moves to StallDetector)
    # ------------------------------------------------------------------
    def perception_node(state: DroneState) -> DroneState:
        prev_image = state.get("prev_image")
        curr_image = state.get("rgb_image")
        prev_telemetry = state.get("prev_telemetry") or {}
        telemetry = state.get("telemetry") or {}
        field = flow_ttc_estimator.estimate(curr_image, prev_image, telemetry, prev_telemetry)
        state["obstacle_field"] = field
        state["estimated_ttc"] = field.min_ttc()
        state["scene_summary"] = field.summary_text()

        # V4: monocular depth injection
        vel_cmd = state.get("velocity_command") or {}
        cmd_vx = float(vel_cmd.get("vx", 0.0))
        bf_now = field.blocked_fraction()
        prev_route = state.get("route", "")
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
            and prev_route not in ("evasive", "deliberative", "tactical")
        )
        new_depth_cycles = min(prev_depth_cycles + 1, 10) if depth_active else 0
        state["_depth_below_cycles"] = new_depth_cycles

        if depth_active and new_depth_cycles >= _DEPTH_BELOW_THRESHOLD:
            field = field.merge_depth_estimate(depth_m, cmd_vx)
            state["obstacle_field"] = field
            state["estimated_ttc"] = field.min_ttc()
            state["scene_summary"] = field.summary_text()
            state["_depth_proximity_m"] = depth_m
            state["_depth_obstacle_type"] = obstacle_type
            _type_hints = {
                "follaje": "Posibles huecos entre ramas -- evasion diagonal o +1 m de altura puede ser viable.",
                "superficie plana": "Superficie compacta -- evasion lateral amplia o ascenso significativo necesario.",
            }
            _hint = _type_hints.get(obstacle_type or "", "")
            if _hint:
                state["scene_summary"] = (
                    state["scene_summary"]
                    + f"\nObstaculo frontal (profundidad monocular): {obstacle_type}. {_hint}"
                )
        else:
            state["_depth_proximity_m"] = None
            state["_depth_obstacle_type"] = None

        # G1: invisible wall warning
        _g1_frente_stall = float(state.get("_traj_frente_stall_rate") or 0.0)
        _g1_frente_att = int(state.get("_traj_frente_attempts") or 0)
        if (_g1_frente_stall >= _G1_STALL_MIN
                and _g1_frente_att >= _G1_ATT_MIN
                and field.blocked_fraction() < _G1_OCC_MAX):
            state["scene_summary"] = (
                state.get("scene_summary", "")
                + f"\nAVISO [G1]: stall frontal {_g1_frente_stall:.0%}"
                  f" ({_g1_frente_att} intentos) con campo optico despejado"
                  f" -- posible obstaculo invisible (muro liso, baja textura)."
                  f" MANTENER_RUMBO agravara el bloqueo."
                  f" Priorizar GIRAR_90 o evasion lateral amplia."
            )
        return state

    # ------------------------------------------------------------------
    # 3. Navigate node -- layered architecture
    # ------------------------------------------------------------------
    def _poll_vlm(state: DroneState) -> None:
        """Non-blocking VLM response check."""
        result, _age_ms, _has_pending = deliberation_service.poll()
        req_id = state.get("slm_request_id")
        if result is not None and req_id is not None and result.request_id == req_id:
            state["slm_request_id"] = None
            state["_deliberation_pending"] = False
            parsed = result.parsed_decision
            # Entrada completa de auditoria (2026-0928): antes solo guardaba
            # macro/rationale/raw[:200] sin id ni prompt, y el logger dejaba
            # delib_id=None / raw_response="" / frames sin asociar. Se registra
            # tambien la respuesta invalida (adherent=False) para poder auditarla.
            _dl = list(state.get("deliberations") or [])
            _dl.append({
                "id": len(_dl) + 1,
                "timestamp": result.completed_at,
                "arm": "vlm_tactical",
                "prompt": state.get("_pending_delib_prompt") or "",
                "raw_response": result.raw_response or "",
                "macro_action": parsed.get("macro_action") if parsed else None,
                "rationale": parsed.get("rationale") if parsed else "",
                "is_fallback": not bool(parsed),
                "timeout": False,
                "adherent": bool(parsed),
                "used_json_schema": bool((parsed or {}).get("used_json_schema", False)),
                "latency_ms": round(float(result.latency_ms or 0.0), 1),
            })
            state["deliberations"] = _dl
            if parsed:
                state["_vlm_intention"] = {
                    **parsed,
                    "_ts": result.completed_at,
                    "_latency_ms": result.latency_ms,
                }
                # VLM goal extraction
                vlm_goal = parse_vlm_goal(parsed)
                if vlm_goal:
                    state["vlm_goal"] = vlm_goal
                    gh = list(state.get("_vlm_goal_history") or [])
                    gh.append({"vlm_goal": vlm_goal, "trigger_type": "navigate"})
                    state["_vlm_goal_history"] = gh[-3:]
                    corner = vlm_goal_to_inject_corner(vlm_goal, state)
                    if corner:
                        state["inject_corner"] = corner
            # Audit frames
            state["_last_delib_frames"] = state.get("_pending_delib_frames")
            state["_pending_delib_frames"] = None
            state["_pending_delib_prompt"] = None

    def _send_vlm_request(state: DroneState, field: ObstacleField,
                          guidance: Dict, telem: Dict) -> None:
        """Build and send a VLM request. Non-blocking."""
        # El servicio tiene UN solo slot y el pedido nuevo reemplaza al pendiente:
        # durante un escaneo profundo un pedido tactico le pisaba el resultado
        # (citysim_pilot seed 99 01:21, ciclos 358-989). No competir con el escaneo.
        if state.get("_scan_phase") is not None or state.get("_deep_scan_request_id") is not None:
            return
        prompt = _build_user_prompt(
            field, telem, guidance,
            stuck_cycles=int(state.get("evasion_stuck_cycles", 0)),
            frente_stall_rate=float(state.get("_traj_frente_stall_rate") or 0.0),
            frente_attempts=int(state.get("_traj_frente_attempts") or 0),
            imu_jitter_level=str(state.get("imu_jitter_level") or "normal"),
            use_vision=True,
        )
        frame_history = list(state.get("frame_history") or [])
        encoded = [enc for f in frame_history if (enc := _encode_frame_base64(f)) is not None]
        images_b64 = encoded or None
        req_id = deliberation_service.request({"prompt": prompt, "images_b64": images_b64})
        state["slm_request_id"] = req_id
        state["_pending_delib_prompt"] = prompt
        frame_history_ts = state.get("frame_history_ts") or []
        state["_pending_delib_frames"] = (
            list(zip(frame_history, frame_history_ts)) if frame_history else []
        )

    def _maybe_request_vlm(state: DroneState, stuck: int,
                           field: ObstacleField, guidance: Dict,
                           telem: Dict) -> None:
        """Proactively request VLM when trouble is brewing."""
        if state.get("slm_request_id") is not None:
            return
        halfway = max(1, effective_stall_threshold() // 2)
        traj_stall = float(state.get("_traj_frente_stall_rate", 0))
        traj_att = int(state.get("_traj_frente_attempts", 0))
        should_request = (
            stuck >= halfway
            or stall.stuck_invisible
            or (traj_stall >= 0.50 and traj_att >= 5)
        )
        if should_request:
            _send_vlm_request(state, field, guidance, telem)

    def _dispatch_action(state: DroneState, macro: str, guidance: Dict,
                         telem: Dict, rationale: str, route: str) -> DroneState:
        """Set velocity command and maneuver state for a macro action."""
        cmd = action_to_command(macro, guidance=guidance, telemetry=telem)
        cmd["rationale"] = rationale
        state["velocity_command"] = cmd
        state["next_action"] = macro
        state["route"] = route
        _MANEUVER_ACTIONS = {
            "EVADIR_IZQUIERDA", "EVADIR_DERECHA", "RETROCEDER", "GIRAR_90",
            "GANAR_ALTURA", "PERDER_ALTURA", "DESCENDER",
        }
        if macro in _MANEUVER_ACTIONS:
            dur = escape_duration_s if macro in ("GANAR_ALTURA", "PERDER_ALTURA", "DESCENDER", "RETROCEDER") else maneuver_duration_s
            state["active_maneuver"] = macro
            state["maneuver_cycles_left"] = max(1, round(dur * loop_hz))
            state["maneuver_command"] = cmd
        _STATUS_MAP = {
            "MANTENER_RUMBO": "vuelo_waypoint",
            "EVADIR_IZQUIERDA": "evasion_lateral",
            "EVADIR_DERECHA": "evasion_lateral",
            "RETROCEDER": "escape_retroceso",
            "GIRAR_90": "exploracion_yaw",
            "GANAR_ALTURA": "escape_altitud",
            "PERDER_ALTURA": "escape_altitud",
            "DESCENDER": "escape_altitud",
            "FRENAR": "frenado",
        }
        state["flight_status"] = _STATUS_MAP.get(macro, "vuelo")
        return state

    def _dispatch_girar_90(state: DroneState, guidance: Dict,
                           telem: Dict, field: ObstacleField) -> DroneState:
        """GIRAR_90 with trajectory-aware direction selection (D1)."""
        bearing_err = float(guidance.get("bearing_err_deg", 0.0))
        pref_key = "izq" if bearing_err < 0.0 else "der"
        opp_key = "der" if pref_key == "izq" else "izq"
        pref_stall = float(state.get(f"_traj_{pref_key}_stall_rate") or 0.0)
        pref_att = int(state.get(f"_traj_{pref_key}_attempts") or 0)
        opp_stall = float(state.get(f"_traj_{opp_key}_stall_rate") or 0.0)
        opp_att = int(state.get(f"_traj_{opp_key}_attempts") or 0)
        flip = (
            pref_stall >= _GIRAR90_STALL_THRESHOLD and pref_att >= _GIRAR90_MIN_ATTEMPTS
            and not (opp_stall >= _GIRAR90_STALL_THRESHOLD and opp_att >= _GIRAR90_MIN_ATTEMPTS)
        )
        eff_guidance = {**guidance, "bearing_err_deg": -(bearing_err or 0.01)} if flip else guidance
        cmd = action_to_command("GIRAR_90", guidance=eff_guidance, telemetry=telem)
        side = "izquierda" if cmd["yaw_rate"] < 0 else "derecha"
        cmd["rationale"] = f"FOV bloqueado ({field.blocked_fraction()*100:.0f}%). Girando 90 hacia {side}."
        state["next_action"] = "GIRAR_90"
        state["velocity_command"] = cmd
        state["route"] = "girar_90"
        state["flight_status"] = "exploracion_yaw"
        state["active_maneuver"] = "GIRAR_90"
        state["maneuver_cycles_left"] = max(1, round(girar90_duration_s * loop_hz))
        state["maneuver_command"] = cmd
        if _GIRAR90_COMMIT_CORNER and cmd.get("target_yaw") is not None:
            state["inject_corner"] = compute_corner_waypoint(
                telem, float(cmd["target_yaw"]), guidance=guidance, offset_m=_GIRAR90_CORNER_OFFSET_M,
            )
        return state

    def _register_scan_resolution(state: DroneState, telem: Dict) -> None:
        """Mide desplazamiento real desde la resolucion de escaneo anterior."""
        ev = state.get("_deadlock_event")
        if not ev or not ev.get("resolved_by_scan"):
            return
        p = telem.get("position") or {}
        pos = (float(p.get("x", 0.0)), float(p.get("y", 0.0)))
        prev = scan_track["pos"]
        if prev is not None:
            disp = math.hypot(pos[0] - prev[0], pos[1] - prev[1])
            futile = disp < _ESCAPE_MIN_DISP_M
            ev["disp_since_prev_scan_m"] = round(disp, 2)
            ev["prev_scan_futile"] = futile
            scan_track["futile"] = scan_track["futile"] + 1 if futile else 0
        scan_track["pos"] = pos

    def _vertical_escape_due(state: DroneState) -> bool:
        if state.get("_scan_phase") is not None or state.get("slm_request_id") is not None:
            return False
        if scan_track["futile"] >= _VERTICAL_ESCAPE_FUTILE_SCANS:
            return True
        return bool(stall.stuck_invisible
                    and stall.pos_freeze_cycles >= _VERTICAL_ESCAPE_FREEZE_CYCLES)

    def _vertical_escape(state: DroneState, guidance: Dict, telem: Dict,
                         alt_m: float) -> DroneState:
        n = int(scan_track["vert_n"])
        macro = "GANAR_ALTURA" if n % 2 == 0 else "PERDER_ALTURA"
        if macro == "GANAR_ALTURA" and (
                alt_m >= _VERTICAL_ESCAPE_MAX_ALT_M or guidance.get("ceiling_z") is not None):
            macro = "PERDER_ALTURA"
        scan_track["vert_n"] = n + 1
        scan_track["futile"] = 0
        scan_track["pos"] = None
        stall.reset_freeze()
        state["_escape_reset"] = True
        state["evasion_stuck_cycles"] = 0
        state["_deadlock_event"] = {
            "strategy": "vertical_escape", "arm": AGENT_ARM,
            "resolved_by_scan": False, "cycles_to_resolve": None,
            "fell_back_to_blind": True, "macro": macro,
        }
        return _dispatch_action(
            state, macro, guidance, telem,
            "Escaneos futiles / posicion congelada -- escape vertical forzado", "tactical",
        )

    def _deadlock_resolve(state: DroneState, stuck: int, field: ObstacleField,
                          guidance: Dict, telem: Dict) -> DroneState:
        """Immediate deadlock resolution. Never waits for VLM."""
        from .deep_scan import (
            _apply_trajectory_overrides, _slam_assess_cycle,
            deep_scan_cycle, DEADLOCK_STRATEGY,
        )

        last_scan_call["n"] = nav_cycle["n"]
        cons_esc = int(state.get("_consecutive_escapes", 0))
        dc = int(state.get("_deadlock_cycles", 0)) + 1
        state["_deadlock_cycles"] = dc

        # Extreme stuck with no trajectory data and slam_assess: immediate escape
        orient = telem.get("orientation") or {}
        hdg = math.degrees(float(orient.get("yaw", 0.0)))
        total_traj_attempts = sum(
            z["attempts"] for z in flight_trajectory.zone_stats(hdg).values()
        )
        if (stuck >= hard_stall_threshold()
                and total_traj_attempts == 0
                and DEADLOCK_STRATEGY != "deep_vlm"):
            if cons_esc < MAX_CONSECUTIVE_ESCAPES and not bool(state.get("_escape_locked")):
                state["_consecutive_escapes"] = cons_esc + 1
                state["_escape_baseline_dist"] = float(guidance.get("dist_xy", 0))
                state["_escape_reset"] = True
                return _dispatch_action(
                    state, "GANAR_ALTURA", guidance, telem,
                    "Extreme deadlock, no trajectory data -- altitude escape", "tactical",
                )
            state["_escape_locked"] = True
            state["_escape_reset"] = True
            return _dispatch_action(
                state, "RETROCEDER", guidance, telem,
                "Extreme deadlock, altitude exhausted -- reverse", "tactical",
            )

        # Delegate to deep_scan strategy when configured
        if DEADLOCK_STRATEGY in ("deep_vlm", "slam_assess"):
            if DEADLOCK_STRATEGY == "deep_vlm":
                resolved = deep_scan_cycle(
                    state, deliberation_service, field, telem, guidance,
                    AGENT_ARM, dc, cons_esc, flight_trajectory,
                )
            else:
                resolved = _slam_assess_cycle(
                    state, deliberation_service, field, telem, guidance,
                    AGENT_ARM, dc, cons_esc, flight_trajectory,
                )
            if resolved:
                _register_scan_resolution(state, telem)
                macro_resolved = state.get("next_action", "")
                if macro_resolved in ("GANAR_ALTURA", "PERDER_ALTURA", "DESCENDER"):
                    if cons_esc < MAX_CONSECUTIVE_ESCAPES and not bool(state.get("_escape_locked")):
                        state["_consecutive_escapes"] = cons_esc + 1
                        state["_escape_baseline_dist"] = float(guidance.get("dist_xy", 0))
                    else:
                        state["_escape_locked"] = True
                if macro_resolved not in ("ESCANEO", "FRENAR", ""):
                    state["_escape_reset"] = True
                return state
            # resolved=False: VLM failed or timed out. Fall through to
            # deterministic trajectory-based resolution below.

        # Check for fresh VLM intention (blind strategy or fallback)
        intention = state.get("_vlm_intention")
        if intention:
            age = time.time() - float(intention.get("_ts", 0))
            if age < 10.0:
                decision = _apply_trajectory_overrides(dict(intention), flight_trajectory, telem)
                macro = decision.get("macro_action", "MANTENER_RUMBO")
                state["_vlm_intention"] = None
                if macro in ("GANAR_ALTURA", "PERDER_ALTURA", "DESCENDER"):
                    if cons_esc >= MAX_CONSECUTIVE_ESCAPES or state.get("_escape_locked"):
                        decision = _fallback_decision(field, guidance)
                        macro = decision.get("macro_action", "EVADIR_DERECHA")
                    else:
                        state["_consecutive_escapes"] = cons_esc + 1
                        state["_escape_baseline_dist"] = float(guidance.get("dist_xy", 0))
                state["_escape_reset"] = True
                return _dispatch_action(
                    state, macro, guidance, telem,
                    decision.get("rationale", "VLM tactical"), "tactical",
                )

        # Request VLM if not already pending
        if state.get("slm_request_id") is None:
            _send_vlm_request(state, field, guidance, telem)

        # Deterministic trajectory-based resolution
        orient = telem.get("orientation") or {}
        hdg = math.degrees(float(orient.get("yaw", 0.0)))
        stats = flight_trajectory.zone_stats(hdg)
        frente = stats["FRENTE"]
        izq = stats["IZQUIERDA"]
        der = stats["DERECHA"]

        cons_esc = int(state.get("_consecutive_escapes", 0))
        escape_locked = bool(state.get("_escape_locked", False))

        all_blocked = (
            frente["stall_rate"] >= 0.70 and frente["attempts"] >= 3
            and izq["stall_rate"] >= 0.70 and izq["attempts"] >= 3
            and der["stall_rate"] >= 0.70 and der["attempts"] >= 3
        )
        if all_blocked:
            if cons_esc < MAX_CONSECUTIVE_ESCAPES and not escape_locked:
                state["_consecutive_escapes"] = cons_esc + 1
                state["_escape_baseline_dist"] = float(guidance.get("dist_xy", 0))
                state["_escape_reset"] = True
                return _dispatch_action(
                    state, "GANAR_ALTURA", guidance, telem,
                    "Trajectory: all zones blocked, altitude escape", "tactical",
                )
            state["_escape_locked"] = True
            corner = compute_corner_waypoint(guidance, telem)
            if corner:
                state["inject_corner"] = corner
            state["_escape_reset"] = True
            return _dispatch_action(
                state, "RETROCEDER", guidance, telem,
                "Trajectory: all zones blocked, altitude exhausted", "tactical",
            )

        # Unexplored lateral
        if izq["attempts"] == 0:
            state["_escape_reset"] = True
            return _dispatch_action(
                state, "EVADIR_IZQUIERDA", guidance, telem,
                "Trajectory: unexplored left zone", "tactical",
            )
        if der["attempts"] == 0:
            state["_escape_reset"] = True
            return _dispatch_action(
                state, "EVADIR_DERECHA", guidance, telem,
                "Trajectory: unexplored right zone", "tactical",
            )

        # Best lateral (least blocked)
        if izq["stall_rate"] <= der["stall_rate"]:
            macro = "EVADIR_IZQUIERDA"
        else:
            macro = "EVADIR_DERECHA"
        state["_escape_reset"] = True
        return _dispatch_action(
            state, macro, guidance, telem,
            f"Trajectory: least blocked lateral (izq={izq['stall_rate']:.0%} der={der['stall_rate']:.0%})",
            "tactical",
        )

    def navigate_node(state: DroneState) -> DroneState:
        """Layered navigation: always-reactive baseline + tactical overlay."""
        nav_cycle["n"] += 1
        stall.update(state)
        stall.publish(state)
        state["_scan_track"] = {
            "futile_scans": scan_track["futile"], "vertical_escapes": scan_track["vert_n"],
        }

        # --- ARM routing ---
        if AGENT_ARM == "reactive":
            return reactive_node(state)
        if AGENT_ARM == "fsm":
            return _fsm_node_fn(state, service=deliberation_service, trajectory=flight_trajectory)

        # --- VLM poll (non-blocking) ---
        _poll_vlm(state)

        # --- Escaneo huerfano: la navegacion salio de la rama de deadlock sin
        # cerrarlo (nadie lo vuelve a sondear) y deja `_deliberation_pending`
        # activo, lo que silencia el conteo de progreso. Se descarta al vencer
        # 1.5x el watchdog del pedido (o 60 s en fase de rotacion).
        if state.get("_scan_phase") is not None or state.get("_deep_scan_request_id") is not None:
            _now = time.time()
            _req_ts = state.get("_deep_scan_request_ts")
            _start_ts = state.get("_scan_started_ts")
            _idle = nav_cycle["n"] - last_scan_call["n"]
            _orphan = (
                _idle > _ORPHAN_SCAN_IDLE_CYCLES
                or (_req_ts is not None and (_now - float(_req_ts)) * 1000.0 > 1.5 * _DEEP_WATCHDOG_MS)
                or (_req_ts is None and _start_ts is not None and _now - float(_start_ts) > 60.0)
            )
            if _orphan:
                from .deep_scan import clear_scan_state as _clear_scan_state

                print("[graph] Escaneo profundo huerfano descartado.")
                _clear_scan_state(state)
                state["_deliberation_pending"] = False

        # --- Escape resolution tracking ---
        if int(state.get("_consecutive_escapes", 0)) > 0:
            baseline = state.get("_escape_baseline_dist")
            if baseline is not None:
                dist = float((state.get("waypoint_guidance") or {}).get("dist_xy", 0))
                eps_m = float(os.getenv("WAYPOINT_PROGRESS_EPS_M", "0.5"))
                if dist < float(baseline) - eps_m:
                    state["_consecutive_escapes"] = 0
                    state["_escape_locked"] = False
                    state["_escape_baseline_dist"] = None

        # --- Active maneuver continuation ---
        active_man = state.get("active_maneuver")
        cycles_left = int(state.get("maneuver_cycles_left", 0))
        if active_man and cycles_left > 0:
            cmd = state.get("maneuver_command") or {}
            state["velocity_command"] = cmd
            state["next_action"] = active_man
            state["maneuver_cycles_left"] = cycles_left - 1
            if cycles_left <= 1:
                state["active_maneuver"] = None
                state["maneuver_command"] = None
            state["route"] = "evasive"
            state["flight_status"] = f"maniobra_{active_man.lower()}"
            return state

        # --- Immediate threats ---
        if stall.imu_contact or stall.blind_wall:
            return evasive_node(state)

        # --- Below optical floor ---
        # Despegue/aterrizaje: reactivo puro (el flujo no es valido cerca del suelo). PERO si la altura baja
        # es deliberada por un techo detectado (ceiling_z), el dron vuela de verdad: se mantiene la deteccion
        # de atasco/deadlock y solo se omite la evasion por flujo (mas abajo). Antes TODO se saltaba y el
        # dron quedo 178 ciclos parado a 4.4 m sin que ningun detector actuara (seed 99 02:57).
        telem = state.get("telemetry") or {}
        pos = telem.get("position") or {}
        alt_m = abs(float(pos.get("z", 0.0)))
        guidance = state.get("waypoint_guidance") or {}
        below_floor = alt_m < _OPTICAL_MIN_ALT_M
        if below_floor and guidance.get("ceiling_z") is None:
            return reactive_node(state)

        stuck = int(state.get("evasion_stuck_cycles", 0))
        field: ObstacleField = state.get("obstacle_field") or empty_field()

        # --- Forced vertical escape (futile scans / frozen position) ---
        if _vertical_escape_due(state):
            return _vertical_escape(state, guidance, telem, alt_m)

        # --- Stopped prolonged: direct escalation ---
        if stall.stopped_prolonged:
            return _deadlock_resolve(state, stuck, field, guidance, telem)

        # --- stuck_invisible: evasion or escalation ---
        if stall.stuck_invisible:
            if (stuck >= hard_stall_threshold()
                    or stall.stopped_cycles >= _STUCK_RETROCEDER_LIMIT):
                return _deadlock_resolve(state, stuck, field, guidance, telem)
            return evasive_node(state)

        # --- WP no-progress ---
        if stall.wp_no_progress:
            return _deadlock_resolve(state, stuck, field, guidance, telem)

        # --- Trajectory stall trigger ---
        traj_stall_rate = float(state.get("_traj_frente_stall_rate", 0.0))
        traj_att = int(state.get("_traj_frente_attempts", 0))
        if traj_stall_rate >= _TRAJ_STALL_TRIGGER and traj_att >= _TRAJ_ATT_TRIGGER:
            return _deadlock_resolve(state, stuck, field, guidance, telem)

        # --- Stuck cycles escalation ---
        if stuck >= effective_stall_threshold():
            if stuck >= hard_stall_threshold() or not has_open_corridor(field, guidance):
                return _deadlock_resolve(state, stuck, field, guidance, telem)

        # Bajo el piso optico (por un techo): sin evasion basada en flujo.
        if below_floor:
            return reactive_node(state)

        # --- Proactive VLM request (before deadlock) ---
        _maybe_request_vlm(state, stuck, field, guidance, telem)

        # --- TTC-based evasion ---
        ttc = field.min_ttc()
        center_blocked = field.is_blocked("centro")
        center_ttc = field.sector_ttc("centro")
        center_imminent = center_ttc <= TTC_EVASION_THRESHOLD

        if center_imminent or (center_blocked and center_ttc <= TTC_SAFE_THRESHOLD):
            if field.blocked_fraction() > FOV_BLOCKED_THRESHOLD:
                if alt_m < SLM_MIN_ALT_M:
                    return evasive_node(state)
                n_now = nav_cycle["n"]
                blocked_events.append(n_now)
                while blocked_events and n_now - blocked_events[0] > _BLOCKED_EVENTS_WINDOW:
                    blocked_events.popleft()
                state["_blocked_events"] = len(blocked_events)
                if len(blocked_events) >= _BLOCKED_EVENTS_TRIGGER:
                    print(f"[graph] {len(blocked_events)} frentes bloqueados en {_BLOCKED_EVENTS_WINDOW} ciclos "
                          f"-> deadlock (independiente del progreso al WP).")
                    blocked_events.clear()
                    return _deadlock_resolve(state, stuck, field, guidance, telem)
                return _dispatch_girar_90(state, guidance, telem, field)
            if alt_m < SLM_MIN_ALT_M:
                return evasive_node(state)
            # Check VLM intention before defaulting to evasive
            intention = state.get("_vlm_intention")
            if intention and (time.time() - float(intention.get("_ts", 0))) < 5.0:
                from .deep_scan import _apply_trajectory_overrides
                decision = _apply_trajectory_overrides(dict(intention), flight_trajectory, telem)
                macro = decision.get("macro_action", "EVADIR_DERECHA")
                state["_vlm_intention"] = None
                return _dispatch_action(
                    state, macro, guidance, telem,
                    decision.get("rationale", "VLM tactical evasion"), "tactical",
                )
            return evasive_node(state)

        if center_blocked or ttc <= TTC_SAFE_THRESHOLD:
            return evasive_node(state)

        # --- Normal guidance ---
        return reactive_node(state)

    # ------------------------------------------------------------------
    # 4. Motor node
    # ------------------------------------------------------------------
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
            dz = anchor - current_z
            if abs(dz) > HOVER_ALT_DEADZONE_M:
                cmd = dict(cmd)
                cmd["vz"] = max(-HOVER_ALT_MAX_VZ, min(HOVER_ALT_MAX_VZ, HOVER_ALT_KP * dz))
            state["_hover_alt_anchor"] = anchor
        else:
            state["_hover_alt_anchor"] = None

        # Gobernador de velocidad: limita el avance de MANTENER_RUMBO sin evidencia de flujo, tras un
        # frente bloqueado o al terminar una maniobra (ver src/navigation/speed_governor.py).
        _fld = state.get("obstacle_field")
        cap = governor.update(
            getattr(_fld, "source", "none") if _fld is not None else "none",
            _fld.blocked_fraction() if _fld is not None else 0.0,
            bool(state.get("active_maneuver")),
            str(state.get("next_action", "")),
        )
        # Freno de proximidad por profundidad (cristal/parapets sin colision ni flujo): la capa externa
        # (runner) arma `_depth_brake_left`; el grafo solo recibe un tope, nunca lee profundidad.
        _brake_left = int(state.get("_depth_brake_left", 0) or 0)
        if _brake_left > 0:
            state["_depth_brake_left"] = _brake_left - 1
            cap = _DEPTH_BRAKE_SPEED_MPS if cap is None else min(cap, _DEPTH_BRAKE_SPEED_MPS)
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
        deliberations = state.get("deliberations") or []
        if deliberations:
            state["last_deliberation"] = deliberations[-1]
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


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------
def degraded_router(state: DroneState) -> str:
    return "degraded_hover" if state.get("degraded") else "perception"


def build_workflow(airsim_client: Any) -> Any:
    """Build the StateGraph with layered navigation architecture."""
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
    """Compile the StateGraph. Returns (compiled_app, deliberation_service)."""
    workflow = build_workflow(airsim_client)
    app = workflow.compile()
    return app, workflow._nodes_extra["_deliberation_service"]


def get_airsim_client() -> Optional[Any]:
    """Deprecated (F0.3): backward compat only."""
    import warnings
    warnings.warn(
        "get_airsim_client() esta deprecado: usar AirSimClient() + compile_workflow(client).",
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


# Backward compat: policy_router is no longer used but some tests import it.
def policy_router(state: DroneState) -> str:
    """Routing logic mirroring navigate_node decisions (for testing)."""
    if AGENT_ARM == "reactive":
        return "keep_going"
    if AGENT_ARM == "fsm":
        return "fsm"

    active_man = state.get("active_maneuver")
    cycles_left = int(state.get("maneuver_cycles_left", 0))
    if active_man and cycles_left > 0:
        return "evasive"

    if state.get("slm_request_id") is not None:
        return "deliberative"

    telem = state.get("telemetry") or {}
    pos = telem.get("position") or {}
    alt_m = abs(float(pos.get("z", 0.0)))
    if alt_m < _OPTICAL_MIN_ALT_M:
        return "keep_going"

    stuck = int(state.get("evasion_stuck_cycles", 0))
    field = state.get("obstacle_field") or empty_field()

    if stuck >= effective_stall_threshold():
        if stuck >= hard_stall_threshold() or not has_open_corridor(field, state.get("waypoint_guidance") or {}):
            return "deliberative"

    ttc = field.min_ttc()
    center_blocked = field.is_blocked("centro")
    center_ttc = field.sector_ttc("centro")
    center_imminent = center_ttc <= TTC_EVASION_THRESHOLD

    if center_imminent or (center_blocked and center_ttc <= TTC_SAFE_THRESHOLD):
        if field.blocked_fraction() > FOV_BLOCKED_THRESHOLD:
            if alt_m < SLM_MIN_ALT_M:
                return "evasive"
            return "girar_90"
        if alt_m < SLM_MIN_ALT_M:
            return "evasive"
        return "deliberative"

    if center_blocked or ttc <= TTC_SAFE_THRESHOLD:
        return "evasive"

    return "keep_going"

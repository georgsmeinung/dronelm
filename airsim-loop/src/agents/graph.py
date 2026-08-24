# Definición del flujo de LangGraph y el Bucle de Control Jerárquico (5 Pasos).
from __future__ import annotations

import math
import os
from typing import Any, Dict, List, Optional, TypedDict
# pyrefly: ignore [missing-import]
import numpy as np

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover
    pass

# pyrefly: ignore [missing-import]
from langgraph.graph import END, StateGraph


# ---------------------------------------------------------------------------
# Estado del grafo (DroneState)
# ---------------------------------------------------------------------------
class DroneState(TypedDict, total=False):
    """Estado que circula entre los nodos del grafo en el nuevo pipeline jerárquico."""

    rgb_image: Any
    prev_image: Any  # Memoria del fotograma anterior para el flujo óptico
    annotated_image: Any  # Frame con bboxes de YOLO superpuestos para el VLM
    frame_history: List[Any]  # Ring buffer de los últimos N frames anotados [t-3, t-2, t-1, t]
    prev_canny_edges: Any
    xor_change_ratio: float
    telemetry: Dict[str, Any]
    # Deprecated YOLO fields removed
    optical_flow_map: Any        # Campo denso de vectores (H×W×2)
    obstacle_mask: Any           # Máscara binaria del IPM/SLIC
    occlusion_ratio: float       # % de pantalla bloqueada
    fov_blocked: bool            # True si occlusion_ratio > threshold
    estimated_ttc: float
    ttc_details: Dict[str, Any]
    detected_obstacles: List[Dict[str, Any]]
    scene_summary: str
    next_action: str
    velocity_command: Dict[str, Any]
    route: str
    flight_status: str  # "vuelo" | "hover_slm" | "evasion_local" | "vuelo_waypoint" | "mision_completada"
    deliberations: List[Dict[str, Any]]
    last_deliberation: Optional[Dict[str, Any]]
    collision_result: Dict[str, Any]
    waypoints: List[Dict[str, Any]]
    current_wp_index: int
    target_waypoint: Optional[Dict[str, Any]]
    waypoint_guidance: Dict[str, Any]
    mission_completed: bool
    active_maneuver: Optional[str]
    maneuver_cycles_left: int
    maneuver_command: Optional[Dict[str, Any]]
    # Número de ciclos consecutivos en ruta evasiva/deliberativa sin reducir distancia al waypoint.
    # Cuando alcanza EVASION_STUCK_THRESHOLD, el ttc_router fuerza hover_and_slm para
    # que deliberative_node aplique el escape por GANAR_ALTURA sin consultar al LLM.
    evasion_stuck_cycles: int


# ---------------------------------------------------------------------------
# Lazy imports y construcción de nodos
# ---------------------------------------------------------------------------
def _build_nodes() -> Dict[str, Any]:
    """Construye los callables de los nodos y los componentes persistentes."""
    from .reactive import reactive_node
    from .deliberative import deliberative_node
    from .evasive import evasive_node
    from src.perception import (
        TTCEstimator,
        CannyGate,
        OpticalFlowEstimator,
        IPMSegmentator,
    )
    from src.hardware import AirSimClient

    # YOLO detector removed – not used in new pipeline
    # detector = None    )

    canny_gate = CannyGate()
    ttc_estimator = TTCEstimator()

    airsim_client = AirSimClient()
    airsim_client.connect()

    # 1. Nodo de captura de cámara en tiempo real
    def capture_node(state: DroneState) -> DroneState:
        print("[Grafo] -> Entrando a capture_node")
        # Store previous frame for optical flow
        prev_image = state.get("rgb_image")
        state["prev_image"] = prev_image
        # pyrefly: ignore [bad-unpacking]
        image, telemetry = airsim_client.capture()
        state["rgb_image"] = image
        state["telemetry"] = telemetry
        return state

    # 2. Paso 1: Gating de Bordes XOR (Canny)
    def canny_xor_gate_node(state: DroneState) -> DroneState:
        print("[Grafo] -> Entrando a canny_xor_gate_node")
        image = state.get("rgb_image")
        change_ratio, edges, _ = canny_gate.evaluate(image)
        state["xor_change_ratio"] = change_ratio
        state["prev_canny_edges"] = edges
        return state

    def optical_flow_node(state: DroneState) -> DroneState:
        print("[Grafo] -> Entrando a optical_flow_node")
        prev_image = state.get("prev_image")
        curr_image = state.get("rgb_image")
        if prev_image is None or curr_image is None:
            # Not enough data yet, skip processing
            state["optical_flow_map"] = None
            return state
        ttc, flow = OpticalFlowEstimator().estimate(curr_image, prev_image)
        state["optical_flow_map"] = flow
        return state

    def ipm_segmentation_node(state: DroneState) -> DroneState:
        print("[Grafo] -> Entrando a ipm_segmentation_node")
        image = state.get("rgb_image")
        if image is None:
            state["obstacle_mask"] = None
            state["occlusion_ratio"] = 0.0
            state["fov_blocked"] = False
            return state
        prev_image = state.get("prev_image")
        telemetry = state.get("telemetry", {})
        mask, occ_pct, annotated = IPMSegmentator().segment(image, prev_image, telemetry)
        state["obstacle_mask"] = mask
        occlusion = occ_pct / 100.0
        state["occlusion_ratio"] = occlusion
        threshold = float(os.getenv("FOV_BLOCKED_THRESHOLD", "0.6"))
        state["fov_blocked"] = occlusion > threshold
        return state

    # 4. Paso 3: Estimación de Tiempo de Colisión (TTC) No Neuronal
    def ttc_estimate_node(state: DroneState) -> DroneState:
        print("[Grafo] -> Entrando a ttc_estimate_node")
        # Intentar usar el mapa de flujo óptico ya calculado
        flow = state.get("optical_flow_map")
        if flow is None:
            # Calcular si no está disponible
            prev_image = state.get("prev_image")
            curr_image = state.get("rgb_image")
            if prev_image is None or curr_image is None:
                state["estimated_ttc"] = float('inf')
                state["ttc_details"] = {"method": "none"}
                return state
            ttc, flow = OpticalFlowEstimator().estimate(curr_image, prev_image)
            state["optical_flow_map"] = flow
        else:
            # Calcular TTC a partir del flujo existente (divergencia media en ROI central)
            mag = np.linalg.norm(flow, axis=2)
            h, w = mag.shape
            cx, cy = w // 2, h // 2
            roi_sz = int(min(w, h) * 0.4)
            x0, y0 = cx - roi_sz // 2, cy - roi_sz // 2
            roi_mag = mag[y0:y0 + roi_sz, x0:x0 + roi_sz]
            mean_div = np.mean(roi_mag) + 1e-6
            ttc = max(0.1, min(10.0, 1.0 / mean_div))
        state["estimated_ttc"] = float(ttc)
        state["ttc_details"] = {"method": "optical_flow"}
        return state

    # 5. Paso 5: Parada de seguridad previa al SLM
    def hover_before_slm_node(state: DroneState) -> DroneState:
        print("[Grafo] -> Entrando a hover_before_slm_node (Freno de seguridad)")
        # Enviar comando de frenado inmediato para evitar colisión durante inferencia
        airsim_client.execute_velocity(vx=0.0, vy=0.0, vz=0.0, yaw_rate=0.0)
        # Ejecutar segmentación IPM para obtener máscara y ratio de oclusión
        state = ipm_segmentation_node(state)
        # Decidir acción: girar 90° si el FOV está bloqueado, de lo contrario usar VLM
        return blind_wall_router_node(state)

    def blind_wall_router_node(state: DroneState) -> DroneState:
        if state.get("fov_blocked", False):
            telemetry = state.get("telemetry", {})
            current_yaw = math.degrees(telemetry.get("orientation", {}).get("yaw", 0.0))
            target_yaw = (current_yaw + 90.0) % 360.0
            cmd = {
                "macro_action": "GIRAR_90",
                "vx": 0.0,
                "vy": 0.0,
                "vz": 0.0,
                "yaw_rate": 20.0,
                "target_yaw": target_yaw,
                "rationale": f"FOV bloqueado ({state['occlusion_ratio']:.0f}%). Girando 90° para buscar corredor.",
            }
            state["next_action"] = "GIRAR_90"
            state["velocity_command"] = cmd
            state["active_maneuver"] = "GIRAR_90"
            state["maneuver_cycles_left"] = 15  # ~1.5s a 10Hz
            state["flight_status"] = "exploracion_yaw"
            return state
        else:
            return deliberative_node(state)

    # 6. Nodo de actuación motriz
    def motor_node(state: DroneState) -> DroneState:
        print("[Grafo] -> Entrando a motor_node")
        cmd = state.get("velocity_command") or {
            "macro_action": state.get("next_action", "MANTENER_RUMBO"),
            "vx": 0.0,
            "vy": 0.0,
            "vz": 0.0,
            "yaw_rate": 0.0,
        }
        target_yaw = cmd.get("target_yaw")
        if target_yaw is not None:
            target_yaw = float(target_yaw)

        airsim_client.execute_velocity(
            vx=float(cmd.get("vx", 0.0)),
            vy=float(cmd.get("vy", 0.0)),
            vz=float(cmd.get("vz", 0.0)),
            yaw_rate=float(cmd.get("yaw_rate", 0.0)),
            target_yaw=target_yaw,
        )
        state["velocity_command"] = cmd
        return state

    return {
        "capture": capture_node,
        "canny_xor_gate": canny_xor_gate_node,
        "optical_flow": optical_flow_node,
        "ipm_segmentation": ipm_segmentation_node,
        "ttc_estimate": ttc_estimate_node,
        "keep_going": reactive_node,
        "evasive": evasive_node,
        "hover_and_slm": hover_before_slm_node,
        "blind_wall_router": blind_wall_router_node,
        "motor": motor_node,
        "_airsim_client": airsim_client,
    }


# ---------------------------------------------------------------------------
# Routers Condicionales del Grafo
# ---------------------------------------------------------------------------
XOR_THRESHOLD = float(os.getenv("CANNY_XOR_THRESHOLD", "0.02"))
TTC_EVASION_THRESHOLD = float(os.getenv("TTC_EVASION_THRESHOLD", "2.0"))
TTC_SAFE_THRESHOLD = float(os.getenv("TTC_SAFE_THRESHOLD", "5.0"))


def xor_router(state: DroneState) -> str:
    """Decisión de Paso 1: Si el cambio de bordes es menor al umbral, sigue adelante directo."""
    change_ratio = state.get("xor_change_ratio", 1.0)
    if change_ratio < XOR_THRESHOLD:
        return "keep_going"
    return "optical_flow"


def ttc_router(state: DroneState) -> str:
    """Decisión de Paso 4: Router Táctico Jerárquico con Priorización de Estructuras Urbanas.

    - Caso 0 (hover_and_slm): Drone atascado N ciclos sin progresar → escape por GANAR_ALTURA.
    - Caso C (hover_and_slm): Estructura frontal (edificio/muro) en Cerca/Inminente,
      o cualquier objeto Inminente (<2.5m), o Looming dinámico crítico (TTC <= 2.0s).
    - Caso B (evasive): Obstáculo central en Cerca (postes, árboles, tráfico) o TTC <= 5.0s.
    - Caso A (keep_going): Sector central totalmente libre de obstáculos cercanos/inminentes.
    """
    # PRIORIDAD 0: Escape de deadlock si el drone lleva N ciclos en modo evasivo
    # sin progresar hacia el waypoint (building omnidireccional u otros bloqueos persistentes).
    STUCK_THRESHOLD = int(os.getenv("EVASION_STUCK_THRESHOLD", "10"))
    stuck = int(state.get("evasion_stuck_cycles", 0))
    if stuck >= STUCK_THRESHOLD:
        # Forzar deliberación: deliberative_node detectará el contador y aplicará
        # GANAR_ALTURA sin consultar al LLM para escapar del bloqueo.
        return "hover_and_slm"

    ttc = state.get("estimated_ttc", float("inf"))
    obstacles = state.get("detected_obstacles", []) or []

    # Categorías críticas
    structural_names = {"building", "wall", "house", "roof", "tower", "bridge", "structure"}

    # 1. Peligro Inminente Masivo en sector Centro (Looming crítico <= 2.5s o proximidad inminente)
    center_imminent = (ttc <= 2.5) or any(
        o.get("sector") == "Centro"
        and o.get("proximity") == "Inminente"
        for o in obstacles
    )

    # 2. Estructura Crítica Frontal en sector Centro (Edificios/Muros en Inminente o Cerca <6.0m)
    center_structural_blocking = any(
        o.get("sector") == "Centro"
        and (str(o.get("object", "")).lower() in structural_names or o.get("category") == "structural")
        and o.get("proximity") in ("Inminente", "Cerca")
        for o in obstacles
    )

    # 3. Obstáculos generales en sector central en proximidad Cerca
    center_near = any(
        o.get("sector") == "Centro" and o.get("proximity") in ("Inminente", "Cerca")
        for o in obstacles
    )

    # 4. Persistencia Táctica de Maniobra (Ejecución comprometida anti-oscilación)
    maneuver_cycles = int(state.get("maneuver_cycles_left", 0))
    active_man = state.get("active_maneuver")
    if active_man and maneuver_cycles > 0:
        # Durante la maniobra de escape, si hay riesgo inminente de impacto (<2.0s), re-deliberar; sino continuar
        if ttc > 2.0:
            return "evasive"

    # Caso C: Peligro Crítico / Estructura bloqueando el pasillo
    if center_imminent or center_structural_blocking or (center_near and ttc <= TTC_EVASION_THRESHOLD):
        return "hover_and_slm"

    # Caso B: Maniobra Evasiva Local Rápida (TTC dinámico en ventana de advertencia <= 3.5s)
    if (center_near and ttc <= TTC_SAFE_THRESHOLD) or (ttc <= 3.5):
        return "evasive"

    # Caso A: Camino despejado / Corredor abierto -> Navegación nominal hacia el Waypoint activo
    return "keep_going"


# ---------------------------------------------------------------------------
# Construcción e Integración del Grafo
# ---------------------------------------------------------------------------
def build_workflow() -> Any:
    """Construye el StateGraph de 7 nodos y 2 routers condicionales."""
    nodes = _build_nodes()
    workflow = StateGraph(DroneState)

    workflow.add_node("capture", nodes["capture"])
    workflow.add_node("canny_xor_gate", nodes["canny_xor_gate"])
    workflow.add_node("optical_flow", nodes["optical_flow"])
    workflow.add_node("ipm_segmentation", nodes["ipm_segmentation"])
    workflow.add_node("ttc_estimate", nodes["ttc_estimate"])
    workflow.add_node("keep_going", nodes["keep_going"])
    workflow.add_node("evasive", nodes["evasive"])
    workflow.add_node("hover_and_slm", nodes["hover_and_slm"])
    workflow.add_node("blind_wall_router", nodes["blind_wall_router"])
    workflow.add_node("motor", nodes["motor"])

    # Flujo y conexiones
    workflow.set_entry_point("capture")
    workflow.add_edge("capture", "canny_xor_gate")
    workflow.add_edge("canny_xor_gate", "optical_flow")
    workflow.add_edge("optical_flow", "ipm_segmentation")
    workflow.add_edge("ipm_segmentation", "ttc_estimate")

    # Router Táctico Jerárquico: TTC + Proximidad + Estructuras + Persistencia
    workflow.add_conditional_edges(
        "ttc_estimate",
        ttc_router,
        {
            "keep_going": "keep_going",
            "evasive": "evasive",
            "hover_and_slm": "hover_and_slm",
        },
    )

    workflow.add_edge("keep_going", "motor")
    workflow.add_edge("evasive", "motor")
    workflow.add_edge("hover_and_slm", "blind_wall_router")
    workflow.add_edge("blind_wall_router", "motor")
    workflow.add_edge("motor", END)

    return workflow


def compile_workflow():
    """Atajo para compilar el StateGraph."""
    workflow = build_workflow()
    return workflow.compile()


def get_airsim_client() -> Optional[Any]:
    """Obtiene el cliente de AirSim asociado al grafo."""
    try:
        return _build_nodes()["_airsim_client"]
    except Exception:
        return None

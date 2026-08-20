# Definición del flujo de LangGraph y el Bucle de Control Jerárquico (5 Pasos).
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


# ---------------------------------------------------------------------------
# Estado del grafo (DroneState)
# ---------------------------------------------------------------------------
class DroneState(TypedDict, total=False):
    """Estado que circula entre los nodos del grafo en el nuevo pipeline jerárquico."""

    rgb_image: Any
    annotated_image: Any  # Frame con bboxes de YOLO superpuestos para el VLM
    prev_canny_edges: Any
    xor_change_ratio: float
    telemetry: Dict[str, Any]
    roi_image: Any
    roi_info: Any  # (x_offset, y_offset, roi_w, roi_h)
    detections: List[Any]
    roi_detections: List[Any]
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


# ---------------------------------------------------------------------------
# Lazy imports y construcción de nodos
# ---------------------------------------------------------------------------
def _build_nodes() -> Dict[str, Any]:
    """Construye los callables de los nodos y los componentes persistentes."""
    from .reactive import reactive_node
    from .deliberative import deliberative_node
    from .evasive import evasive_node
    from src.perception import (
        CannyGate,
        YoloDetector,
        crop_roi_62,
        TTCEstimator,
        translate_detections,
        summarize_scene,
    )
    from src.hardware import AirSimClient

    weights_path = os.getenv("YOLO_WEIGHTS", "weights/yolov8n.pt")
    confidence_threshold = float(os.getenv("YOLO_CONF", "0.35"))
    detector = YoloDetector(
        weights_path=weights_path,
        confidence_threshold=confidence_threshold,
    )

    canny_gate = CannyGate()
    ttc_estimator = TTCEstimator()

    airsim_client = AirSimClient()
    airsim_client.connect()

    # 1. Nodo de captura de cámara en tiempo real
    def capture_node(state: DroneState) -> DroneState:
        # pyrefly: ignore [bad-unpacking]
        image, telemetry = airsim_client.capture()
        state["rgb_image"] = image
        state["telemetry"] = telemetry
        return state

    # 2. Paso 1: Gating de Bordes XOR (Canny)
    def canny_xor_gate_node(state: DroneState) -> DroneState:
        image = state.get("rgb_image")
        change_ratio, edges, _ = canny_gate.evaluate(image)
        state["xor_change_ratio"] = change_ratio
        state["prev_canny_edges"] = edges
        return state

    # 3. Paso 2: Restricción de ROI de 62° + Inferencia YOLO
    def roi_yolo_detect_node(state: DroneState) -> DroneState:
        image = state.get("rgb_image")
        roi_image, roi_info = crop_roi_62(image)

        # Ejecutamos YOLO sobre el recorte ROI para ahorrar hardware
        roi_detections = detector.detect(roi_image)

        # Remapar bboxes al marco global para la visualización y compatibilidad
        x_off, y_off, _, _ = roi_info
        global_detections = []
        global_det_objs = []
        from src.perception import Detection
        for det in roi_detections:
            if det.bbox and len(det.bbox) == 4:
                g_bbox = [
                    det.bbox[0] + x_off,
                    det.bbox[1] + y_off,
                    det.bbox[2] + x_off,
                    det.bbox[3] + y_off,
                ]
                det_dict = det.to_dict()
                det_dict["bbox"] = g_bbox
                global_detections.append(det_dict)
                global_det_objs.append(
                    Detection(object=det.object, confidence=float(det.confidence), bbox=g_bbox)
                )

        obstacles = translate_detections(
            global_det_objs if global_det_objs else roi_detections,
            frame_width=airsim_client.frame_width,
            frame_height=airsim_client.frame_height,
        )

        state["roi_image"] = roi_image
        state["roi_info"] = roi_info
        state["roi_detections"] = [d.to_dict() for d in roi_detections]
        state["detections"] = global_detections
        state["detected_obstacles"] = [o.to_dict() for o in obstacles]
        state["scene_summary"] = summarize_scene(obstacles)
        state["collision_result"] = detector.last_collision_result.to_dict()

        # Generar frame anotado con bboxes para el VLM deliberativo
        annotated = None
        if image is not None:
            try:
                import cv2
                annotated = image.copy()
                for det in global_detections:
                    bbox = det.get("bbox", [0, 0, 0, 0])
                    obj_name = det.get("object", "")
                    if len(bbox) == 4:
                        x1, y1, x2, y2 = map(int, bbox)
                        cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 255, 100), 2)
                        cv2.putText(annotated, obj_name, (x1, max(y1 - 5, 15)),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 100), 1)
            except Exception:
                annotated = image  # Si falla cv2, usar el frame crudo
        state["annotated_image"] = annotated

        return state

    # 4. Paso 3: Estimación de Tiempo de Colisión (TTC) No Neuronal
    def ttc_estimate_node(state: DroneState) -> DroneState:
        raw_detections = state.get("roi_detections", [])
        # Reconstruir objetos Detection si venían como dicts
        from src.perception import Detection
        det_objs = []
        for d in raw_detections:
            if isinstance(d, dict):
                det_objs.append(Detection(object=d.get("object", "objeto"), confidence=float(d.get("confidence", 0.0)), bbox=d.get("bbox", [0, 0, 0, 0])))
            elif isinstance(d, Detection):
                det_objs.append(d)
            else:
                det_objs.append(d)

        estimated_ttc, details = ttc_estimator.estimate(det_objs)
        state["estimated_ttc"] = estimated_ttc
        state["ttc_details"] = details
        return state

    # 5. Paso 5: Parada de seguridad previa al SLM
    def hover_before_slm_node(state: DroneState) -> DroneState:
        # Enviar comando de frenado inmediato para evitar colisión durante inferencia
        airsim_client.execute_velocity(vx=0.0, vy=0.0, vz=0.0, yaw_rate=0.0)
        return deliberative_node(state)

    # 6. Nodo de actuación motriz
    def motor_node(state: DroneState) -> DroneState:
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
        "roi_yolo_detect": roi_yolo_detect_node,
        "ttc_estimate": ttc_estimate_node,
        "keep_going": reactive_node,
        "evasive": evasive_node,
        "hover_and_slm": hover_before_slm_node,
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
    return "roi_yolo_detect"


def ttc_router(state: DroneState) -> str:
    """Decisión de Paso 4: Router Táctico Jerárquico con Priorización de Estructuras Urbanas.

    - Caso C (hover_and_slm): Estructura frontal (edificio/muro) en Cerca/Inminente,
      o cualquier objeto Inminente (<2.5m), o Looming dinámico crítico (TTC <= 2.0s).
    - Caso B (evasive): Obstáculo central en Cerca (postes, árboles, tráfico) o TTC <= 5.0s.
    - Caso A (keep_going): Sector central totalmente libre de obstáculos cercanos/inminentes.
    """
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
    workflow.add_node("roi_yolo_detect", nodes["roi_yolo_detect"])
    workflow.add_node("ttc_estimate", nodes["ttc_estimate"])
    workflow.add_node("keep_going", nodes["keep_going"])
    workflow.add_node("evasive", nodes["evasive"])
    workflow.add_node("hover_and_slm", nodes["hover_and_slm"])
    workflow.add_node("motor", nodes["motor"])

    # Flujo y conexiones
    workflow.set_entry_point("capture")
    workflow.add_edge("capture", "canny_xor_gate")
    workflow.add_edge("canny_xor_gate", "roi_yolo_detect")
    workflow.add_edge("roi_yolo_detect", "ttc_estimate")

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
    workflow.add_edge("hover_and_slm", "motor")
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

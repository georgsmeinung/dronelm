# Definición del flujo de LangGraph y el Bucle de Control Jerárquico (5 Pasos).
from __future__ import annotations

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
    flight_status: str  # "vuelo" | "hover_slm" | "evasion_local"
    deliberations: List[Dict[str, Any]]
    collision_result: Dict[str, Any]


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

    # 1. Nodo de captura de cámara
    def capture_node(state: DroneState) -> DroneState:
        image = state.get("rgb_image")
        telemetry = state.get("telemetry")

        if image is None or telemetry is None:
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

        obstacles = translate_detections(
            roi_detections,
            frame_width=roi_info[2] if roi_info[2] > 0 else airsim_client.frame_width,
            frame_height=roi_info[3] if roi_info[3] > 0 else airsim_client.frame_height,
        )

        state["roi_image"] = roi_image
        state["roi_info"] = roi_info
        state["roi_detections"] = [d.to_dict() for d in roi_detections]
        state["detections"] = global_detections
        state["detected_obstacles"] = [o.to_dict() for o in obstacles]
        state["scene_summary"] = summarize_scene(obstacles)
        state["collision_result"] = detector.last_collision_result.to_dict()
        return state

    # 4. Paso 3: Estimación de Tiempo de Colisión (TTC) No Neuronal
    def ttc_estimate_node(state: DroneState) -> DroneState:
        roi_detections = [
            d if isinstance(d, Any) else d for d in state.get("roi_detections", [])
        ]
        # Reconstruir objetos Detection si venían como dicts
        from src.perception import Detection
        det_objs = []
        for d in roi_detections:
            if isinstance(d, dict):
                det_objs.append(Detection(object=d["object"], confidence=d["confidence"], bbox=d["bbox"]))
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
        airsim_client.execute_velocity(
            vx=float(cmd.get("vx", 0.0)),
            vy=float(cmd.get("vy", 0.0)),
            vz=float(cmd.get("vz", 0.0)),
            yaw_rate=float(cmd.get("yaw_rate", 0.0)),
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
    """Decisión de Paso 4: Router de 3 Vías según el TTC estimado."""
    ttc = state.get("estimated_ttc", float("inf"))
    obstacles = state.get("detected_obstacles", []) or []

    # Caso A: Sin peligro (TTC > 5.0 segundos)
    if ttc > TTC_SAFE_THRESHOLD and not obstacles:
        return "keep_going"

    # Caso B: Maniobra Evasiva Local Directa (2.0s < TTC <= 5.0s)
    if TTC_EVASION_THRESHOLD < ttc <= TTC_SAFE_THRESHOLD:
        return "evasive"

    # Caso C: Zona de Incertidumbre o Peligro Inminente (TTC <= 2.0s)
    return "hover_and_slm"


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

    # Router 1: Canny XOR
    workflow.add_conditional_edges(
        "canny_xor_gate",
        xor_router,
        {
            "keep_going": "keep_going",
            "roi_yolo_detect": "roi_yolo_detect",
        },
    )

    workflow.add_edge("roi_yolo_detect", "ttc_estimate")

    # Router 2: TTC 3 Vías
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

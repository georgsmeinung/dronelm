# Definicion del flujo de LangGraph, el estado del dron y el Gatekeeper.
# El grafo cablea los pasos 1-5 del pipeline:
#   perception -> [gatekeeper] -> reactive | deliberative -> motor -> END
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, TypedDict

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover
    pass

from langgraph.graph import END, StateGraph


# ---------------------------------------------------------------------------
# Estado del grafo (DroneState)
# ---------------------------------------------------------------------------
class DroneState(TypedDict, total=False):
    """Estado que circula entre los nodos del grafo.

    Atributos:
        rgb_image: imagen RGB (numpy.ndarray) o ``None`` si no hay captura.
        telemetry: telemetria cruda (posicion, velocidad, orientacion).
        detections: detecciones crudas de YOLO (lista de ``Detection``).
        detected_obstacles: obstaculos traducidos (sector + proximidad).
        scene_summary: resumen textual para el SLM.
        next_action: macro-accion elegida por el nodo correspondiente.
        velocity_command: vectores de velocidad calculados para AirSim.
        route: nombre del ultimo nodo ejecutado ("reactive"/"deliberative").
        deliberations: historial de prompts/decisiones del SLM.
    """

    rgb_image: Any
    telemetry: Dict[str, Any]
    detections: List[Any]
    detected_obstacles: List[Dict[str, Any]]
    scene_summary: str
    next_action: str
    velocity_command: Dict[str, Any]
    route: str
    deliberations: List[Dict[str, Any]]


# ---------------------------------------------------------------------------
# Lazy imports de los nodos para evitar ciclos y cargas costosas en import.
# ---------------------------------------------------------------------------
def _build_nodes() -> Dict[str, Any]:
    """Construye los callables de los nodos a partir de los modulos."""
    from .reactive import reactive_node
    from .deliberative import deliberative_node
    from src.perception import YoloDetector, translate_detections, summarize_scene
    from src.hardware import AirSimClient

    detector = YoloDetector(
        weights_path=os.getenv("YOLO_WEIGHTS", "weights/yolov8n.pt"),
        confidence_threshold=float(os.getenv("YOLO_CONF", "0.35")),
    )
    airsim_client = AirSimClient()
    airsim_client.connect()

    def perception_node(state: DroneState) -> DroneState:
        """Pasos 1 y 2: captura sensorial + traduccion pixeles-a-palabras."""
        image = state.get("rgb_image")
        telemetry = state.get("telemetry")

        # Si el orquestador externo no inyecto una imagen/telemetria, las
        # capturamos desde AirSim (modo simulado si no hay conexion).
        if image is None or telemetry is None:
            image, telemetry = airsim_client.capture()

        detections = detector.detect(image)
        obstacles = translate_detections(
            detections,
            frame_width=airsim_client.frame_width,
            frame_height=airsim_client.frame_height,
            proximity_threshold_m=float(
                os.getenv("PROXIMITY_THRESHOLD_METERS", "5.0")
            ),
        )
        obstacle_dicts = [o.to_dict() for o in obstacles]

        state["rgb_image"] = image
        state["telemetry"] = telemetry
        state["detections"] = [d.to_dict() for d in detections]
        state["detected_obstacles"] = obstacle_dicts
        state["scene_summary"] = summarize_scene(obstacles)
        return state

    def motor_node(state: DroneState) -> DroneState:
        """Paso 5: traduce la macro-accion en velocidades y las envia."""
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
        "perception": perception_node,
        "reactive": reactive_node,
        "deliberative": deliberative_node,
        "motor": motor_node,
        "_airsim_client": airsim_client,
    }


# ---------------------------------------------------------------------------
# Paso 3: Gatekeeper (arista condicional)
# ---------------------------------------------------------------------------
PROXIMITY_BLOCKING = {"Inminente", "Cerca"}


def gatekeeper_router(state: DroneState) -> str:
    """Decide si el flujo va al reflejo rapido o al cerebro deliberativo.

    Reglas:
        * Si hay algun obstaculo con sector "Centro" y proximidad
          ``Inminente`` o ``Cerca`` -> deliberativo.
        * Si no -> reactivo.
    """
    obstacles = state.get("detected_obstacles", []) or []
    for obs in obstacles:
        sector = str(obs.get("sector", "")).strip()
        proximity = str(obs.get("proximity", "")).strip()
        if sector == "Centro" and proximity in PROXIMITY_BLOCKING:
            return "deliberative"
    return "reactive"


# ---------------------------------------------------------------------------
# Construccion del grafo
# ---------------------------------------------------------------------------
def build_workflow() -> Any:
    """Construye un ``StateGraph`` cableado con todos los nodos."""
    nodes = _build_nodes()
    workflow = StateGraph(DroneState)

    workflow.add_node("perception", nodes["perception"])
    workflow.add_node("reactive", nodes["reactive"])
    workflow.add_node("deliberative", nodes["deliberative"])
    workflow.add_node("motor", nodes["motor"])

    workflow.set_entry_point("perception")
    workflow.add_conditional_edges(
        "perception",
        gatekeeper_router,
        {
            "reactive": "reactive",
            "deliberative": "deliberative",
        },
    )
    workflow.add_edge("reactive", "motor")
    workflow.add_edge("deliberative", "motor")
    workflow.add_edge("motor", END)
    return workflow


def compile_workflow():
    """Atajo para construir y compilar el grafo en una sola llamada."""
    workflow = build_workflow()
    return workflow.compile()


def get_airsim_client() -> Optional[Any]:
    """Devuelve el cliente AirSim asociado al grafo ya compilado, si existe."""
    try:
        return _build_nodes()["_airsim_client"]
    except Exception:
        return None

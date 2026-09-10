# S1 + S2 (PLAN-SLAM): buffer de trayectoria acumulada para slam_assess.
#
# A diferencia de ObstacleField (que depende de foe_confidence y falla
# exactamente en los escenarios de bloqueo), FlightTrajectory acumula
# eventos de vuelo basados en telemetría — posición, heading, acción y
# resultado (avance / stall) — que son confiables incluso cuando el sensor
# óptico es ciego. Un stall repetido en la misma posición es evidencia de
# bloqueo con independencia del canal de TTC.
#
# trajectory_context_text() produce el bloque textual que slam_assess
# envía al VLM en lugar del panorama de rotación de deep_vlm.
from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from typing import List, Optional

SLAM_HISTORY_SIZE = int(os.getenv("SLAM_HISTORY_SIZE", "80"))
SLAM_STALL_THRESHOLD_M = float(os.getenv("SLAM_STALL_THRESHOLD_M", "0.3"))
SLAM_CONTEXT_MAX_EVENTS = int(os.getenv("SLAM_CONTEXT_MAX_EVENTS", "30"))


@dataclass
class TrajectoryEvent:
    """Un ciclo de vuelo con su resultado."""

    timestamp: float
    position: tuple          # (x, y, z) NED, metros
    heading_deg: float       # rumbo en grados [-180, 180]
    action_taken: str        # macro_action del ciclo anterior
    delta_wp_m: float        # Δ distancia al waypoint: positivo = retroceso, negativo = avance
    stall: bool              # True si delta_wp_m > SLAM_STALL_THRESHOLD_M
    flow_had_evidence: bool  # foe_confidence > 0 ese ciclo
    obstacle_class: Optional[str] = None   # S3b: "tree" | "building" | None
    obstacle_conf: float = 0.0             # S3b: confianza de la detección YOLO


class FlightTrajectory:
    """Ring buffer de eventos de trayectoria.

    Se instancia una vez en _build_nodes() (estado del proceso, no del grafo)
    y se actualiza al inicio de cada ciclo con los datos del ciclo anterior.
    """

    def __init__(self, max_size: int = SLAM_HISTORY_SIZE) -> None:
        self._max_size = max_size
        self._events: List[TrajectoryEvent] = []

    def record(self, event: TrajectoryEvent) -> None:
        self._events.append(event)
        if len(self._events) > self._max_size:
            self._events.pop(0)

    def __len__(self) -> int:
        return len(self._events)

    def trajectory_context_text(
        self,
        current_heading_deg: float = 0.0,
        max_events: int = 0,
    ) -> str:
        """Resumen textual de trayectoria para el prompt de slam_assess (S2).

        Agrupa eventos por zona angular relativa al heading actual y cuenta
        intentos y stalls por zona. El vocabulario está alineado con las
        macro-acciones disponibles (MANTENER_RUMBO, EVADIR_IZQUIERDA, etc.).
        """
        events = self._events
        cap = max_events if max_events > 0 else SLAM_CONTEXT_MAX_EVENTS
        events = events[-cap:] if len(events) > cap else events

        if not events:
            return "HISTORIAL DE TRAYECTORIA: sin datos disponibles aún."

        zones: dict = {
            "FRENTE":    {"attempts": 0, "stalls": 0, "classes": []},
            "IZQUIERDA": {"attempts": 0, "stalls": 0, "classes": []},
            "DERECHA":   {"attempts": 0, "stalls": 0, "classes": []},
            "ATRÁS":     {"attempts": 0, "stalls": 0, "classes": []},
        }

        total_delta = 0.0
        stall_count = 0

        for ev in events:
            rel = ((ev.heading_deg - current_heading_deg) + 180.0) % 360.0 - 180.0
            if -30.0 <= rel <= 30.0:
                zone = "FRENTE"
            elif -150.0 <= rel < -30.0:
                zone = "IZQUIERDA"
            elif 30.0 < rel <= 150.0:
                zone = "DERECHA"
            else:
                zone = "ATRÁS"

            zones[zone]["attempts"] += 1
            if ev.stall:
                zones[zone]["stalls"] += 1
                stall_count += 1
                if ev.obstacle_class and ev.obstacle_conf >= 0.45:
                    zones[zone]["classes"].append((ev.obstacle_class, ev.obstacle_conf))
            total_delta += ev.delta_wp_m

        lines = [f"HISTORIAL DE TRAYECTORIA (últimos {len(events)} ciclos):"]
        for zone, data in zones.items():
            attempts = data["attempts"]
            stalls = data["stalls"]
            if attempts == 0:
                lines.append(f"- {zone}: 0 intentos. No explorado.")
                continue
            progress = attempts - stalls
            note = ""
            if stalls >= attempts * 0.7:
                note = " Zona probable de bloqueo."
            elif stalls == 0:
                note = " Sin stalls registrados."
            # S3b: incluir clase de obstáculo si hay anotaciones
            obs_notes = ""
            if data["classes"]:
                top = max(data["classes"], key=lambda x: x[1])
                obs_notes = f" Obstáculo identificado: {top[0]} (conf={top[1]:.2f})."
            lines.append(
                f"- {zone} ({attempts} intentos → {stalls} stalls, {progress} con progreso).{note}{obs_notes}"
            )

        direction = "retroceso" if total_delta > 0 else "avance"
        lines.append(
            f"Ciclos en stall acumulados: {stall_count}. "
            f"Progreso total al waypoint: {abs(total_delta):.1f}m ({direction} neto)."
        )
        return "\n".join(lines)

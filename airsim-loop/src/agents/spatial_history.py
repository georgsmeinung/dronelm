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
from collections import deque
from dataclasses import dataclass, field
from typing import List, Optional

SLAM_HISTORY_SIZE = int(os.getenv("SLAM_HISTORY_SIZE", "60"))
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
        self._events: deque[TrajectoryEvent] = deque(maxlen=max_size)

    def record(self, event: TrajectoryEvent) -> None:
        self._events.append(event)  # deque(maxlen) descarta el más antiguo en O(1)

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
        events = list(self._events)
        cap = max_events if max_events > 0 else SLAM_CONTEXT_MAX_EVENTS
        events = events[-cap:] if len(events) > cap else events

        if not events:
            return "HISTORIAL DE TRAYECTORIA: sin datos disponibles aún."

        zones: dict = {
            "FRENTE":    {"attempts": 0, "stalls": 0, "classes": [], "delta_sum": 0.0},
            "IZQUIERDA": {"attempts": 0, "stalls": 0, "classes": [], "delta_sum": 0.0},
            "DERECHA":   {"attempts": 0, "stalls": 0, "classes": [], "delta_sum": 0.0},
            "ATRÁS":     {"attempts": 0, "stalls": 0, "classes": [], "delta_sum": 0.0},
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
            zones[zone]["delta_sum"] += ev.delta_wp_m
            if ev.stall:
                zones[zone]["stalls"] += 1
                stall_count += 1
                if ev.obstacle_class and ev.obstacle_conf >= 0.45:
                    zones[zone]["classes"].append((ev.obstacle_class, ev.obstacle_conf))
            total_delta += ev.delta_wp_m

        # Umbral bajo el cual el progreso se considera marginal (posible bloqueo invisible).
        # SLAM_STALL_THRESHOLD_M mide RETROCESO; este umbral mide avance insuficiente.
        # Default 0.28m: el árbol invisible produce ~0.25m/ciclo; el test base usa -0.3m.
        _MARGINAL_PROGRESS_M = float(os.getenv("SLAM_MARGINAL_PROGRESS_M", "0.28"))

        lines = [f"HISTORIAL DE TRAYECTORIA (últimos {len(events)} ciclos):"]
        for zone, data in zones.items():
            attempts = data["attempts"]
            stalls = data["stalls"]
            if attempts == 0:
                lines.append(f"- {zone}: 0 intentos. No explorado.")
                continue
            progress = attempts - stalls
            avg_prog = -data["delta_sum"] / attempts  # negativo delta = avance → positivo aquí

            note = ""
            if stalls >= attempts * 0.7:
                note = " Zona probable de bloqueo."
            elif stalls == 0 and attempts >= 3 and avg_prog < _MARGINAL_PROGRESS_M:
                # Sin retroceso pero con avance marginal: firma típica de árbol/malla invisible.
                note = (
                    f" ADVERTENCIA: sin stalls registrados pero avance promedio"
                    f" {avg_prog:.2f}m/ciclo < {_MARGINAL_PROGRESS_M:.2f}m"
                    f" — posible colisión con obstáculo invisible al flujo óptico."
                    " MANTENER_RUMBO en FRENTE refuerza este bloqueo."
                )
            elif stalls == 0:
                note = f" Sin stalls registrados (avance promedio {avg_prog:.2f}m/ciclo)."
            else:
                note = f" Avance promedio {avg_prog:.2f}m/ciclo."

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

    def zone_stats(
        self,
        current_heading_deg: float = 0.0,
        max_events: int = 0,
    ) -> dict:
        """Devuelve {zona: {"attempts": int, "stall_rate": float}} para las 4 zonas.

        Útil para decidir overrides de acción sin re-parsear el texto del prompt.
        """
        events = list(self._events)
        cap = max_events if max_events > 0 else SLAM_CONTEXT_MAX_EVENTS
        events = events[-cap:] if len(events) > cap else events
        raw: dict = {
            "FRENTE":    {"attempts": 0, "stalls": 0},
            "IZQUIERDA": {"attempts": 0, "stalls": 0},
            "DERECHA":   {"attempts": 0, "stalls": 0},
            "ATRÁS":     {"attempts": 0, "stalls": 0},
        }
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
            raw[zone]["attempts"] += 1
            if ev.stall:
                raw[zone]["stalls"] += 1
        return {
            z: {
                "attempts": d["attempts"],
                "stall_rate": d["stalls"] / d["attempts"] if d["attempts"] > 0 else 0.0,
            }
            for z, d in raw.items()
        }

    def frente_stall_rate(
        self,
        current_heading_deg: float = 0.0,
        max_events: int = 0,
    ) -> float:
        """Tasa de stall de la zona FRENTE en los últimos max_events ciclos.

        Devuelve 0.0 si no hay eventos en FRENTE. Misma zonificación que
        trajectory_context_text(): ±30° del heading actual = FRENTE.
        """
        events = list(self._events)
        cap = max_events if max_events > 0 else SLAM_CONTEXT_MAX_EVENTS
        events = events[-cap:] if len(events) > cap else events
        attempts = stalls = 0
        for ev in events:
            rel = ((ev.heading_deg - current_heading_deg) + 180.0) % 360.0 - 180.0
            if -30.0 <= rel <= 30.0:
                attempts += 1
                if ev.stall:
                    stalls += 1
        return stalls / attempts if attempts > 0 else 0.0

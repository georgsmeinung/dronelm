# Gobernador de velocidad del crucero (2026-0929).
#
# Motivo (citysim_pilot seed 99 02:32, incrustado en una fachada): con la pared a 4 m el campo
# de obstaculos estaba `degraded`/sin TTC y el guiado comandaba crucero (~3 m/s); el dron acelero
# de 0.5 a 2.7 m/s hacia ella y GIRAR_90 (vx=0) no alcanzo a frenarlo. "Ausencia de evidencia" se
# trataba como espacio libre. Este modulo NO toca la percepcion: solo limita la velocidad hacia
# adelante de MANTENER_RUMBO segun cuanta evidencia hay y que paso hace poco:
#   * sin flujo valido (degraded/none) varios ciclos seguidos -> tope MID y luego SLOW;
#   * tras un frente bloqueado (GIRAR_90 o blocked_fraction ~ 1) -> tope SLOW durante un tiempo;
#   * al terminar una maniobra (giro/evasion/retroceso) -> rampa desde SLOW hasta el crucero.
from __future__ import annotations

import os
from typing import Optional

GOV_ENABLED = os.getenv("GOV_ENABLED", "true").lower() == "true"
GOV_SLOW_MPS = float(os.getenv("GOV_SLOW_MPS", "1.0"))
GOV_MID_MPS = float(os.getenv("GOV_MID_MPS", "1.5"))
GOV_MID_CYCLES = int(os.getenv("GOV_DEGRADED_MID_CYCLES", "3"))
GOV_SLOW_CYCLES = int(os.getenv("GOV_DEGRADED_SLOW_CYCLES", "8"))
GOV_BLOCK_MEMORY_CYCLES = int(os.getenv("GOV_BLOCK_MEMORY_CYCLES", "40"))
GOV_RAMP_CYCLES = int(os.getenv("GOV_RAMP_CYCLES", "15"))
GOV_RAMP_TOP_MPS = float(os.getenv("GOV_RAMP_TOP_MPS", "6.0"))
_NO_EVIDENCE = ("degraded", "none")


class SpeedGovernor:
    """Calcula, ciclo a ciclo, un tope de velocidad hacia adelante (None = sin tope)."""

    def __init__(self) -> None:
        self._no_evidence = 0
        self._block_left = 0
        self._ramp_left = 0
        self._was_maneuver = False

    def update(self, field_source: str, blocked_fraction: float, maneuver_active: bool,
               action: str = "") -> Optional[float]:
        if not GOV_ENABLED:
            return None
        # Evidencia: solo `flow` la renueva; `holdover` (evidencia retenida) no cuenta como ciega.
        if field_source in _NO_EVIDENCE:
            self._no_evidence += 1
        elif field_source == "flow":
            self._no_evidence = 0
        # Memoria de frente bloqueado.
        if action == "GIRAR_90" or blocked_fraction >= 0.99:
            self._block_left = GOV_BLOCK_MEMORY_CYCLES
        elif self._block_left > 0:
            self._block_left -= 1
        # Rampa al terminar una maniobra.
        if self._was_maneuver and not maneuver_active:
            self._ramp_left = GOV_RAMP_CYCLES
        elif self._ramp_left > 0 and not maneuver_active:
            self._ramp_left -= 1
        self._was_maneuver = maneuver_active

        caps = []
        if self._no_evidence >= GOV_SLOW_CYCLES:
            caps.append(GOV_SLOW_MPS)
        elif self._no_evidence >= GOV_MID_CYCLES:
            caps.append(GOV_MID_MPS)
        if self._block_left > 0:
            caps.append(GOV_SLOW_MPS)
        if self._ramp_left > 0:
            k = (GOV_RAMP_CYCLES - self._ramp_left) / float(GOV_RAMP_CYCLES)
            caps.append(GOV_SLOW_MPS + (GOV_RAMP_TOP_MPS - GOV_SLOW_MPS) * k)
        return min(caps) if caps else None

    def reset(self) -> None:
        self.__init__()

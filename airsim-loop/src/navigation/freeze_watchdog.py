# Vigilante de congelamiento fisico (2026-0929).
#
# Cuando el dron queda incrustado en la malla (balcones/balaustradas sin colision) AirSim deja
# pos, yaw, pitch, roll y velocidad IDENTICOS ciclo tras ciclo (un vuelo real siempre tiene ruido)
# y `has_collided` sigue en False. Los detectores de atasco no lo distinguen de un hover y el
# grafo repite escaneo/evasion/retroceso sin efecto (135 ciclos perdidos en seed 99 02:32, 876 en
# 00:19). `landed_state == 0` (en el suelo) NO cuenta: ese caso lo cubre la guarda de despegue.
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Sequence, Tuple

FREEZE_CYCLES = int(os.getenv("FREEZE_CYCLES", "25"))
FREEZE_TOL = float(os.getenv("FREEZE_TOL", "1e-6"))


class FreezeWatchdog:
    def __init__(self, cycles: Optional[int] = None, tol: Optional[float] = None) -> None:
        self.cycles = FREEZE_CYCLES if cycles is None else cycles
        self.tol = FREEZE_TOL if tol is None else tol
        self._prev: Optional[Tuple[float, ...]] = None
        self.count = 0

    @staticmethod
    def _signature(telem: Dict[str, Any]) -> Optional[Tuple[float, ...]]:
        if not telem or telem.get("source") != "airsim":
            return None
        p, o, v = telem.get("position") or {}, telem.get("orientation") or {}, telem.get("velocity") or {}
        try:
            return (float(p["x"]), float(p["y"]), float(p["z"]),
                    float(o.get("yaw", 0.0)), float(o.get("pitch", 0.0)), float(o.get("roll", 0.0)),
                    float(v.get("vx", 0.0)), float(v.get("vy", 0.0)), float(v.get("vz", 0.0)))
        except (KeyError, TypeError, ValueError):
            return None

    def update(self, telem: Dict[str, Any]) -> int:
        """Devuelve cuantos ciclos seguidos lleva el estado identico (0 si no aplica)."""
        sig = self._signature(telem)
        if sig is None or telem.get("landed_state") == 0:
            self._prev, self.count = None, 0
            return 0
        if self._prev is not None and all(abs(a - b) < self.tol for a, b in zip(sig, self._prev)):
            self.count += 1
        else:
            self.count = 0
        self._prev = sig
        return self.count

    @property
    def frozen(self) -> bool:
        return self.count >= self.cycles

    def reset(self) -> None:
        self._prev, self.count = None, 0


def pick_recovery_pose(history: Sequence[Tuple[int, float, float, float, float, float]],
                       frozen_since: int, backoff: int = 30, min_speed: float = 0.8
                       ) -> Optional[Tuple[float, float, float, float]]:
    """Ultima pose LIBRE anterior al bloqueo: (x, y, z, yaw_deg) o None.

    `history`: (ciclo, x, y, z, yaw_deg, velocidad_horizontal). Se elige, entre las entradas
    al menos `backoff` ciclos antes de que empezara el congelamiento, la mas reciente en la que el
    dron avanzaba (>= min_speed); si no hay ninguna, la mas reciente sin ese requisito.
    """
    older = [h for h in history if h[0] <= frozen_since - backoff]
    if not older:
        return None
    moving = [h for h in older if h[5] >= min_speed]
    h = (moving or older)[-1]
    return (h[1], h[2], h[3], h[4])

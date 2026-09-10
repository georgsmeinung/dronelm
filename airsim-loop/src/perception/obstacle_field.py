# Paso 3/4: Contrato unico de percepcion (F1.1 del plan de mejoras).
# ObstacleField es el UNICO objeto que router, evasive, deliberative, fsm y
# el logger de vuelo consultan. Ningun consumidor debe leer campos crudos de
# flujo optico o mascaras: todo pasa por esta API.
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

SECTORS: Tuple[str, ...] = ("izquierda", "centro", "derecha")
BANDS: Tuple[str, ...] = ("superior", "medio", "inferior")

# OCCUPANCY_BLOCKED_THRESHOLD calibrado D2 (2026-0910, TownSim, 196 frames,
# 4 velocidades). AUC=0.87; threshold Youden t=0.011 → TPR=0.931, FPR=0.222.
# Valor seteado en config/.env; el default 0.011 refleja la calibración.
OCCUPANCY_BLOCKED_THRESHOLD = float(os.getenv("OBSTACLE_OCCUPANCY_BLOCKED", "0.011"))
TTC_BLOCKED_THRESHOLD_S = float(os.getenv("OBSTACLE_TTC_BLOCKED_S", "2.5"))
MIN_CONFIDENCE_FOR_BLOCKED = float(os.getenv("OBSTACLE_MIN_CONFIDENCE", "0.15"))
# Piso de confianza mas exigente para que el TTC por si solo (sin apoyo de
# occupancy) baste para marcar una celda bloqueada (2026-0826, ver CHANGELOG.md).
# El camino de "pocos inliers" en flow_ttc.py clipea foe_confidence a 0.3 como
# senal de FOE poco confiable -- ese 0.3 superaba de sobra el piso general
# (0.15) y terminaba votando "bloqueado" con la misma autoridad que un FOE
# robusto. Con este umbral, esa evidencia degradada ya no puede bloquear un
# sector por TTC solo (occupancy sigue usando el piso general).
MIN_CONFIDENCE_FOR_TTC_BLOCKED = float(os.getenv("OBSTACLE_MIN_CONFIDENCE_TTC", "0.35"))


@dataclass(frozen=True)
class Cell:
    """Una celda sector x banda del campo de obstaculos."""

    sector: str
    band: str
    occupancy: float = 0.0     # [0,1] fraccion de la celda con evidencia de obstaculo
    ttc_s: float = float("inf")  # segundos; inf si no hay evidencia de aproximacion
    divergence: float = 0.0    # 1/s, tasa de expansion del campo traslacional
    confidence: float = 0.0    # [0,1] fraccion de pixeles validos de la celda

    def is_blocked(self) -> bool:
        if self.confidence < MIN_CONFIDENCE_FOR_BLOCKED:
            return False
        if self.occupancy >= OCCUPANCY_BLOCKED_THRESHOLD:
            return True
        return self.confidence >= MIN_CONFIDENCE_FOR_TTC_BLOCKED and self.ttc_s <= TTC_BLOCKED_THRESHOLD_S


def _empty_cells() -> Dict[Tuple[str, str], Cell]:
    return {
        (sector, band): Cell(sector=sector, band=band)
        for sector in SECTORS
        for band in BANDS
    }


@dataclass(frozen=True)
class ObstacleField:
    """Descriptor de escena por sector x banda. Producido por perception_node."""

    cells: Dict[Tuple[str, str], Cell] = field(default_factory=_empty_cells)
    dt_s: float = 0.0
    timestamp: float = 0.0
    source: str = "none"  # "flow" | "degraded" | "none"
    foe: Optional[Tuple[float, float]] = None
    foe_confidence: float = 0.0

    # ---- API de consumo (unica superficie publica) -----------------------
    def cells_in_sector(self, sector: str):
        return [self.cells[(sector, band)] for band in BANDS if (sector, band) in self.cells]

    def sector_ttc(self, sector: str) -> float:
        """Minimo robusto de TTC en la columna, ponderado por confianza."""
        vals = [c.ttc_s for c in self.cells_in_sector(sector) if c.confidence >= MIN_CONFIDENCE_FOR_BLOCKED]
        if not vals:
            return float("inf")
        return min(vals)

    def sector_occupancy(self, sector: str) -> float:
        cells = self.cells_in_sector(sector)
        if not cells:
            return 0.0
        weighted = [c.occupancy for c in cells if c.confidence >= MIN_CONFIDENCE_FOR_BLOCKED]
        if not weighted:
            return 0.0
        return max(weighted)

    def sector_confidence(self, sector: str) -> float:
        cells = self.cells_in_sector(sector)
        if not cells:
            return 0.0
        return max((c.confidence for c in cells), default=0.0)

    def is_blocked(self, sector: str) -> bool:
        return any(c.is_blocked() for c in self.cells_in_sector(sector))

    def blocked_fraction(self) -> float:
        """Reemplaza a occlusion_ratio del IPM retirado."""
        if not self.cells:
            return 0.0
        blocked = sum(1 for c in self.cells.values() if c.is_blocked())
        return blocked / len(self.cells)

    def min_ttc(self) -> float:
        vals = [c.ttc_s for c in self.cells.values() if c.confidence >= MIN_CONFIDENCE_FOR_BLOCKED]
        if not vals:
            return float("inf")
        return min(vals)

    def has_evidence(self) -> bool:
        return self.source == "flow" and self.foe_confidence > 0.0

    def summary_text(self) -> str:
        """Unica fuente del resumen de sectores para el prompt del SLM."""
        lines = ["SECTORES VISUALES:"]
        labels = {"izquierda": "IZQUIERDA", "centro": "CENTRO", "derecha": "DERECHA"}
        for sector in SECTORS:
            occ = self.sector_occupancy(sector)
            ttc = self.sector_ttc(sector)
            conf = self.sector_confidence(sector)
            if conf < MIN_CONFIDENCE_FOR_BLOCKED:
                status = "SIN EVIDENCIA (confianza baja)"
            elif self.is_blocked(sector):
                ttc_str = f"{ttc:.1f}s" if ttc != float("inf") else "inf"
                status = f"BLOQUEADO (ocupacion={occ*100:.0f}%, TTC={ttc_str})"
            else:
                status = "DESPEJADO"
            lines.append(f"- {labels[sector]}: {status}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        """Unica fuente de la representacion serializable (JSONL)."""
        return {
            "source": self.source,
            "dt_s": self.dt_s,
            "timestamp": self.timestamp,
            "foe": list(self.foe) if self.foe else None,
            "foe_confidence": self.foe_confidence,
            "blocked_fraction": self.blocked_fraction(),
            "min_ttc_s": None if self.min_ttc() == float("inf") else round(self.min_ttc(), 2),
            "sectors": {
                sector: {
                    "occupancy": round(self.sector_occupancy(sector), 3),
                    "ttc_s": None if self.sector_ttc(sector) == float("inf") else round(self.sector_ttc(sector), 2),
                    "confidence": round(self.sector_confidence(sector), 3),
                    "blocked": self.is_blocked(sector),
                }
                for sector in SECTORS
            },
        }


class OccupancyCalibrator:
    """Auto-calibra OCCUPANCY_BLOCKED_THRESHOLD midiendo el ruido de hover inicial.

    Durante los primeros `n_samples` ciclos (dron quieto en zona despejada),
    recoge el máximo de occ por sector y estima el piso de ruido de la escena.
    Aplica threshold = mean + k_sigma * std, con un piso mínimo de `min_threshold`.

    Uso en main.py::

        calibrator = OccupancyCalibrator()
        # dentro del loop, tras graph.invoke():
        if not calibrator.is_calibrated:
            calibrator.feed(final_state.get("obstacle_field"))
    """

    def __init__(
        self,
        n_samples: int = 25,
        k_sigma: float = 3.0,
        min_threshold: float = 0.005,
        max_threshold: float = 0.05,
    ):
        self._n = n_samples
        self._k = k_sigma
        self._min = min_threshold
        self._max = max_threshold
        self._samples: list = []
        self._calibrated = False

    @property
    def is_calibrated(self) -> bool:
        return self._calibrated

    def feed(self, field: "ObstacleField | None") -> bool:
        """Agrega una muestra. Retorna True cuando la calibración se completa."""
        if self._calibrated or field is None or field.source == "none":
            return self._calibrated

        occ_max = max(
            field.sector_occupancy("izquierda"),
            field.sector_occupancy("centro"),
            field.sector_occupancy("derecha"),
        )
        self._samples.append(occ_max)

        if len(self._samples) >= self._n:
            self._apply()
        return self._calibrated

    def _apply(self) -> None:
        global OCCUPANCY_BLOCKED_THRESHOLD
        n = len(self._samples)
        mean = sum(self._samples) / n
        variance = sum((x - mean) ** 2 for x in self._samples) / max(n - 1, 1)
        std = variance ** 0.5
        threshold = mean + self._k * std
        threshold = max(self._min, min(self._max, threshold))
        OCCUPANCY_BLOCKED_THRESHOLD = threshold
        self._calibrated = True
        print(
            f"[OccupancyCalibrator] Threshold adaptativo: {threshold:.4f} "
            f"(mean={mean:.4f}, std={std:.4f}, n={n})"
        )


def empty_field(source: str = "none", timestamp: float = 0.0) -> ObstacleField:
    """Campo vacio (sin evidencia): usado en el primer ciclo o en modo degradado."""
    return ObstacleField(cells=_empty_cells(), dt_s=0.0, timestamp=timestamp, source=source)


# --------------------------------------------------------------------------- #
# Consultas compartidas router / deliberative / fsm                            #
# --------------------------------------------------------------------------- #
# Medio ancho (grados) de la banda de rumbo que se considera "de frente". Fuera
# de esta banda, el waypoint cae en el sector lateral correspondiente.
BEARING_SECTOR_DEG = float(os.getenv("BEARING_SECTOR_DEG", "15.0"))


def sector_towards_waypoint(bearing_err_deg: float) -> str:
    """Sector visual en el que cae el waypoint activo segun el error de rumbo."""
    if bearing_err_deg < -BEARING_SECTOR_DEG:
        return "izquierda"
    if bearing_err_deg > BEARING_SECTOR_DEG:
        return "derecha"
    return "centro"


def has_open_corridor(field: ObstacleField, guidance: Optional[dict] = None) -> bool:
    """True si la percepcion tiene evidencia valida Y ve al menos un sector transitable.

    Existe para que el escape de deadlock (policy_router / deliberative / fsm)
    deje de ser ciego a la percepcion. En el vuelo del 2026-0824 el dron subio
    12 metros seguidos mientras el ObstacleField reportaba `DERECHA: DESPEJADO`
    ciclo tras ciclo: tanto el router como el nodo deliberativo cortocircuitaban
    hacia GANAR_ALTURA por `evasion_stuck_cycles` ANTES de mirar el campo, asi
    que la evidencia de corredor libre no la leia nadie.

    Requiere evidencia real (`has_evidence()` + confianza del sector sobre el
    piso): "sin evidencia" no es lo mismo que "despejado", y un hover sin flujo
    optico produce exactamente ese vacio -- tratarlo como corredor abierto
    desactivaria el escape justo cuando mas hace falta.
    """
    if not field.has_evidence():
        return False

    guidance = guidance or {}
    target = sector_towards_waypoint(float(guidance.get("bearing_err_deg", 0.0)))

    # Se prioriza el sector hacia el waypoint, pero cualquier sector lateral
    # con evidencia y libre tambien rompe el atasco mejor que subir en el lugar.
    for sector in (target, *(s for s in SECTORS if s != target)):
        if field.sector_confidence(sector) < MIN_CONFIDENCE_FOR_BLOCKED:
            continue
        if not field.is_blocked(sector):
            return True
    return False

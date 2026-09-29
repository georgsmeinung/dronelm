"""Analisis offline: ¿la IMU separa los bloqueos/contactos del vuelo normal? (2026-0929)

Uso:
    python experiments/analyze_imu_contact.py <raiz_de_corridas> [--pre 3] [--post 2]

Toma las corridas cuyo JSONL guarda `state.telemetry.imu_*` (solo las recientes).
Etiquetas independientes de los detectores actuales (imu_contact / blind_wall):

  * EVENTO de bloqueo: el dron viene comandado hacia adelante (vx_cmd >= CMD_VX) y la
    velocidad medida cae por debajo de STOP_SPEED durante >= STOP_CYCLES ciclos. El ciclo
    de inicio (t0) es el primero con velocidad < STOP_SPEED.
  * CRUCERO: ciclos comandados hacia adelante con velocidad > CRUISE_SPEED, a mas de
    GUARD ciclos de cualquier evento.

Caracteristicas por ciclo: rms(ax,ay), |az + g|, |omega|, salto de |omega| y caida de
velocidad por ciclo. Se reporta AUC (evento vs crucero) y, con umbral en el percentil 99
del crucero, la tasa de deteccion de eventos y los falsos positivos por 1000 ciclos.
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import sys
from pathlib import Path
from typing import Dict, List, Tuple

G = 9.80665
CMD_VX = 0.8
STOP_SPEED = 0.3
STOP_CYCLES = 3
CRUISE_SPEED = 1.0
GUARD = 15


def _load(path: str) -> List[dict]:
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            try:
                rows.append(json.loads(line))
            except ValueError:
                break
    return rows


def _has_imu(rows: List[dict]) -> bool:
    st = rows[0].get("state") if rows else None
    return bool(st and (st.get("telemetry") or {}).get("imu_linear_acceleration") is not None)


def _features(rows: List[dict]) -> Dict[str, List[float]]:
    n = len(rows)
    f = {k: [0.0] * n for k in ("rms_xy", "az_dev", "w_mag", "w_jump", "v_drop", "speed")}
    prev_w = prev_v = None
    for i, r in enumerate(rows):
        tel = r["state"]["telemetry"]
        la = tel.get("imu_linear_acceleration") or {}
        av = tel.get("imu_angular_velocity") or {}
        vel = r.get("vel") or {}
        v = math.hypot(vel.get("vx", 0.0), vel.get("vy", 0.0))
        w = math.sqrt(sum(float(x) ** 2 for x in av.values())) if av else 0.0
        f["rms_xy"][i] = math.hypot(la.get("ax", 0.0), la.get("ay", 0.0))
        f["az_dev"][i] = abs(abs(la.get("az", -G)) - G)
        f["w_mag"][i] = w
        f["w_jump"][i] = abs(w - prev_w) if prev_w is not None else 0.0
        f["v_drop"][i] = max(0.0, prev_v - v) if prev_v is not None else 0.0
        f["speed"][i] = v
        prev_w, prev_v = w, v
    return f


def _cmd_vx(r: dict) -> float:
    return float(((r.get("state") or {}).get("velocity_command") or {}).get("vx", 0.0) or 0.0)


def _events(rows: List[dict], speed: List[float]) -> List[int]:
    """Indices t0 (primer ciclo detenido) de cada bloqueo estando comandado hacia adelante."""
    ev, i, n = [], 1, len(rows)
    while i < n - STOP_CYCLES:
        moving_cmd = _cmd_vx(rows[i - 1]) >= CMD_VX and speed[i - 1] >= STOP_SPEED
        if moving_cmd and all(speed[i + k] < STOP_SPEED for k in range(STOP_CYCLES)):
            ev.append(i)
            i += 25  # un bloqueo por episodio
        else:
            i += 1
    return ev


def _auc(pos: List[float], neg: List[float]) -> float:
    if not pos or not neg:
        return float("nan")
    allv = sorted([(v, 1) for v in pos] + [(v, 0) for v in neg])
    rank_sum, i = 0.0, 0
    while i < len(allv):
        j = i
        while j + 1 < len(allv) and allv[j + 1][0] == allv[i][0]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        rank_sum += avg * sum(1 for k in range(i, j + 1) if allv[k][1] == 1)
        i = j + 1
    n1, n0 = len(pos), len(neg)
    return (rank_sum - n1 * (n1 + 1) / 2.0) / (n1 * n0)


def _pct(vals: List[float], p: float) -> float:
    s = sorted(vals)
    return s[min(len(s) - 1, int(p * len(s)))] if s else float("nan")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("root")
    ap.add_argument("--pre", type=int, default=3, help="ciclos antes de t0 que entran en la ventana de evento")
    ap.add_argument("--post", type=int, default=2, help="ciclos despues de t0")
    args = ap.parse_args()

    names = ("rms_xy", "az_dev", "w_mag", "w_jump", "v_drop")
    ev_vals: Dict[str, List[float]] = {k: [] for k in names}
    cr_vals: Dict[str, List[float]] = {k: [] for k in names}
    windows: List[Tuple[str, int, Dict[str, List[float]]]] = []
    n_runs = n_cycles = 0
    for path in sorted(glob.glob(str(Path(args.root) / "**" / "*.jsonl"), recursive=True)):
        rows = _load(path)
        if len(rows) < 100 or not _has_imu(rows):
            continue
        n_runs += 1
        n_cycles += len(rows)
        f = _features(rows)
        evs = _events(rows, f["speed"])
        near = set()
        for t0 in evs:
            lo, hi = max(0, t0 - args.pre), min(len(rows) - 1, t0 + args.post)
            near.update(range(max(0, t0 - GUARD), min(len(rows), t0 + GUARD + 25)))
            windows.append((Path(path).parent.name, t0, {k: f[k][lo:hi + 1] for k in names}))
            for i in range(lo, hi + 1):
                for k in names:
                    ev_vals[k].append(f[k][i])
        for i in range(1, len(rows)):
            if i in near:
                continue
            if _cmd_vx(rows[i - 1]) >= CMD_VX and f["speed"][i] > CRUISE_SPEED:
                for k in names:
                    cr_vals[k].append(f[k][i])

    print(f"corridas con IMU: {n_runs} ({n_cycles} ciclos) | eventos de bloqueo: {len(windows)} | "
          f"ciclos de crucero: {len(cr_vals['rms_xy'])} | ciclos en ventana de evento: {len(ev_vals['rms_xy'])}")
    if not windows:
        return 0
    print(f"\n{'caracteristica':<10} {'AUC':>6} | crucero p50/p99/max        | ventana-evento p50/p99/max | umbral(p99 crucero)"
          f" | eventos detectados | FP/1000 ciclos crucero")
    for k in names:
        thr = _pct(cr_vals[k], 0.99)
        det = sum(1 for _, _, w in windows if any(v > thr for v in w[k]))
        fp = 1000.0 * sum(1 for v in cr_vals[k] if v > thr) / max(1, len(cr_vals[k]))
        print(f"{k:<10} {_auc(ev_vals[k], cr_vals[k]):6.2f} | "
              f"{_pct(cr_vals[k], .5):6.3f}/{_pct(cr_vals[k], .99):6.3f}/{max(cr_vals[k]):6.3f} | "
              f"{_pct(ev_vals[k], .5):6.3f}/{_pct(ev_vals[k], .99):6.3f}/{max(ev_vals[k]):6.3f} | "
              f"{thr:8.3f}            | {det:3d}/{len(windows):<3d}            | {fp:6.1f}")
    print("\nAUC 0.5 = sin poder de separacion; >0.8 = util. v_drop es la referencia (velocidad medida).")
    return 0


if __name__ == "__main__":
    sys.exit(main())

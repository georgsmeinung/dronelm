"""Avance hacia el waypoint a los 20 s de cada consulta de la capa estrategica (cap. 10 Sec. 10.6.3).

Metrica declarada en 10.6.3 y no calculada en la corrida v4; sale de las trazas por ciclo (*.jsonl), sin volar.

Evento: una respuesta nueva de la capa estrategica en el brazo slm (state._vlm_strategic con un anchor.ts
distinto del anterior). Resultado: "subgoal" (inserta una sub-meta), "directo_libre" (camino directo libre)
u otro (sin_sector_libre, superada, wp_cambio, ...).

Avance a H segundos (H = 20 por defecto), en el plano horizontal, sobre la RUTA RESTANTE:
    R(t) = d(pos(t), proximo waypoint) + suma de los tramos siguientes de la ruta
    delta = R(t0) - R(t0 + H)
Medir sobre la ruta restante y no contra un waypoint fijo evita topar el avance cuando el waypoint se alcanza
dentro de la ventana. Si la corrida termina antes de t0 + H, delta = R(t0) si la mision se completo; si no,
la ventana se descarta (se cuenta aparte).

Dos rutas de referencia:
  - "manifiesto": solo los waypoints del manifiesto (sin sub-metas ni puntos de paso del plan de ruta). Es la
    referencia primaria: la que mide 10.6.3.
  - "plan": los waypoints del manifiesto mas los puntos de paso del plan de ruta (VIA_*), que es la ruta a la
    que apunta la capa estrategica. En los lotes 1, 2 y 5 (sin plan) coinciden.

Comparaciones (descriptivas):
  - slm, sub-meta  vs  slm, directo_libre (mismas corridas): si avanzar por la sub-meta rinde como avanzar
    por el camino directo cuando la capa lo declara libre.
  - slm (todos los eventos) vs ventanas de fsm:depth, fsm:blind y reactive en el mismo lote, con inicio cada
    STRIDE_S segundos de vuelo (sin capa estrategica).
Las ventanas se superponen y los eventos de una corrida no son independientes: los IC 95 % se calculan por
bootstrap remuestreando corridas (cluster), no eventos.

Uso:
    python experiments/analyze_subgoal_progress.py ../airsim-runs/produccion/v4
    python experiments/analyze_subgoal_progress.py ../airsim-runs/produccion/v4 --horizon 20 --out notebooks/output
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import math
from collections import defaultdict
from pathlib import Path

import numpy as np

LOTE_NUM = {
    "minisim_clear": 1, "townsim_clear": 2, "townsim_ini": 3,
    "townsim_calib_cruce_frontal": 4, "citysim_clear": 5, "citysim_pilot": 6,
}
STRIDE_S = 2.0
MIN_ALT_M = 3.0   # ventanas de los brazos sin capa: solo en vuelo (la capa tampoco consulta en el despegue)


def _is_manifest(w: dict) -> bool:
    return not w.get("is_temporary") and not w.get("planned_via")


def _remaining_labels(wps: list, idx: int) -> set:
    return {w.get("label") for w in wps[idx:]}


def _first(wps: list, idx: int, pred) -> dict | None:
    for w in wps[idx:]:
        if pred(w):
            return w
    return None


def load_trace(path: Path) -> list[dict]:
    """Extrae por ciclo solo lo necesario: t, pos, indice, waypoints (por referencia si no cambian), evento."""
    rows = []
    last_wps_raw = None
    last_wps = None
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            st = d.get("state") or {}
            wps = st.get("waypoints") or []
            raw = json.dumps(wps, sort_keys=True)
            if raw != last_wps_raw:
                last_wps_raw, last_wps = raw, wps
            strat = st.get("_vlm_strategic") or {}
            anchor = strat.get("anchor") or {}
            pos = d.get("pos") or {}
            rows.append({
                "t": float(d["t"]), "x": float(pos.get("x", 0.0)), "y": float(pos.get("y", 0.0)),
                "z": float(pos.get("z", 0.0)),
                "idx": int(st.get("current_wp_index") or 0), "wps": last_wps,
                "ev_ts": anchor.get("ts"), "ev_outcome": strat.get("outcome"),
                "ev_label": anchor.get("wp_label"),
                "done": bool(st.get("mission_completed")),
            })
    return rows


def _is_route(w: dict, ref: str) -> bool:
    return not w.get("is_temporary") and (ref == "plan" or not w.get("planned_via"))


def remaining_route(r: dict, ref: str, legs: dict) -> float | None:
    """R(t): distancia al proximo waypoint de la ruta `ref` mas los tramos siguientes. 0 si no queda ninguno."""
    nxt = _first(r["wps"], r["idx"], lambda w: _is_route(w, ref))
    if nxt is None or r["done"]:
        return 0.0
    tail = legs[ref].get(nxt.get("label"))
    if tail is None:
        return None
    return math.hypot(float(nxt["x"]) - r["x"], float(nxt["y"]) - r["y"]) + tail


def route_legs(wps: list) -> dict:
    """{ref: {label: longitud de la ruta desde ese waypoint hasta el final}} con la lista inicial de waypoints."""
    out = {}
    for ref in ("manifiesto", "plan"):
        route = [w for w in wps if _is_route(w, ref)]
        acc, tails = 0.0, {}
        for k in range(len(route) - 1, -1, -1):
            tails[route[k].get("label")] = acc
            if k > 0:
                acc += math.hypot(float(route[k]["x"]) - float(route[k - 1]["x"]),
                                  float(route[k]["y"]) - float(route[k - 1]["y"]))
        out[ref] = tails
    return out


def window_delta(rows: list[dict], i0: int, ref: str, legs: dict, horizon: float) -> float | None:
    r0 = rows[i0]
    R0 = remaining_route(r0, ref, legs)
    if R0 is None:
        return None
    t_end = r0["t"] + horizon
    for r in rows[i0 + 1:]:
        if r["done"]:
            return R0
        if r["t"] >= t_end:
            R1 = remaining_route(r, ref, legs)
            return None if R1 is None else R0 - R1
    return None


def _cell(path: Path, root: Path) -> tuple[str, str, str]:
    parts = path.relative_to(root).parts
    # loteN_<escenario>/<escenario>/<brazo>/<estrategia>/seed_*/seed_*.jsonl  (reactive sin estrategia)
    scenario = parts[1]
    arm = parts[2]
    # reactive se guarda bajo reactive/depth/ pero no usa la estrategia de bloqueo: la celda es "reactive"
    strat = parts[3] if arm != "reactive" and not parts[3].startswith("seed_") else ""
    return scenario, arm, (f"{arm}:{strat}" if strat else arm)


def analyze_run(path: Path, root: Path, horizon: float) -> list[dict]:
    scenario, arm, cell = _cell(path, root)
    rows = load_trace(path)
    if not rows:
        return []
    legs = route_legs(rows[0]["wps"])
    out = []
    base = {"lote": LOTE_NUM.get(scenario), "escenario": scenario, "celda": cell,
            "corrida": path.parent.name}
    if arm == "slm":
        seen = None
        for i, r in enumerate(rows):
            ts = r["ev_ts"]
            if ts is None or ts == seen:
                continue
            seen = ts
            for ref in ("manifiesto", "plan"):
                out.append({**base, "t0": r["t"], "tipo": r["ev_outcome"], "referencia": ref,
                            "objetivo": r["ev_label"], "delta_m": window_delta(rows, i, ref, legs, horizon)})
    # Ventanas cada STRIDE_S s en todos los brazos (slm incluido): la capa no consulta durante el barrido de
    # bloqueos, de modo que sus eventos excluyen los peores tramos; las ventanas no, y son las comparables.
    if True:
        next_t = None
        for i, r in enumerate(rows):
            if abs(r["z"]) < MIN_ALT_M or r["done"]:
                continue
            if next_t is not None and r["t"] < next_t:
                continue
            next_t = r["t"] + STRIDE_S
            for ref in ("manifiesto", "plan"):
                out.append({**base, "t0": r["t"], "tipo": "ventana", "referencia": ref, "objetivo": "",
                            "delta_m": window_delta(rows, i, ref, legs, horizon)})
    return out


def cluster_boot(groups: dict[str, list[float]], stat, n_boot: int = 4000, seed: int = 0):
    keys = sorted(k for k, v in groups.items() if len(v))  # orden fijo: IC reproducibles
    if not keys:
        return float("nan"), (float("nan"), float("nan"))
    point = stat(np.concatenate([groups[k] for k in keys]))
    rng = np.random.default_rng(seed)
    bs = []
    for _ in range(n_boot):
        pick = rng.choice(len(keys), size=len(keys), replace=True)
        bs.append(stat(np.concatenate([groups[keys[j]] for j in pick])))
    lo, hi = np.percentile(bs, [2.5, 97.5])
    return float(point), (float(lo), float(hi))


def summarize(events: list[dict]) -> list[dict]:
    valid = [e for e in events if e["delta_m"] is not None]
    keyf = lambda e: (e["lote"], e["celda"], e["referencia"],
                      "subgoal" if e["tipo"] == "subgoal" else
                      "directo_libre" if e["tipo"] == "directo_libre" else
                      "ventana" if e["tipo"] == "ventana" else "otro")
    buckets = defaultdict(lambda: defaultdict(list))
    for e in valid:
        buckets[keyf(e)][e["corrida"]].append(e["delta_m"])
    # slm, todos los eventos (para comparar con las ventanas de los brazos sin capa)
    for e in valid:
        if e["celda"].startswith("slm"):
            k = keyf(e)
            buckets[(k[0], k[1], k[2], "todos")][e["corrida"]].append(e["delta_m"])
    dropped = defaultdict(int)
    for e in events:
        if e["delta_m"] is None:
            dropped[keyf(e)] += 1
    rows = []
    for k in sorted(buckets, key=lambda k: (k[0] or 0, k[1], k[2], k[3])):
        g = {c: np.asarray(v, float) for c, v in buckets[k].items()}
        n = sum(len(v) for v in g.values())
        med, med_ci = cluster_boot(g, np.median)
        pos, pos_ci = cluster_boot(g, lambda a: float(np.mean(a > 0)))
        rows.append({"lote": k[0], "celda": k[1], "referencia": k[2], "tipo": k[3], "corridas": len(g),
                     "n": n, "descartadas": dropped.get(k, 0) if k[3] != "todos" else "",
                     "mediana_m": round(med, 2), "ic_mediana": f"[{med_ci[0]:.2f}, {med_ci[1]:.2f}]",
                     "frac_avanza": round(pos, 3), "ic_frac": f"[{pos_ci[0]:.2f}, {pos_ci[1]:.2f}]"})
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description="Avance a H s de cada consulta de la capa estrategica (10.6.3)")
    ap.add_argument("root", help="Raiz de la corrida v4 (airsim-runs/produccion/v4)")
    ap.add_argument("--horizon", type=float, default=20.0)
    ap.add_argument("--out", default="notebooks/output")
    args = ap.parse_args()
    root = Path(args.root)
    paths = []
    for p in glob.glob(str(root / "lote*" / "**" / "seed_*.jsonl"), recursive=True):
        pp = Path(p)
        if {"pilotos", "descarte"} & set(pp.relative_to(root).parts):
            continue
        paths.append(pp)
    print(f"corridas: {len(paths)}")
    events = []
    for k, p in enumerate(sorted(paths), 1):
        events.extend(analyze_run(p, root, args.horizon))
        if k % 20 == 0:
            print(f"  {k}/{len(paths)}")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    tag = f"{int(args.horizon)}s"
    with open(out / f"v4_avance_submeta_eventos_{tag}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(events[0].keys()))
        w.writeheader()
        w.writerows(events)
    summ = summarize(events)
    with open(out / f"v4_avance_submeta_{tag}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(summ[0].keys()))
        w.writeheader()
        w.writerows(summ)
    print("| Lote | Celda | Ref. | Tipo | Corridas | n | Desc. | Mediana (m) [IC] | Frac. avanza [IC] |")
    print("|---|---|---|---|---|---|---|---|---|")
    for r in summ:
        print(f"| {r['lote']} | {r['celda']} | {r['referencia']} | {r['tipo']} | {r['corridas']} | {r['n']} | "
              f"{r['descartadas']} | {r['mediana_m']} {r['ic_mediana']} | {r['frac_avanza']} {r['ic_frac']} |")


if __name__ == "__main__":
    main()

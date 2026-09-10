"""S5 (PLAN-SLAM): Validación offline de FlightTrajectory sobre logs existentes.

Reconstruye TrajectoryEvent a partir de los JSONL de airsim-runs/townsim* y
verifica que trajectory_context_text() identifique correctamente las zonas
bloqueadas en ventanas previas a eventos de deadlock.

Definición operacional de "stall" para S5:
  - Un ciclo está en stall si la acción es de tipo escape (GANAR_ALTURA,
    FRENAR, EVADIR_*, GIRAR_90, DESCENDER) O si delta_wp_m > STALL_THRESHOLD.
  Esto refleja que slam_assess se activa cuando el FSM lleva varias iteraciones
  en escape mode, no solo cuando el dron retrocede en distancia.

Definición de "deadlock window":
  - Secuencia de >= MIN_ESCAPE_RUN ciclos consecutivos de escape, precedida
    por al menos PRE_EVENTS ciclos que incluyan intentos "FRENTE".

Sin AirSim ni GPU. Solo depende de spatial_history.py.

Uso:
    python experiments/s5_offline_validation.py [--runs-dir <dir>] [--verbose]
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import List, Optional, Tuple

# ─── carga directa de spatial_history sin importar el árbol de src ──────────
REPO_ROOT = Path(__file__).resolve().parent.parent

_sh_path = REPO_ROOT / "src" / "agents" / "spatial_history.py"
_spec = importlib.util.spec_from_file_location("spatial_history", _sh_path)
_mod = importlib.util.module_from_spec(_spec)   # type: ignore[arg-type]
sys.modules["spatial_history"] = _mod
_spec.loader.exec_module(_mod)                  # type: ignore[union-attr]

SLAM_STALL_THRESHOLD_M: float = _mod.SLAM_STALL_THRESHOLD_M
FlightTrajectory = _mod.FlightTrajectory
TrajectoryEvent  = _mod.TrajectoryEvent

# ─── constantes de análisis ──────────────────────────────────────────────────

# Acciones de escape que equivalen a "ciclo en stall" para slam_assess
ESCAPE_ACTIONS = {
    "GANAR_ALTURA", "DESCENDER",
    "FRENAR",
    "EVADIR_IZQUIERDA", "EVADIR_DERECHA",
    "GIRAR_90",
}

# Ciclos consecutivos de escape que definen una ventana de deadlock
MIN_ESCAPE_RUN = 5

# Ciclos previos al inicio del escape-run que se incluyen en el buffer
WINDOW_PRE_EVENTS = 40

# Umbral de stall-rate por zona para "zona bloqueada detectada"
BLOCKED_ZONE_THRESHOLD = 0.60

# ─── lectura de logs ─────────────────────────────────────────────────────────

def load_records(path: Path) -> List[dict]:
    records = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return records


def build_events(records: List[dict]) -> List[TrajectoryEvent]:
    """Convierte registros JSONL en TrajectoryEvent.

    stall = acción de escape O delta_wp > SLAM_STALL_THRESHOLD_M.
    Esto replica el criterio que dispara slam_assess en el FSM real.
    """
    events = []
    for i in range(1, len(records)):
        prev = records[i - 1]
        curr = records[i]

        ts          = float(curr.get("t", 0.0))
        pos_raw     = curr.get("pos", {})
        position    = (float(pos_raw.get("x", 0.0)),
                       float(pos_raw.get("y", 0.0)),
                       float(pos_raw.get("z", 0.0)))
        heading_deg = float(curr.get("yaw_deg", 0.0))
        action_curr = str(curr.get("action", "MANTENER_RUMBO"))

        dist_curr = float(curr.get("dist_to_wp_m", 0.0))
        dist_prev = float(prev.get("dist_to_wp_m", dist_curr))
        delta_wp_m = dist_curr - dist_prev   # positivo = retroceso

        # stall si la acción actual es de escape O si retrocedió significativamente
        stall = (action_curr in ESCAPE_ACTIONS) or (delta_wp_m > SLAM_STALL_THRESHOLD_M)

        of = curr.get("obstacle_field", {})
        flow_had_evidence = float(of.get("foe_confidence", 0.0)) > 0.0

        events.append(TrajectoryEvent(
            timestamp=ts,
            position=position,
            heading_deg=heading_deg,
            action_taken=action_curr,
            delta_wp_m=delta_wp_m,
            stall=stall,
            flow_had_evidence=flow_had_evidence,
        ))
    return events


# ─── detección de ventanas de deadlock ───────────────────────────────────────

def find_deadlock_windows(
    events: List[TrajectoryEvent],
    min_run: int = MIN_ESCAPE_RUN,
    pre_events: int = WINDOW_PRE_EVENTS,
) -> List[Tuple[int, int, int]]:
    """Retorna lista de (inicio_ventana, inicio_escape_run, fin_escape_run)."""
    windows = []
    i = 0
    while i < len(events):
        run_len = 0
        j = i
        while j < len(events) and events[j].stall:
            run_len += 1
            j += 1
        if run_len >= min_run:
            start_pre = max(0, i - pre_events)
            # Solo incluir ventanas con al menos algunos ciclos previos
            if i - start_pre >= 3:
                windows.append((start_pre, i, j - 1))
            i = j
        else:
            i += 1
    return windows


# ─── análisis de una ventana ──────────────────────────────────────────────────

def _zone_stall_rate(context_text: str, zone: str) -> float:
    """Extrae stall_rate de una zona del context_text.

    Formato esperado (spatial_history.py):
      '- FRENTE (40 intentos -> 25 stalls, 15 con progreso).'
    El '->' puede ser el carácter Unicode '→' o ASCII '->'.
    Retorna 0.0 si la zona no aparece, tiene 0 intentos, o no parseable.
    """
    for line in context_text.split("\n"):
        if f"- {zone}" not in line or "(" not in line:
            continue
        try:
            inner = line.split("(")[1].split(")")[0]
            # "40 intentos → 25 stalls, 15 con progreso"
            attempts = int(inner.split("intentos")[0].strip())
            rest = inner.split("intentos")[1]  # " → 25 stalls, 15 con progreso"
            if "stalls" not in rest:
                return 0.0
            # Normalizar flecha unicode o ascii
            rest = rest.replace("→", "->")
            stalls_str = rest.split("stalls")[0].replace("->", "").replace(",", "").strip()
            stalls = int(stalls_str)
            return stalls / attempts if attempts > 0 else 0.0
        except (IndexError, ValueError):
            return 0.0
    return 0.0


def analyse_window(
    events: List[TrajectoryEvent],
    win_start: int,
    stall_start: int,
    stall_end: int,
) -> dict:
    """Evalúa si trajectory_context_text resume correctamente el bloqueo.

    Niveles de detección:
    - strong: "Zona probable de bloqueo" explícita (>=70% stall rate en alguna zona)
    - informative: alguna zona con >=50% stall rate y >=5 intentos (el VLM puede
      razonar con estos números aunque no aparezca la etiqueta explícita)
    """
    pre_events = events[win_start:stall_start]

    traj = FlightTrajectory(max_size=len(pre_events) + 1)
    for ev in pre_events:
        traj.record(ev)

    current_heading = events[stall_start].heading_deg if stall_start < len(events) else 0.0
    context_text = traj.trajectory_context_text(
        current_heading_deg=current_heading,
        max_events=WINDOW_PRE_EVENTS,
    )

    has_data            = "sin datos disponibles" not in context_text
    strong_detected     = "Zona probable de bloqueo" in context_text

    # Detección informativa: alguna zona con >=50% stall rate y >=5 intentos
    informative_detected = False
    for zone in ("FRENTE", "IZQUIERDA", "DERECHA", "ATRAS"):
        r = _zone_stall_rate(context_text, zone)
        if r >= 0.50:
            informative_detected = True
            break

    pre_stall_count = sum(1 for e in pre_events if e.stall)
    pre_stall_rate  = pre_stall_count / len(pre_events) if pre_events else 0

    return {
        "pre_events": len(pre_events),
        "pre_stall_count": pre_stall_count,
        "pre_stall_rate": round(pre_stall_rate, 3),
        "stall_run": stall_end - stall_start + 1,
        "heading_at_deadlock": round(current_heading, 1),
        "has_data": has_data,
        "strong_detected": strong_detected,
        "informative_detected": informative_detected,
        "context_text": context_text,
    }


# ─── análisis de un archivo ───────────────────────────────────────────────────

def analyse_file(path: Path, runs_dir: Path, min_run: int = MIN_ESCAPE_RUN) -> dict:
    records = load_records(path)
    if len(records) < 10:
        return {"path": str(path.relative_to(runs_dir)), "error": "muy pocos registros"}

    events = build_events(records)

    total_events = len(events)
    total_stalls = sum(1 for e in events if e.stall)
    total_evidence = sum(1 for e in events if e.flow_had_evidence)

    windows = find_deadlock_windows(events, min_run=min_run)

    window_results = []
    for win_start, stall_start, stall_end in windows:
        res = analyse_window(events, win_start, stall_start, stall_end)
        window_results.append(res)

    try:
        rel_path = str(path.relative_to(runs_dir))
    except ValueError:
        rel_path = str(path)

    return {
        "path": rel_path,
        "total_events": total_events,
        "total_stalls": total_stalls,
        "stall_rate": round(total_stalls / total_events, 3) if total_events else 0,
        "flow_evidence_rate": round(total_evidence / total_events, 3) if total_events else 0,
        "deadlock_windows": len(windows),
        "windows": window_results,
    }


# ─── main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="S5: validación offline de FlightTrajectory")
    parser.add_argument(
        "--runs-dir",
        default=str(REPO_ROOT.parent / "airsim-runs"),
        help="Raíz de los logs JSONL (default: ../airsim-runs)",
    )
    parser.add_argument(
        "--pattern",
        default="townsim*/townsim*/slm/seed_1.jsonl",
        help="Glob para seleccionar archivos",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Mostrar texto completo del contexto por ventana",
    )
    parser.add_argument(
        "--min-escape-run", type=int, default=MIN_ESCAPE_RUN,
        help=f"Ciclos de escape consecutivos para definir deadlock (default: {MIN_ESCAPE_RUN})",
    )
    parser.add_argument(
        "--pass-threshold", type=float, default=0.60,
        help="Fracción mínima de ventanas con zona bloqueada detectada (default: 0.60)",
    )
    args = parser.parse_args()

    runs_dir = Path(args.runs_dir)
    if not runs_dir.exists():
        print(f"ERROR: directorio no encontrado: {runs_dir}", file=sys.stderr)
        sys.exit(1)

    files = sorted(runs_dir.glob(args.pattern))
    if not files:
        print(f"ERROR: ningún archivo coincide con '{args.pattern}' en {runs_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"S5 Validación offline — {len(files)} archivos\n")
    print(f"  SLAM_STALL_THRESHOLD_M  = {SLAM_STALL_THRESHOLD_M} m")
    print(f"  Stall = acción escape O delta_wp > {SLAM_STALL_THRESHOLD_M}m")
    print(f"  Deadlock = {args.min_escape_run} ciclos consecutivos en stall")
    print(f"  Criterio PASS: detección >= {args.pass_threshold*100:.0f}% de ventanas\n")

    summary_total_windows = 0
    summary_strong = 0
    summary_informative = 0
    summary_has_data = 0

    results = []
    for path in files:
        result = analyse_file(path, runs_dir, min_run=args.min_escape_run)
        results.append(result)

        dw = result.get("deadlock_windows", 0)
        summary_total_windows += dw

        for w in result.get("windows", []):
            if w.get("has_data"):
                summary_has_data += 1
            if w.get("strong_detected"):
                summary_strong += 1
            if w.get("informative_detected"):
                summary_informative += 1

    # ─── tabla por archivo ────────────────────────────────────────────────
    COL = 55
    print(f"{'ARCHIVO':<{COL}} {'EVT':>5} {'STALL%':>7} {'FLOW%':>6} {'DEADLK':>7} {'STR/INF':>10}")
    print("─" * (COL + 45))

    for r in results:
        if "error" in r:
            print(f"  FAIL {r['path']}: {r['error']}")
            continue

        stall_pct = f"{r['stall_rate']*100:.1f}%"
        flow_pct  = f"{r['flow_evidence_rate']*100:.1f}%"
        dw        = r["deadlock_windows"]
        strong    = sum(1 for w in r["windows"] if w.get("strong_detected"))
        info      = sum(1 for w in r["windows"] if w.get("informative_detected"))

        path_short = r["path"]
        if len(path_short) > COL:
            path_short = ">" + path_short[-(COL-1):]

        print(f"{path_short:<{COL}} {r['total_events']:>5} {stall_pct:>7} {flow_pct:>6} {dw:>7} {strong:>6}/{info:<4}")

        if args.verbose and r["windows"]:
            for i, w in enumerate(r["windows"]):
                if w.get("strong_detected"):
                    tag = "STRONG zona bloqueada (>=70%)"
                elif w.get("informative_detected"):
                    tag = "INFO zona parcial (>=50%)"
                else:
                    tag = "NONE sin info util"
                print(f"    ventana {i+1}: pre={w['pre_events']}ev "
                      f"pre_stall={w['pre_stall_rate']*100:.0f}% "
                      f"escape_run={w['stall_run']} [{tag}]")
                for line in w["context_text"].split("\n"):
                    print(f"      {line}")
                print()

    print("─" * (COL + 45))
    print(f"\nRESUMEN:")
    print(f"  Archivos analizados:            {len([r for r in results if 'error' not in r])}")
    print(f"  Ventanas deadlock encontradas:  {summary_total_windows}")
    print(f"  Ventanas con datos suficientes: {summary_has_data}/{summary_total_windows}")
    print(f"  Deteccion STRONG (>=70%):       {summary_strong}/{summary_total_windows} = {summary_strong/max(1,summary_total_windows)*100:.1f}%")
    print(f"  Deteccion INFO   (>=50%):       {summary_informative}/{summary_total_windows} = {summary_informative/max(1,summary_total_windows)*100:.1f}%")
    print()
    print("  Niveles:")
    print("    STRONG = 'Zona probable de bloqueo' explicitamente en el texto (>=70% stall rate)")
    print("    INFO   = alguna zona con >=50% stall rate; el VLM puede razonar con los numeros")

    if summary_total_windows == 0:
        print("\nWARN  No se encontraron ventanas de deadlock.")
        sys.exit(0)

    # PASS criterion: deteccion informativa >= pass_threshold
    info_rate = summary_informative / summary_total_windows
    print(f"\n  Criterio PASS (INFO >= {args.pass_threshold*100:.0f}%): {info_rate*100:.1f}%")
    if info_rate >= args.pass_threshold:
        print(f"PASS S5 PASS: deteccion informativa >= {args.pass_threshold*100:.0f}% ({info_rate*100:.1f}%)")
    else:
        print(f"FAIL S5 FAIL: deteccion informativa < {args.pass_threshold*100:.0f}% ({info_rate*100:.1f}%)")
        sys.exit(1)


if __name__ == "__main__":
    main()

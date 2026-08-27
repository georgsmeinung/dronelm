"""F3.3: runner batch headless para comparar los 3 brazos (slm/fsm/reactive).

N misiones x M escenarios x K semillas, sin ventana cv2 ni stream_hub.
Escribe un JSONL por corrida via FlightLogger.

Uso:
    python experiments/runner.py --scenarios missions/manhattan_a.json missions/manhattan_b.json \
        --arms slm fsm reactive --seeds 1 2 3 --out-dir runs/

Cada archivo de escenario es un manifiesto con el mismo formato que consume
main.py (mission_id, waypoints, rules_of_engagement, pose inicial opcional
"start_pose": {"x":.., "y":.., "z":.., "yaw_deg":..}).
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from pathlib import Path

# Jitter reproducible del start_pose por semilla (2026-0824): AIRSIM_SEED no
# perturbaba nada -- se pasaba a FlightLogger solo como etiqueta del archivo.
# Sin una fuente de variacion real, "seed 1" y "seed 2" con brazos
# deterministas (fsm/reactive) producian trayectorias practicamente
# identicas, y Mann-Whitney U no tenia con que comparar entre semillas.
SEED_JITTER_XY_M = 1.5
SEED_JITTER_YAW_DEG = 10.0

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass


def run_one(scenario_path: str, arm: str, seed: int, out_dir: str, max_cycles: int, max_seconds: float) -> dict:
    os.environ["AGENT_ARM"] = arm
    os.environ["AIRSIM_SEED"] = str(seed)

    # Import diferido: AGENT_ARM se lee a nivel de modulo en graph.py, asi que
    # cada corrida necesita un interprete/subproceso propio para que el valor
    # tome efecto de forma limpia. Este runner asume que se invoca UNA
    # combinacion (arm, seed, escenario) por proceso; ver el bucle en main()
    # mas abajo, que lanza un subproceso por corrida.
    from src.agents.graph import compile_workflow
    from src.hardware import AirSimClient
    from src.logging import FlightLogger
    from src.navigation import WaypointTracker

    with open(scenario_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    scenario_name = Path(scenario_path).stem
    out_path = Path(out_dir) / scenario_name / arm / f"seed_{seed}.jsonl"

    loop_hz = float(os.getenv("LOOP_HZ", "5.0"))
    depth_metric_every_n = int(os.getenv("DEPTH_METRIC_EVERY_N", "5"))  # G3.1: capturar depth cada N ciclos
    client = AirSimClient(loop_hz=loop_hz)
    client.connect()
    # Limpia colision/velocidad/estado del controlador interno que pudiera
    # haber quedado de una corrida anterior en el mismo proceso de AirSim
    # (ver PLAN-MEJORAS.md F3.3: "client.reset()" antes de reposicionar).
    client.reset()

    start_pose = manifest.get("start_pose")
    if start_pose:
        rng = random.Random(seed)
        jitter_x = rng.uniform(-SEED_JITTER_XY_M, SEED_JITTER_XY_M)
        jitter_y = rng.uniform(-SEED_JITTER_XY_M, SEED_JITTER_XY_M)
        jitter_yaw = rng.uniform(-SEED_JITTER_YAW_DEG, SEED_JITTER_YAW_DEG)
        client.set_vehicle_pose(
            start_pose.get("x", 0.0) + jitter_x, start_pose.get("y", 0.0) + jitter_y, start_pose.get("z", -10.0),
            yaw_deg=start_pose.get("yaw_deg", 0.0) + jitter_yaw,
        )

    graph, service = compile_workflow(client)
    waypoints_list = manifest.get("waypoints", [])
    tracker = WaypointTracker(waypoints_list)
    logger = FlightLogger(str(out_path), scenario=scenario_name, seed=seed, arm=arm)

    # Healthcheck del SLM antes de empezar (G1.2).
    if arm == "slm":
        local_llm_url = os.getenv("LOCAL_LLM_URL", "http://localhost:11434/v1")
        try:
            import httpx
            with httpx.Client(timeout=5.0) as http_client:
                resp = http_client.get(f"{local_llm_url.rstrip('/')}/models")
                if resp.status_code != 200:
                    raise RuntimeError(f"SLM retornó {resp.status_code}")
        except Exception as exc:
            raise RuntimeError(f"SLM healthcheck falló: {exc}. Verificar LOCAL_LLM_URL={local_llm_url}")

    state = {
        "waypoints": waypoints_list, "current_wp_index": 0, "target_waypoint": None,
        "waypoint_guidance": {}, "mission_completed": False, "rgb_image": None,
        "telemetry": {}, "frame_history": [],
        "estimated_ttc": float("inf"), "next_action": "", "flight_status": "vuelo",
        "deliberations": [], "active_maneuver": None, "maneuver_cycles_left": 0,
        "maneuver_command": None, "evasion_stuck_cycles": 0, "slm_request_id": None,
    }

    sleep_s = 1.0 / loop_hz
    t_start = time.time()
    cycles = 0
    success = False
    try:
        while cycles < max_cycles and (time.time() - t_start) < max_seconds:
            cycles += 1
            t0 = time.time()
            telem = client.get_telemetry()
            pos = telem.get("position", {})
            yaw = telem.get("orientation", {}).get("yaw", 0.0)
            target_wp = tracker.update(pos)
            guidance = tracker.compute_guidance(pos, yaw)
            state["current_wp_index"] = tracker.current_index
            # Fix 1 (2026-0824): frenar a proposito mientras se espera al SLM
            # (dentro del watchdog) no cuenta como "sin progresar" -- ver
            # _deliberation_pending en deliberative.py. Fix 2: distancia
            # HORIZONTAL, no 3D -- subir para escapar de un atasco no debe
            # empeorar mecanicamente la metrica que decide si el atasco se
            # resolvio (los waypoints estan a altitud constante).
            if not state.get("_deliberation_pending", False):
                tracker.record_progress(
                    guidance.get("dist_xy", guidance.get("distance", 0.0)),
                    bearing_err_deg=guidance.get("bearing_err_deg", 0.0),
                )

            state["target_waypoint"] = target_wp
            state["waypoint_guidance"] = guidance
            state["mission_completed"] = tracker.is_completed
            state["telemetry"] = telem
            state["evasion_stuck_cycles"] = tracker.progress_stall_cycles

            state = graph.invoke(state)
            if state.pop("_escape_reset", False):
                tracker.reset_progress()

            field = state.get("obstacle_field")

            # G3.1: Capturar profundidad cada N ciclos para métrica min_obstacle_dist_m.
            # Solo para observabilidad (no realimenta control). Captura adicional sin
            # impactar hot path si depth_metric_every_n es suficientemente grande (default 5).
            min_obstacle_dist_m = None
            if depth_metric_every_n > 0 and cycles % depth_metric_every_n == 0:
                try:
                    _, depth, _ = client.capture(return_depth=True)
                    if depth is not None:
                        h, w = depth.shape[:2]
                        center = depth[h // 3: 2 * h // 3, w // 3: 2 * w // 3]
                        if center.size > 0:
                            min_obstacle_dist_m = float(__import__("numpy").percentile(center, 5))
                except Exception:
                    pass  # Si falla la captura de depth, solo no registramos la métrica

            logger.log_cycle(state, latency_ms={"graph": (time.time() - t0) * 1000.0}, min_obstacle_dist_m=min_obstacle_dist_m)

            if telem.get("collision", {}).get("has_collided"):
                break

            if tracker.is_completed and waypoints_list:
                success = True
                break

            time.sleep(max(0.0, sleep_s - (time.time() - t0)))
    finally:
        logger.mark_success(success)
        summary = logger.close()
        service.stop()
        try:
            client.land()
        except Exception:
            pass
        client.disconnect()

    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenarios", nargs="+", required=True)
    parser.add_argument("--arms", nargs="+", default=["slm", "fsm", "reactive"])
    parser.add_argument("--seeds", nargs="+", type=int, default=[1, 2, 3])
    parser.add_argument("--out-dir", default="runs")
    parser.add_argument("--max-cycles", type=int, default=2000)
    parser.add_argument("--max-seconds", type=float, default=300.0)
    args = parser.parse_args()

    # Cada combinacion corre en un subproceso propio: AGENT_ARM se lee a
    # nivel de modulo en graph.py al importar, asi que reusar el mismo
    # interprete para multiples brazos en la misma corrida arrastraria el
    # primer valor. Ademas aisla crashes de una corrida del resto del batch.
    import subprocess

    results = []
    for scenario in args.scenarios:
        for arm in args.arms:
            for seed in args.seeds:
                print(f"[runner] scenario={scenario} arm={arm} seed={seed}")
                cmd = [
                    sys.executable, __file__, "--_single",
                    "--scenario", scenario, "--arm", arm, "--seed", str(seed),
                    "--out-dir", args.out_dir, "--max-cycles", str(args.max_cycles),
                    "--max-seconds", str(args.max_seconds),
                ]
                proc = subprocess.run(cmd, capture_output=True, text=True)
                if proc.returncode != 0:
                    print(f"[runner] FALLO scenario={scenario} arm={arm} seed={seed}:\n{proc.stderr[-2000:]}")
                else:
                    print(proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else "[runner] ok")
                results.append({"scenario": scenario, "arm": arm, "seed": seed, "returncode": proc.returncode})

    print(f"\n[runner] {len(results)} corridas completadas. Ver {args.out_dir}/ para los JSONL y usar experiments/analyze.py.")


def _single_main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--_single", action="store_true")
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--arm", required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--out-dir", default="runs")
    parser.add_argument("--max-cycles", type=int, default=2000)
    parser.add_argument("--max-seconds", type=float, default=300.0)
    args = parser.parse_args()
    summary = run_one(args.scenario, args.arm, args.seed, args.out_dir, args.max_cycles, args.max_seconds)
    print(f"[runner] summary: {json.dumps(summary)}")


if __name__ == "__main__":
    if "--_single" in sys.argv:
        _single_main()
    else:
        main()

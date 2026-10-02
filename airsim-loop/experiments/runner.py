"""F3.3: runner batch headless para comparar los 3 brazos (slm/fsm/reactive).

N misiones x M escenarios x K semillas, sin ventana cv2 ni overhead de UI.
Escribe un JSONL por corrida via FlightLogger.

Uso:
    python experiments/runner.py --scenarios ../airsim-plan/missions/flightplans/minisim_clear.json ../airsim-plan/missions/flightplans/citysim_clear.json \
        --arms slm fsm reactive --seeds 1 2 3 --out-dir runs/

Cada archivo de escenario es el manifiesto unico de airsim-plan/missions/flightplans/
(2026-0828, ver CHANGELOG.md): mission_id en MAYUSCULAS, waypoints, y
opcionalmente "start_pose": {"x":.., "y":.., "z":.., "yaw_deg":..} -- si no
esta declarado, se usa el primer waypoint como pose de partida.
"""
from __future__ import annotations

import argparse
from collections import deque
import json
import math
import os
import random
import sys
import time
from datetime import datetime
from pathlib import Path

# Jitter reproducible del start_pose por semilla (2026-0824): AIRSIM_SEED no
# perturbaba nada -- se pasaba a FlightLogger solo como etiqueta del archivo.
# Sin una fuente de variacion real, "seed 1" y "seed 2" con brazos
# deterministas (fsm/reactive) producian trayectorias practicamente
# identicas, y Mann-Whitney U no tenia con que comparar entre semillas.
SEED_JITTER_XY_M = 1.5
# Espera maxima (s) al cierre ordenado de una corrida tras Ctrl+C.
CLOSE_WAIT_S = float(os.getenv("RUNNER_CLOSE_WAIT_S", "180"))
# Congelamiento fisico (dron incrustado en la malla): "abort" (default, integridad del experimento) o
# "teleport" (vuelve a la ultima pose libre anterior al bloqueo, registra el contacto y sigue; queda
# marcado en el log como evento freeze_recovery y en el summary como freeze_recoveries).
FREEZE_RECOVERY = os.getenv("FREEZE_RECOVERY", "abort").lower()
FREEZE_MAX_RECOVERIES = int(os.getenv("FREEZE_MAX_RECOVERIES", "2"))
FREEZE_BACKOFF_CYCLES = int(os.getenv("FREEZE_BACKOFF_CYCLES", "30"))
# Ciclos seguidos en `Landed` que disparan el rearmado (5 Hz -> ~3 s).
LANDED_STREAK_MAX = int(os.getenv("LANDED_STREAK_MAX", "15"))


class _Tee:
    """Escribe en el stream original y en un archivo (consola de la corrida)."""

    def __init__(self, stream, fh):
        self._stream, self._fh = stream, fh

    def write(self, data):
        self._stream.write(data)
        try:
            self._fh.write(data)
            self._fh.flush()
        except Exception:
            pass
        return len(data)

    def flush(self):
        self._stream.flush()

    def __getattr__(self, name):
        return getattr(self._stream, name)


def _tee_console(path):
    """Duplica stdout/stderr a `path`; devuelve la funcion que restaura los streams."""
    fh = open(path, "w", encoding="utf-8", errors="replace")
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = _Tee(old_out, fh), _Tee(old_err, fh)

    def _restore():
        sys.stdout, sys.stderr = old_out, old_err
        fh.close()
    return _restore
SEED_JITTER_YAW_DEG = 10.0


def _ts() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from pathlib import Path
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[2] / "config" / ".env")
except Exception:
    pass


def run_one(
    scenario_path: str,
    arm: str,
    seed: int,
    out_dir: str,
    max_cycles: int,
    max_seconds: float,
    seed_jitter: bool = False,
    deadlock_strategy: str = "deep_vlm",  # 2026-0930: slam_assess movido a legacy (sin evidencia)
    record_video: bool = True,
    record_viewport: bool = False,
    record_follow: bool = True,
) -> dict:
    os.environ["AGENT_ARM"] = arm
    os.environ["AIRSIM_SEED"] = str(seed)
    # Segunda variable del factorial (deep_vlm | blind), leida a nivel de modulo por src/agents/deep_scan.py.
    # Cada combinacion corre en su propio subproceso (ver main() mas abajo).
    os.environ["DEADLOCK_STRATEGY"] = deadlock_strategy

    # Import diferido: AGENT_ARM se lee a nivel de modulo en graph.py, asi que
    # cada corrida necesita un interprete/subproceso propio para que el valor
    # tome efecto de forma limpia. Este runner asume que se invoca UNA
    # combinacion (arm, seed, escenario) por proceso; ver el bucle en main()
    # mas abajo, que lanza un subproceso por corrida.
    from src.agents.graph import compile_workflow
    from src.navigation.freeze_watchdog import FreezeWatchdog, pick_recovery_pose
    from src.hardware import AirSimClient
    from src.logging import FlightLogger
    from src.navigation import WaypointTracker

    with open(scenario_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    scenario_name = Path(scenario_path).stem
    iso_ts = datetime.now().strftime("%Y%m%dT%H%M%SZ")
    # 2026-0929: un directorio por corrida (igual que main.py/WebDCS): el
    # .jsonl, .csv, .summary.json, .webm, .viewer.html y los photo-*.png de
    # auditoria quedan juntos y autocontenidos. Antes los PNG de todas las
    # corridas de una celda se mezclaban en el mismo directorio.
    run_name = f"seed_{seed}_{iso_ts}"
    out_path = Path(out_dir) / scenario_name / arm / deadlock_strategy / run_name / f"{run_name}.jsonl"
    # Copia de la consola de esta corrida junto al resto de los archivos (antes solo se veia la
    # ultima linea y los avisos del arranque -- fallo al armar/despegar, camara, etc. -- se perdian).
    out_path.parent.mkdir(parents=True, exist_ok=True)
    _restore_console = _tee_console(out_path.with_name(out_path.stem + ".console.log"))

    loop_hz = float(os.getenv("LOOP_HZ", "5.0"))
    client = AirSimClient(loop_hz=loop_hz)
    client.connect()
    # Limpia colision/velocidad/estado del controlador interno que pudiera
    # haber quedado de una corrida anterior en el mismo proceso de AirSim
    # (ver PLAN-MEJORAS.md F3.3: "client.reset()" antes de reposicionar).
    client.reset()
    # 2026-0903: los dibujos de scripts/plot_mission_route.py se ven en la
    # captura de camara que recibe el VLM (mismo motivo que main.py) --
    # limpiar siempre, no depender de que quien corrio el batch se acuerde.
    client.clear_debug_markers()

    # Jitter de pose por semilla: DESHABILITADO por defecto (2026-0828, ver
    # CHANGELOG.md). set_vehicle_pose() usa simSetVehiclePose(ignore_collision=
    # True) -- un teletransporte instantaneo que no chequea colision en el
    # posicionamiento. Con +-1.5m de jitter, eso podia materializar al dron
    # mas cerca de un obstaculo cercano (poste, tronco) que el spawn limpio
    # de AirSim, y explica variacion real de corrida a corrida que no tenia
    # que ver con el codigo de control. client.reset() (arriba) ya devuelve
    # el vehiculo a su pose de spawn original definida en settings.json --
    # sin --seed-jitter, el runner no vuelve a reposicionarlo. El jitter
    # sigue disponible detras de --seed-jitter para cuando haga falta variar
    # la pose inicial entre semillas para el analisis estadistico
    # (Mann-Whitney U necesita variacion real entre "seed 1" y "seed 2" con
    # brazos deterministas, ver comentario original mas arriba).
    if seed_jitter:
        start_pose = manifest.get("start_pose")
        waypoints_for_pose = manifest.get("waypoints") or []
        if not start_pose and waypoints_for_pose:
            first_wp = waypoints_for_pose[0]
            start_pose = {"x": first_wp.get("x", 0.0), "y": first_wp.get("y", 0.0), "z": first_wp.get("z", -10.0), "yaw_deg": 0.0}
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

    # Video WebM + visor HTML de auditoria (mismos modulos que main.py). Cualquier
    # falla de grabacion se degrada a "sin video": nunca tumba la corrida.
    video_recorder = None
    viewport_capture = None
    if record_video:
        try:
            from src.logging import FlightVideoRecorder, ViewportCapture
            from src.logging.flight_overlay import annotate_frame

            video_recorder = FlightVideoRecorder(
                str(out_path.with_suffix(".webm")),
                frame_size=(client.frame_width, client.frame_height),
                fps=loop_hz,
                with_viewport=record_viewport,
            )
            if record_viewport:
                viewport_capture = ViewportCapture()
        except Exception as exc:
            print(f"[runner] video deshabilitado: {exc}")
            video_recorder = None

    # FollowCam (camara externa, solo auditoria): un .follow.webm sincronizado con el frontal.
    follow_recorder = None
    if video_recorder is not None and record_follow:
        try:
            from src.logging import FollowCamRecorder
            from src.logging.follow_cam import annotate_follow_frame, follow_cam_config

            _follow_name = follow_cam_config()
            if _follow_name and client.enable_follow_cam(_follow_name):
                follow_recorder = FollowCamRecorder(str(out_path.with_suffix(".webm")), fps=loop_hz)
        except Exception as exc:
            print(f"[runner] FollowCam deshabilitada: {exc}")
            follow_recorder = None

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
    # Antes de empezar (pasaron varios segundos desde el despegue: grafo, video, healthcheck):
    # comprobar que el dron sigue volando; si no, rearmar. Sin esto una corrida puede pasar
    # entera posada en el suelo con todos los comandos ignorados.
    airborne_ok = client.ensure_airborne()
    if not airborne_ok:
        print(f"[{_ts()}][runner] ABORTADA: el dron no logra despegar (ver .console.log).")
    t_start = time.time()
    cycles = 0
    success = False
    interrupted = False
    landed_streak = 0
    freeze_wd = FreezeWatchdog()
    # Auditoria DistMin: hilo aislado con su propia conexion a AirSim; solo escribe
    # <stem>.distmin.ndjson. Nada de lo que mide llega al grafo ni al estado (ver finalize_run).
    from src.logging.distmin_audit import start_tracker

    distmin_tracker = start_tracker(out_path, client) if airborne_ok else None
    pose_hist: "deque" = deque(maxlen=600)
    freeze_recoveries = 0
    freeze_aborted = False
    pending_freeze_event = None
    try:
        while airborne_ok and cycles < max_cycles and (time.time() - t_start) < max_seconds:
            cycles += 1
            t0 = time.time()
            telem = client.get_telemetry()
            pos = telem.get("position", {})
            yaw = telem.get("orientation", {}).get("yaw", 0.0)
            # Guarda de despegue: en `Landed` (landed_state == 0) durante ~3 s seguidos el dron
            # no esta ejecutando la mision (desarmado / sin control API): rearmar o abortar.
            if telem.get("landed_state") == 0:
                landed_streak += 1
            else:
                landed_streak = 0
            if landed_streak >= LANDED_STREAK_MAX:
                print(f"[{_ts()}][runner] c{cycles}: {landed_streak} ciclos en Landed; rearmando...")
                landed_streak = 0
                if not client.ensure_airborne():
                    print(f"[{_ts()}][runner] ABORTADA: el dron no vuelve a despegar.")
                    airborne_ok = False
                    break
            # Vigilante de congelamiento fisico (incrustado en la malla): estado identico N ciclos.
            frozen_n = freeze_wd.update(telem)
            state["_freeze_cycles"] = frozen_n
            _vel = telem.get("velocity", {}) or {}
            pose_hist.append((cycles, pos.get("x", 0.0), pos.get("y", 0.0), pos.get("z", 0.0),
                              math.degrees(yaw), math.hypot(_vel.get("vx", 0.0), _vel.get("vy", 0.0))))
            if freeze_wd.frozen:
                frozen_since = cycles - freeze_wd.count
                print(f"[{_ts()}][runner] c{cycles}: estado fisico CONGELADO {freeze_wd.count} ciclos "
                      f"(desde c{frozen_since}): dron incrustado en la malla.")
                rec_pose = None
                if FREEZE_RECOVERY == "teleport" and freeze_recoveries < FREEZE_MAX_RECOVERIES:
                    rec_pose = pick_recovery_pose(pose_hist, frozen_since, backoff=FREEZE_BACKOFF_CYCLES)
                if rec_pose is None:
                    print(f"[{_ts()}][runner] ABORTADA: physics_locked (FREEZE_RECOVERY={FREEZE_RECOVERY}).")
                    freeze_aborted = True
                    break
                from src.agents.deep_scan import clear_scan_state

                print(f"[{_ts()}][runner] recuperacion {freeze_recoveries + 1}/{FREEZE_MAX_RECOVERIES}: teletransporte a "
                      f"({rec_pose[0]:.1f},{rec_pose[1]:.1f},{rec_pose[2]:.1f}) yaw={rec_pose[3]:.0f}.")
                client.set_vehicle_pose(rec_pose[0], rec_pose[1], rec_pose[2], yaw_deg=rec_pose[3])
                client.ensure_airborne()
                clear_scan_state(state)
                state["active_maneuver"], state["maneuver_command"], state["maneuver_cycles_left"] = None, None, 0
                state["_deliberation_pending"] = False
                tracker.reset_progress()
                pending_freeze_event = {
                    "strategy": "freeze_recovery", "arm": arm, "resolved_by_scan": False, "cycles_to_resolve": None,
                    "fell_back_to_blind": False, "frozen_cycles": freeze_wd.count,
                    "from": [round(pos.get("x", 0.0), 2), round(pos.get("y", 0.0), 2)],
                    "to": [round(rec_pose[0], 2), round(rec_pose[1], 2)],
                }
                freeze_wd.reset()
                freeze_recoveries += 1
                continue
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
            # NO pisar state["telemetry"] aca (2026-0827, ver CHANGELOG.md): este
            # get_telemetry() es una lectura rapida solo para el guiado (pos/yaw),
            # separada del capture() que corre adentro del grafo. Si se guarda en
            # state["telemetry"], capture_node la toma como prev_telemetry en el
            # siguiente ciclo -- pero es casi el mismo instante que el propio
            # capture() de este ciclo (milisegundos de diferencia, mismo reloj de
            # pared), no la telemetria del ciclo anterior. Eso hacia que
            # flow_ttc.py calculara dt=~0 SIEMPRE y degradara la percepcion en
            # el 100% de los ciclos, en todos los escenarios corridos hoy.
            state["evasion_stuck_cycles"] = tracker.progress_stall_cycles

            state = graph.invoke(state)
            # Deteccion de techo con el comando EJECUTADO, no con la demanda del guiado.
            tracker.note_executed_command(state.get("velocity_command"))
            # El VLM vio libre el camino directo al WP real: la sub-meta pendiente sobra.
            if state.pop("_clear_subgoals", False):
                tracker.drop_temporary("VLM: camino directo libre")
            if state.pop("_escape_reset", False):
                tracker.reset_progress()
            # H3.2: evento de resolucion de atasco (blind vs. deep_vlm),
            # consumido por FlightLogger para el ablation (mismo patron que
            # main.py: se saca del estado con pop(), nunca queda pisandolo).
            deadlock_event = state.pop("_deadlock_event", None)
            if pending_freeze_event is not None and not deadlock_event:
                deadlock_event, pending_freeze_event = pending_freeze_event, None
            # Instrumentacion de auditoria VLM (2026-0901, mismo patron que
            # main.py): frames RAW del ciclo exacto en que una deliberacion
            # se resolvio, si los hay.
            delib_frames = state.pop("_last_delib_frames", None)

            # Desvio persistente por esquina (2026-0827, ver CHANGELOG.md):
            # main.py ya consumia inject_corner, este runner no -- asi que
            # ninguna corrida automatica de hoy pudo haberlo aplicado aunque
            # algun nodo lo hubiera producido (tampoco lo producian, ver
            # fsm.py/deliberative.py).
            corner = state.pop("inject_corner", None)
            if corner and isinstance(corner, dict):
                injected = tracker.inject_corner_waypoint(
                    corner.get("x", 0.0), corner.get("y", 0.0), corner.get("z", -10.0),
                    label=corner.get("label", "VLM_SUBGOAL"),
                )
                if injected:
                    state["waypoints"] = tracker.waypoints
                    state["target_waypoint"] = tracker.current_waypoint

            # 2026-0930: el lazo de vuelo NO lee el sensor de profundidad del simulador en ningun caso
            # (ni para control, ni para freno, ni para abortar, ni como metrica): antes el freno de
            # proximidad por profundidad realimentaba el grafo (freno de proximidad) y registraba
            # contactos en el tracker, lo que invalidaba la comparacion entre brazos. La seguridad
            # queda medida solo por colisiones de AirSim y por el vigilante de congelamiento.
            logger.log_cycle(
                state,
                latency_ms={"graph": (time.time() - t0) * 1000.0},
                min_obstacle_dist_m=None,
                deadlock_event=deadlock_event,
                delib_frames=delib_frames,
            )

            if video_recorder is not None:
                try:
                    annotated = annotate_frame(
                        state, guidance, wp_index=tracker.current_index, wp_total=len(waypoints_list),
                        elapsed_s=time.time() - t_start, cycle=cycles,
                    )
                    vp = viewport_capture.capture() if viewport_capture is not None else None
                    video_recorder.write_frame(annotated, viewport_frame=vp)
                except Exception as exc:
                    print(f"[runner] error grabando frame de video (c{cycles}): {exc}")
                if follow_recorder is not None:
                    try:
                        _ff = client.last_follow_frame
                        follow_recorder.write(
                            annotate_follow_frame(_ff, state, cycles, time.time() - t_start) if _ff is not None else None
                        )
                    except Exception as exc:
                        print(f"[runner] error grabando FollowCam (c{cycles}): {exc}")

            if telem.get("collision", {}).get("has_collided"):
                break

            if tracker.is_completed and waypoints_list:
                success = True
                break

            time.sleep(max(0.0, sleep_s - (time.time() - t0)))
    except KeyboardInterrupt:
        # Ctrl+C: salir del lazo y dejar que el finally cierre CSV/video/visor.
        print(f"[{_ts()}][runner] interrumpido por el usuario en c{cycles}; cerrando la corrida...")
        interrupted = True
    finally:
        if distmin_tracker is not None:
            distmin_tracker.stop()
        logger.mark_success(success)
        # El motivo de termino va al summary.json (antes solo se agregaba al dict devuelto, no al archivo).
        if interrupted:
            logger.extra_summary["termination_reason"] = "interrupted"
        if not airborne_ok:
            logger.extra_summary["termination_reason"] = "not_airborne"
        if freeze_aborted:
            logger.extra_summary["termination_reason"] = "physics_locked"
        logger.extra_summary["freeze_recoveries"] = freeze_recoveries
        summary = logger.close()
        if viewport_capture is not None:
            viewport_capture.close()
        if video_recorder is not None:
            try:
                n_frames = video_recorder.close()
                if follow_recorder is not None:
                    follow_recorder.close()
                print(f"[runner] video cerrado ({n_frames} frames)")
            except Exception as exc:
                print(f"[runner] error cerrando video: {exc}")
        service.stop()
        client.land_smooth()
        # Cierre de la corrida (2026-0930): visor HTML y consolidacion de DistMin en el summary.json.
        try:
            from src.logging.finalize_run import finalize_run

            rep = finalize_run(str(out_path.parent))
            summary["min_obstacle_dist_m"] = _read_summary_field(out_path, "min_obstacle_dist_m")
            print(f"[runner] cierre: viewer={rep.get('viewer')} distmin={rep.get('distmin')}")
        except Exception as exc:
            print(f"[runner] error en el cierre de la corrida: {exc}")
        client.disconnect()
        _restore_console()

    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenarios", nargs="+", required=True)
    parser.add_argument("--arms", nargs="+", default=["slm", "fsm", "reactive"])
    parser.add_argument(
        "--deadlock-strategies", nargs="+", default=["deep_vlm"],
        choices=["blind", "deep_vlm"],
        help="H3.1/S6 (PLAN-SLAM): factorial AGENT_ARM x DEADLOCK_STRATEGY. "
             "'deep_vlm' (default): barrido + VLM. 'blind': escape determinista sin VLM (ablacion).",
    )
    parser.add_argument("--seeds", nargs="+", type=int, default=[1, 2, 3])
    parser.add_argument("--out-dir", default=str(Path(__file__).resolve().parents[2] / "airsim-runs"))
    parser.add_argument("--max-cycles", type=int, default=2000)
    parser.add_argument("--max-seconds", type=float, default=300.0)
    parser.add_argument("--no-video", action="store_true",
                         help="No grabar el .webm ni generar el .viewer.html de cada corrida (por defecto se graban).")
    parser.add_argument("--no-follow-cam", action="store_true",
                         help="No grabar el video de la camara externa FollowCam (por defecto se graba si existe en settings.json).")
    parser.add_argument("--viewport", action="store_true",
                         help="Video split-screen con la captura del viewport de Unreal (requiere mss/pywin32).")
    parser.add_argument("--seed-jitter", action="store_true",
                         help="Teletransportar (ignore_collision=True) a una pose con jitter aleatorio "
                              "por semilla, en vez de arrancar del spawn limpio de AirSim. Desactivado "
                              "por defecto (2026-0828, ver CHANGELOG.md) -- solo para corridas "
                              "estadisticas multi-semilla que necesiten variacion real entre seeds.")
    args = parser.parse_args()

    # Cada combinacion corre en un subproceso propio: AGENT_ARM se lee a
    # nivel de modulo en graph.py al importar, asi que reusar el mismo
    # interprete para multiples brazos en la misma corrida arrastraria el
    # primer valor. Ademas aisla crashes de una corrida del resto del batch.
    import subprocess

    results = []
    for scenario in args.scenarios:
        for arm in args.arms:
            for deadlock_strategy in args.deadlock_strategies:
                for seed in args.seeds:
                    print(f"[{_ts()}][runner] scenario={scenario} arm={arm} deadlock_strategy={deadlock_strategy} seed={seed}")
                    cmd = [
                        sys.executable, __file__, "--_single",
                        "--scenario", scenario, "--arm", arm, "--seed", str(seed),
                        "--out-dir", args.out_dir, "--max-cycles", str(args.max_cycles),
                        "--max-seconds", str(args.max_seconds),
                        "--deadlock-strategy", deadlock_strategy,
                    ]
                    if args.seed_jitter:
                        cmd.append("--seed-jitter")
                    if args.no_video:
                        cmd.append("--no-video")
                    if args.viewport:
                        cmd.append("--viewport")
                    if args.no_follow_cam:
                        cmd.append("--no-follow-cam")
                    # Popen en vez de subprocess.run: ante Ctrl+C, run() hace kill() al
                    # hijo a los 0.25 s y lo corta a mitad de close() (cola de video,
                    # CSV aplanado, visor). Aca se espera su cierre ordenado.
                    run_started = time.time()
                    popen = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    interrupted = False
                    try:
                        out_txt, err_txt = popen.communicate()
                    except KeyboardInterrupt:
                        interrupted = True
                        print(f"[{_ts()}][runner] Ctrl+C: esperando el cierre de la corrida "
                              f"(video/CSV/visor, hasta {CLOSE_WAIT_S:.0f} s)...")
                        try:
                            out_txt, err_txt = popen.communicate(timeout=CLOSE_WAIT_S)
                        except (KeyboardInterrupt, subprocess.TimeoutExpired):
                            popen.kill()
                            out_txt, err_txt = popen.communicate()
                    proc = subprocess.CompletedProcess(cmd, popen.returncode, out_txt, err_txt)
                    # Red de seguridad: si el hijo murio antes de cerrar (kill, 2do Ctrl+C,
                    # crash), reconstruir CSV aplanado / video / visor desde el JSONL.
                    _finalize_if_incomplete(args.out_dir, scenario, arm, deadlock_strategy, run_started)
                    if proc.returncode != 0:
                        print(f"[{_ts()}][runner] FALLO scenario={scenario} arm={arm} deadlock_strategy={deadlock_strategy} seed={seed}:\n{proc.stderr[-2000:]}")
                    else:
                        last = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else "[runner] ok"
                        print(f"[{_ts()}] {last}")
                    results.append({
                        "scenario": scenario, "arm": arm, "deadlock_strategy": deadlock_strategy,
                        "seed": seed, "returncode": proc.returncode,
                    })
                    if interrupted:
                        print(f"[{_ts()}][runner] Interrumpido: no se lanzan las corridas restantes.")
                        print(f"\n[{_ts()}][runner] {len(results)} corrida(s) (interrumpido). Ver {args.out_dir}/.")
                        return

    print(f"\n[{_ts()}][runner] {len(results)} corridas completadas. Ver {args.out_dir}/ para los JSONL y usar experiments/analyze.py.")


def _read_summary_field(jsonl_path: Path, key: str):
    try:
        return json.loads(jsonl_path.with_name(jsonl_path.stem + ".summary.json").read_text(encoding="utf-8")).get(key)
    except (OSError, ValueError):
        return None


def _finalize_if_incomplete(out_dir: str, scenario: str, arm: str, strategy: str, since: float) -> None:
    try:
        from src.logging.finalize_run import finalize_run, needs_finalize

        cell = Path(out_dir) / Path(scenario).stem / arm / strategy
        runs = [p for p in cell.glob("seed_*") if p.is_dir() and p.stat().st_mtime >= since - 1.0] if cell.exists() else []
        for run in sorted(runs, key=lambda p: p.stat().st_mtime)[-1:]:
            if needs_finalize(str(run)):
                print(f"[{_ts()}][runner] corrida incompleta en {run.name}: reconstruyendo CSV/video/visor...")
                finalize_run(str(run))
    except Exception as exc:  # nunca tumbar el batch por el cierre
        print(f"[{_ts()}][runner] no se pudo cerrar la corrida: {exc}")


def _single_main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--_single", action="store_true")
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--arm", required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--out-dir", default=str(Path(__file__).resolve().parents[2] / "airsim-runs"))
    parser.add_argument("--max-cycles", type=int, default=2000)
    parser.add_argument("--max-seconds", type=float, default=300.0)
    parser.add_argument("--seed-jitter", action="store_true")
    parser.add_argument("--no-video", action="store_true")
    parser.add_argument("--viewport", action="store_true")
    parser.add_argument("--no-follow-cam", action="store_true")
    parser.add_argument("--deadlock-strategy", default="deep_vlm", choices=["blind", "deep_vlm"])
    args = parser.parse_args()
    summary = run_one(
        args.scenario, args.arm, args.seed, args.out_dir, args.max_cycles, args.max_seconds,
        seed_jitter=args.seed_jitter, deadlock_strategy=args.deadlock_strategy,
        record_video=not args.no_video, record_viewport=args.viewport,
        record_follow=not args.no_follow_cam,
    )
    print(f"[{_ts()}][runner] summary: {json.dumps(summary)}")


if __name__ == "__main__":
    if "--_single" in sys.argv:
        _single_main()
    else:
        main()

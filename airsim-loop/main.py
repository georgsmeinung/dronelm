# Paso 6: Bucle continuo de control autonomo.
# Captura -> percepcion -> gatekeeper -> (reflejo | cerebro) -> motor -> ...
#
# F0.3: un unico AirSimClient se crea y conecta aca, y se inyecta en
# compile_workflow(). F0.5: compile_workflow() devuelve tambien el
# DeliberationService para poder apagarlo prolijamente al salir.
import math
import os
import time

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover
    pass

from src.agents.graph import DroneState, compile_workflow
from src.hardware import AirSimClient
from src.navigation import WaypointTracker

DEFAULT_LOOP_HZ = float(os.getenv("LOOP_HZ", "5.0"))
AGENT_ARM = os.getenv("AGENT_ARM", "slm")
FLIGHT_LOG_PATH = os.getenv("AIRSIM_FLIGHT_LOG")  # F3.2: si se setea, se escribe un JSONL
MISSION_MAX_SECONDS = float(os.getenv("MISSION_MAX_SECONDS", "0.0"))  # 0 = sin límite de tiempo
MISSION_MAX_CYCLES = int(os.getenv("MISSION_MAX_CYCLES", "0"))  # 0 = sin límite de ciclos


def _print_state(state: DroneState, cycle_num: int = 0) -> None:
    route = state.get("route", "")
    delib = state.get("last_deliberation")
    cmd = state.get("velocity_command") or {}
    guidance = state.get("waypoint_guidance") or {}
    target_wp = state.get("target_waypoint") or {}
    ttc = state.get("estimated_ttc", float("inf"))
    ttc_str = f"{ttc:.1f}s" if ttc != float("inf") else "inf"
    field = state.get("obstacle_field")

    wp_idx = state.get("current_wp_index", 0) + 1
    wp_total = len(state.get("waypoints") or [])
    wp_label = target_wp.get("label", f"WP_{wp_idx}")
    dist = guidance.get("distance", 0.0)
    err = guidance.get("bearing_err_deg", 0.0)
    telem = state.get("telemetry") or {}
    pos = telem.get("position") or {}
    alt = abs(float(pos.get("z", 0.0)))

    orient = telem.get("orientation") or {}
    yaw_deg = math.degrees(float(orient.get("yaw", 0.0)))

    collision = telem.get("collision") or {}
    has_collided = collision.get("has_collided", False)
    coll_obj = collision.get("object_name", "")
    coll_str = f" | Colisión: SÍ ({coll_obj})" if has_collided else " | Colisión: No"
    degraded_str = " | ⚠️ DEGRADADO" if state.get("degraded") else ""

    wp_info = f"WP {wp_idx}/{wp_total} ({wp_label}) | Dist: {dist:.1f}m | Desvío: {err:+.0f}°" if target_wp else "Misión sin WP activo"
    print(f"\n[Ciclo #{cycle_num}][{AGENT_ARM}] {wp_info} | Alt: {alt:.1f}m | Yaw: {yaw_deg:.1f}°{coll_str} | TTC: {ttc_str}{degraded_str}")

    # Línea de percepción: resumen por sector del ObstacleField (F1.1).
    if field is not None and hasattr(field, "summary_text"):
        for line in field.summary_text().split("\n")[1:]:
            print(f"  {line}")
    else:
        print("  Percepción : sin datos.")

    # Bloque de auditoría SLM
    if route == "deliberative" and delib:
        delib_id = delib.get("id", 1)
        model = delib.get("model", "SLM")
        lat = delib.get("latency_ms", 0.0)
        is_fb = delib.get("is_fallback", False)
        timed_out = delib.get("timeout", False)
        has_vision = delib.get("vision_enabled", False)
        if timed_out:
            type_str = "FALLBACK (TIMEOUT/WATCHDOG)"
        elif is_fb:
            type_str = "FALLBACK DETERMINISTA"
        elif has_vision:
            type_str = "VLM VISIÓN DIRECTA"
        else:
            type_str = "SLM TEXTO"
        raw = delib.get("raw_response", "").strip()

        print("  ----------------------------------------------------------------------")
        print(f"  [AUDITORÍA SLM #{delib_id}] Modelo: {model} | Latencia: {lat:.0f}ms | Tipo: {type_str}")
        print("  Respuesta SLM:")
        for line in raw.split("\n"):
            print(f"    {line}")
        print(f"  Decisión: {delib.get('macro_action', '')} | {delib.get('rationale', '')}")
        print("  ----------------------------------------------------------------------")

    route_tag = route.upper() if route else "DIRECT"
    action = state.get("next_action", "MANTENER_RUMBO")
    if cmd:
        vx = cmd.get("vx", 0.0)
        vy = cmd.get("vy", 0.0)
        vz = cmd.get("vz", 0.0)
        yaw = cmd.get("yaw_rate", 0.0)
        rat = cmd.get("rationale", "")
        rat_str = f" | {rat}" if rat and route != "deliberative" else ""
        print(f"  Control    : [{route_tag}] {action} -> vx={vx:+.2f} vy={vy:+.2f} vz={vz:+.2f} yaw={yaw:+.1f}°/s{rat_str}")


def _update_delib_outcomes(drone_state: DroneState, guidance: dict) -> None:
    """F2.2: memoria corta de resultados de deliberaciones previas para el prompt.

    Compara la distancia al waypoint y el TTC minimo entre el momento en que
    se tomo la ultima decision deliberativa y el ciclo actual, para que el
    prompt del SLM incluya el efecto medido de su decision anterior en lugar
    de re-decidir en el vacio.
    """
    baseline = drone_state.get("_delib_baseline")
    current_dist = guidance.get("distance", 0.0)
    current_ttc = drone_state.get("estimated_ttc", float("inf"))

    if baseline is not None:
        outcomes = list(drone_state.get("_delib_outcomes") or [])
        delta_ttc = None
        if baseline["min_ttc"] != float("inf") and current_ttc != float("inf"):
            delta_ttc = current_ttc - baseline["min_ttc"]
        outcomes.append({
            "macro_action": baseline["macro_action"],
            "delta_dist_wp": baseline["dist"] - current_dist,
            "delta_min_ttc": delta_ttc,
        })
        drone_state["_delib_outcomes"] = outcomes[-5:]
        drone_state["_delib_baseline"] = None

    deliberations = drone_state.get("deliberations") or []
    if deliberations and drone_state.get("route") == "deliberative" and drone_state.get("next_action") != "FRENAR":
        last = deliberations[-1]
        # Solo fijar nueva baseline si esta deliberacion todavia no genero una
        # (evita sobreescribir con el mismo id en ciclos de espera consecutivos).
        if drone_state.get("_delib_last_baselined_id") != last.get("id"):
            drone_state["_delib_baseline"] = {
                "macro_action": last.get("macro_action", ""),
                "dist": current_dist,
                "min_ttc": current_ttc,
            }
            drone_state["_delib_last_baselined_id"] = last.get("id")


def main() -> None:
    print(f"Inicializando drone autonomo con LangGraph + AirSim... [AGENT_ARM={AGENT_ARM}]")
    import json

    manifest_path = os.getenv("AIRSIM_PLAN_MANIFEST") or globals().get("AIRSIM_PLAN_MANIFEST")
    manifest_data = {}
    if manifest_path and os.path.exists(manifest_path):
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest_data = json.load(f)
            print(f"Manifiesto de misión cargado con éxito: {manifest_path}")
        except Exception as e:
            print(f"Error al cargar manifiesto: {e}")

    mission_id = manifest_data.get("mission_id", "MOCK_MISSION")
    os.environ.pop(f"STOP_MISSION_{mission_id}", None)

    watch_mode = (os.getenv("AIRSIM_LOOP_WATCH") or globals().get("AIRSIM_LOOP_WATCH", "false")).lower() == "true"
    if watch_mode:
        # pyrefly: ignore [missing-import]
        import cv2
        cv2.namedWindow("Drone Camera Feed", cv2.WINDOW_NORMAL)
        cv2.resizeWindow("Drone Camera Feed", 640, 480)
        print("[Watch] Modo visualización activado. Mostrando señal de video nativa.")

    # F0.3: un unico cliente de AirSim para todo el proceso.
    airsim_client = AirSimClient(loop_hz=DEFAULT_LOOP_HZ)
    airsim_client.connect()

    graph, deliberation_service = compile_workflow(airsim_client)
    sleep_s = 1.0 / max(DEFAULT_LOOP_HZ, 0.01)

    waypoints_list = manifest_data.get("waypoints", [])
    waypoint_tracker = WaypointTracker(waypoints_list)
    if waypoints_list:
        print(f"[Navegación] Cargados {len(waypoints_list)} waypoints de misión. Iniciando hacia {waypoints_list[0].get('label', 'WP_1')}.")

    flight_logger = None
    if FLIGHT_LOG_PATH:
        from src.logging import FlightLogger

        flight_logger = FlightLogger(
            FLIGHT_LOG_PATH,
            scenario=manifest_data.get("mission_id", "default"),
            seed=int(os.getenv("AIRSIM_SEED", "0")),
            arm=AGENT_ARM,
        )

    cycle_count = 0
    mission_start_time = time.time()
    mission_termination_reason = None

    drone_state: DroneState = {
        "waypoints": waypoints_list,
        "current_wp_index": waypoint_tracker.current_index,
        "target_waypoint": None,
        "waypoint_guidance": {},
        "mission_completed": False,
        "rgb_image": None,
        "telemetry": {},
        "frame_history": [],
        "estimated_ttc": float("inf"),
        "next_action": "",
        "flight_status": "vuelo",
        "deliberations": [],
        "active_maneuver": None,
        "maneuver_cycles_left": 0,
        "maneuver_command": None,
        "evasion_stuck_cycles": 0,
        "slm_request_id": None,
    }

    try:
        while True:
            mission_id = manifest_data.get("mission_id", "MOCK_MISSION")
            if os.getenv(f"STOP_MISSION_{mission_id}") == "1":
                print(f"[Ciclo] Detención solicitada para misión {mission_id}. Saliendo del bucle.")
                mission_termination_reason = "stopped"
                break

            # Verificar límites de tiempo y ciclos (G3.2).
            if MISSION_MAX_CYCLES > 0 and cycle_count >= MISSION_MAX_CYCLES:
                print(f"[Ciclo] Límite de ciclos alcanzado ({cycle_count} >= {MISSION_MAX_CYCLES}). Abortando misión.")
                mission_termination_reason = "max_cycles"
                break

            if MISSION_MAX_SECONDS > 0 and (time.time() - mission_start_time) >= MISSION_MAX_SECONDS:
                print(f"[Ciclo] Límite de tiempo alcanzado ({time.time() - mission_start_time:.1f}s >= {MISSION_MAX_SECONDS}s). Abortando misión.")
                mission_termination_reason = "timeout"
                break

            cycle_count += 1
            t0 = time.time()

            t_telem = time.time()
            telem_now = airsim_client.get_telemetry()
            pos_now = telem_now.get("position", {}) if telem_now else {}
            orient_now = telem_now.get("orientation", {}) if telem_now else {}
            yaw_now = float(orient_now.get("yaw", 0.0)) if isinstance(orient_now, dict) else 0.0
            latency_telem_ms = (time.time() - t_telem) * 1000.0

            target_wp = waypoint_tracker.update(pos_now)
            guidance = waypoint_tracker.compute_guidance(pos_now, yaw_now)
            # F2.5: progreso real (no ciclos-en-ruta-evasiva) para decidir el escape de deadlock.
            # Fix 1 (2026-0824): esperar al SLM dentro del watchdog no cuenta
            # como "sin progresar" (ver _deliberation_pending en deliberative.py).
            # Fix 2: distancia HORIZONTAL, no 3D -- subir para escapar de un
            # atasco no debe empeorar la metrica que decide si se resolvio.
            if not drone_state.get("_deliberation_pending", False):
                waypoint_tracker.record_progress(
                    guidance.get("dist_xy", guidance.get("distance", 0.0)),
                    bearing_err_deg=guidance.get("bearing_err_deg", 0.0),
                )

            drone_state["waypoints"] = waypoint_tracker.waypoints
            drone_state["current_wp_index"] = waypoint_tracker.current_index
            drone_state["target_waypoint"] = target_wp
            drone_state["waypoint_guidance"] = guidance
            drone_state["mission_completed"] = waypoint_tracker.is_completed
            # NO pisar drone_state["telemetry"] aca (2026-0827, ver CHANGELOG.md):
            # mismo fix que experiments/runner.py -- este get_telemetry() es una
            # lectura rapida solo para el guiado (pos/yaw), separada del capture()
            # que corre adentro del grafo. Guardarla ahi hacia que capture_node
            # tomara como prev_telemetry un timestamp de milisegundos antes (este
            # mismo ciclo), no el del ciclo anterior -- dt=~0 siempre, percepcion
            # degradada en el 100% de los ciclos.
            drone_state["evasion_stuck_cycles"] = waypoint_tracker.progress_stall_cycles
            if waypoint_tracker.is_completed:
                drone_state["flight_status"] = "mision_completada"

            t_graph = time.time()
            try:
                final_state = graph.invoke(drone_state)
                drone_state = final_state
            except Exception as exc:
                print(f"[Ciclo #{cycle_count}] Error en el grafo: {exc}")
                time.sleep(sleep_s)
                continue
            latency_graph_ms = (time.time() - t_graph) * 1000.0

            if drone_state.pop("_escape_reset", False):
                # Escape de deadlock forzado: el progreso medido (xy) puede no
                # reflejar la subida vertical, asi que se resetea manualmente
                # el contador de atasco de la ruta para no re-disparar de inmediato.
                waypoint_tracker.reset_progress()

            _update_delib_outcomes(drone_state, guidance)

            corner = final_state.get("inject_corner")
            if corner and isinstance(corner, dict):
                injected = waypoint_tracker.inject_corner_waypoint(
                    corner.get("x", 0.0), corner.get("y", 0.0), corner.get("z", -10.0),
                    label=corner.get("label", "CORNER_WP"),
                )
                final_state["inject_corner"] = None
                if injected:
                    drone_state["waypoints"] = waypoint_tracker.waypoints
                    drone_state["target_waypoint"] = waypoint_tracker.current_waypoint

            _print_state(final_state, cycle_count)

            if flight_logger is not None:
                flight_logger.log_cycle(
                    final_state,
                    latency_ms={"telemetry": round(latency_telem_ms, 1), "graph": round(latency_graph_ms, 1)},
                )

            frame = final_state.get("rgb_image")
            annotated_frame = None
            if frame is not None:
                # pyrefly: ignore [missing-import]
                import cv2
                annotated_frame = frame.copy()

                decision = final_state.get("next_action", "MANTENER_RUMBO")
                flight_status = final_state.get("flight_status", "vuelo")
                ttc_val = final_state.get("estimated_ttc", float("inf"))
                ttc_str = f"{ttc_val:.1f}s" if ttc_val != float("inf") else "inf"

                h, w = annotated_frame.shape[:2]
                cv2.rectangle(annotated_frame, (0, 0), (w, 42), (10, 10, 15), -1)

                dec_color = (0, 255, 100) if "MANTENER" in decision else (0, 165, 255)
                if "SLM" in decision or "PARADA" in decision or "FRENAR" in decision:
                    dec_color = (255, 100, 200)

                wp_str = f"WP {waypoint_tracker.current_index + 1}/{len(waypoints_list)} ({guidance.get('distance', 0.0):.0f}m)" if waypoints_list else ""
                cv2.putText(annotated_frame, f"ACT: {decision} {wp_str}", (10, 26),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.52, dec_color, 2, cv2.LINE_AA)

                cv2.putText(annotated_frame, f"TTC: {ttc_str} | {flight_status}", (w - 280, 26),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, (220, 220, 220), 1, cv2.LINE_AA)

                try:
                    # pyrefly: ignore [missing-import]
                    from airsim_plan.bridge.stream_hub import stream_hub
                    field = final_state.get("obstacle_field")
                    stream_hub.publish(
                        frame=annotated_frame,
                        telemetry={
                            "connected": True,
                            "mission_id": manifest_data.get("mission_id", "MISION_ACTIVA"),
                            "decision": decision,
                            "flight_status": flight_status,
                            "estimated_ttc": ttc_val if ttc_val != float("inf") else None,
                            "obstacle_field": field.to_dict() if field is not None else None,
                            "scene_summary": final_state.get("scene_summary", ""),
                            "velocity": final_state.get("velocity_command", {}),
                            "target_waypoint": target_wp,
                            "waypoint_index": waypoint_tracker.current_index,
                            "waypoint_total": len(waypoints_list),
                            "waypoint_distance": guidance.get("distance", 0.0),
                            "last_deliberation": final_state.get("last_deliberation"),
                            "deliberations": final_state.get("deliberations", []),
                            "timestamp": time.time(),
                        }
                    )
                except Exception:
                    pass

                if watch_mode:
                    cv2.imshow("Drone Camera Feed", annotated_frame)
                    key = cv2.waitKey(1) & 0xFF
                    if key == ord('q') or key == 27:
                        print("[Watch] Bucle detenido desde la ventana de video.")
                        break

            if waypoint_tracker.is_completed and waypoints_list:
                print("\n[Misión] ¡Misión completada exitosamente! Iniciando secuencia de aterrizaje autónomo...")
                mission_termination_reason = "completed"
                if flight_logger is not None:
                    flight_logger.mark_success(True)
                try:
                    # pyrefly: ignore [missing-import]
                    from airsim_plan.bridge.stream_hub import stream_hub
                    stream_hub.publish(
                        frame=annotated_frame,
                        telemetry={
                            "connected": True,
                            "mission_id": manifest_data.get("mission_id", "MISION_ACTIVA"),
                            "decision": "ATERRIZANDO",
                            "flight_status": "aterrizando",
                            "estimated_ttc": None,
                            "obstacle_field": None,
                            "scene_summary": "Misión completada con éxito. Aterrizando...",
                            "velocity": {"vx": 0.0, "vy": 0.0, "vz": 0.0, "yaw_rate": 0.0},
                            "target_waypoint": None,
                            "waypoint_index": len(waypoints_list),
                            "waypoint_total": len(waypoints_list),
                            "waypoint_distance": 0.0,
                            "timestamp": time.time(),
                        },
                    )
                except Exception:
                    pass

                airsim_client.land()
                print("[Misión] Aterrizaje completado y motores desarmados. Devolviendo control a WebDCS.\n")

                try:
                    # pyrefly: ignore [missing-import]
                    from airsim_plan.bridge.stream_hub import stream_hub
                    stream_hub.publish(
                        frame=None,
                        telemetry={
                            "connected": False,
                            "mission_id": manifest_data.get("mission_id", "MISION_ACTIVA"),
                            "decision": "MISIÓN_COMPLETADA",
                            "flight_status": "completada_en_tierra",
                            "estimated_ttc": None,
                            "obstacle_field": None,
                            "scene_summary": "Dron en tierra. Control disponible en WebDCS.",
                            "velocity": {"vx": 0.0, "vy": 0.0, "vz": 0.0, "yaw_rate": 0.0},
                            "target_waypoint": None,
                            "waypoint_index": len(waypoints_list),
                            "waypoint_total": len(waypoints_list),
                            "waypoint_distance": 0.0,
                            "timestamp": time.time(),
                        },
                    )
                except Exception:
                    pass

                break

            elapsed = time.time() - t0
            wait = max(0.0, sleep_s - elapsed)
            time.sleep(wait)
    except KeyboardInterrupt:
        print("\nApagando sistema de navegacion.")
        mission_termination_reason = "interrupted"
    finally:
        try:
            # pyrefly: ignore [missing-import]
            from airsim_plan.bridge.stream_hub import stream_hub
            stream_hub.publish(
                frame=None,
                telemetry={"connected": False, "status": "idle", "flight_status": "detenido", "timestamp": time.time()},
            )
        except Exception:
            pass

        # Detectar colisión si no se documentó otra razón (G3.2).
        if mission_termination_reason is None:
            collision = drone_state.get("telemetry", {}).get("collision", {})
            if collision.get("has_collided"):
                mission_termination_reason = "collision"
            else:
                mission_termination_reason = "unknown"

        if flight_logger is not None:
            flight_logger.mark_success(waypoint_tracker.is_completed)
            summary = flight_logger.close()
            if mission_termination_reason and mission_termination_reason != "completed":
                summary["termination_reason"] = mission_termination_reason
                print(f"[Misión] Terminada: {mission_termination_reason}")

        deliberation_service.stop()

        if watch_mode:
            # pyrefly: ignore [missing-import]
            import cv2
            cv2.destroyAllWindows()
        if airsim_client is not None:
            try:
                airsim_client.disconnect()
            except Exception:  # pragma: no cover
                pass


if __name__ == "__main__":
    main()

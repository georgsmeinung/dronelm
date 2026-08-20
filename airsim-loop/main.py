# Paso 6: Bucle continuo de control autonomo.
# Captura -> percepcion -> gatekeeper -> (reflejo | cerebro) -> motor -> ...
import math
import os
import time

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover
    pass

from src.agents import compile_workflow, get_airsim_client
from src.agents.graph import DroneState


DEFAULT_LOOP_HZ = float(os.getenv("LOOP_HZ", "0.5"))


def _print_state(state: DroneState, cycle_num: int = 0) -> None:
    route = state.get("route", "")
    delib = state.get("last_deliberation")
    cmd = state.get("velocity_command") or {}
    guidance = state.get("waypoint_guidance") or {}
    target_wp = state.get("target_waypoint") or {}
    ttc = state.get("estimated_ttc", float("inf"))
    ttc_str = f"{ttc:.1f}s" if ttc != float("inf") else "inf"
    obstacles = state.get("detected_obstacles") or []

    # 1. Cabecera estructurada del ciclo
    wp_idx = state.get("current_wp_index", 0) + 1
    wp_total = len(state.get("waypoints") or [])
    wp_label = target_wp.get("label", f"WP_{wp_idx}")
    dist = guidance.get("distance", 0.0)
    err = guidance.get("bearing_err_deg", 0.0)
    telem = state.get("telemetry") or {}
    pos = telem.get("position") or {}
    alt = abs(float(pos.get("z", 0.0)))

    wp_info = f"WP {wp_idx}/{wp_total} ({wp_label}) | Dist: {dist:.1f}m | Desvío: {err:+.0f}°" if target_wp else "Misión sin WP activo"
    print(f"\n[Ciclo #{cycle_num}] {wp_info} | Alt: {alt:.1f}m | TTC: {ttc_str}")

    # 2. Línea de percepción concisa
    if not obstacles:
        print("  Percepción : Camino despejado.")
    else:
        obs_descs = []
        for o in obstacles[:3]:
            obj_name = o.get("object", "?")
            sec = o.get("sector", "?")
            prox = o.get("proximity", "?")
            dist_o = o.get("distance_m")
            dist_str = f"{dist_o:.1f}m" if isinstance(dist_o, (int, float)) else "N/A"
            obs_descs.append(f"{obj_name} {sec.lower()} ({prox}, {dist_str})")
        total_obs = len(obstacles)
        extra_str = f" [Total: {total_obs}]" if total_obs > 3 else ""
        print(f"  Percepción : {'; '.join(obs_descs)}{extra_str}")

    # 3. Bloque de auditoría SLM (con líneas simples y limpias)
    if route == "deliberative" and delib:
        delib_id = delib.get("id", 1)
        model = delib.get("model", "SLM")
        lat = delib.get("latency_ms", 0.0)
        is_fb = delib.get("is_fallback", False)
        has_vision = delib.get("vision_enabled", False)
        if is_fb:
            type_str = "FALLBACK DETERMINISTA"
        elif has_vision:
            type_str = "VLM VISIÓN DIRECTA"
        else:
            type_str = "SLM TEXTO"
        prompt = delib.get("prompt", "").strip()
        raw = delib.get("raw_response", "").strip()

        print("  ----------------------------------------------------------------------")
        print(f"  [AUDITORÍA SLM #{delib_id}] Modelo: {model} | Latencia: {lat:.0f}ms | Tipo: {type_str}")
        print("  Prompt enviado:")
        for line in prompt.split("\n"):
            print(f"    {line}")
        print("  Respuesta SLM:")
        for line in raw.split("\n"):
            print(f"    {line}")
        print(f"  Decisión: {delib.get('macro_action', '')} | {delib.get('rationale', '')}")
        print("  ----------------------------------------------------------------------")

    # 4. Línea de control consolidada
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


def main() -> None:
    print("Inicializando drone autonomo con LangGraph + AirSim...")
    import json
    
    # 1) Cargar manifiesto si existe (cuando se lanza desde el GCS)
    manifest_path = os.getenv("AIRSIM_PLAN_MANIFEST") or globals().get("AIRSIM_PLAN_MANIFEST")
    manifest_data = {}
    if manifest_path and os.path.exists(manifest_path):
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest_data = json.load(f)
            print(f"Manifiesto de misión cargado con éxito: {manifest_path}")
        except Exception as e:
            print(f"Error al cargar manifiesto: {e}")

    # Purgar cualquier señal de detención residual previa para esta misión
    mission_id = manifest_data.get("mission_id", "MOCK_MISSION")
    os.environ.pop(f"STOP_MISSION_{mission_id}", None)

    # 2) Verificar si se solicitó ver el video
    watch_mode = (os.getenv("AIRSIM_LOOP_WATCH") or globals().get("AIRSIM_LOOP_WATCH", "false")).lower() == "true"
    if watch_mode:
        import cv2
        cv2.namedWindow("Drone Camera Feed", cv2.WINDOW_NORMAL)
        cv2.resizeWindow("Drone Camera Feed", 640, 480)
        print("[Watch] Modo visualización activado. Mostrando señal de video nativa.")

    from src.navigation import WaypointTracker

    graph = compile_workflow()
    airsim_client = get_airsim_client()
    sleep_s = 1.0 / max(DEFAULT_LOOP_HZ, 0.01)

    # 3) Inicializar el gestor de waypoints con la misión
    waypoints_list = manifest_data.get("waypoints", [])
    waypoint_tracker = WaypointTracker(waypoints_list)
    if waypoints_list:
        print(f"[Navegación] Cargados {len(waypoints_list)} waypoints de misión. Iniciando hacia {waypoints_list[0].get('label', 'WP_1')}.")

    cycle_count = 0

    # Estado persistente del dron que preserva memoria táctica entre ciclos
    drone_state: DroneState = {
        "mission_id": manifest_data.get("mission_id", "MOCK_MISSION"),
        "waypoints": waypoints_list,
        "current_wp_index": waypoint_tracker.current_index,
        "target_waypoint": None,
        "waypoint_guidance": {},
        "mission_completed": False,
        "rules_of_engagement": manifest_data.get("rules_of_engagement", {}),
        "tactical_system_prompt": manifest_data.get("tactical_system_prompt") or os.getenv("AIRSIM_PLAN_TACTICAL_PROMPT") or globals().get("AIRSIM_PLAN_TACTICAL_PROMPT") or "",
        "rgb_image": None,
        "telemetry": {},
        "xor_change_ratio": 1.0,
        "estimated_ttc": float("inf"),
        "detected_obstacles": [],
        "next_action": "",
        "flight_status": "vuelo",
        "deliberations": [],
        "active_maneuver": None,
        "maneuver_cycles_left": 0,
        "maneuver_command": None,
    }

    try:
        while True:
            # Verificar si se solicitó detener la misión
            mission_id = manifest_data.get("mission_id", "MOCK_MISSION")
            if os.getenv(f"STOP_MISSION_{mission_id}") == "1":
                print(f"[Ciclo] Detención solicitada para misión {mission_id}. Saliendo del bucle.")
                break

            cycle_count += 1
            t0 = time.time()

            # 4) Calcular progreso y vector de guiado hacia el waypoint activo
            telem_now = airsim_client.get_telemetry()
            pos_now = telem_now.get("position", {}) if telem_now else {}
            orient_now = telem_now.get("orientation", {}) if telem_now else {}
            yaw_now = float(orient_now.get("yaw", 0.0)) if isinstance(orient_now, dict) else 0.0

            target_wp = waypoint_tracker.update(pos_now)
            guidance = waypoint_tracker.compute_guidance(pos_now, yaw_now)

            # Actualizar entradas dinámicas del ciclo en el estado persistente con los waypoints del tracker
            drone_state["waypoints"] = waypoint_tracker.waypoints
            drone_state["current_wp_index"] = waypoint_tracker.current_index
            drone_state["target_waypoint"] = target_wp
            drone_state["waypoint_guidance"] = guidance
            drone_state["mission_completed"] = waypoint_tracker.is_completed
            drone_state["telemetry"] = telem_now
            drone_state["rgb_image"] = None
            if waypoint_tracker.is_completed:
                drone_state["flight_status"] = "mision_completada"

            try:
                final_state = graph.invoke(drone_state)
                drone_state = final_state  # Heredar toda la memoria táctica y persistencia
            except Exception as exc:
                print(f"[Ciclo #{cycle_count}] Error en el grafo: {exc}")
                time.sleep(sleep_s)
                continue

            # Inyección de Sub-Waypoint Manhattan si el deliberador planificó una esquina
            corner = final_state.get("inject_corner")
            if corner and isinstance(corner, dict):
                injected = waypoint_tracker.inject_corner_waypoint(
                    corner.get("x", 0.0),
                    corner.get("y", 0.0),
                    corner.get("z", -10.0),
                    label=corner.get("label", "CORNER_WP"),
                )
                final_state["inject_corner"] = None
                if injected:
                    drone_state["waypoints"] = waypoint_tracker.waypoints
                    drone_state["target_waypoint"] = waypoint_tracker.current_waypoint

            _print_state(final_state, cycle_count)

            # 3) Anotar imagen y publicar en StreamHub / OpenCV
            frame = final_state.get("rgb_image")
            if frame is not None:
                import cv2
                annotated_frame = frame.copy()

                # 3.1) Dibujar caja de ROI si existe
                roi_info = final_state.get("roi_info")
                if roi_info and len(roi_info) == 4 and roi_info[2] > 0 and roi_info[3] > 0:
                    rx, ry, rw, rh = map(int, roi_info)
                    cv2.rectangle(annotated_frame, (rx, ry), (rx + rw, ry + rh), (255, 200, 0), 1)
                    cv2.putText(annotated_frame, "ROI 62%", (rx + 5, ry + 15),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 200, 0), 1, cv2.LINE_AA)

                # 3.2) Dibujar rectángulos de YOLO y etiquetas
                for det in final_state.get("detections", []):
                    bbox = det.get("bbox", [0, 0, 0, 0]) if isinstance(det, dict) else getattr(det, "bbox", [0, 0, 0, 0])
                    obj_name = det.get("object", "objeto") if isinstance(det, dict) else getattr(det, "object", "objeto")
                    conf = det.get("confidence", 0.0) if isinstance(det, dict) else getattr(det, "confidence", 0.0)

                    x_min, y_min, x_max, y_max = map(int, bbox)
                    cv2.rectangle(annotated_frame, (x_min, y_min), (x_max, y_max), (0, 255, 100), 2)

                    label_str = f"{obj_name}: {conf:.2f}"
                    cv2.putText(annotated_frame, label_str, (x_min, max(y_min - 5, 15)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 100), 1, cv2.LINE_AA)

                # 3.3) Dibujar banner superior con estado, decisión y métricas
                decision = final_state.get("next_action", "MANTENER_RUMBO")
                flight_status = final_state.get("flight_status", "vuelo")
                xor_pct = final_state.get("xor_change_ratio", 0.0) * 100.0
                ttc_val = final_state.get("estimated_ttc", float("inf"))
                ttc_str = f"{ttc_val:.1f}s" if ttc_val != float("inf") else "inf"

                h, w = annotated_frame.shape[:2]
                cv2.rectangle(annotated_frame, (0, 0), (w, 42), (10, 10, 15), -1)

                # Color de decisión
                dec_color = (0, 255, 100) if "MANTENER" in decision else (0, 165, 255)
                if "SLM" in decision or "PARADA" in decision:
                    dec_color = (255, 100, 200)

                wp_str = f"WP {waypoint_tracker.current_index + 1}/{len(waypoints_list)} ({guidance.get('distance', 0.0):.0f}m)" if waypoints_list else ""
                cv2.putText(annotated_frame, f"ACT: {decision} {wp_str}", (10, 26),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.52, dec_color, 2, cv2.LINE_AA)

                cv2.putText(annotated_frame, f"XOR: {xor_pct:.1f}% | TTC: {ttc_str} | {flight_status}", (w - 280, 26),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, (220, 220, 220), 1, cv2.LINE_AA)

                # 3.4) Publicar en StreamHub para WebDCS
                try:
                    # pyrefly: ignore [missing-import]
                    from airsim_plan.bridge.stream_hub import stream_hub
                    stream_hub.publish(
                        frame=annotated_frame,
                        telemetry={
                            "connected": True,
                            "mission_id": manifest_data.get("mission_id", "MISION_ACTIVA"),
                            "decision": decision,
                            "flight_status": flight_status,
                            "estimated_ttc": ttc_val if ttc_val != float("inf") else None,
                            "xor_change_ratio": final_state.get("xor_change_ratio", 0.0),
                            "detections": final_state.get("detections", []),
                            "detected_obstacles": final_state.get("detected_obstacles", []),
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

                # 3.5) Mostrar en ventana local de OpenCV si watch_mode está activo
                if watch_mode:
                    cv2.imshow("Drone Camera Feed", annotated_frame)
                    key = cv2.waitKey(1) & 0xFF
                    if key == ord('q') or key == 27:
                        print("[Watch] Bucle detenido desde la ventana de video.")
                        break

            # 4) Si la misión fue completada, ejecutar secuencia de aterrizaje y devolver control
            if waypoint_tracker.is_completed and waypoints_list:
                print("\n[Misión] ¡Misión completada exitosamente! Iniciando secuencia de aterrizaje autónomo...")
                try:
                    # pyrefly: ignore [missing-import]
                    from airsim_plan.bridge.stream_hub import stream_hub
                    stream_hub.publish(
                        frame=annotated_frame if frame is not None else None,
                        telemetry={
                            "connected": True,
                            "mission_id": manifest_data.get("mission_id", "MISION_ACTIVA"),
                            "decision": "ATERRIZANDO",
                            "flight_status": "aterrizando",
                            "estimated_ttc": None,
                            "xor_change_ratio": 0.0,
                            "detections": [],
                            "detected_obstacles": [],
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
                            "xor_change_ratio": 0.0,
                            "detections": [],
                            "detected_obstacles": [],
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
    finally:
        if watch_mode:
            import cv2
            cv2.destroyAllWindows()
        if airsim_client is not None:
            try:
                airsim_client.disconnect()
            except Exception:  # pragma: no cover
                pass


if __name__ == "__main__":
    main()

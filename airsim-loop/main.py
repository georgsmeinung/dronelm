# Paso 6: Bucle continuo de control autonomo.
# Captura -> percepcion -> gatekeeper -> (reflejo | cerebro) -> motor -> ...
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


def _print_state(state: DroneState) -> None:
    obstacles = state.get("detected_obstacles") or []
    if not obstacles:
        print("  detecciones: ninguna")
    else:
        for obs in obstacles[:5]:
            print(
                f"  - {obs.get('object', '?')} sector={obs.get('sector', '?')} "
                f"proximidad={obs.get('proximity', '?')} "
                f"dist={obs.get('distance_m', '?')}m"
            )
    summary = state.get("scene_summary")
    if summary:
        print(f"  resumen: {summary}")
    print(f"  ruta   : {state.get('route', '')}")
    print(f"  accion : {state.get('next_action', '')}")
    cmd = state.get("velocity_command") or {}
    if cmd:
        print(
            "  motor  : "
            f"vx={cmd.get('vx', 0):+.2f} vy={cmd.get('vy', 0):+.2f} "
            f"vz={cmd.get('vz', 0):+.2f} yaw={cmd.get('yaw_rate', 0):+.2f} "
            f"({cmd.get('rationale', '')})"
        )


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

    # 2) Verificar si se solicitó ver el video
    watch_mode = (os.getenv("AIRSIM_LOOP_WATCH") or globals().get("AIRSIM_LOOP_WATCH", "false")).lower() == "true"
    if watch_mode:
        import cv2
        cv2.namedWindow("Drone Camera Feed", cv2.WINDOW_NORMAL)
        cv2.resizeWindow("Drone Camera Feed", 640, 480)
        print("[Watch] Modo visualización activado. Mostrando señal de video nativa.")

    graph = compile_workflow()
    airsim_client = get_airsim_client()
    sleep_s = 1.0 / max(DEFAULT_LOOP_HZ, 0.01)

    try:
        while True:
            # Verificar si se solicitó detener la misión
            mission_id = manifest_data.get("mission_id", "MOCK_MISSION")
            if os.getenv(f"STOP_MISSION_{mission_id}") == "1":
                print(f"[Ciclo] Detención solicitada para misión {mission_id}. Saliendo del bucle.")
                break

            t0 = time.time()
            print("\n[Ciclo] Capturando sensores y ejecutando grafo...")
            
            # Inyectamos el estado inicial poblado con datos del manifiesto si existen
            initial_state: DroneState = {
                "mission_id": manifest_data.get("mission_id", "MOCK_MISSION"),
                "waypoints": manifest_data.get("waypoints", []),
                "rules_of_engagement": manifest_data.get("rules_of_engagement", {}),
                "tactical_system_prompt": manifest_data.get("tactical_system_prompt") or os.getenv("AIRSIM_PLAN_TACTICAL_PROMPT") or globals().get("AIRSIM_PLAN_TACTICAL_PROMPT") or "",
                "rgb_image": None,
                "telemetry": None,
                "detected_obstacles": [],
                "next_action": "",
                "deliberations": [],
            }
            try:
                final_state = graph.invoke(initial_state)
            except Exception as exc:
                print(f"[Ciclo] Error en el grafo: {exc}")
                time.sleep(sleep_s)
                continue

            _print_state(final_state)

            # 3) Mostrar video localmente si watch_mode está activo
            if watch_mode:
                import cv2
                frame = final_state.get("rgb_image")
                if frame is not None:
                    # Crear copia para anotar sin alterar la imagen original
                    annotated_frame = frame.copy()
                    
                    # 1. Dibujar rectángulos de YOLO y etiquetas de clase/confianza
                    for det in final_state.get("detections", []):
                        bbox = det.get("bbox", [0, 0, 0, 0])
                        obj_name = det.get("object", "objeto")
                        conf = det.get("confidence", 0.0)
                        
                        x_min, y_min, x_max, y_max = map(int, bbox)
                        cv2.rectangle(annotated_frame, (x_min, y_min), (x_max, y_max), (0, 255, 0), 2)
                        
                        label_str = f"{obj_name}: {conf:.2f}"
                        cv2.putText(annotated_frame, label_str, (x_min, max(y_min - 5, 15)),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1, cv2.LINE_AA)
                    
                    # 2. Dibujar la decisión del grafo en la parte superior
                    decision = final_state.get("next_action", "MANTENER_RUMBO")
                    h, w = annotated_frame.shape[:2]
                    cv2.rectangle(annotated_frame, (0, 0), (w, 40), (0, 0, 0), -1)
                    cv2.putText(annotated_frame, f"DECISION: {decision}", (10, 25),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2, cv2.LINE_AA)
                    
                    # 3. Dibujar telemetría (altura, velocidad)
                    tel = final_state.get("telemetry") or {}
                    alt = abs(tel.get("z", 0.0))
                    speed = tel.get("speed", 0.0)
                    cv2.putText(annotated_frame, f"Alt: {alt:.1f}m | Vel: {speed:.1f}m/s", (w - 220, 25),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1, cv2.LINE_AA)
                    
                    cv2.imshow("Drone Camera Feed", annotated_frame)
                    key = cv2.waitKey(1) & 0xFF
                    if key == ord('q') or key == 27:
                        print("[Watch] Bucle detenido desde la ventana de video.")
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

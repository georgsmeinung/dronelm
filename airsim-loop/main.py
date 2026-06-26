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
    graph = compile_workflow()
    airsim_client = get_airsim_client()
    sleep_s = 1.0 / max(DEFAULT_LOOP_HZ, 0.01)

    try:
        while True:
            t0 = time.time()
            print("\n[Ciclo] Capturando sensores y ejecutando grafo...")
            # Inyectamos un estado vacio: el nodo de percepcion se encarga
            # de capturar imagen + telemetria desde AirSim (o modo simulado).
            initial_state: DroneState = {
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
            elapsed = time.time() - t0
            wait = max(0.0, sleep_s - elapsed)
            time.sleep(wait)
    except KeyboardInterrupt:
        print("\nApagando sistema de navegacion.")
    finally:
        if airsim_client is not None:
            try:
                airsim_client.disconnect()
            except Exception:  # pragma: no cover
                pass


if __name__ == "__main__":
    main()

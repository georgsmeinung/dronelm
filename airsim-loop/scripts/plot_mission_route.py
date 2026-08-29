"""Dibuja la ruta de una mision en el viewport de UE, antes de volar.

Pinta la linea de trayectoria, un marcador en cada waypoint y su etiqueta
(WP_1, WP_2, ...) como dibujo de depuracion persistente de AirSim
(simPlotLineStrip/simPlotPoints/simPlotStrings). No arma ni despega el
vehiculo -- es un chequeo visual previo al vuelo, para detectar a simple
vista si la ruta cruza un obstaculo evidente (ver CHANGELOG.md 2026-0827:
el atasco de townsim_a en la copa de un arbol hubiera sido obvio con esto
antes de gastar ciclos de vuelo descubriendolo).

Acepta tanto el formato de mision de airsim-loop/missions/*.json
(mission_id, waypoints, start_pose opcional) como el de
airsim-plan/missions/*.preloop.json (mismo campo "waypoints").

Uso:
    python scripts/plot_mission_route.py missions/townsim_a.json
    python scripts/plot_mission_route.py ../airsim-plan/missions/A_TOWN_MISSION.preloop.json --color 0 1 0 1
    python scripts/plot_mission_route.py missions/townsim_a.json --clear-only   # solo borra dibujos previos
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover
    pass

try:
    import cosysairsim as airsim  # type: ignore
except Exception:  # pragma: no cover
    import airsim  # type: ignore

DEFAULT_IP = os.getenv("AIRSIM_IP", "127.0.0.1")
DEFAULT_PORT = int(os.getenv("AIRSIM_PORT", "41451"))
DEFAULT_VEHICLE = os.getenv("AIRSIM_VEHICLE_NAME", "SimpleFlight")


def load_waypoints(mission_path: str) -> List[Dict[str, Any]]:
    with open(mission_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    waypoints = list(manifest.get("waypoints") or [])
    start_pose = manifest.get("start_pose")
    if start_pose and waypoints:
        # Antepone el punto de partida si el manifiesto lo declara por separado
        # (formato de airsim-loop/missions/*.json), para que la linea dibujada
        # arranque en el spawn real y no en el primer WP.
        first = waypoints[0]
        same_as_first = (
            abs(float(start_pose.get("x", 0.0)) - float(first.get("x", 0.0))) < 0.5
            and abs(float(start_pose.get("y", 0.0)) - float(first.get("y", 0.0))) < 0.5
        )
        if not same_as_first:
            waypoints = [
                {
                    "x": start_pose.get("x", 0.0),
                    "y": start_pose.get("y", 0.0),
                    "z": start_pose.get("z", -10.0),
                    "label": "START",
                },
                *waypoints,
            ]
    return waypoints


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("mission", help="Ruta al manifiesto de mision (.json o .preloop.json)")
    parser.add_argument("--color", nargs=4, type=float, default=[1.0, 0.0, 0.0, 1.0], metavar=("R", "G", "B", "A"),
                         help="Color RGBA de la linea/puntos de RUTA PLANIFICADA, 0.0-1.0 (default: rojo opaco)")
    parser.add_argument("--thickness", type=float, default=12.0, help="Grosor de la linea de ruta")
    parser.add_argument("--point-size", type=float, default=25.0, help="Tamano de los marcadores de waypoint")
    parser.add_argument("--text-scale", type=float, default=8.0, help="Tamano del texto de las etiquetas")
    parser.add_argument("--text-duration", type=float, default=90.0,
                         help="Segundos que dura cada etiqueta de texto (simPlotStrings no admite "
                              "is_persistent -- solo duration -- asi que simFlushPersistentMarkers() NO "
                              "las borra; corridas repetidas en poco tiempo dejan etiquetas viejas "
                              "superpuestas hasta que expira esta duracion)")
    parser.add_argument("--trace-color", nargs=4, type=float, default=[0.0, 1.0, 1.0, 1.0], metavar=("R", "G", "B", "A"),
                         help="Color RGBA de la TRAZA REAL del dron (simSetTraceLine), distinto del de la "
                              "ruta planificada para poder comparar ambas -- default: cyan opaco")
    parser.add_argument("--trace-thickness", type=float, default=6.0, help="Grosor de la traza real del dron")
    parser.add_argument("--vehicle-name", default=DEFAULT_VEHICLE)
    parser.add_argument("--clear-only", action="store_true",
                         help="Solo borra los dibujos persistentes previos, no dibuja nada nuevo")
    parser.add_argument("--simple-labels", action="store_true",
                         help="Etiquetar los waypoints como 1, 2, 3, ..., END en vez de usar el campo "
                              "'label' del manifiesto (util para video/demo, mas legible que WP_X)")
    args = parser.parse_args()

    client = airsim.MultirotorClient(ip=DEFAULT_IP, port=DEFAULT_PORT)
    client.confirmConnection()
    print(f"[plot_mission_route] Conectado a AirSim en {DEFAULT_IP}:{DEFAULT_PORT}")

    # simSetTraceLine solo fija color/grosor -- la traza en si se activa/
    # desactiva apretando 'T' en el viewport de UE (o EnableTrace=true en
    # settings.json, que requiere reiniciar el proyecto). Se fija un color
    # distinto al de la ruta planificada para poder comparar visualmente
    # "donde deberia ir" vs "por donde vuela de verdad" en la misma corrida.
    client.simSetTraceLine(color_rgba=args.trace_color, thickness=args.trace_thickness, vehicle_name=args.vehicle_name)
    print(f"[plot_mission_route] Color de traza configurado ({args.trace_color}). "
          f"Si todavia no esta activa, apreta 'T' en el viewport de UE para activarla.")

    # Siempre limpia dibujos persistentes previos primero -- sin esto, cada
    # corrida se apila sobre las anteriores y el viewport queda ilegible.
    client.simFlushPersistentMarkers()
    print("[plot_mission_route] Dibujos persistentes previos borrados.")

    if args.clear_only:
        return

    waypoints = load_waypoints(args.mission)
    if len(waypoints) < 1:
        print(f"[plot_mission_route] '{args.mission}' no tiene waypoints, nada para dibujar.")
        return

    points = [
        airsim.Vector3r(float(wp.get("x", 0.0)), float(wp.get("y", 0.0)), float(wp.get("z", -10.0)))
        for wp in waypoints
    ]
    if args.simple_labels:
        labels = [str(i + 1) for i in range(len(waypoints))]
        labels[-1] = "END"
    else:
        labels = [str(wp.get("label", f"WP_{i + 1}")) for i, wp in enumerate(waypoints)]

    if len(points) >= 2:
        client.simPlotLineStrip(points, color_rgba=args.color, thickness=args.thickness, is_persistent=True)
    client.simPlotPoints(points, color_rgba=args.color, size=args.point_size, is_persistent=True)
    client.simPlotStrings(labels, points, scale=args.text_scale, color_rgba=[1.0, 1.0, 1.0, 1.0], duration=args.text_duration)

    total_dist = sum(
        points[i].distance_to(points[i + 1]) if hasattr(points[i], "distance_to") else (
            (points[i].x_val - points[i + 1].x_val) ** 2
            + (points[i].y_val - points[i + 1].y_val) ** 2
            + (points[i].z_val - points[i + 1].z_val) ** 2
        ) ** 0.5
        for i in range(len(points) - 1)
    )
    print(f"[plot_mission_route] Ruta dibujada: {len(waypoints)} waypoints ({', '.join(labels)}), "
          f"{total_dist:.1f}m totales. Revisar el viewport de UE antes de volar.")


if __name__ == "__main__":
    main()

"""Plan de ruta con el VLM sobre el mapa cenital, sin volar (src/planning/route_planner.py).

Escribe en --out el manifiesto planificado, plan.json (candidatas, respuesta y probabilidad de cada una,
elegida y motivo), las imagenes que vio el modelo y una vista del plan completo sobre el mapa.
Es lo mismo que hacen runner.py y batch_runner.py antes de la primera corrida de cada escenario.

Uso:
    python experiments/plan_route.py --scenario ../airsim-plan/missions/flightplans/citysim_pilot.json --out ../airsim-runs/route_plans
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.planning.route_planner import MapView, plan_scenario  # noqa: E402


def draw_overview(planned_path: str) -> Path:
    import cv2
    import numpy as np

    m = json.loads(Path(planned_path).read_text(encoding="utf-8"))
    mv = MapView.load(m["map"])
    sp = m.get("start_pose")
    pts = ([(sp["x"], sp["y"], "START")] if sp else []) + [(w["x"], w["y"], w["label"]) for w in m["waypoints"]]
    img = mv.image.copy()
    px = [tuple(int(round(v)) for v in mv.to_px(x, y)) for x, y, _l in pts]
    cv2.polylines(img, [np.int32(px)], False, (0, 0, 255), 3, cv2.LINE_AA)
    for (x, y, label), p in zip(pts, px):
        via = label.startswith("VIA_")
        cv2.circle(img, p, 5 if via else 8, (0, 200, 255) if via else (255, 80, 0), -1)
        if not via:
            cv2.putText(img, label, (p[0] + 8, p[1] - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 4)
            cv2.putText(img, label, (p[0] + 8, p[1] - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
    xs, ys = [p[0] for p in px], [p[1] for p in px]
    pad = 80
    crop = img[max(0, min(ys) - pad):max(ys) + pad, max(0, min(xs) - pad):max(xs) + pad]
    out = Path(planned_path).with_name("plan_overview.png")
    cv2.imwrite(str(out), crop)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scenario", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    planned = plan_scenario(args.scenario, args.out)
    print(f"vista del plan: {draw_overview(planned)}")


if __name__ == "__main__":
    main()

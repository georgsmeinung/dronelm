#!/usr/bin/env python3
"""End-to-end runner: YOLO + AirSim + the tactical LangGraph loop.

Run on the ground station *after* the manifest has been compiled. It owns the
AirSim hand-off (arm + takeoff) and the tactical state machine, then feeds it
a fresh observation every tick.

Usage:
    python scripts/fly_with_yolo.py --manifest manifests/perimeter_north_01.json
    python scripts/fly_with_yolo.py --manifest manifests/perimeter_north_01.json --mock-airsim
    python scripts/fly_with_yolo.py --manifest manifests/perimeter_north_01.json --headless

Requires ``ultralytics`` (``pip install ultralytics``) and ``cosys-airsim``.
Both are optional at import time so the script can be tested with --mock-airsim.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

# Repo-local imports. ``conftest.py`` adds ``src/`` to sys.path for tests; we
# reproduce the same logic here so the script works from a checkout without
# installing the package.
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if SRC.exists() and str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# Local imports (after sys.path tweak)
from airsim_plan.missions.manifest import (  # noqa: E402
    MissionManifest,
    RulesOfEngagement,
    Waypoint,
)
from airsim_plan.bridge.airsim_bridge import AirSimBridge  # noqa: E402
from airsim_plan.config import get_settings  # noqa: E402

# External imports guarded so the script still runs with --mock-airsim.
try:
    import numpy as np  # noqa: E402
    import cv2  # noqa: E402
except Exception as _exc:  # pragma: no cover
    np = None  # type: ignore[assignment]
    cv2 = None  # type: ignore[assignment]
    _NUMPY_CV2_ERR = _exc

try:
    from ultralytics import YOLO  # noqa: E402
    _YOLO_OK = True
except Exception:  # pragma: no cover
    YOLO = None  # type: ignore[assignment]
    _YOLO_OK = False


# --------------------------------------------------------------------------- #
# Observation types                                                           #
# --------------------------------------------------------------------------- #

@dataclass
class YoloDetection:
    label: str
    confidence: float
    bbox_xyxy: tuple[float, float, float, float]


@dataclass
class Observation:
    battery_percent: float
    position: dict[str, float]
    velocity: dict[str, float]
    heading_deg: float
    detections: list[YoloDetection]

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "battery_percent": round(self.battery_percent, 2),
            "position": {k: round(v, 3) for k, v in self.position.items()},
            "velocity": {k: round(v, 3) for k, v in self.velocity.items()},
            "heading_deg": round(self.heading_deg, 2),
            "detections": [
                {
                    "label": d.label,
                    "confidence": round(d.confidence, 3),
                    "bbox_xyxy": [round(v, 1) for v in d.bbox_xyxy],
                }
                for d in self.detections
            ],
        }


# --------------------------------------------------------------------------- #
# Sensors                                                                     #
# --------------------------------------------------------------------------- #

def make_mock_sensor(manifest: MissionManifest):
    """Deterministic sensor for dry-runs / CI / unit tests."""

    state = {"tick": 0}

    def sensor(_state: dict[str, Any] | None = None) -> Observation:
        state["tick"] += 1
        wp = manifest.waypoints[min(state["tick"] // 20, len(manifest.waypoints) - 1)]
        # Pretend the drone is moving toward the current waypoint.
        pos = {"x": wp.x * 0.3, "y": wp.y * 0.3, "z": wp.z}
        # Slow drain so we can verify the RTL safety at low battery.
        battery = max(100.0 - state["tick"] * 0.5, 15.0)
        return Observation(
            battery_percent=battery,
            position=pos,
            velocity={"x": 1.0, "y": 1.0, "z": 0.0},
            heading_deg=0.0,
            detections=[
                YoloDetection("person", 0.78, (120, 80, 200, 240)),
                YoloDetection("car", 0.55, (300, 110, 410, 220)),
            ] if state["tick"] % 5 == 0 else [],
        )

    return sensor


def make_airsim_yolo_sensor(
    client: Any,
    vehicle: str,
    *,
    model_path: str = "yolov8n.pt",
    conf: float = 0.35,
    imgsz: int = 640,
    camera_name: str = "0",
):
    """Real sensor: grab AirSim RGB frame + telemetry, run YOLO."""

    if not _YOLO_OK:
        raise RuntimeError(
            "ultralytics not installed. Run `pip install ultralytics` or pass --mock-airsim."
        )
    if np is None or cv2 is None:
        raise RuntimeError(
            f"numpy/opencv required for the live sensor ({_NUMPY_CV2_ERR})."
        )
    import airsim  # local import; cosys-airsim only needed when really flying

    model = YOLO(model_path)
    ignore_classes = {c.strip().lower() for c in
                      os.environ.get("DEFAULT_IGNORE_CLASSES", "person,car").split(",")
                      if c.strip()}

    def sensor(_state: dict[str, Any] | None = None) -> Observation:
        # 1) RGB frame from AirSim
        raw = client.simGetImage(camera_name, airsim.ImageType.Scene, vehicle_name=vehicle)
        img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            raise RuntimeError("AirSim returned an empty frame; is the camera enabled?")

        # 2) YOLO inference
        results = model.predict(img, verbose=False, conf=conf, imgsz=imgsz)
        detections: list[YoloDetection] = []
        for r in results:
            names = r.names
            for i in range(len(r.boxes)):
                cls_id = int(r.boxes.cls[i])
                label = str(names[cls_id])
                if label.lower() in ignore_classes:
                    continue
                x1, y1, x2, y2 = (float(v) for v in r.boxes.xyxy[i].tolist())
                detections.append(
                    YoloDetection(label, float(r.boxes.conf[i]),
                                  (x1, y1, x2, y2))
                )

        # 3) Telemetry
        s = client.getMultirotorState(vehicle_name=vehicle)
        pos = s.kinematics_estimated.position
        vel = s.kinematics_estimated.linear_velocity
        battery = float(getattr(s, "battery_percent", 100.0) or 100.0)
        orientation = s.kinematics_estimated.orientation
        # Convert quaternion (w, x, y, z) -> yaw degrees.
        w, x, y, z = orientation.w_val, orientation.x_val, orientation.y_val, orientation.z_val
        siny_cosp = 2.0 * (w * z + x * y)
        cosy_cosp = 1.0 - 2.0 * (y * y + z * z)
        import math
        heading = math.degrees(math.atan2(siny_cosp, cosy_cosp))

        return Observation(
            battery_percent=battery,
            position={"x": pos.x_val, "y": pos.y_val, "z": pos.z_val},
            velocity={"x": vel.x_val, "y": vel.y_val, "z": vel.z_val},
            heading_deg=heading,
            detections=detections,
        )

    return sensor


# --------------------------------------------------------------------------- #
# Tactical state machine (local reimplementation that talks airsim-loop)       #
# --------------------------------------------------------------------------- #
#
# ``airsim-loop`` is the package that owns the LangGraph workflow. We import
# ``compile_workflow`` and ``DroneState`` lazily so this script also works in
# environments where ``airsim-loop`` isn't installed (use --dry-loop).

class TacticalController:
    """Wrap the LangGraph workflow with helpers the runner needs.

    Falls back to a deterministic state machine when ``airsim_loop`` is not
    available so the script remains useful for smoke tests.
    """

    def __init__(self, manifest: MissionManifest, *, dry_loop: bool = False) -> None:
        self.manifest = manifest
        self.dry_loop = dry_loop
        self.next_waypoint_index = 0
        self.scratchpad = ""
        self.mission_complete = False
        self._graph = None
        self._initial_state: dict[str, Any] | None = None
        if not dry_loop:
            try:
                import airsim_loop  # noqa: F401
                loop = airsim_loop
                self._graph = loop.compile_workflow()
                self._initial_state = {
                    "mission_id": manifest.mission_id,
                    "waypoints": [w.model_dump() for w in manifest.waypoints],
                    "rules_of_engagement": manifest.rules_of_engagement.model_dump(),
                    "tactical_system_prompt": manifest.tactical_system_prompt or "",
                }
            except Exception as exc:  # pragma: no cover
                print(f"[fly_with_yolo] airsim_loop unavailable ({exc}); using dry-loop.")
                self.dry_loop = True

    # ------------------------------------------------------------------ #
    def current_waypoint(self) -> Waypoint:
        return self.manifest.waypoints[self.next_waypoint_index]

    def reached(self, position: dict[str, float], radius: float = 3.0) -> bool:
        wp = self.current_waypoint()
        dx = wp.x - position["x"]
        dy = wp.y - position["y"]
        dz = wp.z - position["z"]
        return (dx * dx + dy * dy + dz * dz) ** 0.5 <= radius

    def advance(self) -> bool:
        self.next_waypoint_index += 1
        if self.next_waypoint_index >= len(self.manifest.waypoints):
            self.mission_complete = True
            return False
        return True

    # ------------------------------------------------------------------ #
    def step(self, observation: Observation) -> dict[str, Any]:
        # Hard safety overrides — the SLM cannot negotiate these.
        rtl_threshold = self.manifest.rules_of_engagement.return_to_launch_battery_threshold
        if observation.battery_percent <= rtl_threshold:
            self.scratchpad = "battery critical -> RTL"
            self.mission_complete = True
            return {"macro_action": "RETURN_TO_LAUNCH", "rationale": "battery critical"}

        if self.dry_loop or self._graph is None:
            return self._dry_decision(observation)

        # Drive the real LangGraph workflow.
        state = dict(self._initial_state or {})
        state["telemetry"] = observation.to_jsonable()
        state["scratchpad"] = self.scratchpad
        state["next_waypoint_index"] = self.next_waypoint_index
        try:
            new_state = self._graph.invoke(state)
        except Exception as exc:  # pragma: no cover - graph runtime
            print(f"[fly_with_yolo] graph.invoke failed: {exc}")
            return {"macro_action": "MANTENER_RUMBO", "rationale": f"graph error: {exc}"}
        self.scratchpad = new_state.get("scratchpad", self.scratchpad)
        return new_state.get("last_decision", {"macro_action": "MANTENER_RUMBO",
                                                "rationale": "noop"})

    def _dry_decision(self, observation: Observation) -> dict[str, Any]:
        # Pretend the SLM:
        #   * goes straight to the next waypoint when the path is clear,
        #   * dodges anything not on the ignore list,
        #   * lands when nothing is left to do.
        if not observation.detections:
            wp = self.current_waypoint()
            return {
                "macro_action": "MANTENER_RUMBO",
                "rationale": f"path clear, heading to wp#{self.next_waypoint_index} "
                             f"[{wp.x:.0f},{wp.y:.0f},{wp.z:.0f}]",
            }
        # Find the closest non-ignored detection.
        target = min(observation.detections, key=lambda d: d.bbox_xyxy[0])
        return {
            "macro_action": "EVADIR_DERECHA",
            "rationale": f"obstacle {target.label}@{target.confidence:.2f}; sidestep",
        }


# --------------------------------------------------------------------------- #
# Action -> AirSim command                                                    #
# --------------------------------------------------------------------------- #

MACRO_TO_VEL = {
    "MANTENER_RUMBO":   (1.0,  0.0, 0.0, 0.0),
    "EVADIR_IZQUIERDA": (-1.0,  0.0, 0.0, 0.0),
    "EVADIR_DERECHA":   ( 1.0,  0.0, 0.0, 0.0),
    "GANAR_ALTURA":     ( 0.0,  0.0, 1.0, 0.0),
    "PERDER_ALTURA":    ( 0.0,  0.0,-1.0, 0.0),
    "FRENAR":           ( 0.0,  0.0, 0.0, 0.0),
}


def action_to_velocity(action: dict[str, Any]) -> tuple[float, float, float, float]:
    name = action.get("macro_action", "MANTENER_RUMBO")
    if name == "RETURN_TO_LAUNCH":
        return (0.0, 0.0, 0.0, 0.0)  # RTL handled by the runner, not velocity stream
    return MACRO_TO_VEL.get(name, (0.0, 0.0, 0.0, 0.0))


# --------------------------------------------------------------------------- #
# Main loop                                                                   #
# --------------------------------------------------------------------------- #

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="fly_with_yolo",
        description="End-to-end runner: YOLO + AirSim + tactical LangGraph.",
    )
    parser.add_argument("--manifest", type=Path, required=True,
                        help="Path to the compiled MissionManifest JSON.")
    parser.add_argument("--mock-airsim", action="store_true",
                        help="Use the deterministic sensor (no AirSim needed).")
    parser.add_argument("--dry-loop", action="store_true",
                        help="Skip airsim_loop and use the built-in dry-loop.")
    parser.add_argument("--headless", action="store_true",
                        help="Connect to AirSim but do not call takeoff (for sensor debugging).")
    parser.add_argument("--yolo-model", default="yolov8n.pt",
                        help="Ultralytics model path or name (default: yolov8n.pt).")
    parser.add_argument("--conf", type=float, default=0.35,
                        help="YOLO confidence threshold.")
    parser.add_argument("--hz", type=float, default=2.0,
                        help="Loop frequency in Hz.")
    parser.add_argument("--max-ticks", type=int, default=600,
                        help="Safety cap on tick count.")
    parser.add_argument("--log", type=Path, default=Path("missions/fly_with_yolo.log.jsonl"),
                        help="Where to append per-tick JSONL logs.")
    args = parser.parse_args(argv)

    manifest = MissionManifest.from_json(args.manifest.read_text(encoding="utf-8"))
    settings = get_settings()
    print(f"[fly_with_yolo] mission={manifest.mission_id} "
          f"waypoints={len(manifest.waypoints)} mock_airsim={args.mock_airsim}")

    bridge: Optional[AirSimBridge] = None
    sensor = None
    if args.mock_airsim:
        sensor = make_mock_sensor(manifest)
    else:
        bridge = AirSimBridge(settings=settings)
        if not bridge.connect():
            print("[fly_with_yolo] AirSim unavailable; aborting.")
            return 2
        sensor = make_airsim_yolo_sensor(
            bridge._client,  # type: ignore[attr-defined]
            settings.airsim_vehicle_name,
            model_path=args.yolo_model,
            conf=args.conf,
        )

    if bridge is not None and not args.headless:
        bridge.takeoff(altitude=manifest.waypoints[0].z)

    controller = TacticalController(manifest, dry_loop=args.dry_loop)
    args.log.parent.mkdir(parents=True, exist_ok=True)
    log_fp = args.log.open("a", encoding="utf-8")

    period = 1.0 / max(args.hz, 0.1)
    last_action: dict[str, Any] = {"macro_action": "MANTENER_RUMBO", "rationale": "init"}
    try:
        for tick in range(args.max_ticks):
            t0 = time.time()
            observation = sensor({"tick": tick})
            if controller.reached(observation.position):
                if not controller.advance():
                    print(f"[fly_with_yolo] tick={tick} all waypoints reached; landing.")
                    break
            decision = controller.step(observation)
            last_action = decision
            record = {
                "tick": tick,
                "ts": round(t0, 3),
                "observation": observation.to_jsonable(),
                "decision": decision,
                "next_waypoint_index": controller.next_waypoint_index,
            }
            log_fp.write(json.dumps(record) + "\n")
            log_fp.flush()
            print(
                f"tick={tick:03d} batt={observation.battery_percent:5.1f}% "
                f"pos=({observation.position['x']:6.1f},{observation.position['y']:6.1f},"
                f"{observation.position['z']:5.1f}) "
                f"dets={len(observation.detections):2d} "
                f"action={decision.get('macro_action','?'):<18} "
                f"why={decision.get('rationale','')!r}",
                flush=True,
            )
            if bridge is not None and not args.headless:
                _dispatch_action(bridge, settings.airsim_vehicle_name,
                                 controller, decision, observation)
            if controller.mission_complete:
                print(f"[fly_with_yolo] tick={tick} mission_complete; stopping.")
                break
            time.sleep(max(0.0, period - (time.time() - t0)))
    except KeyboardInterrupt:
        print("\n[fly_with_yolo] KeyboardInterrupt — stopping.")
    finally:
        log_fp.close()
        if bridge is not None:
            try:
                if last_action.get("macro_action") == "RETURN_TO_LAUNCH" or controller.mission_complete:
                    bridge.land()
                else:
                    bridge.land()
            except Exception as exc:  # pragma: no cover
                print(f"[fly_with_yolo] land failed: {exc}")
            bridge.disconnect()
    return 0


def _dispatch_action(bridge: AirSimBridge, vehicle: str,
                     controller: TacticalController, decision: dict[str, Any],
                     observation: Observation) -> None:
    name = decision.get("macro_action", "MANTENER_RUMBO")
    client = bridge._client  # type: ignore[attr-defined]
    if name == "RETURN_TO_LAUNCH":
        wp0 = controller.manifest.waypoints[0]
        client.moveToPositionAsync(wp0.x, wp0.y, wp0.z, 6.0, vehicle_name=vehicle).join()
        return
    if name == "EVADIR_IZQUIERDA" or name == "EVADIR_DERECHA":
        # Quick horizontal shove while the SLM recomputes.
        vx, vy, vz, _ = action_to_velocity(decision)
        client.moveByVelocityAsync(vx * 2.0, vy * 2.0, vz, 0.6,
                                   vehicle_name=vehicle).join()
        return
    if name in {"GANAR_ALTURA", "PERDER_ALTURA"}:
        vx, vy, vz, _ = action_to_velocity(decision)
        client.moveByVelocityAsync(vx, vy, vz, 0.6, vehicle_name=vehicle).join()
        return
    if name == "FRENAR":
        client.hoverAsync(vehicle_name=vehicle).join()
        return
    # Default: MANTENER_RUMBO -> keep cruising toward the next waypoint.
    wp = controller.current_waypoint()
    speed = controller.manifest.rules_of_engagement.max_speed_mps or 5.0
    client.moveToPositionAsync(wp.x, wp.y, wp.z, speed, vehicle_name=vehicle)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

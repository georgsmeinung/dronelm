"""Le entrega el manifiesto compilado a ``airsim-loop``.

``airsim-loop`` es un paquete Python separado con su propio grafo, pero
exporta ``compile_workflow`` y ``DroneState``. Lo invocamos in-process si
es importable; si no, caemos a ``python -m`` como subproceso.

:class:`LoopRunner` centraliza tres cosas:

* El pre-vuelo de AirSim (delegado a :class:`AirSimBridge`).
* La inyección de pre-prompt (paso 3 del pipeline).
* Correr el lazo táctico hasta ``RETURN_TO_LAUNCH`` o KeyboardInterrupt.
"""
from __future__ import annotations

import importlib
import runpy
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

from ..config import Settings, get_settings
from ..missions.manifest import MissionManifest
from .airsim_bridge import AirSimBridge, BridgeError


class LoopRunnerError(RuntimeError):
    """Se lanza cuando el lazo táctico no puede iniciarse."""


class LoopRunner:
    """Coordina el pre-vuelo de AirSim + la invocación de ``airsim-loop``."""

    LOOP_PACKAGE = "airsim_loop"

    def __init__(
        self,
        manifest: MissionManifest,
        *,
        bridge: Optional[AirSimBridge] = None,
        settings: Optional[Settings] = None,
        loop_path: Optional[Path] = None,
        loop_hz: float = 0.5,
    ) -> None:
        self._manifest = manifest
        self._settings = settings or get_settings()
        self._bridge = bridge or AirSimBridge(settings=self._settings)
        self._loop_path = loop_path  # si es None, usamos import in-process
        self._loop_hz = max(loop_hz, 0.05)

    # ------------------------------------------------------------------ #
    # Propiedades                                                       #
    # ------------------------------------------------------------------ #
    @property
    def manifest(self) -> MissionManifest:
        return self._manifest

    @property
    def bridge(self) -> AirSimBridge:
        return self._bridge

    def stop(self) -> None:
        """Solicita la detención de la misión en ejecución."""
        import os
        os.environ[f"STOP_MISSION_{self._manifest.mission_id}"] = "1"

    # ------------------------------------------------------------------ #
    # Inyección de pre-prompt                                           #
    # ------------------------------------------------------------------ #
    def build_initial_state(self) -> Dict[str, Any]:
        """Arma el ``DroneState`` inicial inyectado en ``airsim-loop``."""
        return {
            "mission_id": self._manifest.mission_id,
            "waypoints": [w.model_dump() for w in self._manifest.waypoints],
        }

    # ------------------------------------------------------------------ #
    # API pública                                                       #
    # ------------------------------------------------------------------ #
    def run(self, *, takeoff_altitude: Optional[float] = None) -> None:
        """Despega y conduce el lazo táctico hasta que se interrumpa."""
        import os
        os.environ.pop(f"STOP_MISSION_{self._manifest.mission_id}", None)
        try:
            self._bridge.hand_off(altitude=takeoff_altitude)
        except BridgeError as exc:
            raise LoopRunnerError(str(exc)) from exc

        initial_state = self.build_initial_state()
        try:
            if self._loop_path is not None:
                self._run_as_subprocess(initial_state)
            else:
                self._run_in_process(initial_state)
        finally:
            try:
                self._bridge.land()
            except BridgeError:  # pragma: no cover
                pass
            self._bridge.disconnect()

    # ------------------------------------------------------------------ #
    # Ejecución in-process                                              #
    # ------------------------------------------------------------------ #
    def _run_in_process(self, initial_state: Dict[str, Any]) -> None:
        try:
            loop_module = importlib.import_module(self.LOOP_PACKAGE)
        except Exception as exc:
            raise LoopRunnerError(
                f"Could not import {self.LOOP_PACKAGE!r} in-process "
                f"({exc}). Pass `loop_path` to fall back to subprocess."
            ) from exc

        if not hasattr(loop_module, "compile_workflow"):
            raise LoopRunnerError(
                f"{self.LOOP_PACKAGE!r} does not expose compile_workflow()."
            )

        graph = loop_module.compile_workflow()
        sleep_s = 1.0 / self._loop_hz
        print(
            f"[LoopRunner] Entering tactical loop "
            f"(mission={self._manifest.mission_id}, hz={self._loop_hz})."
        )
        try:
            while True:
                t0 = time.time()
                try:
                    state = graph.invoke(dict(initial_state))
                except Exception as exc:  # pragma: no cover - graph runtime
                    print(f"[LoopRunner] graph.invoke failed: {exc}")
                    time.sleep(sleep_s)
                    continue
                action = state.get("next_action", "")
                if action == "RETURN_TO_LAUNCH":
                    print("[LoopRunner] RETURN_TO_LAUNCH received. Stopping loop.")
                    break
                elapsed = time.time() - t0
                time.sleep(max(0.0, sleep_s - elapsed))
        except KeyboardInterrupt:
            print("\n[LoopRunner] KeyboardInterrupt — stopping loop.")

    # ------------------------------------------------------------------ #
    # Fallback a subproceso                                             #
    # ------------------------------------------------------------------ #
    def _run_as_subprocess(self, initial_state: Dict[str, Any]) -> None:
        import os
        import subprocess
        import sys
        
        script = Path(self._loop_path).resolve()
        if not script.exists():
            raise LoopRunnerError(f"loop script not found: {script}")
            
        env_path = self._settings.mission_dir / f"{self._manifest.mission_id}.preloop.json"
        env_path.parent.mkdir(parents=True, exist_ok=True)
        env_path.write_text(
            self._manifest.to_json(indent=2), encoding="utf-8"
        )
        
        # Preparar las variables de entorno para el nuevo proceso
        env = os.environ.copy()
        env["AIRSIM_PLAN_MANIFEST"] = str(env_path)

        try:
            # Lanzar el script del loop en un proceso del SO completamente aislado, con salida sin buffer (-u)
            process = subprocess.Popen(
                [sys.executable, "-u", str(script)],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1  # buffer por línea
            )

            # Imprimir la salida en tiempo real directo a sys.stdout
            if process.stdout:
                for line in process.stdout:
                    sys.stdout.write(line)
                    sys.stdout.flush()
                    
            process.wait()
            if process.returncode not in (None, 0):
                raise LoopRunnerError(f"loop process exited with code {process.returncode}")
        except Exception as exc:
            raise LoopRunnerError(f"Failed to execute loop subprocess: {exc}") from exc

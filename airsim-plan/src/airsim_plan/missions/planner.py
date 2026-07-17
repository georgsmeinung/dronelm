"""High-level Mission Planner (NL -> Manifest)."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from ..config import Settings, get_settings
from ..llm import (
    LMStudioClient,
    PlannerLLM,
    extract_json_object,
    looks_like_manifest,
)
from .manifest import MissionManifest


class PlannerError(RuntimeError):
    """Se lanza cuando el planificador no puede producir un :class:`MissionManifest` válido."""


class MissionPlanner:
    """Traduce una instrucción en lenguaje natural a un :class:`MissionManifest`.

    El planificador posee:

    * El mensaje del sistema de la estación terrestre (cargado desde``airsim_plan/prompts/compiler_system.md``).
    * El :class:`LMStudioClient` utilizado para comunicarse con el modelo.
    * La plantilla del mensaje del sistema táctico + la ampliación del manifiesto.
    * Persistencia en disco (``MISSION_DIR``).
    """

    DEFAULT_TACTICAL_PROMPT_PATH = (
        Path(__file__).resolve().parent.parent / "prompts" / "tactical_system.md"
    )

    def __init__(
        self,
        *,
        client: Optional[LMStudioClient] = None,
        settings: Optional[Settings] = None,
        compiler_prompt: Optional[str] = None,
        tactical_prompt_template: Optional[str] = None,
        llm: Optional[PlannerLLM] = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._client = client or LMStudioClient(settings=self._settings)
        self._compiler_prompt = compiler_prompt or self._load_compiler_prompt()
        self._tactical_template = (
            tactical_prompt_template or self._load_tactical_template()
        )
        # `llm` is injected by tests; otherwise we build a default one per
        # compile() call so callers can swap the model cheaply.
        self._llm_override = llm

    # ------------------------------------------------------------------ #
    # Prompt loaders                                                    #
    # ------------------------------------------------------------------ #
    @staticmethod
    def _package_prompt_path(name: str) -> Path:
        return Path(__file__).resolve().parent.parent / "prompts" / name

    def _load_compiler_prompt(self) -> str:
        path = self._package_prompt_path("compiler_system.md")
        if not path.exists():
            raise PlannerError(
                f"Compiler system prompt missing at {path}. Reinstall the package."
            )
        return path.read_text(encoding="utf-8")

    def _load_tactical_template(self) -> str:
        path = self.DEFAULT_TACTICAL_PROMPT_PATH
        if not path.exists():
            raise PlannerError(
                f"Tactical prompt template missing at {path}. Reinstall the package."
            )
        return path.read_text(encoding="utf-8")

    # ------------------------------------------------------------------ #
    # Public API                                                        #
    # ------------------------------------------------------------------ #
    @property
    def settings(self) -> Settings:
        return self._settings

    @property
    def client(self) -> LMStudioClient:
        return self._client

    def _build_llm(self) -> PlannerLLM:
        if self._llm_override is not None:
            return self._llm_override
        return PlannerLLM(system_prompt=self._compiler_prompt, client=self._client)

    def compile(self, instruction: str) -> MissionManifest:
        """Traduce ``instruction`` (NL) a un :class:`MissionManifest` validado.

        Lanza :class:`PlannerError` si el modelo es inalcanzable, la respuesta
        no es analizable o la carga falla la validación del manifiesto.
        """
        if not instruction or not instruction.strip():
            raise PlannerError("La instrucción está vacía.")

        llm = self._build_llm()
        response = llm.complete(instruction.strip())
        content = response.content if isinstance(response.content, str) else ""
        payload = extract_json_object(content)
        if payload is None or not looks_like_manifest(payload):
            raise PlannerError(
                "Planner response did not contain a manifest-shaped JSON. "
                f"Raw content: {content[:300]!r}"
            )

        manifest = MissionManifest.from_dict(payload)
        manifest.tactical_system_prompt = self.build_tactical_prompt(manifest)
        return manifest

    def compile_and_save(
        self,
        instruction: str,
        *,
        filename: Optional[str] = None,
    ) -> tuple[MissionManifest, Path]:
        """Conveniencia: :meth:`compile` luego persiste bajo ``MISSION_DIR``."""
        manifest = self.compile(instruction)
        target_dir = self._settings.mission_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        name = filename or f"{manifest.mission_id.lower()}.json"
        path = target_dir / name
        from .manifest import save_manifest  # local import to avoid cycles

        save_manifest(manifest, path)
        return manifest, path

    # ------------------------------------------------------------------ #
    # Tactical prompt builder                                           #
    # ------------------------------------------------------------------ #
    def build_tactical_prompt(self, manifest: MissionManifest) -> str:
        """Componer el mensaje del sistema entregado a ``airsim-loop``.

        El paso 3 del pipeline: el Manifiesto se convierte en un *pre-prompt* que
        el SLM en vuelo recibe en cada ciclo, junto con YOLO/telemetría.
        """
        roe = manifest.rules_of_engagement
        target_waypoint = manifest.waypoints[-1]
        ignore_str = ", ".join(roe.ignore_objects) if roe.ignore_objects else "(ninguna)"
        return (
            self._tactical_template.format(
                rtl_battery_threshold=roe.return_to_launch_battery_threshold,
                ignore_objects=ignore_str,
            )
            + "\n\n"
            f"MISION ACTIVA: {manifest.mission_id}\n"
            f"Objetivo final (waypoint #{len(manifest.waypoints)}): "
            f"[{target_waypoint.x}, {target_waypoint.y}, {target_waypoint.z}]"
            + (f" ({target_waypoint.label})" if target_waypoint.label else "")
            + "\nWaypoints pendientes (en orden): "
            + "; ".join(
                f"#{i + 1}[{w.x},{w.y},{w.z}]" for i, w in enumerate(manifest.waypoints)
            )
            + "\n"
        )

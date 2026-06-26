# Changelog — airsim-plan

All notable changes to the ground-station Mission Planner are documented here.

## [0.1.0] - 2026-06-26

### Added
- Modular Python package layout under `src/airsim_plan/` with `pyproject.toml`.
- `MissionManifest` Pydantic model + bundled JSON Schema (`schemas/manifest_schema.json`).
- `MissionPlanner` (NL -> Manifest) backed by LM Studio / Ollama via the OpenAI SDK.
- Robust JSON extraction that handles Markdown fences and concatenated objects.
- `AirSimBridge` (arm + takeoff) and `LoopRunner` that injects the manifest into
  `airsim-loop` (in-process or subprocess).
- Typer CLI: `plan`, `validate`, `show`, `prompt`, `takeoff`, `run`,
  `interactive`, `dump-schema`.
- System prompts (`prompts/compiler_system.md`, `prompts/tactical_system.md`).
- `examples/perimeter_north_01.json` plus `missions/` output directory.
- 37 pytest tests covering schema, planner, bridge, runner, CLI, and config.

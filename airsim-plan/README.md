# airsim-plan — Ground-Station Mission Planner

> Translates natural-language instructions into a structured **Mission Manifest** that
> the in-flight tactical SLM (in [`/airsim-loop`](../airsim-loop)) can execute.

This package implements the **ground half** of the two-brain architecture: it runs
**before** the drone takes off, can take 5–10 seconds to think, and produces a JSON
contract the tactical brain obeys during the flight.

```
NL instruction  ──►  MissionPlanner  ──►  MissionManifest.json
                                              │
                                              ▼
                              airsim-loop (LangGraph + Phi-3)
                                              │
                                              ▼
                                           AirSim
```

The package is intentionally framework-light: Pydantic for the schema, the official
`openai` SDK for talking to LM Studio/Ollama, and Typer + Rich for the CLI.

## Why a separate planner?

* The flight SLM (Phi-3 on a Jetson Nano) is latency-bound; it cannot afford to
  design missions.
* LM Studio can serve the same Llama-3-8B locally without any extra setup.
* Decoupling lets us validate, persist, and version missions *before* liftoff.

## Layout

```
airsim-plan/
├── pyproject.toml
├── requirements.txt
├── .env.example
├── examples/
│   └── perimeter_north_01.json
├── missions/                       # output dir (one .json per compiled mission)
├── src/airsim_plan/
│   ├── __init__.py
│   ├── config.py                   # Settings (env-backed)
│   ├── llm/
│   │   ├── client.py               # LMStudioClient + PlannerLLM
│   │   └── json_extract.py         # JSON coercion for SLM output
│   ├── missions/
│   │   ├── manifest.py             # MissionManifest (Pydantic)
│   │   └── planner.py              # MissionPlanner (NL -> Manifest)
│   ├── bridge/
│   │   ├── airsim_bridge.py        # AirSim hand-off (arm + takeoff)
│   │   └── loop_runner.py          # Injects manifest into airsim-loop
│   ├── cli/main.py                 # Typer CLI (`airsim-plan …`)
│   ├── prompts/
│   │   ├── compiler_system.md      # Step 2 system prompt
│   │   └── tactical_system.md      # Step 3 system-prompt template
│   └── schemas/manifest_schema.json
└── tests/                          # pytest, 37 tests
```

## Installation

```bash
cd airsim-plan
python -m pip install -r requirements.txt
# or, in editable mode:
python -m pip install -e .
```

Copy `.env.example` to `.env` and adjust `LMSTUDIO_*` and `AIRSIM_*` values.

## CLI

After `pip install -e .` you get the `airsim-plan` entrypoint.

| Command | Purpose |
| --- | --- |
| `airsim-plan plan -i "…"` | Compile a manifest from NL and save it under `missions/`. |
| `airsim-plan validate manifest.json` | Validate a manifest against the Pydantic + JSON Schema. |
| `airsim-plan show manifest.json` | Pretty-print the manifest and its tactical prompt. |
| `airsim-plan prompt manifest.json` | Print only the tactical system prompt that would be injected. |
| `airsim-plan takeoff -a -10` | Just arm + takeoff (no SLM loop). |
| `airsim-plan run -i "…"` | Full hand-off: compile, takeoff, invoke `airsim-loop`. |
| `airsim-plan run -m manifest.json --dry-run` | Compile + show without invoking anything. |
| `airsim-plan interactive` | Tiny REPL: compile, edit, save, launch. |
| `airsim-plan dump-schema -o schema.json` | Export the JSON Schema. |

`run` injects the compiled manifest into `airsim-loop` either **in-process** (when
the package is importable as `airsim_loop`) or as a **subprocess** when you pass
`--loop-path /path/to/airsim-loop/main.py`.

## Mission Manifest shape

```json
{
  "mission_id": "PERIMETER_NORTH_01",
  "summary": "Recorre el perimetro norte hasta [50, 100, -10] ignorando personas y vehiculos.",
  "waypoints": [
    {"x": 0,  "y": 50,  "z": -10, "label": "north_edge"},
    {"x": 50, "y": 100, "z": -10, "label": "target"}
  ],
  "rules_of_engagement": {
    "ignore_objects": ["person", "car"],
    "return_to_launch_battery_threshold": 20.0,
    "max_speed_mps": 5.0,
    "min_altitude_m": -10.0
  },
  "tactical_system_prompt": "Eres el navegador tactico …"
}
```

See [`src/airsim_plan/schemas/manifest_schema.json`](src/airsim_plan/schemas/manifest_schema.json)
for the formal contract.

## Tests

```bash
python -m pytest -q
```

37 tests cover schema validation, JSON extraction, planner error paths, the bridge
dry-run, and CLI smoke tests.

## Programmatic API

```python
from airsim_plan import MissionPlanner

planner = MissionPlanner()
manifest, path = planner.compile_and_save(
    "Revisa el perimetro de la zona industrial norte (X:50, Y:100). "
    "Si ves personas, ignóralas. Si la batería cae por debajo del 20%, "
    "regresa inmediatamente a la base."
)
print(manifest.mission_id, path)
```

To hand off to AirSim + airsim-loop:

```python
from airsim_plan import MissionPlanner
from airsim_plan.bridge import LoopRunner

manifest = MissionPlanner().compile("...")
LoopRunner(manifest).run(takeoff_altitude=-10.0)
```

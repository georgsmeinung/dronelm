# Fase H0 (PLAN-MEJORAS-3): guardia arquitectonica de la exclusion total de
# profundidad. Va primero, antes de que exista codigo nuevo (H1/H2) que
# pueda violarla por accidente -- que es exactamente lo que casi paso en la
# conversacion de diseno que origino este plan (ver PLAN-MEJORAS-3.md §0).
#
# Este test es puramente estatico (lee cada archivo como texto): no importa
# ningun modulo, asi que corre incluso sin las dependencias opcionales
# (cosysairsim, openai, cv2) instaladas.
from __future__ import annotations

from pathlib import Path
from typing import List

REPO_ROOT = Path(__file__).resolve().parent.parent

# Lista blanca (§H0.1): modulos de vuelo. Deben quedar libres de
# `return_depth=True` (o con espacios) y de `DepthPlanar`, tanto en codigo
# como en comentarios que documenten una llamada real.
FLIGHT_WHITELIST: List[str] = [
    "main.py",
    "src/agents/__init__.py",
    "src/agents/action_map.py",
    "src/agents/deep_scan.py",
    "src/agents/deliberation_service.py",
    "src/agents/deliberative.py",
    "src/agents/evasive.py",
    "src/agents/fsm.py",
    "src/agents/graph.py",
    "src/agents/reactive.py",
    "src/agents/spatial_scan.py",
    "src/perception/__init__.py",
    "src/perception/flow_ttc.py",
    "src/perception/obstacle_field.py",
    "src/navigation/waypoint_tracker.py",
]

# Lista de excepcion (§0.2): instrumentacion de laboratorio, corre offline en
# scripts separados del grafo. Nunca se realimenta al control.
DEPTH_EXCEPTION_LIST: List[str] = [
    "experiments/collect_ttc_dataset.py",
    "experiments/analyze_ttc.py",
    "experiments/analyze_occupancy.py",
    "experiments/runner.py",
]

_FORBIDDEN_PATTERNS = ("return_depth=True", "return_depth = True", "DepthPlanar")


def _read(rel_path: str) -> str:
    path = REPO_ROOT / rel_path
    assert path.exists(), f"Archivo de la lista blanca no encontrado: {rel_path}"
    return path.read_text(encoding="utf-8")


def test_flight_modules_never_read_depth():
    offenders = {}
    for rel_path in FLIGHT_WHITELIST:
        text = _read(rel_path)
        hits = [p for p in _FORBIDDEN_PATTERNS if p in text]
        if hits:
            offenders[rel_path] = hits
    assert not offenders, f"Modulos de vuelo con lectura de profundidad: {offenders}"


def test_flight_module_whitelist_covers_every_flight_source_file():
    """Ningun modulo de vuelo nuevo puede agregarse sin pasar por esta guardia.

    Cualquier .py bajo src/agents/ o src/perception/ que no este en
    FLIGHT_WHITELIST hace fallar este test -- fuerza a sumarlo explicitamente
    (y a que test_flight_modules_never_read_depth lo escanee) en vez de que
    quede afuera por omision.
    """
    whitelist_set = set(FLIGHT_WHITELIST)
    missing = []
    for sub_dir in ("src/agents", "src/perception"):
        for path in sorted((REPO_ROOT / sub_dir).glob("*.py")):
            rel = path.relative_to(REPO_ROOT).as_posix()
            if rel not in whitelist_set:
                missing.append(rel)
    assert not missing, f"Modulos de vuelo sin declarar en FLIGHT_WHITELIST: {missing}"


def test_depth_exception_files_exist_and_are_documented():
    """La lista de excepcion (§0.2) tiene que seguir apuntando a archivos
    reales -- si uno se borra o se renombra, la excepcion debe actualizarse
    a mano en vez de quedar como documentacion muerta."""
    for rel_path in DEPTH_EXCEPTION_LIST:
        assert (REPO_ROOT / rel_path).exists(), f"Archivo de excepcion no encontrado: {rel_path}"


def test_guard_actually_detects_a_reintroduced_depth_read(tmp_path, monkeypatch):
    """Prueba que la guardia detecta la violacion (H0.3): sin esto, el test
    de arriba podria estar pasando por casualidad (p. ej. un typo en el
    patron buscado) en vez de por ausencia real de lecturas de profundidad."""
    poisoned = tmp_path / "graph.py"
    poisoned.write_text(
        "airsim_client.capture(return_depth=True)\n",
        encoding="utf-8",
    )
    text = poisoned.read_text(encoding="utf-8")
    assert any(p in text for p in _FORBIDDEN_PATTERNS)

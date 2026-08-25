"""F4.1: regenera el .mmd del grafo de control DESDE el grafo compilado
(en vez de mantenerlo a mano), para que la divergencia doc/codigo no pueda
repetirse.

No requiere conexion a AirSim: build_workflow()/compile_workflow() solo
referencian el cliente dentro de closures de nodo, nunca lo invocan durante
la construccion/compilacion del grafo. Se les pasa un cliente "dummy" que
nunca se usa.

Uso:
    python scripts/export_graph_mmd.py
    python scripts/export_graph_mmd.py --out "../informe/2006-0823 Nuevo  Grafo de Control.mmd"
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass


class _DummyAirSimClient:
    """Placeholder: solo se referencia dentro de closures de nodo (motor_node,
    capture_node), nunca se invoca durante build_workflow()/compile_workflow().
    No conecta, no despega, no tiene efecto sobre el simulador.
    """

    def __getattr__(self, name):  # pragma: no cover - nunca deberia llamarse
        raise RuntimeError(
            f"_DummyAirSimClient.{name} invocado: export_graph_mmd.py solo debe "
            "compilar la estructura del grafo, no ejecutarlo."
        )


def main() -> None:
    default_out = str(
        Path(__file__).resolve().parent.parent.parent
        / "informe"
        / "2006-0823 Nuevo  Grafo de Control.mmd"
    )
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=default_out)
    args = parser.parse_args()

    from src.agents.graph import compile_workflow

    app, service = compile_workflow(_DummyAirSimClient())
    try:
        mermaid = app.get_graph().draw_mermaid()
    finally:
        service.stop()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(mermaid, encoding="utf-8")
    print(f"[export_graph_mmd] Grafo exportado a {out_path} ({len(mermaid.splitlines())} lineas).")


if __name__ == "__main__":
    main()

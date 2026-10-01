"""Cierra / repara corridas: CSV aplanado, .webm valido, viewer.html y DistMin (consolidado).

Uso:
    python experiments/finalize_run.py <directorio_de_corrida> [...]
    python experiments/finalize_run.py --all <raiz>      # todas las corridas incompletas bajo <raiz>
    python experiments/finalize_run.py --force <dir>     # rehace todo aunque parezca completo

Es idempotente: solo toca lo incompleto. El .webm original se conserva como
<stem>.partial.webm cuando hubo que recodificarlo. Ver src/logging/finalize_run.py.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.logging.finalize_run import finalize_run, find_runs, needs_finalize  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="+", help="directorio(s) de corrida, o la raiz con --all")
    ap.add_argument("--all", action="store_true", help="buscar corridas bajo cada ruta y cerrar solo las incompletas")
    ap.add_argument("--force", action="store_true", help="rehacer CSV/video/visor aunque parezcan completos")
    args = ap.parse_args()

    dirs = []
    for p in args.paths:
        dirs.extend(find_runs(p) if args.all else [p])
    n_done = 0
    for d in dirs:
        if args.all and not args.force and not needs_finalize(d):
            continue
        rep = finalize_run(d, force=args.force)
        n_done += 1
        print(f"{d}: csv={rep['csv']} video={rep['video']} viewer={rep['viewer']} distmin={rep['distmin']}")
    print(f"{n_done} corrida(s) procesada(s) de {len(dirs)}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

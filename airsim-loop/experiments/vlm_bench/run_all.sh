#!/usr/bin/env bash
# Pipeline completo del banco de prueba del VLM. REANUDABLE: cada etapa saltea lo ya hecho, asi que se
# puede cortar (Ctrl+C) y volver a lanzar. No borra nada; para empezar de cero, borrar el directorio a mano.
#   bash experiments/vlm_bench/run_all.sh ../airsim-runs/vlm_bench/v1
set -e
cd "$(dirname "$0")/../.."
B=${1:-../airsim-runs/vlm_bench/v1}
FP=../airsim-plan/missions/flightplans
# Python del entorno de los lotes: AIRSIM_ENV_DIR en config/.env (o $PYTHON si se define).
ENV_DIR=$(sed -n 's/^[[:space:]]*AIRSIM_ENV_DIR[[:space:]]*=[[:space:]]*//p' ../config/.env | head -1 | tr -d '"'"'"'')
if [ -z "${PYTHON:-}" ]; then
  if [ -z "$ENV_DIR" ]; then echo "AIRSIM_ENV_DIR no esta definido en config/.env" >&2; exit 1; fi
  command -v cygpath >/dev/null 2>&1 && ENV_DIR=$(cygpath -u "$ENV_DIR")
  PYTHON="$ENV_DIR/python.exe"; [ -x "$PYTHON" ] || PYTHON="$ENV_DIR/bin/python"
fi
echo "== python: $PYTHON"
if [ ! -f "$B/samples.jsonl" ]; then
  echo "== dataset"; "$PYTHON" -u experiments/vlm_bench/dataset.py --runs ../airsim-runs/produccion --out "$B"
fi
echo "== etiquetas de referencia"; "$PYTHON" -u experiments/vlm_bench/ground_truth.py --bench "$B" --trajectory 900
echo "== rutas"; "$PYTHON" -u experiments/vlm_bench/route_bench.py --bench "$B" --missions \
  $FP/citysim_pilot.json $FP/a_basic_city.json $FP/a_city.json $FP/nueva_mision_5.json $FP/nueva_mision_6.json
echo "== evaluacion 384"; "$PYTHON" -u experiments/vlm_bench/evaluate.py --bench "$B" --sizes 384
echo "== evaluacion 672"; "$PYTHON" -u experiments/vlm_bench/evaluate.py --bench "$B" --sizes 672 \
  --questions grid_prod grid_perm centro_libre borde_lateral borde_superior direccion_abierta
echo "== reporte"; "$PYTHON" -u experiments/vlm_bench/report.py --bench "$B"

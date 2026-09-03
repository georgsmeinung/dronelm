# 2026-0903, pedido explicito: `viewer.html` autocontenido por corrida, para
# recorrer el video con un slider y ver resaltado el renglon del CSV
# correspondiente -- herramienta de auditoria detallada, complementaria a
# abrir el CSV en una planilla.
#
# El CSV se embebe INLINE en el HTML (no via fetch()): abrir viewer.html con
# doble clic usa el protocolo file://, y ahi la mayoria de los navegadores
# bloquea fetch()/XHR a otro archivo local por CORS -- <video src="..."> a
# un archivo hermano en la misma carpeta SI funciona bajo file://, pero leer
# el .csv por fetch no. Embebiendo los datos como JSON en un <script> se
# evita el problema por completo: el visor abre sin necesitar un servidor
# local.
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Dict, List

# Columnas mostradas en la tabla compacta (fila por ciclo, resaltada al
# recorrer el video). El resto de las columnas del CSV se muestran completas
# en el panel de detalle del ciclo seleccionado, incluido el prompt/
# respuesta del VLM y los fotogramas de auditoria si los hay.
_TABLE_COLUMNS = [
    "cycle", "t", "route", "action", "wp_index", "dist_to_wp_m",
    "field_centro_ttc_s", "field_centro_blocked", "has_collided", "slm_delib_id",
]


def _load_csv_rows(csv_path: Path) -> List[Dict[str, Any]]:
    with open(csv_path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_viewer_html(html_path: str, video_filename: str, csv_path: str) -> None:
    """Genera `<html_path>` con el video + CSV de una corrida ya cerrada.

    `video_filename` es solo el nombre de archivo (no la ruta completa) --
    se asume que video/CSV/HTML conviven en el mismo directorio (siempre
    cierto para una corrida de FlightLogger, ver src/logging/flight_logger.py).
    """
    rows = _load_csv_rows(Path(csv_path))
    # JSON-escapar cualquier "</script" que pudiera venir dentro de un
    # prompt/respuesta del VLM -- de otro modo cerraria el <script> a mitad
    # de los datos embebidos.
    rows_json = json.dumps(rows, ensure_ascii=False).replace("</script", "<\\/script")

    html = _HTML_TEMPLATE.replace("__VIDEO_FILENAME__", json.dumps(video_filename))
    html = html.replace("__ROWS_JSON__", rows_json)
    html = html.replace("__TABLE_COLUMNS_JSON__", json.dumps(_TABLE_COLUMNS))

    Path(html_path).write_text(html, encoding="utf-8")


_HTML_TEMPLATE = """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>Auditoria de vuelo</title>
<style>
  :root { color-scheme: dark; }
  html, body { height: 100%; }
  body { margin: 0; padding: 12px 16px; background: #14161a; color: #e6e6e6;
         font-family: -apple-system, Segoe UI, Roboto, sans-serif; font-size: 14px;
         box-sizing: border-box; display: flex; flex-direction: column; gap: 10px; overflow: hidden; }
  h1 { font-size: 14px; margin: 0 0 6px; color: #9fd6ff; flex: 0 0 auto; }
  /* Fila superior (2/3 del alto): 3/5 video, 2/5 panel de detalle. */
  .top-section { display: grid; grid-template-columns: 3fr 2fr; gap: 16px; flex: 2 1 0; min-height: 0; }
  .video-col { display: flex; flex-direction: column; min-height: 0; }
  video { flex: 1 1 auto; min-height: 0; width: 100%; background: #000; border-radius: 6px; object-fit: contain; }
  .slider-row { display: flex; align-items: center; gap: 10px; margin-top: 8px; flex: 0 0 auto; }
  .slider-row input[type=range] { flex: 1; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-weight: 600;
           background: #223; margin-right: 6px; }
  .panel { background: #1c1f26; border: 1px solid #2a2e37; border-radius: 8px; padding: 10px 12px;
           overflow-y: auto; min-height: 0; }
  /* 4 columnas = 2 pares clave/valor por renglon, para aprovechar el ancho. */
  .grid2 { display: grid; grid-template-columns: max-content 1fr max-content 1fr; gap: 3px 10px; font-size: 11.5px; }
  .grid2 div.k { color: #8b93a3; }
  .grid2 div.v { color: #e6e6e6; word-break: break-all; }
  .sectors { display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px; margin-top: 8px; }
  .sector-box { background: #14161a; border: 1px solid #2a2e37; border-radius: 6px; padding: 6px; font-size: 11px; }
  .sector-box.blocked { border-color: #b33; background: #2a1416; }
  pre.text { white-space: pre-wrap; word-break: break-word; background: #14161a; padding: 8px;
             border-radius: 6px; max-height: 140px; overflow: auto; font-size: 11px; margin: 4px 0 0; }
  .frames { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 6px; }
  .frames img { max-width: 110px; border-radius: 4px; border: 1px solid #2a2e37; }
  /* Fila inferior (1/3 del alto): tabla del CSV a todo el ancho. */
  .bottom-section { flex: 1 1 0; min-height: 0; display: flex; flex-direction: column; }
  table { border-collapse: collapse; width: 100%; font-size: 12px; }
  thead th { position: sticky; top: 0; background: #1c1f26; padding: 4px 6px; text-align: left;
             border-bottom: 1px solid #2a2e37; color: #8b93a3; }
  tbody td { padding: 3px 6px; border-bottom: 1px solid #202329; white-space: nowrap; }
  tbody tr.active { background: #2a3550; }
  tbody tr:hover { background: #22262f; cursor: pointer; }
  .table-wrap { flex: 1 1 0; min-height: 0; overflow: auto; border: 1px solid #2a2e37; border-radius: 8px; }
  .hint { color: #8b93a3; font-size: 11px; margin-top: 6px; flex: 0 0 auto; }
</style>
</head>
<body>
<div class="top-section">
  <div class="video-col">
    <h1>Auditoria de vuelo — video sincronizado con el CSV por ciclo</h1>
    <video id="vid" src=__VIDEO_FILENAME__ controls preload="metadata"></video>
    <div class="slider-row">
      <span id="idxLabel" style="min-width: 90px;">ciclo 0</span>
      <input id="slider" type="range" min="0" value="0" step="1">
    </div>
    <div class="hint">El slider y el video se sincronizan en ambos sentidos (reproducir mueve el
      slider; arrastrar el slider mueve el video). La correspondencia es por tiempo de misión
      (columna <code>t</code>), no cuadro-a-cuadro exacto -- ver src/logging/flight_video.py.</div>
  </div>
  <div class="panel" id="detailPanel"></div>
</div>

<div class="bottom-section">
  <h1>Ciclos (fila resaltada = ciclo actual)</h1>
  <div class="table-wrap">
    <table>
      <thead><tr id="tableHead"></tr></thead>
      <tbody id="tableBody"></tbody>
    </table>
  </div>
</div>

<script>
const ROWS = __ROWS_JSON__;
const TABLE_COLUMNS = __TABLE_COLUMNS_JSON__;
const vid = document.getElementById('vid');
const slider = document.getElementById('slider');
const idxLabel = document.getElementById('idxLabel');
const detailPanel = document.getElementById('detailPanel');
const tableHead = document.getElementById('tableHead');
const tableBody = document.getElementById('tableBody');

slider.max = String(ROWS.length - 1);

// Header de la tabla compacta.
tableHead.innerHTML = TABLE_COLUMNS.map(c => `<th>${c}</th>`).join('');

// Cuerpo de la tabla: un solo innerHTML (mucho mas rapido que apendear
// fila por fila para misiones de varios miles de ciclos).
tableBody.innerHTML = ROWS.map((r, i) => {
  const cells = TABLE_COLUMNS.map(c => `<td>${(r[c] ?? '')}</td>`).join('');
  return `<tr id="row-${i}" data-idx="${i}">${cells}</tr>`;
}).join('');

for (const tr of tableBody.querySelectorAll('tr')) {
  tr.addEventListener('click', () => {
    const idx = parseInt(tr.dataset.idx, 10);
    seekToIndex(idx);
  });
}

function fmt(v) {
  if (v === undefined || v === null || v === '') return '<span style="color:#555">—</span>';
  return v;
}

function renderDetail(row) {
  const skip = new Set(['slm_prompt', 'slm_raw_response', 'slm_frame_paths']);
  const fieldSkip = /^field_/;
  const kv = Object.keys(row)
    .filter(k => !skip.has(k) && !fieldSkip.test(k))
    .map(k => `<div class="k">${k}</div><div class="v">${fmt(row[k])}</div>`).join('');

  const sectors = ['izquierda', 'centro', 'derecha'].map(s => {
    const occ = row[`field_${s}_occ`], ttc = row[`field_${s}_ttc_s`];
    const conf = row[`field_${s}_conf`], blocked = row[`field_${s}_blocked`] === 'True';
    return `<div class="sector-box ${blocked ? 'blocked' : ''}">
      <b>${s}</b><br>occ=${fmt(occ)} ttc=${fmt(ttc)}<br>conf=${fmt(conf)} bloqueado=${blocked}
    </div>`;
  }).join('');

  const prompt = row['slm_prompt'] ? `<div class="k" style="margin-top:8px;">slm_prompt</div><pre class="text">${row['slm_prompt']}</pre>` : '';
  const resp = row['slm_raw_response'] ? `<div class="k" style="margin-top:8px;">slm_raw_response</div><pre class="text">${row['slm_raw_response']}</pre>` : '';

  const framePaths = (row['slm_frame_paths'] || '').split(';').filter(Boolean);
  const frames = framePaths.length
    ? `<div class="k" style="margin-top:8px;">slm_frame_paths (fotogramas enviados al VLM)</div>
       <div class="frames">${framePaths.map(p => `<img src="${p}" loading="lazy">`).join('')}</div>`
    : '';

  detailPanel.innerHTML = `<div class="grid2">${kv}</div>
    <div class="sectors">${sectors}</div>${prompt}${resp}${frames}`;
}

let lastActive = null;
function highlightRow(idx) {
  if (lastActive) lastActive.classList.remove('active');
  const tr = document.getElementById('row-' + idx);
  if (tr) {
    tr.classList.add('active');
    tr.scrollIntoView({ block: 'center', behavior: 'smooth' });
    lastActive = tr;
  }
}

function render(idx) {
  idx = Math.max(0, Math.min(ROWS.length - 1, idx));
  const row = ROWS[idx];
  idxLabel.textContent = `ciclo ${row.cycle ?? idx} (t=${row.t ?? '?'}s)`;
  slider.value = String(idx);
  renderDetail(row);
  highlightRow(idx);
}

// Busqueda binaria de la fila cuyo `t` esta mas cerca de `currentTime`
// (ROWS ya viene ordenado por t, un ciclo por fila).
function nearestIndexForTime(t) {
  let lo = 0, hi = ROWS.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (parseFloat(ROWS[mid].t) < t) lo = mid + 1; else hi = mid;
  }
  return lo;
}

vid.addEventListener('timeupdate', () => {
  render(nearestIndexForTime(vid.currentTime));
});

slider.addEventListener('input', () => {
  seekToIndex(parseInt(slider.value, 10));
});

function seekToIndex(idx) {
  const row = ROWS[idx];
  if (row && row.t !== undefined && row.t !== '') {
    vid.currentTime = parseFloat(row.t);
  }
  render(idx);
}

render(0);
</script>
</body>
</html>
"""

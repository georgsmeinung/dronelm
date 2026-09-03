# 2026-0903, pedido explicito: viewer.html autocontenido por corrida (video +
# CSV embebido inline, sin fetch() -- ver src/logging/flight_viewer.py para
# el motivo del inline: file:// bloquea fetch() a otro archivo local por
# CORS en la mayoria de los navegadores).
from __future__ import annotations

import csv
import json

from src.logging.flight_viewer import write_viewer_html


def _write_csv(csv_path, rows):
    fieldnames = list(rows[0].keys())
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)


def test_viewer_html_embeds_rows_and_references_video_by_relative_name(tmp_path):
    csv_path = tmp_path / "RUN.csv"
    _write_csv(csv_path, [
        {"cycle": "1", "t": "0.2", "route": "reactive", "action": "MANTENER_RUMBO",
         "slm_prompt": "", "slm_raw_response": "", "slm_frame_paths": ""},
        {"cycle": "2", "t": "0.4", "route": "deliberative", "action": "EVADIR_IZQUIERDA",
         "slm_prompt": "linea 1\nlinea 2", "slm_raw_response": '{"macro_action": "EVADIR_IZQUIERDA"}',
         "slm_frame_paths": "photo-1.png"},
    ])

    html_path = tmp_path / "RUN.viewer.html"
    write_viewer_html(str(html_path), video_filename="RUN.mp4", csv_path=str(csv_path))

    html = html_path.read_text(encoding="utf-8")
    assert '"RUN.mp4"' in html  # referencia relativa al video, no ruta absoluta
    assert "EVADIR_IZQUIERDA" in html
    assert "linea 1" in html
    assert "photo-1.png" in html


def test_viewer_html_escapes_closing_script_tag_inside_embedded_data(tmp_path):
    """Un prompt/respuesta que contenga literalmente "</script>" no puede

    cerrar el bloque <script> a mitad de los datos embebidos -- rompería
    el visor entero para esa fila (y todas las que la sigan) en silencio.
    """
    csv_path = tmp_path / "RUN2.csv"
    _write_csv(csv_path, [
        {"cycle": "1", "t": "0.2", "route": "deliberative", "action": "MANTENER_RUMBO",
         "slm_prompt": "texto con </script> adentro", "slm_raw_response": "", "slm_frame_paths": ""},
    ])

    html_path = tmp_path / "RUN2.viewer.html"
    write_viewer_html(str(html_path), video_filename="RUN2.mp4", csv_path=str(csv_path))

    html = html_path.read_text(encoding="utf-8")
    assert "</script>\n" not in html.split("const ROWS")[1].split("const TABLE_COLUMNS")[0]
    # El dato original sigue recuperable al parsear (escapado, no perdido).
    start = html.index("const ROWS = ") + len("const ROWS = ")
    end = html.index(";\nconst TABLE_COLUMNS")
    rows = json.loads(html[start:end].replace("<\\/script", "</script"))
    assert rows[0]["slm_prompt"] == "texto con </script> adentro"

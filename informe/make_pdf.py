"""
Genera docs/informe/tesis-dronelm.pdf desde el sitio MkDocs servido en localhost.
Uso: python informe/make_pdf.py [--port 8765]
"""
import argparse
import http.server
import socket
import sys
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS_DIR  = REPO_ROOT / "docs"
PDF_OUT   = REPO_ROOT / "docs" / "informe" / "tesis-dronelm.pdf"


def find_free_port(preferred: int) -> int:
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", preferred))
            return preferred
        except OSError:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]


def start_server(port: int) -> http.server.HTTPServer:
    handler = http.server.SimpleHTTPRequestHandler
    handler.log_message = lambda *a: None  # silenciar logs
    server = http.server.HTTPServer(("127.0.0.1", port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def make_pdf(url: str, output: Path) -> None:
    from playwright.sync_api import sync_playwright

    print(f"  Playwright: opening {url} ...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # Cargar con networkidle: espera a que no haya requests pendientes
        page.goto(url, wait_until="networkidle", timeout=60_000)

        # Esperar a que MathJax 3 termine de tipar todas las fórmulas
        page.wait_for_function(
            """() => {
                if (!window.MathJax || !window.MathJax.typesetPromise) return false;
                return window.MathJax.startup && window.MathJax.startup.promise
                    ? window.MathJax.startup.promise.then(() => true).catch(() => false)
                    : true;
            }""",
            timeout=30_000,
        )
        # Forzar re-typeset por si algunas fórmulas llegaron tarde al DOM (print-site)
        page.evaluate("() => window.MathJax && window.MathJax.typesetPromise && window.MathJax.typesetPromise()")
        # Pausa extra para que el re-typeset y las fuentes terminen
        page.wait_for_timeout(3_000)

        # --- Reordenar DOM: mover TOC a DESPUÉS del cover ---
        # Estructura de mkdocs-print-site:
        #   sections[0] = TOC   (queremos que quede en posición 1)
        #   sections[1] = Cover (00-COVER.md — queremos que sea la primera página)
        #   sections[2..] = capítulos
        page.evaluate("""() => {
            const container = document.getElementById('print-site-page');
            if (!container) return;
            const sections = Array.from(container.querySelectorAll(':scope > section.print-page'));
            if (sections.length < 2) return;
            const tocSection   = sections[0];   // TOC
            const coverSection = sections[1];   // Cover

            // Mover TOC para que quede inmediatamente después del Cover
            coverSection.insertAdjacentElement('afterend', tocSection);

            // Renombrar "Table of Contents" → "Índice"
            const tocTitle = tocSection.querySelector('.print-page-toc-title, h1, h2');
            if (tocTitle) tocTitle.textContent = 'Índice';

            // Quitar la numeración automática de la lista del TOC
            // generate_toc() copia el sidebar con texto ya numerado ("2 1. Introducción")
            // → stripar el prefijo "N " o "N.M " hardcodeado en cada span
            tocSection.querySelectorAll('span.md-ellipsis').forEach(span => {
                span.textContent = span.textContent.trim().replace(/^\\d+(\\.\\d+)?\\s+/, '');
            });
            tocSection.querySelectorAll('ol, ul').forEach(list => {
                list.style.listStyleType = 'none';
                list.style.paddingLeft = '0';
            });

            // Quitar la renumeración de headings del plugin
            // (belt-and-suspenders con el !important de austral.css)
            document.querySelectorAll('.print-site-enumerate-headings').forEach(el => {
                el.classList.remove('print-site-enumerate-headings');
            });
        }""")

        # --- Generar PDF con márgenes moderados ---
        page.pdf(
            path=str(output),
            format="A4",
            print_background=True,
            # Los márgenes aquí deben coincidir con el @page CSS de austral.css
            # para que el @bottom-center quede en el espacio correcto
            margin={
                "top":    "2cm",
                "bottom": "2.5cm",   # Extra para el número de página centrado
                "left":   "2cm",
                "right":  "1.5cm",
            },
        )
        browser.close()
    size_kb = round(output.stat().st_size / 1024)
    print(f"  PDF: {output}  ({size_kb} KB)")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    port = find_free_port(args.port)
    print_url = f"http://localhost:{port}/informe/print_page.html"

    if not (DOCS_DIR / "informe" / "print_page.html").exists():
        print("ERROR: docs/informe/print_page.html not found — run mkdocs build first.")
        sys.exit(1)

    import os
    os.chdir(DOCS_DIR)          # HTTP server sirve desde docs/
    server = start_server(port)
    print(f"  HTTP server: localhost:{port}  (serving {DOCS_DIR})")

    try:
        make_pdf(print_url, PDF_OUT)
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()

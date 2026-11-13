"""Genera las ilustraciones de los anexos como SVG (informe/fig-src/anexos/*.svg).

Cada figura se arma con primitivas simples (cajas, texto, flechas) para que todo el texto y las
ecuaciones salgan exactos. Exportar a PNG con export.ps1, por ejemplo:
    .\\informe\\fig-src\\export.ps1 anexos\\a2-estrategias-mitigacion.svg "anexos\\a2-estrategias-mitigacion.png"
"""
from __future__ import annotations

import math
import re
from pathlib import Path

OUT = Path(__file__).resolve().parent / "anexos"

STYLE = """
  <style>
    .bg { fill: #FFFFFF; }
    .panel { fill: #F6F8FA; stroke: #E2E8F0; stroke-width: 1.2; }
    .card { fill: #FFFFFF; stroke: #CBD5E0; stroke-width: 1.4; }
    .card-acc { fill: #FFFFFF; stroke: #0066CC; stroke-width: 1.8; }
    .card-blue { fill: #E6F2FF; stroke: #0066CC; stroke-width: 1.8; }
    .card-green { fill: #EAF7EF; stroke: #259E5F; stroke-width: 1.8; }
    .card-warn { fill: #FFF7E6; stroke: #D97706; stroke-width: 1.8; }
    .card-red { fill: #FDECEC; stroke: #DC2626; stroke-width: 1.8; }
    .card-gray { fill: #F1F3F5; stroke: #A0AEC0; stroke-width: 1.4; stroke-dasharray: 6 4; }
    .head { font-size: 14px; font-weight: 800; letter-spacing: .05em; fill: #0066CC; }
    .head-ink { font-size: 14px; font-weight: 800; letter-spacing: .05em; fill: #2D3748; }
    .title { font-size: 22px; font-weight: 800; fill: #1A202C; }
    .ttl { font-size: 15px; font-weight: 700; fill: #1A202C; }
    .txt { font-size: 13px; fill: #4A5568; }
    .txt-b { font-size: 13px; font-weight: 700; fill: #2D3748; }
    .small { font-size: 11.5px; fill: #718096; }
    .mono { font-family: 'Noto Sans Mono', ui-monospace, monospace; font-size: 12px; fill: #1A202C; }
    .mono-s { font-family: 'Noto Sans Mono', ui-monospace, monospace; font-size: 11px; fill: #4A5568; }
    .math { font-family: 'Cambria Math', 'STIX Two Math', 'Times New Roman', serif; font-size: 17px; fill: #1A202C; }
    .math-s { font-family: 'Cambria Math', 'STIX Two Math', 'Times New Roman', serif; font-size: 14px; fill: #1A202C; }
    .acc { fill: #0066CC; } .safe { fill: #259E5F; } .warn { fill: #B45309; } .crit { fill: #DC2626; }
    .ln { stroke: #4A5568; stroke-width: 1.8; fill: none; }
    .ln-acc { stroke: #0066CC; stroke-width: 1.8; fill: none; }
    .ln-dash { stroke: #718096; stroke-width: 1.4; fill: none; stroke-dasharray: 5 4; }
    .grid { stroke: #2D3748; stroke-width: 1.2; fill: none; }
    .badge { fill: #0066CC; } .badge-t { font-size: 13px; font-weight: 800; fill: #FFFFFF; }
  </style>
  <defs>
    <marker id="ah" viewBox="0 0 10 8" refX="9" refY="4" markerWidth="9" markerHeight="8" orient="auto">
      <polygon points="0 0, 10 4, 0 8" fill="#4A5568" /></marker>
    <marker id="aa" viewBox="0 0 10 8" refX="9" refY="4" markerWidth="9" markerHeight="8" orient="auto">
      <polygon points="0 0, 10 4, 0 8" fill="#0066CC" /></marker>
    <marker id="av" viewBox="0 0 10 8" refX="9" refY="4" markerWidth="5" markerHeight="5" orient="auto">
      <polygon points="0 0, 10 4, 0 8" fill="#0066CC" /></marker>
    <marker id="ag" viewBox="0 0 10 8" refX="9" refY="4" markerWidth="5" markerHeight="5" orient="auto">
      <polygon points="0 0, 10 4, 0 8" fill="#718096" /></marker>
    <marker id="ar" viewBox="0 0 10 8" refX="9" refY="4" markerWidth="5" markerHeight="5" orient="auto">
      <polygon points="0 0, 10 4, 0 8" fill="#DC2626" /></marker>
  </defs>
"""


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def rich(s: str) -> str:
    """Texto con subindices _{..} y superindices ^{..} como tspan."""
    s = esc(s)
    s = re.sub(r"_\{([^}]*)\}", r'<tspan baseline-shift="sub" font-size="72%">\1</tspan>', s)
    s = re.sub(r"\^\{([^}]*)\}", r'<tspan baseline-shift="super" font-size="72%">\1</tspan>', s)
    return s


class Fig:
    def __init__(self, name: str, w: int, h: int, desc: str):
        self.name, self.w, self.h = name, w, h
        self.el = [f"  <!-- {esc(desc)} -->", STYLE, f'  <rect class="bg" x="0" y="0" width="{w}" height="{h}" />']

    def add(self, s: str):
        self.el.append("  " + s)

    def rect(self, x, y, w, h, cls="card", rx=8):
        self.add(f'<rect class="{cls}" x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" />')

    def text(self, x, y, s, cls="txt", anchor="start", extra=""):
        self.add(f'<text class="{cls}" x="{x}" y="{y}" text-anchor="{anchor}" {extra}>{rich(s)}</text>')

    def lines(self, x, y, items, cls="txt", lh=18, anchor="start"):
        for i, s in enumerate(items):
            self.text(x, y + i * lh, s, cls, anchor)

    def bullets(self, x, y, items, cls="txt", lh=19):
        for i, s in enumerate(items):
            self.add(f'<circle cx="{x + 3}" cy="{y + i * lh - 4}" r="2.4" fill="#0066CC" />')
            self.text(x + 12, y + i * lh, s, cls)

    def arrow(self, pts, cls="ln", marker="ah"):
        d = "M" + " L".join(f"{a} {b}" for a, b in pts)
        self.add(f'<path class="{cls}" d="{d}" marker-end="url(#{marker})" />')

    def badge(self, x, y, n):
        self.add(f'<circle class="badge" cx="{x}" cy="{y}" r="12" />')
        self.text(x, y + 4.5, str(n), "badge-t", "middle")

    def card(self, x, y, w, h, title, body, cls="card", tcls="ttl", lh=18, mono=False, title_dy=24):
        self.rect(x, y, w, h, cls)
        self.text(x + 14, y + title_dy, title, tcls)
        self.lines(x + 14, y + title_dy + 22, body, "mono" if mono else "txt", lh)

    def save(self):
        OUT.mkdir(parents=True, exist_ok=True)
        body = "\n".join(self.el)
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {self.w} {self.h}" width="{self.w}" '
               f'height="{self.h}" font-family="Inter, \'Segoe UI\', sans-serif">\n{body}\n</svg>\n')
        (OUT / f"{self.name}.svg").write_text(svg, encoding="utf-8")
        return OUT / f"{self.name}.svg"


# ------------------------------------------------------------------------------------------------ A2
def a2():
    f = Fig("a2-estrategias-mitigacion", 1200, 640, "A2.4: salvaguardas contra las alucinaciones del VLM")
    f.text(24, 36, "SALVAGUARDAS DE LA ARQUITECTURA FRENTE A LAS ALUCINACIONES DEL VLM", "head")
    f.text(24, 56, "Anexo 2, IT.A2.4 · modelo de la tesis: LFM2.5-VL-1.6B Q4_K_M en Ollama, en la misma GPU que Unreal", "small")
    # flujo
    f.rect(24, 76, 1152, 196, "panel", 10)
    f.text(44, 102, "CAMINO DE UNA RESPUESTA DEL MODELO", "head-ink")
    xs = [44, 268, 492, 716, 940]
    cards = [
        ("Fotograma o mapa", ["grilla 3×3 sobre el fotograma,", "imágenes de un barrido", "o parche del mapa cenital"], "card"),
        ("VLM + json_schema", ["los tokens que violan el", "esquema se enmascaran:", "la salida siempre es válida"], "card-blue"),
        ("Enumeración cerrada", ["free / blocked por sector,", "view + free por imagen,", "5 clases de terreno"], "card-blue"),
        ("Parser estricto", ["valida el formato del modo;", "si no coincide: no_parseable,", "ninguna acción por defecto"], "card-warn"),
        ("El código decide", ["sub-meta en coordenadas", "del mundo o puntaje de ruta;", "el modelo no da velocidades"], "card-green"),
    ]
    for i, (x, (t, b, cls)) in enumerate(zip(xs, cards)):
        f.card(x, 118, 196, 132, t, b, cls)
        if i < 4:
            f.arrow([(x + 198, 184), (x + 222, 184)])
    # cuatro salvaguardas
    items = [
        ("1", "Gramática en los logits", ["Se enmascaran los tokens que", "violan el esquema JSON: el 100 %", "de las respuestas tiene formato", "válido (IT.8.2.1)."]),
        ("2", "Describir, no decidir", ["Respuestas en enumeraciones", "cerradas; la geometría y la", "cinemática son funciones", "deterministas (IT.8.3, IT.8.4)."]),
        ("3", "Un solo lazo comanda", ["Solo el lazo rápido comanda", "velocidades; una respuesta", "inválida, tardía u obsoleta", "se descarta (IT.5.1.2)."]),
        ("4", "Medir antes de confiar", ["Cada pregunta se mide contra", "etiquetas de referencia antes", "del vuelo; la que no pasa el", "criterio no vuela (IT.10.2)."]),
    ]
    for i, (n, t, b) in enumerate(items):
        x = 24 + i * 292
        f.rect(x, 292, 276, 166, "card-acc")
        f.badge(x + 26, 318, n)
        f.text(x + 46, 323, t, "ttl")
        f.lines(x + 16, 354, b, "txt", 20)
    # resultado
    f.rect(24, 478, 1152, 140, "card-gray", 10)
    f.text(44, 506, "RESULTADO DE LA SALVAGUARDA 4 EN ESTA TESIS", "head-ink")
    f.bullets(44, 534, [
        "Banco a bordo: la grilla del VLM separa sectores libres de bloqueados con AUC 0.53; ninguna de las ocho preguntas pasa el criterio (IT.11.0).",
        "La misma pregunta la responde una red de profundidad monocular (Depth Anything V2, AUC 0.83–0.87): es la fuente del lazo lento en vuelo.",
        "El VLM queda en el plan de ruta sobre el mapa cenital, antes del despegue, donde sí aporta señal (AUC 0.81).",
        "Ninguna salvaguarda hace que el modelo discrimine: solo evitan que una respuesta errónea se convierta en una maniobra.",
    ], "txt", 21)
    return f.save()


# ------------------------------------------------------------------------------------------------ A3
def a3_peft():
    f = Fig("a3-fundamentos-de-peft", 1200, 600, "A3.1: ajuste fino completo frente a LoRA")
    f.text(24, 36, "AJUSTE FINO COMPLETO FRENTE A ADAPTACIÓN DE BAJO RANGO (LoRA)", "head")
    f.text(24, 56, "Mangrulkar et al., 2022; Hu et al., 2022 · cifras de memoria para un modelo de 3 B, cota superior del VLM de vuelo (1.6 B)", "small")
    f.rect(24, 76, 1152, 150, "panel", 10)
    f.text(44, 104, "AJUSTE FINO COMPLETO (FFT)", "head-ink")
    f.rect(44, 120, 560, 46, "card-red")
    f.text(324, 149, "gradientes + momentos de AdamW para los 3 B parámetros", "txt-b", "middle")
    f.text(44, 200, "Memoria para el estado del optimizador: más de 24 GB de VRAM", "ttl")
    f.text(660, 149, "frente a", "txt", "middle")
    f.rect(716, 120, 440, 46, "card")
    f.text(936, 149, "RTX 5060 de 8 GB, compartida con Unreal Engine", "txt-b", "middle")
    f.text(716, 200, "Inviable en la estación de la tesis", "ttl")
    f.add('<text class="ttl crit" x="1156" y="200" text-anchor="end">×</text>')
    # izquierda: capa estandar
    f.rect(24, 246, 520, 330, "panel", 10)
    f.text(44, 274, "CAPA LINEAL PREENTRENADA", "head-ink")
    f.text(70, 402, "x", "math")
    f.arrow([(86, 397), (166, 397)])
    f.rect(170, 340, 200, 114, "card-blue")
    f.text(270, 382, "W_{0} ∈ ℝ^{d×k}", "math", "middle")
    f.text(270, 410, "congelada", "txt", "middle")
    f.arrow([(372, 397), (450, 397)])
    f.text(460, 402, "h", "math")
    f.text(284, 520, "h = W_{0} x", "math", "middle")
    # derecha: LoRA
    f.rect(564, 246, 612, 330, "panel", 10)
    f.text(584, 274, "LoRA: SE ENTRENAN SOLO A Y B", "head-ink")
    f.text(594, 402, "x", "math")
    f.arrow([(610, 397), (660, 397), (660, 345), (690, 345)])
    f.arrow([(660, 397), (660, 449), (690, 449)])
    f.rect(694, 310, 180, 70, "card-blue")
    f.text(784, 341, "W_{0} ∈ ℝ^{d×k}", "math", "middle")
    f.text(784, 364, "congelada", "txt", "middle")
    f.rect(694, 414, 180, 70, "card-green")
    f.text(784, 445, "A ∈ ℝ^{r×k}", "math", "middle")
    f.text(784, 468, "A ~ 𝒩(0, σ²)", "math-s", "middle")
    f.arrow([(876, 449), (910, 449)])
    f.rect(914, 414, 160, 70, "card-green")
    f.text(994, 445, "B ∈ ℝ^{d×r}", "math", "middle")
    f.text(994, 468, "B = 0 al inicio", "txt", "middle")
    f.add('<circle cx="1110" cy="397" r="16" fill="#FFFFFF" stroke="#4A5568" stroke-width="1.8" />')
    f.text(1110, 403, "+", "ttl", "middle")
    f.arrow([(876, 345), (1110, 345), (1110, 378)])
    f.arrow([(1076, 449), (1110, 449), (1110, 416)])
    f.text(1150, 403, "h", "math")
    f.text(870, 526, "h = W_{0} x + (α / r) · B A x,   r ≪ min(d, k)", "math", "middle")
    f.text(870, 554, "se entrena ~0.15–0.30 % de los parámetros; tras fusionar ΔW en W_{0} no hay costo extra en inferencia", "small", "middle")
    return f.save()


def a3_impacto():
    f = Fig("a3-impacto-lora", 1200, 640, "A3.2: el VLM hoy y con un adaptador LoRA (trabajo futuro)")
    f.text(24, 36, "QUÉ CAMBIARÍA UN ADAPTADOR LoRA EN LA CONSULTA AL VLM", "head")
    f.text(24, 56, "Anexo 3 · trabajo futuro (IT.12.4): nada de la columna derecha está implementado ni medido", "small")
    for x, cls, ttl, sub in ((24, "card-blue", "HOY: ZERO-SHOT + json_schema", "medido en el banco a bordo (IT.11.0)"),
                             (612, "card-green", "PROPUESTA: ADAPTADOR LoRA", "objetivo a verificar con el mismo banco")):
        f.rect(x, 76, 564, 526, "panel", 10)
        f.text(x + 20, 104, ttl, "head-ink")
        f.text(x + 20, 124, sub, "small")
    # izquierda
    f.card(44, 140, 524, 92, "Entrada", ["fotograma frontal recortado (384 px) con la grilla 3×3 y la marca GOAL", "+ «Goal WP_3: 42 m, in cell C2. Altitude 10 m.»"])
    f.arrow([(306, 234), (306, 254)])
    f.card(44, 256, 524, 92, "LFM2.5-VL-1.6B Q4_K_M · pesos genéricos congelados", ["decodificación restringida: la salida cumple el esquema", "{\"cells\": {\"A1\": \"free\" | \"blocked\", …, \"C3\": …}}"], "card-blue")
    f.arrow([(306, 350), (306, 370)])
    f.card(44, 372, 524, 210, "Resultado medido", [
        "exactitud balanceada 53 % [50–55 %], AUC 0.53: no separa",
        "sectores libres de bloqueados",
        "responde según la posición del sector en la imagen:",
        "filas 1 y 3 «libre» en el 100 % de las muestras",
        "latencia: 0.34–0.88 s por pregunta (0.88 s la grilla)",
        "→ la pregunta del lazo lento la responde la profundidad",
        "    estimada; el VLM no vuela",
    ], "card-red")
    # derecha
    f.card(632, 140, 524, 92, "Datos de entrenamiento", ["fotogramas que registra la capa estratégica (> 7500 consultas en la v4),", "etiquetados offline con la profundidad del simulador (p5 por sector)"])
    f.arrow([(894, 234), (894, 254)])
    f.card(632, 256, 524, 92, "Mismo modelo + adaptador LoRA", ["matrices de atención (W_{q}, W_{v}) y proyecciones MLP del LLM;", "el codificador visual (ViT) queda congelado"], "card-green")
    f.arrow([(894, 350), (894, 370)])
    f.card(632, 372, 524, 210, "Qué habría que demostrar", [
        "misma salida y mismo esquema: free / blocked por sector",
        "pasar el criterio del banco: exactitud balanceada ≥ 0.65",
        "y límite inferior del IC 95 % por encima del azar",
        "en un entorno que el adaptador no vio al entrenar",
        "prompt más corto (las reglas quedan en los pesos):",
        "menos tokens de entrada; la ganancia de latencia",
        "es una hipótesis, no una medición",
    ], "card-warn")
    f.text(600, 628, "La profundidad del simulador solo etiqueta los datos de entrenamiento; nunca entra al lazo de vuelo.", "small", "middle")
    return f.save()


# ------------------------------------------------------------------------------------------------ A4
def a4_decod():
    f = Fig("a4-decodificacion-restringida", 1200, 600, "A4.2: enmascaramiento de logits guiado por un automata")
    f.text(24, 36, "DECODIFICACIÓN RESTRINGIDA: UN PASO DE GENERACIÓN", "head")
    f.text(24, 56, "Willard & Louf, 2023; Ugare et al., 2024; Dong et al., 2024", "small")
    f.rect(24, 76, 700, 500, "panel", 10)
    steps = [
        (110, "Contexto: prompt x y tokens previos y_{<t}", "card"),
        (190, "Paso forward del transformer", "card-blue"),
        (270, "Logits crudos z_{t} ∈ ℝ^{|V|}", "card"),
        (350, "Máscara del autómata: z′_{t} = z_{t} + log M(s_{t}),  M ∈ {0,1}^{|V|}", "card-warn"),
        (430, "Softmax y muestreo (temperatura 0 → argmax)", "card-blue"),
        (510, "Token emitido y_{t} ∈ V_{válidos}(s_{t})", "card-green"),
    ]
    for i, (y, s, cls) in enumerate(steps):
        f.rect(64, y, 560, 50, cls)
        f.text(344, y + 31, s, "ttl", "middle")
        if i < len(steps) - 1:
            f.arrow([(344, y + 52), (344, y + 78)])
    f.arrow([(626, 535), (680, 535), (680, 135), (626, 135)], "ln-acc", "aa")
    f.text(690, 340, "s_{t+1} = δ(s_{t}, y_{t})", "math-s", "start", 'transform="rotate(90 690 340)"')
    # ejemplo
    f.rect(744, 76, 432, 500, "panel", 10)
    f.text(764, 104, "EJEMPLO: ESQUEMA DE LA CAPA ESTRATÉGICA", "head-ink")
    f.text(764, 134, "Generado hasta acá:", "txt")
    f.text(764, 158, '{"cells": {"A1": "', "mono")
    f.text(764, 192, "Solo dos continuaciones cumplen el esquema:", "txt")
    rows = [("free", "2.1", "1", "2.1"), ("blocked", "1.3", "1", "1.3"), ("libre", "1.8", "0", "−∞"), ("{", "0.4", "0", "−∞"), ("ok", "0.9", "0", "−∞")]
    f.text(764, 226, "token", "txt-b"); f.text(900, 226, "z_{t}", "txt-b", "middle")
    f.text(980, 226, "M", "txt-b", "middle"); f.text(1080, 226, "z′_{t}", "txt-b", "middle")
    for i, (tok, z, m, zp) in enumerate(rows):
        y = 256 + i * 30
        f.text(764, y, f'"{tok}"' if tok != "{" else "{", "mono")
        f.text(900, y, z, "mono", "middle")
        f.text(980, y, m, "mono", "middle")
        f.text(1080, y, zp, "mono" if m == "1" else "mono", "middle")
    f.add('<line x1="764" y1="236" x2="1156" y2="236" stroke="#CBD5E0" stroke-width="1" />')
    f.lines(764, 430, [
        "El modelo prefería «libre» (1.8), que no está en",
        "la enumeración: la máscara la descarta y el",
        "argmax elige «free». La salida es siempre",
        "válida; que sea correcta depende del modelo.",
    ], "txt", 20)
    f.text(764, 530, "Tokens ilustrativos; el tokenizador real", "small")
    f.text(764, 548, "parte las palabras en fragmentos.", "small")
    return f.save()


def a4_invariante():
    f = Fig("a4-invariante-lazo-tactico", 1200, 640, "A4.4.1: que garantiza la gramatica en el sistema implementado")
    f.text(24, 36, "QUÉ GARANTIZA LA DECODIFICACIÓN RESTRINGIDA EN EL SISTEMA IMPLEMENTADO", "head")
    f.text(24, 56, "Anexo 4, IT.A4.4.1 · el decisor de acciones de IT.A4.4–IT.A4.6 es ilustrativo y no está en el código", "small")
    f.rect(24, 76, 560, 300, "panel", 10)
    f.text(44, 104, "LOS TRES ESQUEMAS DEL CÓDIGO", "head-ink")
    f.card(44, 120, 520, 76, "Capa estratégica (vlm_strategic.py)", ['{"cells": {"A1" … "C3": "free" | "blocked"}}'], "card-blue", mono=True)
    f.card(44, 206, 520, 76, "Barrido de deadlock (deep_scan.py)", ['{"views": [{"img": n, "view": …, "free": bool}]}'], "card-blue", mono=True)
    f.card(44, 292, 520, 76, "Plan de ruta (route_planner.py)", ['{"answer": street | building | trees | parking | …}'], "card-blue", mono=True)
    f.rect(604, 76, 572, 300, "panel", 10)
    f.text(624, 104, "DE LA RESPUESTA A LA ACCIÓN", "head-ink")
    flow = [("VLM + json_schema", "card-blue"), ("parser estricto del modo", "card-warn"),
            ("sub-meta en el mundo o puntaje", "card-green"), ("WaypointTracker", "card")]
    for i, (t, cls) in enumerate(flow):
        y = 120 + i * 62
        f.rect(624, y, 300, 44, cls)
        f.text(774, y + 28, t, "ttl", "middle")
        if i < 3:
            f.arrow([(774, y + 46), (774, y + 60)])
    f.text(944, 208, "si no coincide: no_parseable,", "small")
    f.text(944, 224, "sin acción por defecto", "small")
    f.text(944, 290, "decide_subgoal, panorama_to_subgoal", "small")
    f.text(944, 306, "o elección de la ruta (choose)", "small")
    # lazo rapido
    f.rect(24, 396, 1152, 96, "card-acc", 10)
    f.text(44, 424, "LAZO RÁPIDO (5 Hz) · EL ÚNICO QUE COMANDA VELOCIDADES", "head")
    chain = ["guiado al objetivo activo", "navigate: 8 reglas", "action_to_command()", "motor → AirSim"]
    for i, t in enumerate(chain):
        x = 44 + i * 284
        f.rect(x, 438, 250, 40, "card")
        f.text(x + 125, 463, t, "txt-b", "middle")
        if i < 3:
            f.arrow([(x + 252, 458), (x + 282, 458)])
    f.rect(24, 512, 1152, 108, "card-gray", 10)
    f.text(44, 540, "INVARIANTES", "head-ink")
    f.bullets(44, 566, [
        "Toda respuesta del modelo cumple su esquema, o se descarta sin reemplazarla por un valor por defecto.",
        "Los campos son enumeraciones cerradas: el modelo describe sectores, imágenes o parches; nunca elige una maniobra ni da velocidades.",
        "La cinemática de cada macro-acción tiene una sola definición, action_to_command(), la misma para los tres brazos (IT.5.4).",
    ], "txt", 21)
    return f.save()


# ------------------------------------------------------------------------------------------------ A5
def a5_camara():
    f = Fig("a5-modelo-geometrico-de-camara", 1200, 600, "A5.1: modelo pin-hole de la camara frontal")
    f.text(24, 36, "MODELO DE CÁMARA ESTENOPEICA (PIN-HOLE) DE LA CÁMARA FRONTAL", "head")
    f.text(24, 56, "Anexo 5, IT.A5.1 · ejes de la cámara: X a la derecha, Y hacia abajo, Z hacia adelante", "small")
    # geometria lateral
    f.rect(24, 76, 620, 500, "panel", 10)
    f.text(44, 104, "PROYECCIÓN EN PERSPECTIVA (VISTA LATERAL)", "head-ink")
    cx, cy = 100, 330
    f.add(f'<circle cx="{cx}" cy="{cy}" r="6" fill="#1A202C" />')
    f.text(cx, cy + 28, "centro óptico", "small", "middle")
    f.arrow([(cx, cy), (610, cy)], "ln", "ah"); f.text(612, cy - 8, "Z", "math", "end")
    f.arrow([(cx, cy), (cx, 500)], "ln", "ah"); f.text(cx + 10, 508, "Y (abajo)", "txt")
    px = 260
    f.add(f'<line x1="{px}" y1="150" x2="{px}" y2="520" stroke="#0066CC" stroke-width="2.2" />')
    f.text(px + 6, 146, "plano de imagen", "txt", "start")
    f.add(f'<line x1="{cx}" y1="{cy + 60}" x2="{px}" y2="{cy + 60}" class="ln-dash" />')
    f.text((cx + px) / 2, cy + 78, "f (distancia focal)", "txt", "middle")
    PX, PY = 560, 180
    f.add(f'<circle cx="{PX}" cy="{PY}" r="7" fill="#D97706" />')
    f.text(PX - 6, PY - 14, "P = (X, Y, Z)", "math-s", "end")
    f.add(f'<line x1="{cx}" y1="{cy}" x2="{PX}" y2="{PY}" stroke="#D97706" stroke-width="1.6" />')
    ty = cy + (PY - cy) * (px - cx) / (PX - cx)
    f.add(f'<circle cx="{px}" cy="{ty:.1f}" r="5" fill="#D97706" />')
    f.text(px + 10, ty + 18, "p = (u, v)", "math-s")
    f.add(f'<line x1="{PX}" y1="{PY}" x2="{PX}" y2="{cy}" class="ln-dash" />')
    f.text(PX + 8, (PY + cy) / 2, "−Y", "math-s")
    f.text(330, 560, "y = f · Y / Z : la escala Z se pierde en la proyección", "txt", "middle")
    # ecuaciones
    f.rect(664, 76, 512, 500, "panel", 10)
    f.text(684, 104, "DE LA ESCENA AL PÍXEL", "head-ink")
    f.text(800, 152, "u = f_{x} · X / Z + c_{x}", "math", "middle")
    f.text(1040, 152, "v = f_{y} · Y / Z + c_{y}", "math", "middle")
    f.text(684, 206, "en forma matricial, con la matriz intrínseca K:", "txt")
    # matriz
    f.text(700, 290, "Z", "math"); f.text(716, 290, "·", "math")
    def mat(x0, y0, rows, colw=60):
        h = len(rows) * 30
        f.add(f'<path d="M{x0 + 6} {y0 - 22} H{x0} V{y0 + h - 18} H{x0 + 6}" class="ln" />')
        wd = colw * len(rows[0])
        f.add(f'<path d="M{x0 + wd - 6} {y0 - 22} H{x0 + wd} V{y0 + h - 18} H{x0 + wd - 6}" class="ln" />')
        for i, r in enumerate(rows):
            for j, c in enumerate(r):
                f.text(x0 + colw * j + colw / 2, y0 + i * 30, c, "math", "middle")
        return x0 + wd
    e = mat(730, 262, [["u"], ["v"], ["1"]], 44)
    f.text(e + 18, 292, "=", "math", "middle")
    e = mat(e + 34, 262, [["f_{x}", "0", "c_{x}"], ["0", "f_{y}", "c_{y}"], ["0", "0", "1"]], 56)
    mat(e + 10, 262, [["X"], ["Y"], ["Z"]], 44)
    f.text(684, 380, "PARÁMETROS DE VUELO", "head-ink")
    f.lines(684, 410, [
        "cámara: 1080 × 720 px, campo horizontal de 90°",
        "f_{x} = W / (2 tan 45°) = 540 px; el código usa 554 px (CAMERA_FX)",
        "c_{x} = 540 px, c_{y} = 360 px (centro de la imagen)",
        "el flujo óptico corre a 640 px de ancho (FLOW_DOWNSCALE_WIDTH):",
        "f y c se escalan por s = 640 / 1080 ≈ 0.59",
    ], "txt", 22)
    return f.save()


def _field(f, x0, y0, w, h, fn, n=9, scale=1.0, cls="av", color="#0066CC"):
    f.rect(x0, y0, w, h, "card", 4)
    for i in range(n):
        for j in range(n):
            px = x0 + (i + 0.5) * w / n
            py = y0 + (j + 0.5) * h / n
            xn = (px - (x0 + w / 2)) / (w / 2)
            yn = (py - (y0 + h / 2)) / (h / 2)
            u, v = fn(xn, yn)
            u, v = u * scale, v * scale
            if math.hypot(u, v) < 1.2:
                continue
            f.add(f'<line x1="{px - u / 2:.1f}" y1="{py - v / 2:.1f}" x2="{px + u / 2:.1f}" y2="{py + v / 2:.1f}" '
                  f'stroke="{color}" stroke-width="1.4" marker-end="url(#{cls})" />')


def a5_rotacional():
    f = Fig("a5-campo-de-velocidad-rotacional", 1200, 600, "A5.3: derotacion del flujo optico")
    f.text(24, 36, "DEROTACIÓN: RESTAR EL FLUJO QUE PRODUCE LA ROTACIÓN PROPIA DEL DRON", "head")
    f.text(24, 56, "Anexo 5, IT.A5.3 · x = u − c_{x}, y = v − c_{y}; Δθ de la telemetría entre fotogramas (Δt real); flow_ttc.py, _derotate()", "small")
    f.rect(24, 76, 1152, 130, "panel", 10)
    f.text(600, 120, "u_{rot}(x, y) = (x y / f_{x}) Δθ_{x} − (f_{x} + x² / f_{x}) Δθ_{y} + y Δθ_{z}", "math", "middle")
    f.text(600, 158, "v_{rot}(x, y) = (f_{y} + y² / f_{y}) Δθ_{x} − (x y / f_{y}) Δθ_{y} − x Δθ_{z}", "math", "middle")
    f.text(600, 190, "Δθ_{x}: cabeceo · Δθ_{y}: guiñada · Δθ_{z}: alabeo", "small", "middle")
    # campos: avance + guinada
    fx = 2.2
    def trans(x, y): return (x * 14, y * 14)
    def rot(x, y):
        dy = 0.32
        return (-(fx + (x * x) / fx) * dy * 14, -(x * y / fx) * dy * 14)
    def raw(x, y):
        a, b = trans(x, y); c, d = rot(x, y); return (a + c, b + d)
    boxes = [(64, "flujo medido (u_{raw}, v_{raw})", raw), (454, "campo rotacional (u_{rot}, v_{rot})", rot),
             (844, "campo traslacional (u_{trans}, v_{trans})", trans)]
    for x, t, fn in boxes:
        _field(f, x, 250, 292, 230, fn, n=9)
        f.text(x + 146, 238, t, "ttl", "middle")
    f.text(410, 372, "−", "title", "middle")
    f.text(800, 372, "=", "title", "middle")
    f.add('<circle cx="990" cy="365" r="4" fill="#DC2626" />')
    f.text(998, 360, "FOE", "small")
    f.text(470, 516, "u_{trans} = u_{raw} − u_{rot}", "math", "middle")
    f.text(730, 516, "v_{trans} = v_{raw} − v_{rot}", "math", "middle")
    f.text(600, 552, "Ejemplo: avance con guiñada a la derecha. Tras restar la rotación queda la expansión radial desde el FOE.", "txt", "middle")
    f.text(600, 576, "Con más de 2° de rotación entre fotogramas (FLOW_MAX_ROTATION_DEG) no se estima: se sostiene el campo anterior o sale degradado.", "small", "middle")
    return f.save()


def a5_agregacion():
    f = Fig("a5-agregación-espacial-robusta", 1200, 640, "A5.6: del mapa de TTC por pixel al ObstacleField de 3x3 celdas")
    f.text(24, 36, "DEL MAPA DE TTC POR PÍXEL AL ObstacleField DE 3 × 3 CELDAS", "head")
    f.text(24, 56, "Anexo 5, IT.A5.6 · celdas calculadas en flow_ttc.py; reglas de bloqueo y API en obstacle_field.py", "small")
    # mapa ttc sintetico
    f.rect(24, 76, 330, 330, "panel", 10)
    f.text(44, 104, "TTC POR PÍXEL", "head-ink")
    x0, y0, w, h = 44, 118, 290, 194
    import random
    rnd = random.Random(3)
    n = 24
    for i in range(n):
        for j in range(16):
            cx_, cy_ = (i + 0.5) / n, (j + 0.5) / 16
            d = math.hypot(cx_ - 0.42, cy_ - 0.48)
            ttc = 1.0 + 9 * d + rnd.random() * 0.6
            if 0.30 < cx_ < 0.46 and 0.38 < cy_ < 0.62:
                ttc = 1.2 + rnd.random() * 0.3
            t = max(0.0, min(1.0, (ttc - 1) / 6))
            r_ = int(220 * (1 - t) + 37 * t); g_ = int(60 * (1 - t) + 158 * t); b_ = int(40 * (1 - t) + 95 * t)
            f.add(f'<rect x="{x0 + i * w / n:.1f}" y="{y0 + j * h / 16:.1f}" width="{w / n + .3:.1f}" height="{h / 16 + .3:.1f}" fill="rgb({r_},{g_},{b_})" />')
    for k in (1, 2):
        f.add(f'<line x1="{x0 + k * w / 3:.1f}" y1="{y0}" x2="{x0 + k * w / 3:.1f}" y2="{y0 + h}" stroke="#FFFFFF" stroke-width="2" />')
        f.add(f'<line x1="{x0}" y1="{y0 + k * h / 3:.1f}" x2="{x0 + w}" y2="{y0 + k * h / 3:.1f}" stroke="#FFFFFF" stroke-width="2" />')
    f.lines(44, 336, ["TTC = ‖p − FOE‖ · Δt / ‖v_{trans}‖ en", "segundos, solo en píxeles válidos", "(‖v_{trans}‖ sobre el piso de ruido)"], "txt", 19)
    f.add('<rect x="44" y="392" width="12" height="8" fill="rgb(220,60,40)" /><text class="small" x="60" y="400">TTC bajo</text>')
    f.add('<rect x="130" y="392" width="12" height="8" fill="rgb(37,158,95)" /><text class="small" x="146" y="400">TTC alto</text>')
    f.arrow([(358, 240), (386, 240)])
    # grilla
    f.rect(390, 76, 420, 330, "panel", 10)
    f.text(410, 104, "GRILLA 3 × 3: SECTOR × BANDA", "head-ink")
    gx, gy, cw, ch = 470, 140, 108, 74
    sect = ["izquierda", "centro", "derecha"]
    band = ["superior", "medio", "inferior"]
    vals = [[("∞", ".00", ".41"), ("6.8", ".00", ".46"), ("∞", ".00", ".12")],
            [("3.9", ".004", ".52"), ("1.4", ".021", ".48"), ("4.4", ".006", ".39")],
            [("5.7", ".002", ".44"), ("2.1", ".015", ".50"), ("6.1", ".00", ".37")]]
    for i, s in enumerate(sect):
        f.text(gx + i * cw + cw / 2, gy - 8, s, "txt-b", "middle")
    for j, b in enumerate(band):
        f.text(gx - 8, gy + j * ch + ch / 2 + 4, b, "txt-b", "end")
        for i in range(3):
            ttc, occ, conf = vals[j][i]
            blocked = (float(occ) >= 0.011 and float(conf) >= 0.15) or (ttc != "∞" and float(ttc) <= 2.5 and float(conf) >= 0.35)
            f.rect(gx + i * cw, gy + j * ch, cw, ch, "card-red" if blocked else "card", 0)
            f.text(gx + i * cw + 8, gy + j * ch + 20, f"TTC {ttc} s", "mono-s")
            f.text(gx + i * cw + 8, gy + j * ch + 38, f"ocup {occ}", "mono-s")
            f.text(gx + i * cw + 8, gy + j * ch + 56, f"conf {conf}", "mono-s")
    f.text(600, 384, "rojo: celda bloqueada (valores ilustrativos)", "small", "middle")
    f.arrow([(814, 240), (842, 240)])
    # por celda
    f.rect(846, 76, 330, 330, "panel", 10)
    f.text(866, 104, "POR CELDA", "head-ink")
    f.lines(866, 134, [
        "confianza = fracción de píxeles válidos",
        "    × confianza del FOE",
        "TTC = percentil 20 del TTC de la celda",
        "ocupación = clip(div × 0.45 / 8, 0, 1)",
        "    con div la divergencia media",
    ], "txt", 20)
    f.text(866, 250, "BLOQUEADA SI", "head-ink")
    f.lines(866, 278, [
        "confianza ≥ 0.15 y",
        "  ocupación ≥ 0.011 (Youden, D2)",
        "  o (confianza ≥ 0.35 y TTC ≤ 2.5 s)",
    ], "txt", 20)
    f.text(866, 360, "sin confianza suficiente no bloquea:", "small")
    f.text(866, 376, "falta de evidencia no es obstáculo", "small")
    # sector y consumidores
    f.rect(24, 426, 1152, 194, "card-gray", 10)
    f.text(44, 454, "DE LAS CELDAS A LO QUE CONSULTA EL LAZO RÁPIDO", "head-ink")
    f.bullets(44, 482, [
        "sector_ttc(s): mínimo TTC de las tres bandas del sector con confianza ≥ 0.15 (en el ejemplo, centro = 1.4 s).",
        "is_blocked(s): bloqueado si alguna celda del sector lo está. blocked_fraction(): celdas bloqueadas sobre 9 (en el ejemplo, 2/9).",
        "min_ttc(): mínimo sobre las 9 celdas con confianza suficiente.",
        "navigate, regla 7: evade si el TTC del centro es ≤ 3.2 s, o si el centro está bloqueado con TTC ≤ 4.6 s; gira 90° si blocked_fraction > 0.6.",
        "También lo usan la FSM, el gobernador de velocidad y el registro de vuelo; la capa estratégica no: juzga con la profundidad estimada.",
    ], "txt", 24)
    return f.save()


# ------------------------------------------------------------------------------------------------ A7
def a7():
    f = Fig("a7-maldicion-monocular", 1200, 620, "A7: por que el flujo monocular falla en pasajes obstruidos y que aporta el estereo")
    f.text(24, 36, "LA «MALDICIÓN MONOCULAR» Y LA ALTERNATIVA ESTEREOSCÓPICA", "head")
    f.text(24, 56, "Anexo 7 · complementa el Anexo 5 (flujo óptico, FOE y TTC)", "small")
    # panel 1: FOE
    f.rect(24, 76, 370, 520, "panel", 10)
    f.badge(46, 102, 1); f.text(66, 107, "Ciego en el FOE", "ttl")
    def flow(x, y): return (x * 18, y * 18)
    _field(f, 44, 124, 330, 240, flow, n=11)
    f.add('<circle cx="209" cy="244" r="7" fill="#DC2626" />')
    f.add('<rect x="186" y="222" width="46" height="44" fill="none" stroke="#DC2626" stroke-width="2" stroke-dasharray="4 3" />')
    f.text(209, 384, "recuadro rojo: obstáculo de frente, en el FOE", "small", "middle")
    f.text(209, 416, "‖v_{trans}(p)‖ = (V_{z} / Z) · ‖p − FOE‖", "math-s", "middle")
    f.lines(44, 450, [
        "El flujo crece con la distancia al FOE: un",
        "obstáculo justo en la dirección de avance",
        "casi no se mueve en la imagen, aunque sea",
        "el de mayor riesgo. En follaje denso, además,",
        "la textura repetida degrada el flujo.",
    ], "txt", 20)
    # panel 2: escala
    f.rect(414, 76, 370, 520, "panel", 10)
    f.badge(436, 102, 2); f.text(456, 107, "Escala ambigua", "ttl")
    f.add('<circle cx="460" cy="280" r="5" fill="#1A202C" />')
    f.add('<line x1="460" y1="280" x2="760" y2="170" class="ln-dash" />')
    f.add('<line x1="460" y1="280" x2="760" y2="330" class="ln-dash" />')
    f.add('<rect x="540" y="236" width="20" height="62" fill="#A0AEC0" />')
    f.add('<rect x="690" y="186" width="54" height="134" fill="#4A5568" />')
    f.text(550, 318, "cerca, chico", "small", "middle")
    f.text(717, 340, "lejos, grande", "small", "middle")
    f.lines(434, 404, [
        "Los dos objetos ocupan el mismo ángulo:",
        "una sola imagen no fija la distancia Z.",
        "El flujo solo da TTC = Z / V_{z}, un cociente:",
        "la distancia en metros no se recupera",
        "sin conocer la velocidad respecto de cada",
        "superficie.",
    ], "txt", 20)
    # panel 3: estereo
    f.rect(804, 76, 372, 520, "panel", 10)
    f.badge(826, 102, 3); f.text(846, 107, "Par estéreo", "ttl")
    f.add('<rect x="880" y="140" width="220" height="40" rx="8" fill="#E6F2FF" stroke="#0066CC" stroke-width="1.6" />')
    for cxx in (920, 1060):
        f.add(f'<circle cx="{cxx}" cy="160" r="14" fill="#FFFFFF" stroke="#0066CC" stroke-width="1.6" />')
    f.add('<line x1="920" y1="196" x2="1060" y2="196" class="ln" />')
    f.text(990, 214, "B", "txt-b", "middle")
    f.add('<circle cx="990" cy="300" r="6" fill="#D97706" />')
    f.add('<line x1="920" y1="174" x2="990" y2="300" stroke="#D97706" stroke-width="1.4" />')
    f.add('<line x1="1060" y1="174" x2="990" y2="300" stroke="#D97706" stroke-width="1.4" />')
    f.text(990, 352, "Z = f · B / d,   d = u_{L} − u_{R}", "math", "middle")
    f.lines(824, 392, [
        "Con la baseline B fija, la disparidad d entre",
        "las dos imágenes da la profundidad métrica",
        "en un solo instante: no necesita movimiento",
        "ni depende del FOE.",
        "Límites: superficies sin textura, rango útil",
        "acotado por B y calibración entre cámaras.",
        "En esta tesis el lazo lento usa profundidad",
        "monocular estimada (cap. 6); el estéreo queda",
        "como trabajo futuro (IT.12.4).",
    ], "txt", 20)
    return f.save()


# ------------------------------------------------------------------------------------------------ A8
def a8_capas():
    f = Fig("a8-tres-capas-control", 1200, 640, "A8.1: capas de control y lugar del brazo rl")
    f.text(24, 36, "CAPAS DE DECISIÓN DEL SISTEMA Y LUGAR DEL BRAZO rl PROPUESTO", "head")
    f.text(24, 56, "Anexo 8, IT.A8.1 · de la escala de la misión a la del controlador de vuelo", "small")
    layers = [
        ("EN TIERRA · UNA VEZ POR MISIÓN", "card", ["Manifiesto de misión (WebDCS) y plan de ruta con el VLM sobre el mapa cenital (cap. 4)"],
         ["LFM2.5-VL-1.6B: clasifica parches del mapa", "en los escenarios con obstrucción"]),
        ("CAPA ESTRATÉGICA · LAZO LENTO, ~1 Hz, HILO APARTE", "card-blue", ["Qué sectores del fotograma están libres a 15 m → sub-meta en coordenadas del mundo;", "en deadlock, barrido de 4 rumbos (cap. 5, IT.5.5 e IT.5.6)"],
         ["fuente: profundidad estimada (Depth Anything V2);", "nunca comanda velocidades"]),
        ("CAPA TÁCTICA · LAZO RÁPIDO, 5 Hz", "card-green", ["ObstacleField + guiado → macro-acción → action_to_command() → velocidades (cap. 5)"],
         ["implementados: slm, fsm, reactive", "propuesto: rl, política neuronal (este anexo)"]),
        ("CONTROL DE VUELO", "card", ["Velocidades → actitud y motores: controlador del simulador (Cosys-AirSim);", "en hardware real, el autopiloto (por ejemplo, PX4). No lo modifica ningún brazo."],
         ["fuera del alcance de la tesis"]),
    ]
    y = 76
    for i, (t, cls, body, side) in enumerate(layers):
        f.rect(24, y, 1152, 116, cls, 10)
        f.text(44, y + 28, t, "head-ink")
        f.lines(44, y + 56, body, "txt", 20)
        f.rect(800, y + 16, 356, 84, "card", 8)
        f.lines(816, y + 46, side, "txt-b" if i == 2 else "txt", 22)
        if i < 3:
            lbl = ["manifiesto con los puntos de paso", "sub-meta (x, y, z)", "comando de velocidad"][i]
            f.arrow([(400, y + 118), (400, y + 140)])
            f.text(412, y + 134, lbl, "small")
        y += 140
    return f.save()


def a8_cabezales():
    f = Fig("a8-arquitectura-dos-cabezales", 1200, 620, "A8: politica de dos cabezales propuesta para el brazo rl")
    f.text(24, 36, "POLÍTICA PROPUESTA PARA EL BRAZO rl: DOS RAMAS Y UN ACTOR-CRÍTICO", "head")
    f.text(24, 56, "Anexo 8 · observación {rgb, ttc_field, nav}; PPO con Stable-Baselines3; no implementada", "small")
    f.rect(24, 76, 560, 380, "panel", 10)
    f.text(44, 104, "RAMA CNN · FOTOGRAMA RGB", "head-ink")
    cnn = [("rgb: 84 × 84 × 3", "card"), ("Conv 32 filtros 8 × 8, paso 4 · ReLU", "card-blue"),
           ("Conv 64 filtros 4 × 4, paso 2 · ReLU", "card-blue"), ("Conv 64 filtros 3 × 3, paso 1 · ReLU", "card-blue"),
           ("Flatten (3136) → Linear 512 · ReLU", "card-blue")]
    for i, (t, cls) in enumerate(cnn):
        yy = 120 + i * 64
        f.rect(64, yy, 480, 44, cls)
        f.text(304, yy + 28, t, "ttl", "middle")
        if i < 4:
            f.arrow([(304, yy + 46), (304, yy + 62)])
    f.rect(604, 76, 572, 380, "panel", 10)
    f.text(624, 104, "RAMA DENSA · DATOS DEL LAZO", "head-ink")
    f.card(624, 120, 260, 100, "ttc_field (3, 3, 3) → 27", ["[ttc, ocupación, confianza]", "de las 9 celdas"])
    f.card(896, 120, 260, 100, "nav (6)", ["dist_wp, bearing_err,", "vx, vy, vz, alt"])
    f.add('<path class="ln" d="M754 222 V250 H1026 V222" />')
    f.arrow([(890, 250), (890, 262)])
    f.rect(740, 264, 300, 44, "card-blue")
    f.text(890, 292, "33 → Linear 64 · ReLU", "ttl", "middle")
    # concat
    f.rect(330, 476, 540, 44, "card-acc")
    f.text(600, 504, "Concatenación (512 + 64 = 576) → Linear 256 · ReLU", "ttl", "middle")
    f.arrow([(304, 440), (304, 460), (450, 460), (450, 474)])
    f.arrow([(890, 310), (890, 460), (750, 460), (750, 474)])
    f.rect(214, 552, 360, 52, "card-green")
    f.text(394, 576, "Actor: softmax sobre 6 macro-acciones", "ttl", "middle")
    f.text(394, 595, "MANTENER_RUMBO … FRENAR → action_to_command()", "small", "middle")
    f.rect(626, 552, 360, 52, "card-warn")
    f.text(806, 576, "Crítico: V(s), un valor", "ttl", "middle")
    f.text(806, 595, "solo durante el entrenamiento", "small", "middle")
    f.arrow([(520, 522), (520, 536), (394, 536), (394, 550)])
    f.arrow([(680, 522), (680, 536), (806, 536), (806, 550)])
    return f.save()


# ------------------------------------------------------------------------------------------------ A9
def a9():
    f = Fig("a9-alternativa-con-lewm", 1200, 660, "A9: LeWorldModel frente al VLM de la tesis")
    f.text(24, 36, "MODELO DE MUNDO LATENTE (LeWM) FRENTE AL VLM DE LA TESIS", "head")
    f.text(24, 56, "Anexo 9 · nada está implementado ni medido: [P] dato del paper (Maes et al., 2026); [E] estimación; [T] dato de la tesis", "small")
    f.rect(24, 76, 1152, 236, "panel", 10)
    f.text(44, 104, "LeWM: PREDECIR EN EL ESPACIO LATENTE Y PLANIFICAR CON CEM [P]", "head-ink")
    f.card(44, 124, 200, 110, "Fotograma RGB", ["224 × 224"])
    f.arrow([(246, 179), (270, 179)])
    f.card(272, 124, 230, 110, "Codificador ViT-Tiny", ["~5 M parámetros", "embedding z (192)"], "card-blue")
    f.arrow([(504, 179), (528, 179)])
    f.card(530, 124, 270, 110, "Predictor transformer", ["6 capas, ~10 M parámetros", "z_{t+1} a partir de z_{t} y la", "acción (inyectada por AdaLN)"], "card-blue")
    f.arrow([(802, 179), (826, 179)])
    f.card(828, 124, 328, 110, "Planificación por CEM", ["300 secuencias, 10–30 iteraciones,", "horizonte H = 5; costo ‖z_{H} − z_{g}‖²", "con z_{g} el embedding de la meta"], "card-green")
    f.text(600, 268, "~15 M parámetros en total · evaluado en Push-T, Reacher, OGBench-Cube y Two-Room: sin validación en visión aérea urbana", "txt", "middle")
    f.text(600, 292, "la meta es una imagen; la misión del dron se define por waypoints: habría que adaptar el objetivo", "small", "middle")
    # tabla
    f.rect(24, 332, 640, 304, "panel", 10)
    f.text(44, 360, "COMPARACIÓN", "head-ink")
    rows = [("", "VLM de la tesis", "LeWM"),
            ("Modelo", "LFM2.5-VL-1.6B [T]", "JEPA, ~15 M [P]"),
            ("Memoria", "~1.6 GB, Q4_K_M [T]", "~30 MB en FP16 [E]"),
            ("Función", "describe qué está libre", "predice consecuencias"),
            ("Salida", "enumeración JSON", "secuencia de acciones"),
            ("Rol hoy", "plan de ruta antes del vuelo", "ninguno (propuesta)"),
            ("Interpretable", "respuesta auditable", "latente, por sondas")]
    for i, (a, b, c) in enumerate(rows):
        yy = 392 + i * 34
        cls = "txt-b" if i == 0 or a else "txt"
        f.text(44, yy, a, "txt-b")
        f.text(200, yy, b, "txt-b" if i == 0 else "txt")
        f.text(450, yy, c, "txt-b" if i == 0 else "txt")
        if i == 0:
            f.add(f'<line x1="44" y1="{yy + 10}" x2="644" y2="{yy + 10}" stroke="#CBD5E0" stroke-width="1" />')
    # opciones
    f.rect(684, 332, 492, 304, "panel", 10)
    f.text(704, 360, "OPCIONES DE INTEGRACIÓN (IT.A9.4)", "head-ink")
    opts = [("A · Reemplazar al VLM", "no recomendada: pierde la semántica y", "exige definir la meta como imagen", "card-red"),
            ("B · Verificador de consecuencias", "recomendada como primer paso: predice el", "efecto de la acción y detecta sorpresas", "card-green"),
            ("C · Simulador latente para rl", "complementaria con el Anexo 8: entrenar", "la política del brazo rl «en imaginación»", "card-blue")]
    for i, (t, l1, l2, cls) in enumerate(opts):
        yy = 376 + i * 84
        f.rect(704, yy, 452, 72, cls)
        f.text(720, yy + 24, t, "ttl")
        f.text(720, yy + 46, l1, "txt")
        f.text(720, yy + 64, l2, "txt")
    return f.save()


ALL = [a2, a3_peft, a3_impacto, a4_decod, a4_invariante, a5_camara, a5_rotacional, a5_agregacion, a7, a8_capas, a8_cabezales, a9]

if __name__ == "__main__":
    for fn in ALL:
        print(fn().name)

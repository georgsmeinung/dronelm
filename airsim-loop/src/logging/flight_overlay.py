# Overlay del video de auditoria, compartido por main.py (WebDCS) y
# experiments/runner.py (2026-0929). Antes vivia inline en main.py; se movio
# aca para que ambos escriban exactamente el mismo video. Se dibuja sobre una
# COPIA del frame, hecha despues de que el original ya viajo al VLM/PNG de
# auditoria, asi que nunca vuelve al pipeline de percepcion.
from __future__ import annotations

import math
from typing import Any, Dict, Optional


def annotate_frame(
    final_state: Dict[str, Any],
    guidance: Dict[str, Any],
    wp_index: int,
    wp_total: int,
    elapsed_s: float,
    cycle: int,
) -> Optional[Any]:
    """Devuelve el frame RGB del estado con 4 lineas de overlay, o None si no hay frame."""
    frame = final_state.get("rgb_image")
    if frame is None:
        return None
    # pyrefly: ignore [missing-import]
    import cv2

    annotated_frame = frame.copy()

    decision = final_state.get("next_action", "MANTENER_RUMBO")
    flight_status = final_state.get("flight_status", "vuelo")
    route_ov = final_state.get("route", "")
    route_tag_ov = route_ov.upper() if route_ov else "DIRECT"
    ttc_val = final_state.get("estimated_ttc", float("inf"))
    ttc_str = f"{ttc_val:.1f}s" if ttc_val != float("inf") else "inf"

    h, w = annotated_frame.shape[:2]
    cv2.rectangle(annotated_frame, (0, 0), (w, 88), (10, 10, 15), -1)

    dec_color = (0, 255, 100) if "MANTENER" in decision else (0, 165, 255)
    if "SLM" in decision or "PARADA" in decision or "FRENAR" in decision:
        dec_color = (255, 100, 200)

    wp_str = f"WP {wp_index + 1}/{wp_total} ({guidance.get('distance', 0.0):.0f}m)" if wp_total else ""
    cv2.putText(annotated_frame, f"[{route_tag_ov}] ACT: {decision} {wp_str}", (10, 26),
                cv2.FONT_HERSHEY_SIMPLEX, 0.52, dec_color, 2, cv2.LINE_AA)

    cv2.putText(annotated_frame, f"TTC: {ttc_str} | {flight_status}", (w - 280, 26),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (220, 220, 220), 1, cv2.LINE_AA)

    telem_ov = final_state.get("telemetry") or {}
    pos_ov = telem_ov.get("position", {}) or {}
    vel_ov = telem_ov.get("velocity", {}) or {}
    orient_ov = telem_ov.get("orientation", {}) or {}
    speed_ov = math.hypot(float(vel_ov.get("vx", 0.0)), float(vel_ov.get("vy", 0.0)))
    ceil_ov = guidance.get("ceiling_z")
    ceil_txt = f" ceil={ceil_ov:+.1f}" if isinstance(ceil_ov, (int, float)) else ""
    cv2.putText(
        annotated_frame,
        f"t={elapsed_s:6.1f}s cy={cycle} | "
        f"pos=({pos_ov.get('x', 0.0):+.1f},{pos_ov.get('y', 0.0):+.1f},{pos_ov.get('z', 0.0):+.1f}){ceil_txt} | "
        # "°" no lo soporta la fuente Hershey de cv2.putText -- "deg" en su lugar.
        f"v={speed_ov:.2f}m/s pitch={math.degrees(float(orient_ov.get('pitch', 0.0))):+.1f}deg "
        f"roll={math.degrees(float(orient_ov.get('roll', 0.0))):+.1f}deg",
        (10, 52), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (200, 200, 200), 1, cv2.LINE_AA,
    )

    field_ov = final_state.get("obstacle_field")
    if field_ov is not None:
        sector_bits = []
        for sector, code in (("izquierda", "IZQ"), ("centro", "CEN"), ("derecha", "DER")):
            occ = field_ov.sector_occupancy(sector)
            ttc = field_ov.sector_ttc(sector)
            ttc_txt = f"{ttc:.1f}s" if ttc != float("inf") else "inf"
            bloq_txt = "!" if field_ov.is_blocked(sector) else ""
            sector_bits.append(f"{code} occ={occ:.2f} ttc={ttc_txt}{bloq_txt}")
        cv2.putText(
            annotated_frame, " | ".join(sector_bits),
            (10, 76), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (200, 200, 200), 1, cv2.LINE_AA,
        )
    return annotated_frame

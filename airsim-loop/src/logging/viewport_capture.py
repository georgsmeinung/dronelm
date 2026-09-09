# Captura de pantalla del viewport de Unreal Engine para composición paralela en video.
# Requiere `mss` (pip install mss) y `pywin32` (pip install pywin32) en Windows.
# Si alguno de los dos falta, o la ventana no está visible, capture() retorna None
# y el video se graba sin el panel de viewport (degradación silenciosa).
from __future__ import annotations

import os
from typing import Optional, Tuple

import numpy as np


def _find_window_rect(title_substr: str) -> Optional[Tuple[int, int, int, int]]:
    """Busca la primera ventana visible cuyo título contenga `title_substr`.
    Retorna (left, top, right, bottom) en coordenadas de pantalla, o None."""
    try:
        import win32gui

        found: list[Tuple[int, int, int, int]] = []

        def _cb(hwnd: int, _: object) -> None:
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd)
                if title_substr.lower() in title.lower():
                    rect = win32gui.GetWindowRect(hwnd)
                    # rect = (left, top, right, bottom)
                    w, h = rect[2] - rect[0], rect[3] - rect[1]
                    if w > 100 and h > 100:  # ignorar ventanas fantasma diminutas
                        found.append(rect)

        win32gui.EnumWindows(_cb, None)
        return found[0] if found else None
    except Exception:
        return None


class ViewportCapture:
    """Captura el viewport de Unreal Engine cada ciclo y devuelve un array BGR (numpy).

    Configuración vía variables de entorno:
      VIEWPORT_WINDOW_TITLE  - substring del título de la ventana (default: "UnrealEditor")
      VIEWPORT_REGION        - "left,top,right,bottom" para capturar una región fija en
                               lugar de buscar la ventana automáticamente.
    """

    def __init__(self) -> None:
        self._title = os.getenv("VIEWPORT_WINDOW_TITLE", "UnrealEditor")
        self._fixed_region: Optional[Tuple[int, int, int, int]] = None
        region_env = os.getenv("VIEWPORT_REGION", "")
        if region_env:
            try:
                parts = [int(x.strip()) for x in region_env.split(",")]
                if len(parts) == 4:
                    self._fixed_region = (parts[0], parts[1], parts[2], parts[3])
            except ValueError:
                pass

        self._sct = None
        try:
            import mss  # noqa: F401 -- solo verificamos que está disponible aquí
            import mss as _mss

            self._sct = _mss.mss()
        except Exception:
            pass

        self._warn_shown = False

    def capture(self) -> Optional[np.ndarray]:
        """Retorna frame BGR (H×W×3, uint8) o None si no es posible capturar."""
        if self._sct is None:
            if not self._warn_shown:
                print("[ViewportCapture] mss no disponible; instala con: pip install mss")
                self._warn_shown = True
            return None

        rect = self._fixed_region or _find_window_rect(self._title)
        if rect is None:
            if not self._warn_shown:
                print(f"[ViewportCapture] Ventana '{self._title}' no encontrada. "
                      "Usa VIEWPORT_WINDOW_TITLE o VIEWPORT_REGION para configurar.")
                self._warn_shown = True
            return None

        left, top, right, bottom = rect
        monitor = {"left": left, "top": top, "width": right - left, "height": bottom - top}
        try:
            img = self._sct.grab(monitor)
            # mss devuelve BGRA; np.array da shape (H, W, 4).
            # Descartamos alpha y ya tenemos BGR listo para cv2.
            arr: np.ndarray = np.array(img)[:, :, :3]
            return arr
        except Exception:
            return None

    def close(self) -> None:
        if self._sct is not None:
            try:
                self._sct.close()
            except Exception:
                pass
            self._sct = None

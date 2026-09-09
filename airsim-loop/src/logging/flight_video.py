# 2026-0903: grabacion de video WebM/VP8 de una corrida, sincronizado con el
# timeline del log (JSONL/CSV). Deliberadamente separado de FlightLogger --
# no todo consumidor de FlightLogger quiere pagar el costo de escribir un
# frame por ciclo a disco (batches de tesis, por ejemplo), asi que esto es
# opt-in y lo maneja quien arma el frame anotado (main.py), no el logger.
#
# Sincronizacion con el log: se escribe UN frame de video por ciclo del lazo
# tactico, a `fps=LOOP_HZ` -- el mismo cadencia real del lazo. Con eso,
# `video_t = frame_index / fps` aproxima razonablemente bien el `t` de la
# fila de CSV/JSONL correspondiente (ambos avanzan al mismo ritmo nominal),
# pero NO es una correspondencia exacta cuadro-a-cuadro: el lazo real no
# corre a `LOOP_HZ` perfectamente constante (jitter de red/RPC, deliberacion
# async, etc.), asi que el desvio acumulado crece con la duracion de la
# mision. Para una correspondencia exacta, cruzar por el numero de ciclo
# (columna `cycle` del CSV) en vez de por tiempo de video.
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional, Tuple

import numpy as np


class FlightVideoRecorder:
    """Escribe un frame anotado por ciclo a un archivo .webm (VP8) con cv2.VideoWriter.

    2026-0903: se probo primero con mp4v (MPEG-4 Part 2) y con avc1/H264 --
    mp4v produce un .mp4 que ningun navegador sabe decodificar (el <video>
    muestra duracion pero pantalla negra, cero fotogramas), y avc1/H264
    requiere la DLL de OpenH264 de Cisco que este build de OpenCV/FFmpeg no
    trae instalada (VideoWriter.isOpened() da True pero el archivo queda
    corrupto/vacio). VP8 en contenedor WebM es el unico codec que este build
    sabe codificar de verdad Y que todo navegador sabe reproducir sin
    plugins ni DLLs externas -- confirmado escribiendo y re-leyendo un video
    de prueba con cv2.VideoCapture antes de adoptarlo.

    2026-0909: soporte opcional para video "split-screen": si `with_viewport=True`,
    el VideoWriter se inicializa de forma lazy en el primer write_frame() que
    recibe un viewport_frame no-None, de modo que el ancho total = drone_w +
    viewport_w_escalado_al_mismo_alto. Si viewport_frame es None en un ciclo
    dado, ese ciclo se rellena con un panel negro del mismo ancho que el primero.
    """

    def __init__(self, out_path: str, frame_size: Tuple[int, int], fps: float,
                 with_viewport: bool = False) -> None:
        self.out_path = Path(out_path).with_suffix(".webm")
        self.out_path.parent.mkdir(parents=True, exist_ok=True)
        self.fps = max(1.0, float(fps))
        self._drone_size = (int(frame_size[0]), int(frame_size[1]))  # (ancho, alto), convencion cv2.VideoWriter
        self._with_viewport = with_viewport
        self._writer = None
        self._size: Optional[Tuple[int, int]] = None  # se fija en _init_writer
        self._frame_count = 0
        self._opened = False
        self._vp_panel_h: Optional[int] = None  # alto del panel viewport, fijado al primer frame compuesto

        if not with_viewport:
            # Sin viewport sabemos el tamanio de antemano; abrir ahora.
            self._init_writer(self._drone_size)

    def _init_writer(self, size: Tuple[int, int]) -> None:
        # pyrefly: ignore [missing-import]
        import cv2

        fourcc = cv2.VideoWriter_fourcc(*"VP80")
        self._writer = cv2.VideoWriter(str(self.out_path), fourcc, self.fps, size)
        self._size = size
        self._opened = self._writer.isOpened()
        if not self._opened:
            print(f"[FlightVideoRecorder] No se pudo abrir {self.out_path} para escritura (codec VP8/webm no disponible?).")

    def write_frame(self, frame: Optional[Any], viewport_frame: Optional[Any] = None) -> None:
        """Agrega un frame al video.

        Si `with_viewport=True` (pasado al constructor), viewport_frame se escala
        al alto del frame de drone y se concatena a la derecha. El VideoWriter se
        inicializa de forma lazy en el primer ciclo que tenga ambos frames.
        Ciclos con viewport_frame=None rellenan el panel derecho con negro.
        """
        if frame is None:
            return

        # pyrefly: ignore [missing-import]
        import cv2

        h, w = frame.shape[:2]

        if self._with_viewport:
            if not self._opened:
                if viewport_frame is None:
                    # Todavia no sabemos el alto total; esperar al primer frame con viewport.
                    return
                vp_h, vp_w = viewport_frame.shape[:2]
                # Escalar viewport al mismo ancho que el drone frame.
                vp_panel_h = max(1, int(vp_h * w / vp_w))
                self._vp_panel_h = vp_panel_h
                self._init_writer((w, h + vp_panel_h))

            # Asegurar que el drone frame tiene el tamanio esperado.
            drone_w = self._size[0]              # type: ignore[index]
            drone_h = self._size[1] - self._vp_panel_h  # type: ignore[operator]
            if w != drone_w or h != drone_h:
                frame = cv2.resize(frame, (drone_w, drone_h), interpolation=cv2.INTER_NEAREST)

            if viewport_frame is not None:
                panel = cv2.resize(viewport_frame, (drone_w, self._vp_panel_h), interpolation=cv2.INTER_AREA)
            else:
                panel = np.zeros((self._vp_panel_h, drone_w, 3), dtype=np.uint8)  # negro si no hay captura

            out_frame = np.concatenate([frame, panel], axis=0)  # drone arriba, viewport abajo
        else:
            if not self._opened:
                return
            if (w, h) != self._size:
                frame = cv2.resize(frame, self._size, interpolation=cv2.INTER_NEAREST)
            out_frame = frame

        if self._opened and out_frame is not None:
            self._writer.write(out_frame)  # type: ignore[union-attr]
            self._frame_count += 1

    def close(self) -> int:
        if self._opened and self._writer is not None:
            self._writer.release()
            self._opened = False
        return self._frame_count

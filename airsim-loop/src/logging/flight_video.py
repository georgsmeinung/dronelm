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

import os
import queue
import threading
from pathlib import Path
from typing import Any, Optional, Tuple

import numpy as np

# 2026-0929: escala del video respecto del frame de la camara. Con 1080x720 la
# codificacion VP8 costaba ~275 ms/frame, ejecutada EN el lazo de control: el
# ciclo pasaba de 0.21 s a 0.45 s y volvian los corcoveos de la trayectoria
# (el control da tirones mas grandes con dt mayor). Ahora la codificacion corre
# en un hilo aparte y ademas se reduce la escala para que el encoder alcance el
# ritmo del lazo. 1.0 = resolucion original.
VIDEO_SCALE = float(os.getenv("FLIGHT_VIDEO_SCALE", "0.6"))
_QUEUE_MAX = int(os.getenv("FLIGHT_VIDEO_QUEUE_MAX", "300"))
_SENTINEL = object()


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
                 with_viewport: bool = False, scale: Optional[float] = None,
                 threaded: bool = True) -> None:
        self.out_path = Path(out_path).with_suffix(".webm")
        self.out_path.parent.mkdir(parents=True, exist_ok=True)
        self.fps = max(1.0, float(fps))
        sc = VIDEO_SCALE if scale is None else float(scale)
        sc = min(1.0, max(0.1, sc))
        # (ancho, alto), convencion cv2.VideoWriter; pares (VP8 lo prefiere).
        self._drone_size = (max(2, int(frame_size[0] * sc) // 2 * 2), max(2, int(frame_size[1] * sc) // 2 * 2))
        self._queue: Optional[queue.Queue] = None
        self._thread: Optional[threading.Thread] = None
        if threaded:
            self._queue = queue.Queue(maxsize=max(1, _QUEUE_MAX))
            self._thread = threading.Thread(target=self._worker, name="flight-video", daemon=True)
            self._thread.start()
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

    def _worker(self) -> None:
        while True:
            item = self._queue.get()  # type: ignore[union-attr]
            if item is _SENTINEL:
                return
            try:
                self._write_sync(*item)
            except Exception as exc:  # la grabacion nunca debe tumbar el vuelo
                print(f"[FlightVideoRecorder] error codificando frame: {exc}")

    def write_frame(self, frame: Optional[Any], viewport_frame: Optional[Any] = None) -> None:
        """Encola un frame (un frame por ciclo, orden preservado).

        La codificacion corre en un hilo aparte; put() solo bloquea si el
        encoder lleva mas de FLIGHT_VIDEO_QUEUE_MAX frames de atraso.
        """
        if frame is None:
            return
        if self._queue is None:
            self._write_sync(frame, viewport_frame)
        else:
            self._queue.put((frame, viewport_frame))

    def _write_sync(self, frame: Optional[Any], viewport_frame: Optional[Any] = None) -> None:
        """Agrega un frame al video (codifica; corre en el hilo del recorder).

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
                frame = cv2.resize(frame, (drone_w, drone_h), interpolation=cv2.INTER_AREA)

            if viewport_frame is not None:
                panel = cv2.resize(viewport_frame, (drone_w, self._vp_panel_h), interpolation=cv2.INTER_AREA)
            else:
                panel = np.zeros((self._vp_panel_h, drone_w, 3), dtype=np.uint8)  # negro si no hay captura

            out_frame = np.concatenate([frame, panel], axis=0)  # drone arriba, viewport abajo
        else:
            if not self._opened:
                return
            if (w, h) != self._size:
                interp = cv2.INTER_AREA if (w > self._size[0] or h > self._size[1]) else cv2.INTER_NEAREST
                frame = cv2.resize(frame, self._size, interpolation=interp)
            out_frame = frame

        if self._opened and out_frame is not None:
            self._writer.write(out_frame)  # type: ignore[union-attr]
            self._frame_count += 1

    def close(self) -> int:
        if self._thread is not None:
            self._queue.put(_SENTINEL)  # type: ignore[union-attr]
            self._thread.join()
            self._thread = None
        if self._opened and self._writer is not None:
            self._writer.release()
            self._opened = False
        return self._frame_count

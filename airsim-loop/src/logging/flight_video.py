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
    """

    def __init__(self, out_path: str, frame_size: Tuple[int, int], fps: float) -> None:
        # pyrefly: ignore [missing-import]
        import cv2

        self.out_path = Path(out_path).with_suffix(".webm")
        self.out_path.parent.mkdir(parents=True, exist_ok=True)
        self.fps = max(1.0, float(fps))
        self._size = (int(frame_size[0]), int(frame_size[1]))  # (ancho, alto), convencion cv2.VideoWriter
        fourcc = cv2.VideoWriter_fourcc(*"VP80")
        self._writer = cv2.VideoWriter(str(self.out_path), fourcc, self.fps, self._size)
        self._frame_count = 0
        self._opened = self._writer.isOpened()
        if not self._opened:
            print(f"[FlightVideoRecorder] No se pudo abrir {self.out_path} para escritura (codec VP8/webm no disponible?).")

    def write_frame(self, frame: Optional[Any]) -> None:
        """Agrega un frame (ciclo degradado / sin imagen -> se omite, no se

        duplica el anterior: mantener eso simple es preferible a fingir
        continuidad que no existe).
        """
        if not self._opened or frame is None:
            return
        # pyrefly: ignore [missing-import]
        import cv2

        h, w = frame.shape[:2]
        if (w, h) != self._size:
            frame = cv2.resize(frame, self._size, interpolation=cv2.INTER_NEAREST)
        self._writer.write(frame)
        self._frame_count += 1

    def close(self) -> int:
        if self._opened:
            self._writer.release()
            self._opened = False
        return self._frame_count

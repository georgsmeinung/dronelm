# F0.5: Servicio de deliberacion asincrono.
#
# Antes, deliberative_node llamaba a _query_slm() de forma sincronica dentro
# del grafo: el lazo entero (captura + percepcion + control) quedaba
# bloqueado hasta 8s (el timeout del cliente OpenAI) por ciclo, y ademas
# graph.py invocaba el nodo dos veces por el bug de doble ruta (ver F0.2).
#
# DeliberationService corre la consulta al SLM en un hilo aparte con una cola
# de tamano 1 (el pedido mas nuevo reemplaza al pendiente: no tiene sentido
# acumular pedidos de un dron que ya se movio). El nodo deliberativo encola
# el pedido, emite el freno de seguridad ese ciclo, y en ciclos siguientes
# hace poll() hasta que la respuesta este lista o el watchdog expire.
from __future__ import annotations

import os
import queue
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Tuple

SLM_WATCHDOG_MS = float(os.getenv("SLM_WATCHDOG_MS", "1500"))


@dataclass
class DeliberationRequest:
    request_id: int
    submitted_at: float
    payload: Dict[str, Any]


@dataclass
class DeliberationResult:
    request_id: int
    completed_at: float
    parsed_decision: Optional[Dict[str, Any]]
    raw_response: str
    latency_ms: float
    error: Optional[str]


class DeliberationService:
    """Worker en background que consulta al SLM sin bloquear el lazo de control."""

    def __init__(self, query_fn: Callable[[Dict[str, Any]], Tuple[Optional[Dict[str, Any]], str, float, Optional[str]]]):
        self._query_fn = query_fn
        self._in_queue: "queue.Queue[DeliberationRequest]" = queue.Queue(maxsize=1)
        self._result_lock = threading.Lock()
        self._latest_result: Optional[DeliberationResult] = None
        self._pending_request: Optional[DeliberationRequest] = None
        self._next_id = 0
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, name="DeliberationService", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                req = self._in_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            parsed, raw, latency_ms, err = self._query_fn(req.payload)
            result = DeliberationResult(
                request_id=req.request_id,
                completed_at=time.time(),
                parsed_decision=parsed,
                raw_response=raw,
                latency_ms=latency_ms,
                error=err,
            )
            with self._result_lock:
                self._latest_result = result
                if self._pending_request is not None and self._pending_request.request_id == req.request_id:
                    self._pending_request = None

    def request(self, payload: Dict[str, Any]) -> int:
        """Encola un pedido nuevo, descartando cualquier pedido pendiente sin procesar.

        Devuelve el request_id asignado.
        """
        self._next_id += 1
        req = DeliberationRequest(request_id=self._next_id, submitted_at=time.time(), payload=payload)
        with self._result_lock:
            self._pending_request = req
        # Vaciar la cola (a lo sumo 1 elemento) para que el worker tome siempre
        # el pedido mas reciente en lugar de procesar uno stale.
        try:
            while True:
                self._in_queue.get_nowait()
        except queue.Empty:
            pass
        self._in_queue.put(req)
        return req.request_id

    def poll(self) -> Tuple[Optional[DeliberationResult], float, bool]:
        """Devuelve (resultado_mas_reciente_o_None, edad_del_pedido_pendiente_ms, hay_pedido_pendiente)."""
        with self._result_lock:
            result = self._latest_result
            pending = self._pending_request
        age_ms = (time.time() - pending.submitted_at) * 1000.0 if pending else 0.0
        return result, age_ms, pending is not None

    def is_watchdog_expired(self) -> bool:
        _, age_ms, pending = self.poll()
        return pending and age_ms > SLM_WATCHDOG_MS

    def stop(self) -> None:
        self._stop_event.set()

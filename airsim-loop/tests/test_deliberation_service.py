import time

from src.agents.deliberation_service import DeliberationService


def _slow_query(delay_s):
    def _fn(payload):
        time.sleep(delay_s)
        return {"macro_action": "MANTENER_RUMBO", "rationale": "ok"}, "raw", delay_s * 1000.0, None
    return _fn


def test_request_and_poll_eventually_returns_result():
    service = DeliberationService(query_fn=_slow_query(0.05))
    try:
        req_id = service.request({"prompt": "x"})
        deadline = time.time() + 2.0
        result = None
        while time.time() < deadline:
            result, _, _ = service.poll()
            if result is not None and result.request_id == req_id:
                break
            time.sleep(0.01)
        assert result is not None
        assert result.request_id == req_id
        assert result.parsed_decision["macro_action"] == "MANTENER_RUMBO"
    finally:
        service.stop()


def test_poll_reports_pending_while_worker_busy():
    service = DeliberationService(query_fn=_slow_query(0.3))
    try:
        service.request({"prompt": "x"})
        time.sleep(0.05)
        result, age_ms, pending = service.poll()
        assert pending is True
        assert age_ms > 0.0
    finally:
        service.stop()


def test_new_request_supersedes_pending_one_in_queue():
    """El pedido mas nuevo reemplaza al anterior en la cola (maxsize=1): no

    tiene sentido procesar un pedido stale de un dron que ya se movio.
    """
    calls = []

    def _fn(payload):
        calls.append(payload["prompt"])
        return {"macro_action": "MANTENER_RUMBO", "rationale": "ok"}, "raw", 1.0, None

    service = DeliberationService(query_fn=_fn)
    try:
        # Encolar dos pedidos muy rapido, antes de que el worker procese el primero.
        service.request({"prompt": "first"})
        second_id = service.request({"prompt": "second"})
        deadline = time.time() + 2.0
        while time.time() < deadline and len(calls) < 1:
            time.sleep(0.01)
        time.sleep(0.05)
        # El worker debe haber procesado como mucho el pedido mas reciente encolado
        # (nunca ambos como pedidos separados en la cola, dado maxsize=1).
        assert "second" in calls
    finally:
        service.stop()

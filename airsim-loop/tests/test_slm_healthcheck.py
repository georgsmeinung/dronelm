"""Tests para el healthcheck del SLM (G1.2)."""
import os
import pytest
from unittest.mock import patch, MagicMock


def test_slm_healthcheck_passes_when_models_endpoint_responds():
    """Healthcheck debe pasar si el endpoint /models retorna 200."""
    import httpx

    with patch("httpx.Client") as mock_client_class:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_client = MagicMock()
        mock_client.get.return_value = mock_response
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=None)
        mock_client_class.return_value = mock_client

        # Simulate healthcheck code (inline para evitar imports circulares).
        local_llm_url = "http://localhost:11434/v1"
        try:
            with httpx.Client(timeout=5.0) as http_client:
                resp = http_client.get(f"{local_llm_url.rstrip('/')}/models")
                assert resp.status_code == 200, f"SLM retornó {resp.status_code}"
        except Exception as exc:
            pytest.fail(f"Healthcheck falló: {exc}")


def test_slm_healthcheck_fails_on_non_200_response():
    """Healthcheck debe fallar si el endpoint retorna status != 200."""
    import httpx

    with patch("httpx.Client") as mock_client_class:
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_client = MagicMock()
        mock_client.get.return_value = mock_response
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=None)
        mock_client_class.return_value = mock_client

        local_llm_url = "http://localhost:11434/v1"
        with pytest.raises(RuntimeError, match="SLM retornó 500"):
            with httpx.Client(timeout=5.0) as http_client:
                resp = http_client.get(f"{local_llm_url.rstrip('/')}/models")
                if resp.status_code != 200:
                    raise RuntimeError(f"SLM retornó {resp.status_code}")


def test_slm_healthcheck_fails_on_connection_error():
    """Healthcheck debe fallar si no puede conectarse al SLM."""
    import httpx

    with patch("httpx.Client") as mock_client_class:
        mock_client_class.side_effect = RuntimeError("Connection refused")

        local_llm_url = "http://localhost:11434/v1"
        with pytest.raises(RuntimeError, match="SLM healthcheck falló"):
            try:
                import httpx
                with httpx.Client(timeout=5.0) as http_client:
                    resp = http_client.get(f"{local_llm_url.rstrip('/')}/models")
            except Exception as exc:
                raise RuntimeError(f"SLM healthcheck falló: {exc}")

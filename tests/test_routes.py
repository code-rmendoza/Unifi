"""
Tests de endpoints FastAPI con TestClient.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from fastapi import FastAPI
from fastapi.testclient import TestClient
from unifi_agent.api.routes import router


def get_test_client():
    """Crea un TestClient con la app de pruebas."""
    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


class TestHealthCheck:
    def test_health_returns_200(self):
        client = get_test_client()
        r = client.get("/health")
        assert r.status_code == 200

    def test_health_status_field(self):
        client = get_test_client()
        r = client.get("/health")
        data = r.json()
        assert "status" in data
        assert data["status"] in ("healthy", "degraded")

    def test_health_has_version(self):
        client = get_test_client()
        r = client.get("/health")
        assert "version" in r.json()


class TestHistorial:
    def test_historial_returns_200(self):
        client = get_test_client()
        r = client.get("/api/historial")
        assert r.status_code == 200

    def test_historial_structure(self):
        client = get_test_client()
        r = client.get("/api/historial")
        data = r.json()
        assert data["status"] == "success"
        assert "historial" in data


class TestAuthProtection:
    def test_diagnosticar_sin_auth(self):
        client = get_test_client()
        r = client.post("/api/diagnosticar")
        assert r.status_code == 401

    def test_diagnosticar_key_invalida(self):
        client = get_test_client()
        r = client.post("/api/diagnosticar", headers={"X-API-Key": "wrong-key"})
        assert r.status_code == 401

    def test_reiniciar_sin_auth(self):
        client = get_test_client()
        r = client.post("/api/reiniciar", json={"mac": "aa:bb:cc:dd:ee:ff", "nombre": "Test"})
        assert r.status_code == 401

    def test_optimizar_sin_auth(self):
        client = get_test_client()
        r = client.post("/api/optimizar", json={
            "tipo_red": "wifi", "nombre_red": "Test",
            "parametro": "fast_roaming", "valor": True
        })
        assert r.status_code == 401

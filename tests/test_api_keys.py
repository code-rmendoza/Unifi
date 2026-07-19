"""
Tests del sistema de API keys con rotación.
"""

import sys
import os
import sqlite3
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import pytest
from unifi_agent.services.api_keys import APIKeyManager


class TestAPIKeyManager:
    def _make_manager(self, tmp_path):
        db_path = str(tmp_path / "test_keys.db")
        mgr = APIKeyManager(db_path)
        mgr.inicializar_tabla()
        return mgr

    def test_generar_key(self, tmp_path):
        mgr = self._make_manager(tmp_path)
        result = mgr.generar_key("test-key")
        assert "key" in result
        assert result["key"].startswith("ua_")
        assert result["nombre"] == "test-key"

    def test_validar_key(self, tmp_path):
        mgr = self._make_manager(tmp_path)
        result = mgr.generar_key("valid-test")
        assert mgr.validar_key(result["key"]) is True

    def test_key_invalida(self, tmp_path):
        mgr = self._make_manager(tmp_path)
        assert mgr.validar_key("ua_invalida") is False

    def test_key_vacia(self, tmp_path):
        mgr = self._make_manager(tmp_path)
        assert mgr.validar_key("") is False

    def test_listar_keys(self, tmp_path):
        mgr = self._make_manager(tmp_path)
        mgr.generar_key("key1")
        mgr.generar_key("key2")
        keys = mgr.listar_keys()
        assert len(keys) == 2
        assert keys[0]["nombre"] in ("key1", "key2")

    def test_revocar_key(self, tmp_path):
        mgr = self._make_manager(tmp_path)
        result = mgr.generar_key("to-revoke")
        key_id = mgr.listar_keys()[0]["id"]
        assert mgr.revocar_key(key_id) is True
        # Después de revocar, ya no es válida
        assert mgr.validar_key(result["key"]) is False

    def test_eliminar_key(self, tmp_path):
        mgr = self._make_manager(tmp_path)
        mgr.generar_key("to-delete")
        key_id = mgr.listar_keys()[0]["id"]
        assert mgr.eliminar_key(key_id) is True
        assert len(mgr.listar_keys()) == 0

    def test_key_con_expiracion(self, tmp_path):
        mgr = self._make_manager(tmp_path)
        result = mgr.generar_key("expiring", expira_dias=-1)  # Ya expirada
        assert mgr.validar_key(result["key"]) is False

    def test_actualiza_uso(self, tmp_path):
        mgr = self._make_manager(tmp_path)
        result = mgr.generar_key("usage-test")
        mgr.validar_key(result["key"])
        mgr.validar_key(result["key"])
        keys = mgr.listar_keys()
        assert keys[0]["uso_count"] >= 2

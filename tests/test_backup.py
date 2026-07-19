"""
Tests del sistema de backup automático de SQLite.
"""

import sys
import os
import sqlite3
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import pytest
from unifi_agent.services.backup import BackupManager


def _crear_db_temp(db_path: str):
    """Crea una BD de prueba con datos."""
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS diagnosticos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            resumen_general TEXT,
            num_dispositivos INTEGER,
            num_usuarios INTEGER,
            num_problemas INTEGER,
            datos_completos TEXT
        )
    """)
    conn.execute(
        "INSERT INTO diagnosticos (resumen_general, num_dispositivos) VALUES (?, ?)",
        ("Test backup", 3),
    )
    conn.commit()
    conn.close()


class TestBackupManager:
    def test_crear_backup(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        _crear_db_temp(db_path)
        mgr = BackupManager(db_path, str(tmp_path / "backups"), retention_days=7)

        path = mgr.crear_backup(motivo="test")
        assert path is not None
        assert os.path.exists(path)

    def test_listar_backups(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        _crear_db_temp(db_path)
        mgr = BackupManager(db_path, str(tmp_path / "backups"))

        mgr.crear_backup(motivo="test1")
        mgr.crear_backup(motivo="test2")

        backups = mgr.listar_backups()
        assert len(backups) == 2
        assert backups[0]["nombre"].endswith(".db")

    def test_info_db(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        _crear_db_temp(db_path)
        mgr = BackupManager(db_path, str(tmp_path / "backups"))

        info = mgr.obtener_info_db()
        assert info["existe"] is True
        assert info["registros"] == 1
        assert info["tamano_bytes"] > 0

    def test_info_db_no_existe(self, tmp_path):
        mgr = BackupManager(str(tmp_path / "noexiste.db"), str(tmp_path / "backups"))
        info = mgr.obtener_info_db()
        assert info["existe"] is False

    def test_limpiar_backups_antiguos(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        _crear_db_temp(db_path)
        mgr = BackupManager(db_path, str(tmp_path / "backups"), max_backups=2)

        mgr.crear_backup(motivo="old1")
        mgr.crear_backup(motivo="old2")
        mgr.crear_backup(motivo="new")

        eliminados = mgr.limpiar_backups_antiguos()
        assert eliminados >= 0
        assert len(mgr.listar_backups()) <= 3

    def test_restaurar_backup(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        _crear_db_temp(db_path)
        mgr = BackupManager(db_path, str(tmp_path / "backups"))

        path = mgr.crear_backup(motivo="restore_test")
        nombre = os.path.basename(path)
        ok = mgr.restaurar_backup(nombre)
        assert ok is True

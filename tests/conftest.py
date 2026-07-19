"""
Fixtures compartidas para los tests.
"""

import os
import sys
import tempfile
import sqlite3

import pytest

# Añadir src/ al path para imports del paquete
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))


@pytest.fixture
def tmp_db(tmp_path):
    """BD temporal para tests — no toca la BD real."""
    db_path = str(tmp_path / "test_historial.db")
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
    conn.commit()
    conn.close()
    return db_path

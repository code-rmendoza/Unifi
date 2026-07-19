"""
Gestión de API keys con rotación, almacenamiento en BD y validación.
"""

import os
import secrets
import sqlite3
import hashlib
import logging
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger("UniFiAgent")


# ============================================================================
# API KEY MANAGER
# ============================================================================

class APIKeyManager:
    """Gestiona API keys con rotación y almacenamiento persistente."""

    def __init__(self, db_path: str):
        self.db_path = db_path

    def inicializar_tabla(self):
        """Crea la tabla de API keys si no existe."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS api_keys (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key_hash TEXT UNIQUE NOT NULL,
                    nombre TEXT NOT NULL,
                    activa INTEGER DEFAULT 1,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    expires_at DATETIME,
                    last_used_at DATETIME,
                    uso_count INTEGER DEFAULT 0
                )
            """)

    def _hash_key(self, key: str) -> str:
        """Genera hash SHA-256 de una API key."""
        return hashlib.sha256(key.encode()).hexdigest()

    def generar_key(self, nombre: str, expira_dias: int | None = None) -> dict:
        """
        Genera una nueva API key.

        Args:
            nombre: Nombre descriptivo de la key
            expira_dias: Días hasta la expiración (None = sin expiración)

        Returns:
            Dict con la key en texto plano y metadatos
        """
        key = f"ua_{secrets.token_urlsafe(32)}"
        key_hash = self._hash_key(key)

        expires_at = None
        if expira_dias:
            expires_at = (datetime.now() + timedelta(days=expira_dias)).isoformat()

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO api_keys (key_hash, nombre, expires_at) VALUES (?, ?, ?)",
                (key_hash, nombre, expires_at),
            )

        logger.info(f"API key generada: {nombre}")
        return {
            "key": key,
            "nombre": nombre,
            "expires_at": expires_at,
            "mensaje": "Guarda esta key. No se volverá a mostrar.",
        }

    def validar_key(self, key: str) -> bool:
        """
        Valida si una API key es válida y activa.

        Args:
            key: API key en texto plano

        Returns:
            True si es válida
        """
        if not key:
            return False

        key_hash = self._hash_key(key)

        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT id, activa, expires_at FROM api_keys WHERE key_hash = ?",
                (key_hash,),
            ).fetchone()

        if not row:
            return False

        key_id, activa, expires_at = row

        if not activa:
            return False

        if expires_at:
            expira = datetime.fromisoformat(expires_at)
            if datetime.now() > expira:
                logger.warning(f"API key expirada: id={key_id}")
                return False

        # Actualizar uso
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE api_keys SET last_used_at = CURRENT_TIMESTAMP, uso_count = uso_count + 1 WHERE id = ?",
                (key_id,),
            )

        return True

    def listar_keys(self) -> list[dict]:
        """Lista todas las API keys (sin mostrar el hash)."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT id, nombre, activa, created_at, expires_at, last_used_at, uso_count FROM api_keys ORDER BY created_at DESC"
            ).fetchall()

        return [
            {
                "id": r[0],
                "nombre": r[1],
                "activa": bool(r[2]),
                "created_at": r[3],
                "expires_at": r[4],
                "last_used_at": r[5],
                "uso_count": r[6],
            }
            for r in rows
        ]

    def revocar_key(self, key_id: int) -> bool:
        """Revoca (desactiva) una API key por su ID."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "UPDATE api_keys SET activa = 0 WHERE id = ?", (key_id,)
            )
            if cursor.rowcount > 0:
                logger.info(f"API key revocada: id={key_id}")
                return True
        return False

    def eliminar_key(self, key_id: int) -> bool:
        """Elimina permanentemente una API key."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("DELETE FROM api_keys WHERE id = ?", (key_id,))
            if cursor.rowcount > 0:
                logger.info(f"API key eliminada: id={key_id}")
                return True
        return False

    def limpiar_expiradas(self) -> int:
        """Elimina keys expiradas. Retorna cantidad eliminadas."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "DELETE FROM api_keys WHERE expires_at IS NOT NULL AND expires_at < ?",
                (datetime.now().isoformat(),),
            )
            eliminadas = cursor.rowcount
        if eliminadas > 0:
            logger.info(f"Keys expiradas eliminadas: {eliminadas}")
        return eliminadas


# ============================================================================
# MODO LEGACY: API_KEY desde .env
# ============================================================================

def crear_manager_desde_env(db_path: str) -> APIKeyManager:
    """Crea un manager e importa la key legacy de .env si existe."""
    manager = APIKeyManager(db_path)
    manager.inicializar_tabla()

    legacy_key = os.getenv("API_KEY")
    if legacy_key:
        key_hash = manager._hash_key(legacy_key)
        with sqlite3.connect(db_path) as conn:
            existe = conn.execute(
                "SELECT 1 FROM api_keys WHERE key_hash = ?", (key_hash,)
            ).fetchone()
            if not existe:
                conn.execute(
                    "INSERT INTO api_keys (key_hash, nombre, activa) VALUES (?, ?, ?)",
                    (key_hash, "legacy_env", 1),
                )
                logger.info("API key legacy importada desde .env")

    return manager

"""
Backup automático de SQLite con rotación por fecha y retención configurable.
"""

import os
import shutil
import sqlite3
import logging
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger("UniFiAgent")


# ============================================================================
# BACKUP MANAGER
# ============================================================================

class BackupManager:
    """Gestiona backups automáticos de la base de datos SQLite."""

    def __init__(
        self,
        db_path: str,
        backup_dir: str | None = None,
        retention_days: int = 30,
        max_backups: int = 50,
    ):
        """
        Args:
            db_path: Ruta de la base de datos a respaldar
            backup_dir: Directorio donde almacenar backups
            retention_days: Días de retención de backups antiguos
            max_backups: Número máximo de backups a mantener
        """
        self.db_path = db_path
        self.backup_dir = Path(backup_dir or os.getenv("BACKUP_DIR", "backups"))
        self.retention_days = retention_days
        self.max_backups = max_backups
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    def crear_backup(self, motivo: str = "automatico") -> str | None:
        """
        Crea un backup de la base de datos.

        Args:
            motivo: Razón del backup (automatico, manual, pre_migracion)

        Returns:
            Ruta del backup creado o None si falló
        """
        if not os.path.exists(self.db_path):
            logger.warning(f"No se puede respaldar: {self.db_path} no existe")
            return None

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        db_name = Path(self.db_path).stem
        backup_name = f"{db_name}_{timestamp}_{motivo}.db"
        backup_path = self.backup_dir / backup_name

        try:
            # Usar SQLite backup API (seguro incluso con conexiones activas)
            source = sqlite3.connect(self.db_path)
            dest = sqlite3.connect(str(backup_path))
            source.backup(dest)
            dest.close()
            source.close()

            size_mb = backup_path.stat().st_size / (1024 * 1024)
            logger.info(f"Backup creado: {backup_name} ({size_mb:.2f} MB)")
            return str(backup_path)

        except Exception as e:
            logger.error(f"Error al crear backup: {e}")
            if backup_path.exists():
                backup_path.unlink()
            return None

    def listar_backups(self) -> list[dict]:
        """Lista todos los backups disponibles ordenados por fecha."""
        backups = []
        for f in sorted(self.backup_dir.glob("*.db")):
            stat = f.stat()
            backups.append({
                "nombre": f.name,
                "ruta": str(f),
                "tamano_bytes": stat.st_size,
                "tamano_mb": round(stat.st_size / (1024 * 1024), 2),
                "fecha": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            })
        return backups

    def limpiar_backups_antiguos(self) -> int:
        """
        Elimina backups que excedan la retención configurada.

        Returns:
            Número de backups eliminados
        """
        eliminados = 0
        fecha_limite = datetime.now() - timedelta(days=self.retention_days)

        # Primero: eliminar por antigüedad
        for f in self.backup_dir.glob("*.db"):
            fecha_archivo = datetime.fromtimestamp(f.stat().st_mtime)
            if fecha_archivo < fecha_limite:
                f.unlink()
                eliminados += 1
                logger.info(f"Backup eliminado (antiguo): {f.name}")

        # Segundo: eliminar por exceso de cantidad
        backups = sorted(
            self.backup_dir.glob("*.db"),
            key=lambda x: x.stat().st_mtime,
            reverse=True,
        )
        for f in backups[self.max_backups:]:
            f.unlink()
            eliminados += 1
            logger.info(f"Backup eliminado (exceso): {f.name}")

        if eliminados > 0:
            logger.info(f"Limpieza de backups: {eliminados} eliminados")

        return eliminados

    def restaurar_backup(self, backup_name: str) -> bool:
        """
        Restaura un backup específico sobre la base de datos actual.

        Args:
            backup_name: Nombre del archivo de backup a restaurar

        Returns:
            True si se restauró correctamente
        """
        backup_path = self.backup_dir / backup_name
        if not backup_path.exists():
            logger.error(f"Backup no encontrado: {backup_name}")
            return False

        try:
            # Crear backup de seguridad antes de restaurar
            self.crear_backup(motivo="pre_restauracion")

            shutil.copy2(str(backup_path), self.db_path)
            logger.info(f"Backup restaurado: {backup_name} -> {self.db_path}")
            return True

        except Exception as e:
            logger.error(f"Error al restaurar backup: {e}")
            return False

    def obtener_info_db(self) -> dict:
        """Obtiene información de la base de datos actual."""
        if not os.path.exists(self.db_path):
            return {"existe": False}

        size = os.path.getsize(self.db_path)
        conn = sqlite3.connect(self.db_path)
        try:
            count = conn.execute("SELECT COUNT(*) FROM diagnosticos").fetchone()[0]
        except Exception:
            count = 0
        finally:
            conn.close()

        return {
            "existe": True,
            "ruta": self.db_path,
            "tamano_bytes": size,
            "tamano_mb": round(size / (1024 * 1024), 2),
            "registros": count,
        }

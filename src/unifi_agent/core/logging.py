"""
Logging centralizado: JSON estructurado, syslog, rotación por tiempo.
Configurable via variables de entorno.
"""

import os
import sys
import json
import logging
import logging.handlers
from datetime import datetime, timezone


# ============================================================================
# FORMATEADOR JSON PARA PRODUCCIÓN
# ============================================================================

class JSONFormatter(logging.Formatter):
    """Formatter que emite logs en formato JSON estructurado."""

    def format(self, record):
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        if record.exc_info and record.exc_info[0]:
            log_entry["exception"] = self.formatException(record.exc_info)
        if hasattr(record, "extra_data"):
            log_entry["extra"] = record.extra_data
        return json.dumps(log_entry, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    """Formatter legible para desarrollo."""

    def format(self, record):
        return f"{recordasctime} - {record.levelname} - {record.getMessage()}"


# ============================================================================
# CONFIGURACIÓN DEL SISTEMA DE LOGGING
# ============================================================================

def setup_logging(
    log_level: str | None = None,
    log_file: str | None = None,
    log_format: str | None = None,
    syslog_address: str | None = None,
    max_bytes: int = 5 * 1024 * 1024,
    backup_count: int = 5,
):
    """
    Configura el sistema de logging de la aplicación.

    Args:
        log_level: Nivel de log (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Ruta del archivo de log
        log_format: 'json' o 'text'
        syslog_address: Dirección del syslog (host:port o /path/to/socket)
        max_bytes: Tamaño máximo por archivo de log
        backup_count: Número de backups rotativos a mantener
    """
    level = log_level or os.getenv("LOG_LEVEL", "INFO").upper()
    fmt = log_format or os.getenv("LOG_FORMAT", "text").lower()
    filepath = log_file or os.getenv("LOG_FILE", "unifi_agent.log")
    syslog_addr = syslog_address or os.getenv("LOG_SYSLOG_ADDRESS")

    root_logger = logging.getLogger("UniFiAgent")
    root_logger.setLevel(getattr(logging, level, logging.INFO))

    # Limpiar handlers existentes
    root_logger.handlers.clear()

    # Formatter
    if fmt == "json":
        formatter = JSONFormatter()
    else:
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

    # Handler 1: Archivo rotativo por tamaño
    try:
        file_handler = logging.handlers.RotatingFileHandler(
            filepath, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
    except (OSError, PermissionError):
        pass

    # Handler 2: Consola (solo en desarrollo o si LOG_CONSOLE=true)
    log_console = os.getenv("LOG_CONSOLE", "true").lower() == "true"
    if log_console:
        console_handler = logging.StreamHandler(sys.stdout)
        if fmt == "json":
            console_handler.setFormatter(JSONFormatter())
        else:
            console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

    # Handler 3: Syslog (opcional)
    if syslog_addr:
        try:
            if syslog_addr.startswith("/"):
                address = syslog_addr
            else:
                parts = syslog_addr.split(":")
                address = (parts[0], int(parts[1]) if len(parts) > 1 else 514)

            syslog_handler = logging.handlers.SysLogHandler(address=address)
            syslog_handler.setFormatter(formatter)
            root_logger.addHandler(syslog_handler)
        except (ValueError, OSError):
            root_logger.warning(f"No se pudo conectar a syslog: {syslog_addr}")

    return root_logger


# ============================================================================
# LOGGER COMPARTIDO
# ============================================================================

def get_logger(name: str = "UniFiAgent") -> logging.Logger:
    """Obtiene un logger con el nombre especificado."""
    return logging.getLogger(name)

"""
Utilidades compartidas: colores ANSI, logging, formato de uptime,
y funciones de display para la CLI.
"""

import sys
import logging
from datetime import timedelta

from unifi_agent.core import config
from unifi_agent.core.logging import setup_logging


# ============================================================================
# LOGGER COMPARTIDO (inicializado por setup_logging)
# ============================================================================

logger = logging.getLogger("UniFiAgent")


# ============================================================================
# CÓDIGOS ANSI PARA COLORES EN CONSOLA
# ============================================================================

class Color:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    WHITE = "\033[97m"
    BG_RED = "\033[41m"
    BG_GREEN = "\033[42m"
    BG_YELLOW = "\033[43m"
    BG_BLUE = "\033[44m"


# ============================================================================
# FORMATEO
# ============================================================================

def formatear_uptime(segundos: int) -> str:
    """Convierte segundos de uptime a formato legible (ej: '3d 14h 22m')."""
    if not segundos or segundos <= 0:
        return "N/A"
    delta = timedelta(seconds=segundos)
    dias = delta.days
    horas, resto = divmod(delta.seconds, 3600)
    minutos, _ = divmod(resto, 60)
    partes = []
    if dias > 0:
        partes.append(f"{dias}d")
    if horas > 0:
        partes.append(f"{horas}h")
    partes.append(f"{minutos}m")
    return " ".join(partes)


# ============================================================================
# FUNCIONES DE DISPLAY PARA CONSOLA
# ============================================================================

def imprimir_banner():
    """Imprime el banner de bienvenida del agente en Unicode o ASCII si falla."""
    banner_unicode = f"""
{Color.CYAN}{Color.BOLD}
    ╔══════════════════════════════════════════════════════════════╗
    ║                                                              ║
    ║   🛜  AGENTE DE IA - OPTIMIZACIÓN DE RED UNIFI              ║
    ║                                                              ║
    ║   Diagnóstico inteligente · Acciones automatizadas           ║
    ║   Human-in-the-Loop · Powered by Gemini AI                   ║
    ║                                                              ║
    ╚══════════════════════════════════════════════════════════════╝
{Color.RESET}"""
    banner_ascii = f"""
{Color.CYAN}{Color.BOLD}
    ==============================================================
      AGENTE DE IA - OPTIMIZACIÓN DE RED UNIFI
      Diagnóstico inteligente | Acciones automatizadas
      Human-in-the-Loop | Powered by Gemini AI
    ==============================================================
{Color.RESET}"""
    try:
        print(banner_unicode)
    except UnicodeEncodeError:
        print(banner_ascii)


def imprimir_seccion(titulo: str, icono: str = "▸"):
    """Imprime un separador de sección estilizado y lo registra en el log."""
    ancho = 60
    logger.info(f"=== SECCIÓN: {titulo} ===")
    try:
        print(f"\n{Color.BLUE}{Color.BOLD}{'─' * ancho}")
        print(f"  {icono}  {titulo}")
        print(f"{'─' * ancho}{Color.RESET}\n")
    except UnicodeEncodeError:
        print(f"\n{Color.BLUE}{Color.BOLD}{'-' * ancho}")
        print(f"  >  {titulo}")
        print(f"{'-' * ancho}{Color.RESET}\n")


def imprimir_estado(mensaje: str, tipo: str = "info"):
    """Imprime un mensaje de estado con color y lo registra en el log rotativo."""
    iconos_unicode = {
        "info": "ℹ", "ok": "✔", "warn": "⚠", "error": "✖", "accion": "⚡",
    }
    iconos_ascii = {
        "info": "[INFO]", "ok": "[OK]", "warn": "[WARN]",
        "error": "[ERROR]", "accion": "[ACCION]",
    }
    colores = {
        "info": Color.CYAN, "ok": Color.GREEN, "warn": Color.YELLOW,
        "error": Color.RED, "accion": Color.MAGENTA,
    }

    if tipo == "error":
        logger.error(mensaje)
    elif tipo == "warn":
        logger.warning(mensaje)
    elif tipo in ("ok", "accion"):
        logger.info(f"[{tipo.upper()}] {mensaje}")
    else:
        logger.info(mensaje)

    color = colores.get(tipo, Color.RESET)
    try:
        icono = iconos_unicode.get(tipo, "ℹ")
        print(f"  {color}{icono}  {mensaje}{Color.RESET}")
    except UnicodeEncodeError:
        icono = iconos_ascii.get(tipo, "[INFO]")
        print(f"  {color}{icono} {mensaje}{Color.RESET}")

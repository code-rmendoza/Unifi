"""
╔══════════════════════════════════════════════════════════════════════════════╗
║       AGENTE DE IA PARA OPTIMIZACIÓN DE RED UNIFI                          ║
║       ─────────────────────────────────────────────                         ║
║       Autor: Generado por Antigravity AI                                   ║
║       Versión: 1.0.0                                                       ║
║       Python: 3.10+                                                        ║
║                                                                            ║
║       Este script se conecta a un controlador UniFi Network Application    ║
║       (UDM Pro, Cloud Key, etc.), extrae métricas de salud de los          ║
║       dispositivos, las envía a Google Gemini para diagnóstico             ║
║       inteligente y permite ejecutar acciones correctivas con              ║
║       confirmación humana (Human-in-the-Loop).                             ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

# ============================================================================
# IMPORTACIONES
# ============================================================================
import os
import sys
import json
import time
import warnings
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime, timedelta
from typing import Optional, Union

import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry
import urllib3
from dotenv import load_dotenv
from pydantic import BaseModel, Field

# SDK oficial de Google Gemini (google-genai, reemplaza a google-generativeai)
from google import genai

# ============================================================================
# CONFIGURACIÓN INICIAL Y LOGGING
# ============================================================================

# Cargar variables de entorno desde el archivo .env
load_dotenv()

# Forzar codificación UTF-8 en salida estándar para soportar Unicode en Windows
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Configuración del Logger Rotativo para archivo físico
logger = logging.getLogger("UniFiAgent")
logger.setLevel(logging.DEBUG)

formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
log_file = "unifi_agent.log"
file_handler = RotatingFileHandler(log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding='utf-8')
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

# Suprimir advertencias de SSL para conexiones locales con certificados
# autofirmados. Esto es necesario porque los controladores UniFi usan
# certificados SSL autofirmados por defecto.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- Constantes de Configuración ---
UNIFI_HOST = os.getenv("UNIFI_HOST", "192.168.1.1")
UNIFI_PORT = os.getenv("UNIFI_PORT", "443")
UNIFI_USERNAME = os.getenv("UNIFI_USERNAME")
UNIFI_PASSWORD = os.getenv("UNIFI_PASSWORD")
UNIFI_SITE = os.getenv("UNIFI_SITE", "default")
UNIFI_CONTROLLER_TYPE = os.getenv("UNIFI_CONTROLLER_TYPE", "udm").lower()
UNIFI_VERIFY_SSL = os.getenv("UNIFI_VERIFY_SSL", "false").lower() == "true"
DRY_RUN = os.getenv("DRY_RUN", "false").lower() == "true"

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# --- Construcción de la URL Base ---
# La URL base depende del tipo de controlador:
#
# ┌─────────────────────────────────────────────────────────────────────────┐
# │ TIPO DE CONTROLADOR      │ PREFIJO DE API                             │
# ├─────────────────────────────────────────────────────────────────────────┤
# │ UDM / UDM Pro / UDM SE   │ https://<HOST>/proxy/network/api/s/<SITE>  │
# │ Cloud Key / Software      │ https://<HOST>:<PORT>/api/s/<SITE>         │
# └─────────────────────────────────────────────────────────────────────────┘
#
# Esto se debe a que los UDM ejecutan múltiples aplicaciones (Network,
# Protect, etc.) detrás de un proxy inverso en /proxy/network/.

BASE_URL = f"https://{UNIFI_HOST}:{UNIFI_PORT}"

if UNIFI_CONTROLLER_TYPE == "udm":
    API_PREFIX = f"{BASE_URL}/proxy/network/api/s/{UNIFI_SITE}"
    LOGIN_URL = f"{BASE_URL}/api/auth/login"
else:
    # Cloud Key o UniFi Network Application standalone
    API_PREFIX = f"{BASE_URL}/api/s/{UNIFI_SITE}"
    LOGIN_URL = f"{BASE_URL}/api/login"


# ============================================================================
# MAPEO DE ENDPOINTS DE LA API UNIFI
# ============================================================================
# A continuación se documentan todos los endpoints utilizados por este agente.
#
# ┌───────────────────────────────────────────────────────────────────────────┐
# │ ENDPOINT                          │ MÉTODO │ DESCRIPCIÓN                │
# ├───────────────────────────────────────────────────────────────────────────┤
# │ /api/auth/login        (UDM)      │ POST   │ Autenticación. Devuelve   │
# │ /api/login             (CK)       │        │ cookies de sesión.         │
# ├───────────────────────────────────────────────────────────────────────────┤
# │ {prefix}/stat/device              │ GET    │ Lista todos los            │
# │                                   │        │ dispositivos adoptados     │
# │                                   │        │ con métricas completas.    │
# ├───────────────────────────────────────────────────────────────────────────┤
# │ {prefix}/stat/health              │ GET    │ Salud general de la red    │
# │                                   │        │ (WAN, LAN, WLAN, VPN).    │
# ├───────────────────────────────────────────────────────────────────────────┤
# │ {prefix}/cmd/devmgr               │ POST   │ Comandos de gestión de    │
# │                                   │        │ dispositivos (restart,     │
# │                                   │        │ adopt, force-provision).   │
# └───────────────────────────────────────────────────────────────────────────┘

ENDPOINTS = {
    "login": LOGIN_URL,
    "dispositivos": f"{API_PREFIX}/stat/device",
    "salud": f"{API_PREFIX}/stat/health",
    "comando_dispositivo": f"{API_PREFIX}/cmd/devmgr",
    "config_wlan": f"{API_PREFIX}/rest/wlanconf",
    "config_network": f"{API_PREFIX}/rest/networkconf",
}


# ============================================================================
# EXCEPCIONES PERSONALIZADAS
# ============================================================================

class UniFiError(Exception):
    """Clase base para errores de integración de UniFi."""
    pass

class UniFiConnectionError(UniFiError):
    """Error al conectar físicamente o por tiempo de espera con el controlador."""
    pass

class UniFiAuthError(UniFiError):
    """Error al autenticar contra la API (ej: credenciales inválidas)."""
    pass

class UniFiAPIError(UniFiError):
    """La API devolvió un código de error inesperado o datos corruptos."""
    pass

class IAAnalysisError(Exception):
    """Error al comunicarse o procesar la respuesta con el LLM."""
    pass


# ============================================================================
# MODELOS PYDANTIC PARA VALIDACIÓN Y RESPUESTA ESTRUCTURADA
# ============================================================================

class MetricaDispositivo(BaseModel):
    """Esquema para validar y limpiar las métricas obtenidas del controlador."""
    nombre: str = Field(default="Sin nombre")
    mac: str = Field(default="N/A")
    modelo: str = Field(default="N/A")
    tipo: str
    estado: str = Field(default="desconocido")
    ip: str = Field(default="N/A")
    uptime: str = Field(default="N/A")
    uptime_segundos: int = Field(default=0)
    version_firmware: str = Field(default="N/A")
    satisfaccion: Union[int, str] = Field(default="N/A")
    num_usuarios: int = Field(default=0)
    carga_cpu: str = Field(default="N/A")
    uso_memoria: str = Field(default="N/A")
    tx_bytes: int = Field(default=0)
    rx_bytes: int = Field(default=0)
    ultimo_contacto: str = Field(default="N/A")


class ConfigWlan(BaseModel):
    """Esquema para validar las configuraciones de red WiFi."""
    ssid: str = Field(default="Sin SSID", alias="name")
    seguridad: str = Field(default="open", alias="security")
    wpa3: bool = Field(default=False, alias="wpa3_support")
    pmf: str = Field(default="optional", alias="pmf_mode")
    fast_roaming: bool = Field(default=False, alias="fast_roaming_enabled")
    uapsd: bool = Field(default=False, alias="uapsd_enabled")
    enhancement_multicast: bool = Field(default=False, alias="multicast_enhance")
    oculto: bool = Field(default=False, alias="hide_ssid")


class ConfigNetwork(BaseModel):
    """Esquema para validar las configuraciones de redes locales / VLANs."""
    nombre: str = Field(default="Sin nombre", alias="name")
    vlan_id: Optional[int] = Field(default=None, alias="vlan")
    proposito: str = Field(default="corporate", alias="purpose")
    subred: str = Field(default="N/A", alias="ip_subnet")
    dhcp_habilitado: bool = Field(default=True, alias="dhcpd_enabled")
    igmp_snooping: bool = Field(default=False, alias="igmp_snooping")
    upnp: bool = Field(default=False, alias="upnp_enabled")


class AccionRecomendada(BaseModel):
    """Modelo para una acción correctiva recomendada por la IA."""
    dispositivo: str          # Nombre del dispositivo afectado
    mac: str                  # Dirección MAC del dispositivo
    accion: str               # Tipo de acción: "reiniciar", "monitorear", "ninguna"
    motivo: str               # Justificación de la acción
    prioridad: str            # "critica", "alta", "media", "baja"


class AnalisisMejoresPracticas(BaseModel):
    """Modelo para el análisis de mejores prácticas de la configuración."""
    regla: str                # Regla analizada (ej: "Aislamiento de Red de Invitados", "Seguridad WPA3")
    estado_actual: str        # Configuración actual encontrada
    cumple: bool              # Si cumple o no con la mejor práctica
    recomendacion: str        # Acción correctiva o sugerencia
    prioridad: str            # "alta", "media", "baja"


class DiagnosticoRed(BaseModel):
    """Modelo completo del diagnóstico de la IA con análisis de mejores prácticas."""
    resumen_general: str                        # Resumen del estado de la red
    problemas_detectados: list[str]             # Lista de problemas encontrados
    mejores_practicas: list[AnalisisMejoresPracticas]  # Cumplimiento y optimizaciones de configuración
    acciones_recomendadas: list[AccionRecomendada]  # Acciones correctivas físicas recomendadas
    observaciones_adicionales: list[str]        # Tips adicionales de optimización


# ============================================================================
# UTILIDADES DE FORMATO PARA CONSOLA
# ============================================================================

# Códigos ANSI para colorear la salida en terminal
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
    """Imprime un separador de sección estilizado y lo registra en el archivo de log."""
    ancho = 60
    logger.info(f"=== SECCIÓN: {titulo} ===")
    try:
        print(f"\n{Color.BLUE}{Color.BOLD}{'─' * ancho}")
        print(f"  {icono}  {titulo}")
        print(f"{'─' * ancho}{Color.RESET}\n")
    except UnicodeEncodeError:
        # Caída de respaldo en sistemas que no soportan Unicode
        print(f"\n{Color.BLUE}{Color.BOLD}{'-' * ancho}")
        print(f"  >  {titulo}")
        print(f"{'-' * ancho}{Color.RESET}\n")


def imprimir_estado(mensaje: str, tipo: str = "info"):
    """Imprime un mensaje de estado con color y lo registra en el archivo de log rotativo."""
    iconos_unicode = {
        "info": "ℹ",
        "ok": "✔",
        "warn": "⚠",
        "error": "✖",
        "accion": "⚡",
    }
    iconos_ascii = {
        "info": "[INFO]",
        "ok": "[OK]",
        "warn": "[WARN]",
        "error": "[ERROR]",
        "accion": "[ACCION]",
    }
    
    colores = {
        "info": Color.CYAN,
        "ok": Color.GREEN,
        "warn": Color.YELLOW,
        "error": Color.RED,
        "accion": Color.MAGENTA,
    }
    
    # Escribir en el log rotativo primero
    if tipo == "error":
        logger.error(mensaje)
    elif tipo == "warn":
        logger.warning(mensaje)
    elif tipo in ("ok", "accion"):
        logger.info(f"[{tipo.upper()}] {mensaje}")
    else:
        logger.info(mensaje)

    # Imprimir en consola con respaldo ASCII si falla la codificación
    color = colores.get(tipo, Color.RESET)
    try:
        icono = iconos_unicode.get(tipo, "ℹ")
        print(f"  {color}{icono}  {mensaje}{Color.RESET}")
    except UnicodeEncodeError:
        icono = iconos_ascii.get(tipo, "[INFO]")
        print(f"  {color}{icono} {mensaje}{Color.RESET}")


def formatear_uptime(segundos: int) -> str:
    """Convierte segundos de uptime a un formato legible (ej: '3d 14h 22m')."""
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
# FUNCIÓN 1: CONEXIÓN AL CONTROLADOR UNIFI
# ============================================================================

def conectar_unifi() -> Optional[requests.Session]:
    """
    Autentica con el controlador UniFi y devuelve una sesión HTTP activa.

    Proceso:
    1. Crea una sesión de requests persistente (mantiene cookies).
    2. Configura un adaptador HTTP de reintentos automáticos (Retry) con backoff exponencial.
    3. Envía las credenciales al endpoint de login.
    4. El controlador devuelve cookies de sesión (csrf_token, TOKEN, etc.)
       que se almacenan automáticamente en la sesión.
    5. Todas las solicitudes posteriores usan estas cookies.

    Returns:
        requests.Session con autenticación activa, o None si falla.
    """
    imprimir_seccion("CONEXIÓN AL CONTROLADOR UNIFI", "🔐")
    imprimir_estado(f"Host: {UNIFI_HOST}:{UNIFI_PORT}", "info")
    imprimir_estado(f"Tipo de controlador: {UNIFI_CONTROLLER_TYPE.upper()}", "info")
    imprimir_estado(f"Sitio: {UNIFI_SITE}", "info")
    imprimir_estado(f"Verificación SSL: {'Sí' if UNIFI_VERIFY_SSL else 'No (autofirmado)'}", "info")

    # Validar que las credenciales existan
    if not UNIFI_USERNAME or not UNIFI_PASSWORD:
        imprimir_estado(
            "Las credenciales UNIFI_USERNAME y UNIFI_PASSWORD son obligatorias en .env",
            "error"
        )
        return None

    # Crear sesión persistente de requests
    sesion = requests.Session()
    sesion.verify = UNIFI_VERIFY_SSL

    # ── ESTRATEGIA DE REINTENTOS DE RED ──
    # Reintenta hasta 3 veces con una espera progresiva en caso de errores transitorios
    retries = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[500, 502, 503, 504],
        raise_on_status=False
    )
    adapter = HTTPAdapter(max_retries=retries)
    sesion.mount("https://", adapter)
    sesion.mount("http://", adapter)

    # Payload de autenticación
    payload_login = {
        "username": UNIFI_USERNAME,
        "password": UNIFI_PASSWORD,
    }

    try:
        imprimir_estado("Intentando autenticación...", "info")

        # ── ENDPOINT DE LOGIN ──
        # UDM Pro:  POST https://<HOST>/api/auth/login
        # Cloud Key: POST https://<HOST>:8443/api/login
        respuesta = sesion.post(
            ENDPOINTS["login"],
            json=payload_login,
            timeout=15,
        )

        if respuesta.status_code == 200:
            imprimir_estado("Autenticación exitosa ✓", "ok")

            # En UDM Pro / UniFi OS, el token CSRF se devuelve en las cabeceras (headers) de la respuesta de login.
            csrf_token = respuesta.headers.get("X-CSRF-Token")
            
            # Si no se encuentra en las cabeceras, buscamos en las cookies como fallback secundario.
            if not csrf_token:
                csrf_token = sesion.cookies.get("csrf_token")
                
            if csrf_token:
                sesion.headers.update({
                    "X-CSRF-Token": csrf_token,
                    "x-csrf-token": csrf_token
                })
                imprimir_estado("Token CSRF configurado y añadido a cabeceras de sesión", "ok")
            else:
                imprimir_estado("Aviso: No se detectó Token CSRF en cabeceras ni cookies de autenticación.", "warn")

            return sesion
        elif respuesta.status_code in (401, 403):
            raise UniFiAuthError(
                "Credenciales incorrectas o acceso denegado por el controlador."
            )
        else:
            raise UniFiAPIError(
                f"Error al intentar autenticar. Código HTTP: {respuesta.status_code}. "
                f"Respuesta: {respuesta.text[:150]}"
            )

    except UniFiAuthError as e:
        imprimir_estado(str(e), "error")
        imprimir_estado("Por favor, verifica UNIFI_USERNAME y UNIFI_PASSWORD en tu archivo .env", "warn")
        return None
    except UniFiAPIError as e:
        imprimir_estado(str(e), "error")
        return None
    except requests.exceptions.ConnectTimeout:
        imprimir_estado(
            f"Tiempo de conexión agotado al intentar alcanzar {UNIFI_HOST}:{UNIFI_PORT}",
            "error"
        )
        imprimir_estado(
            "Verifica que el controlador esté encendido y accesible en la red local.",
            "warn"
        )
        return None
    except requests.exceptions.ConnectionError as e:
        imprimir_estado(
            f"No se pudo conectar al controlador en {UNIFI_HOST}:{UNIFI_PORT}",
            "error"
        )
        imprimir_estado(
            "Posibles causas: host/puerto incorrecto, cortafuegos bloqueando la conexión, controlador apagado.",
            "warn"
        )
        return None
    except requests.exceptions.RequestException as e:
        imprimir_estado(f"Error inesperado de red durante la autenticación: {e}", "error")
        return None


# ============================================================================
# FUNCIÓN 2: OBTENER MÉTRICAS DE LA RED
# ============================================================================

def obtener_metricas_red(sesion: requests.Session) -> Optional[list[dict]]:
    """
    Extrae métricas de salud de todos los dispositivos UniFi adoptados.

    Proceso:
    1. Consulta el endpoint /stat/device que devuelve un JSON masivo
       con toda la información de cada dispositivo.
    2. Filtra solo Access Points (tipo "uap") y Switches (tipo "usw").
    3. Extrae campos relevantes y los estructura en un formato limpio.

    Campos extraídos por dispositivo:
    ┌────────────────────┬──────────────────────────────────────────────────┐
    │ Campo              │ Descripción                                      │
    ├────────────────────┼──────────────────────────────────────────────────┤
    │ nombre             │ Alias asignado al dispositivo o "Sin nombre"     │
    │ mac                │ Dirección MAC (identificador único)              │
    │ modelo             │ Modelo del hardware (ej: "U6-Pro", "USW-24")    │
    │ tipo               │ "Access Point" o "Switch"                        │
    │ estado             │ "conectado", "desconectado", etc.                │
    │ ip                 │ Dirección IP asignada                            │
    │ uptime             │ Tiempo de actividad en formato legible           │
    │ uptime_segundos    │ Tiempo de actividad en bruto (segundos)          │
    │ version_firmware   │ Versión del firmware instalado                   │
    │ satisfaccion       │ Puntuación de satisfacción de red (0-100)        │
    │ num_usuarios       │ Cantidad de clientes conectados                  │
    │ carga_cpu          │ Porcentaje de uso de CPU                         │
    │ uso_memoria        │ Porcentaje de uso de memoria RAM                 │
    │ tx_bytes           │ Bytes transmitidos (total)                       │
    │ rx_bytes           │ Bytes recibidos (total)                          │
    │ ultimo_contacto    │ Último contacto con el controlador (timestamp)   │
    └────────────────────┴──────────────────────────────────────────────────┘

    Args:
        sesion: Sesión HTTP autenticada con el controlador.

    Returns:
        Lista de diccionarios con las métricas, o None si falla.
    """
    imprimir_seccion("RECOPILACIÓN DE MÉTRICAS DE RED", "📊")

    try:
        imprimir_estado("Consultando dispositivos adoptados...", "info")

        # ── ENDPOINT: GET /stat/device ──
        # Devuelve un JSON con la estructura:
        # {
        #   "meta": {"rc": "ok"},
        #   "data": [
        #     {
        #       "mac": "aa:bb:cc:dd:ee:ff",
        #       "type": "uap",               ← Tipo: uap, usw, ugw, udm, etc.
        #       "name": "AP-Sala",
        #       "model": "U6Pro",
        #       "state": 1,                  ← 1=conectado, 0=desconectado
        #       "uptime": 345600,            ← Segundos
        #       "satisfaction": 98,          ← Score de experiencia (0-100)
        #       "num_sta": 12,               ← Número de clientes conectados
        #       "system-stats": {
        #         "cpu": "5.2",
        #         "mem": "42.1"
        #       },
        #       ...
        #     },
        #     ...
        #   ]
        # }
        respuesta = sesion.get(
            ENDPOINTS["dispositivos"],
            timeout=15,
        )

        if respuesta.status_code != 200:
            imprimir_estado(
                f"Error al consultar dispositivos. HTTP {respuesta.status_code}",
                "error"
            )
            return None

        datos = respuesta.json()
        dispositivos_raw = datos.get("data", [])

        if not dispositivos_raw:
            imprimir_estado("No se encontraron dispositivos adoptados.", "warn")
            return []

        imprimir_estado(
            f"Se encontraron {len(dispositivos_raw)} dispositivo(s) en total.",
            "ok"
        )

        # Mapeo de tipos internos de UniFi a nombres legibles
        tipos_validos = {
            "uap": "Access Point",    # UniFi Access Point
            "usw": "Switch",          # UniFi Switch
        }

        # Mapeo de estados numéricos a texto
        estados = {
            0: "desconectado",
            1: "conectado",
            2: "gestionando",
            4: "actualizando",
            5: "provisionando",
            6: "no adoptado",
            7: "adoptando",
        }

        metricas = []

        for dispositivo in dispositivos_raw:
            tipo_raw = dispositivo.get("type", "")

            # Solo nos interesan APs y Switches
            if tipo_raw not in tipos_validos:
                continue

            # Extraer estadísticas del sistema (CPU y Memoria)
            sys_stats = dispositivo.get("system-stats", {})
            cpu = sys_stats.get("cpu", "N/A")
            mem = sys_stats.get("mem", "N/A")

            # Extraer estadísticas de tráfico
            stat = dispositivo.get("stat", {})
            # Las estadísticas pueden estar en el objeto raíz o en "stat"
            tx_bytes = dispositivo.get("tx_bytes", stat.get("tx_bytes", 0))
            rx_bytes = dispositivo.get("rx_bytes", stat.get("rx_bytes", 0))

            # Calcular último contacto
            last_seen = dispositivo.get("last_seen", 0)
            if last_seen > 0:
                ultimo_dt = datetime.fromtimestamp(last_seen)
                ultimo_contacto = ultimo_dt.strftime("%Y-%m-%d %H:%M:%S")
            else:
                ultimo_contacto = "N/A"

            uptime_seg = dispositivo.get("uptime", 0)

            metrica = {
                "nombre": dispositivo.get("name", dispositivo.get("hostname", "Sin nombre")),
                "mac": dispositivo.get("mac", "N/A"),
                "modelo": dispositivo.get("model", "N/A"),
                "tipo": tipos_validos[tipo_raw],
                "estado": estados.get(dispositivo.get("state", -1), "desconocido"),
                "ip": dispositivo.get("ip", "N/A"),
                "uptime": formatear_uptime(uptime_seg),
                "uptime_segundos": uptime_seg,
                "version_firmware": dispositivo.get("version", "N/A"),
                "satisfaccion": dispositivo.get("satisfaction", "N/A"),
                "num_usuarios": dispositivo.get("num_sta", 0),
                "carga_cpu": f"{cpu}%" if cpu != "N/A" else "N/A",
                "uso_memoria": f"{mem}%" if mem != "N/A" else "N/A",
                "tx_bytes": tx_bytes,
                "rx_bytes": rx_bytes,
                "ultimo_contacto": ultimo_contacto,
            }
            
            try:
                from pydantic import ValidationError
                # Validar de forma estricta contra el esquema Pydantic
                metrica_validada = MetricaDispositivo(**metrica)
                metricas.append(metrica_validada.model_dump())
            except ValidationError as ve:
                imprimir_estado(
                    f"Ignorando dispositivo '{metrica.get('nombre')}' ({metrica.get('mac')}) debido a datos inválidos en la API: {ve.errors()}",
                    "warn"
                )

        # Filtrar y mostrar resumen en consola
        aps = [m for m in metricas if m["tipo"] == "Access Point"]
        switches = [m for m in metricas if m["tipo"] == "Switch"]

        imprimir_estado(f"Access Points detectados: {len(aps)}", "ok")
        imprimir_estado(f"Switches detectados: {len(switches)}", "ok")

        # Mostrar tabla resumida de dispositivos
        print(f"\n  {Color.WHITE}{Color.BOLD}{'Dispositivo':<25} {'Tipo':<15} {'Estado':<15} {'Satisf.':<10} {'Usuarios':<10}{Color.RESET}")
        print(f"  {'─' * 75}")

        for m in metricas:
            # Colorear estado
            if m["estado"] == "conectado":
                color_estado = Color.GREEN
            elif m["estado"] == "desconectado":
                color_estado = Color.RED
            else:
                color_estado = Color.YELLOW

            # Colorear satisfacción
            sat = m["satisfaccion"]
            if isinstance(sat, (int, float)):
                if sat >= 80:
                    color_sat = Color.GREEN
                elif sat >= 50:
                    color_sat = Color.YELLOW
                else:
                    color_sat = Color.RED
                sat_str = f"{sat}%"
            else:
                color_sat = Color.DIM
                sat_str = str(sat)

            print(
                f"  {m['nombre']:<25} "
                f"{m['tipo']:<15} "
                f"{color_estado}{m['estado']:<15}{Color.RESET} "
                f"{color_sat}{sat_str:<10}{Color.RESET} "
                f"{m['num_usuarios']:<10}"
            )

        print()
        return metricas

    except requests.exceptions.RequestException as e:
        imprimir_estado(f"Error de red al obtener métricas: {e}", "error")
        return None
    except (json.JSONDecodeError, KeyError) as e:
        imprimir_estado(f"Error al procesar la respuesta del controlador: {e}", "error")
        return None


# ============================================================================
# FUNCIÓN ADICIONAL: OBTENER CONFIGURACIONES DE RED (WLAN y LAN)
# ============================================================================

def obtener_configuraciones_red(sesion: requests.Session) -> Optional[dict]:
    """
    Consulta las configuraciones de redes inalámbricas (WLAN) y cableadas (LAN/VLAN)
    del controlador UniFi y las valida para su análisis posterior.

    Args:
        sesion: Sesión HTTP autenticada con el controlador.

    Returns:
        Diccionario con las configuraciones validadas de redes_wifi y redes_lan,
        o None si falla alguna consulta crítica.
    """
    imprimir_seccion("RECOPILACIÓN DE CONFIGURACIONES DE RED", "⚙️")
    
    redes_wifi = []
    redes_lan = []

    try:
        # 1. Consultar configuraciones de redes inalámbricas (WLAN)
        imprimir_estado("Consultando redes WiFi (WLAN)...", "info")
        respuesta_wlan = sesion.get(ENDPOINTS["config_wlan"], timeout=15)
        
        if respuesta_wlan.status_code == 200:
            datos_wlan = respuesta_wlan.json().get("data", [])
            imprimir_estado(f"Se encontraron {len(datos_wlan)} red(es) WiFi configurada(s).", "ok")
            
            for wlan in datos_wlan:
                try:
                    from pydantic import ValidationError
                    # Validar con Pydantic para asegurar que no contenga datos corruptos
                    wlan_validada = ConfigWlan(**wlan)
                    redes_wifi.append(wlan_validada.model_dump())
                except ValidationError as ve:
                    imprimir_estado(
                        f"Aviso: Ignorando SSID '{wlan.get('name')}' debido a discrepancias en el esquema: {ve.errors()}",
                        "warn"
                    )
        else:
            imprimir_estado(f"No se pudieron obtener redes WLAN. Código HTTP: {respuesta_wlan.status_code}", "warn")

        # 2. Consultar configuraciones de redes cableadas/VLANs (LAN)
        imprimir_estado("Consultando redes cableadas y VLANs (LAN)...", "info")
        respuesta_lan = sesion.get(ENDPOINTS["config_network"], timeout=15)
        
        if respuesta_lan.status_code == 200:
            datos_lan = respuesta_lan.json().get("data", [])
            imprimir_estado(f"Se encontraron {len(datos_lan)} red(es) LAN/VLAN configurada(s).", "ok")
            
            for lan in datos_lan:
                try:
                    from pydantic import ValidationError
                    # Validar con Pydantic
                    lan_validada = ConfigNetwork(**lan)
                    redes_lan.append(lan_validada.model_dump())
                except ValidationError as ve:
                    imprimir_estado(
                        f"Aviso: Ignorando red LAN '{lan.get('name')}' debido a discrepancias en el esquema: {ve.errors()}",
                        "warn"
                    )
        else:
            imprimir_estado(f"No se pudieron obtener redes LAN. Código HTTP: {respuesta_lan.status_code}", "warn")

        # Mostrar tabla resumida de configuraciones
        print(f"\n  {Color.WHITE}{Color.BOLD}{'SSID (WiFi)':<25} {'Seguridad':<15} {'WPA3':<10} {'Fast Roaming':<12}{Color.RESET}")
        print(f"  {'─' * 67}")
        for w in redes_wifi:
            print(f"  {w['ssid']:<25} {w['seguridad']:<15} {'Sí' if w['wpa3'] else 'No':<10} {'Sí' if w['fast_roaming'] else 'No':<12}")
        
        print(f"\n  {Color.WHITE}{Color.BOLD}{'Red LAN':<25} {'VLAN ID':<10} {'Propósito':<15} {'Subred':<17}{Color.RESET}")
        print(f"  {'─' * 67}")
        for l in redes_lan:
            vlan_str = str(l['vlan_id']) if l['vlan_id'] is not None else "Default"
            print(f"  {l['nombre']:<25} {vlan_str:<10} {l['proposito']:<15} {l['subred']:<17}")
        print()

        return {
            "redes_wifi": redes_wifi,
            "redes_lan": redes_lan
        }

    except requests.exceptions.RequestException as e:
        imprimir_estado(f"Error de red al obtener configuraciones: {e}", "error")
        return None
    except Exception as e:
        imprimir_estado(f"Error inesperado al recopilar configuraciones: {e}", "error")
        return None


# ============================================================================
# FUNCIÓN 3: ANÁLISIS CON INTELIGENCIA ARTIFICIAL (GEMINI)
# ============================================================================

def analizar_con_ia(datos_red: list[dict], config_red: dict, memoria_historial: Optional[str] = None) -> Optional[DiagnosticoRed]:
    """
    Envía las métricas de los dispositivos y las configuraciones de red a Google Gemini
    para obtener un diagnóstico estructurado que incluya análisis de salud, mejores
    prácticas de configuración inalámbrica/cableada y acciones correctivas.

    Utiliza el SDK google-genai con respuesta estructurada (Pydantic)
    para garantizar que la respuesta del LLM se ajuste exactamente
    al esquema DiagnosticoRed.

    Args:
        datos_red: Lista de diccionarios con las métricas de cada dispositivo.
        config_red: Diccionario con redes_wifi y redes_lan del controlador.

    Returns:
        Objeto DiagnosticoRed con el análisis completo, o None si falla.
    """
    imprimir_seccion("ANÁLISIS CON INTELIGENCIA ARTIFICIAL", "🧠")

    # Validar API Key
    if not GEMINI_API_KEY:
        imprimir_estado(
            "La GEMINI_API_KEY no está configurada en el archivo .env",
            "error"
        )
        return None

    # ── Prompt interno del sistema ──
    # Este prompt convierte al LLM en un ingeniero de redes UniFi experto y auditor de configuraciones.
    prompt_sistema = """Eres un ingeniero de redes senior y arquitecto de soluciones especializado en infraestructura Ubiquiti UniFi.
Tu tarea es auditar y analizar tanto la salud de los dispositivos como las configuraciones de red (WLAN y LAN) de un controlador local UniFi.

Debes emitir un diagnóstico estructurado que cubra:
1. SALUD Y ESTABILIDAD:
   - Identificar anomalías en dispositivos (satisfacción baja < 75%, CPU > 80%, memoria > 85%, uptimes inusualmente cortos o excesivos > 30 días, caídas de dispositivos).
2. AUDITORÍA DE CONFIGURACIÓN Y MEJORES PRÁCTICAS UNIFI:
   - Evaluar si las redes WiFi (WLAN) siguen mejores prácticas:
     * Seguridad: Recomendar WPA3 (wpa3=True) o mixto. Exigir PMF (pmf='optional' o 'required') en SSIDs corporativos.
     * Roaming: Comprobar si Fast Roaming (fast_roaming=True) está activo en redes corporativas con múltiples APs.
     * Multicast: Verificar si Multicast Enhancement / IGMP Snooping (enhancement_multicast=True) está activo para optimizar tráfico inalámbrico.
     * Red de Invitados: Validar que los SSIDs de invitados estén asignados a VLANs dedicadas y que su propósito en red sea 'guest' (para aislamiento de capa 2).
   - Evaluar si las redes cableadas (LAN) siguen mejores prácticas:
     * VLANs: Comprobar que no todo esté en la red por defecto (VLAN 1). Recomendar segmentar tráfico (CCTV, Invitados, IoT, Corporativo) en VLANs dedicadas.
     * IGMP Snooping: Verificar si IGMP Snooping (igmp_snooping=True) está habilitado en redes cableadas con alto tráfico multicast (como CCTV).
     * UPnP: Desaconsejar UPnP habilitado (upnp=True) en redes de producción por implicaciones de seguridad.
   - Evaluar la asignación de Radios en los Puntos de Acceso (Tx Power y canales):
     * Desaconsejar que la potencia de transmisión (tx_power_mode) esté en 'Auto' o 'High' en todos los APs de forma generalizada. Recomendar optimizar la potencia de transmisión a 2.4GHz en Low/Medium y 5GHz en Medium/High para mejorar el roaming de clientes.

3. ACCIONES RECOMENDADAS:
   - Sugerir 'reiniciar' solo ante fallos reales demostrados (CPU/memoria crítica persistente).
   - Sugerir 'monitorear' para alertas leves.
   - Sugerir 'ninguna' en estados estables.

Para cada regla de mejor práctica analizada en el esquema Pydantic:
- Indica el 'estado_actual' (resumiendo lo configurado en la red).
- Define 'cumple' en True o False.
- Explica la 'recomendacion' técnica y clara de qué cambiar y su 'prioridad' (alta, media, baja).

SÉ CONCISO pero TÉCNICAMENTE PRECISO en tus descripciones."""

    # Construir el prompt del usuario con las métricas y configuraciones en formato JSON
    datos_completos = {
        "metricas_dispositivos": datos_red,
        "configuraciones_red": config_red
    }

    prompt_usuario = f"""Analiza la salud de los dispositivos y audita las configuraciones de red UniFi adjuntas, recopiladas el {datetime.now().strftime('%Y-%m-%d a las %H:%M:%S')}:

```json
{json.dumps(datos_completos, indent=2, ensure_ascii=False)}
```

Proporciona el diagnóstico completo de salud, la auditoría detallada de mejores prácticas con el estado de cumplimiento para cada regla, y las recomendaciones de acción correctiva."""

    if memoria_historial:
        prompt_usuario += f"\n\n{memoria_historial}"

    intentos_max = 5
    espera = 3  # segundos iniciales de espera

    for intento in range(1, intentos_max + 1):
        try:
            imprimir_estado(f"Conectando con modelo {GEMINI_MODEL} (Intento {intento}/{intentos_max})...", "info")
            
            # Inicializar el cliente de Gemini (SDK google-genai)
            cliente = genai.Client(api_key=GEMINI_API_KEY)

            # Generar respuesta estructurada usando el esquema Pydantic
            # El parámetro response_schema fuerza al modelo a devolver JSON
            # que se ajuste exactamente al modelo DiagnosticoRed.
            respuesta = cliente.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt_usuario,
                config={
                    "system_instruction": prompt_sistema,
                    "response_mime_type": "application/json",
                    "response_schema": DiagnosticoRed,
                    "temperature": 0.3,   # Baja temperatura para respuestas consistentes
                },
            )

            # Parsear la respuesta JSON al modelo Pydantic
            diagnostico_json = json.loads(respuesta.text)
            diagnostico = DiagnosticoRed(**diagnostico_json)

            imprimir_estado("Análisis completado exitosamente ✓", "ok")

            # ── Mostrar el diagnóstico en consola ──
            _mostrar_diagnostico(diagnostico)

            return diagnostico

        except json.JSONDecodeError as e:
            imprimir_estado(f"Error al parsear la respuesta de la IA (Intento {intento}/{intentos_max}): {e}", "warn")
            if intento == intentos_max:
                imprimir_estado("La IA no devolvió un JSON válido y se agotaron los intentos.", "error")
                return None
            time.sleep(espera)
            espera *= 2
        except Exception as e:
            error_msg = str(e)
            es_error_temporal = any(kw in error_msg.upper() for kw in ["503", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED", "LIMIT"])

            if es_error_temporal and intento < intentos_max:
                imprimir_estado(
                    f"La API de Gemini está sobrecargada o sin cuota disponible (Código 503/429). "
                    f"Esperando {espera} segundos antes de reintentar...",
                    "warn"
                )
                time.sleep(espera)
                espera *= 2
            else:
                if "API_KEY" in error_msg.upper() or "401" in error_msg or "403" in error_msg:
                    imprimir_estado(
                        "API Key de Gemini inválida o sin permisos. Verifica GEMINI_API_KEY en .env",
                        "error"
                    )
                elif "model" in error_msg.lower() and "not found" in error_msg.lower():
                    imprimir_estado(
                        f"El modelo '{GEMINI_MODEL}' no existe o no está disponible. "
                        f"Verifica GEMINI_MODEL en .env",
                        "error"
                    )
                else:
                    imprimir_estado(f"Error al comunicarse con Gemini: {e}", "error")
                return None


def _mostrar_diagnostico(diagnostico: DiagnosticoRed):
    """Imprime el diagnóstico de la IA de forma visual en la consola, incluyendo salud y mejores prácticas."""

    # Resumen general
    print(f"\n  {Color.BOLD}{Color.WHITE}📋 RESUMEN GENERAL{Color.RESET}")
    print(f"  {Color.DIM}{'─' * 56}{Color.RESET}")
    # Dividir el resumen en líneas para mejor legibilidad
    for linea in diagnostico.resumen_general.split(". "):
        linea = linea.strip()
        if linea:
            print(f"  {Color.WHITE}  {linea}{'.' if not linea.endswith('.') else ''}{Color.RESET}")

    # Problemas detectados
    if diagnostico.problemas_detectados:
        print(f"\n  {Color.BOLD}{Color.YELLOW}⚠️  PROBLEMAS DE SALUD DETECTADOS ({len(diagnostico.problemas_detectados)}){Color.RESET}")
        print(f"  {Color.DIM}{'─' * 56}{Color.RESET}")
        for i, problema in enumerate(diagnostico.problemas_detectados, 1):
            print(f"  {Color.YELLOW}  {i}. {problema}{Color.RESET}")
    else:
        print(f"\n  {Color.GREEN}{Color.BOLD}✅ No se detectaron problemas de salud en los dispositivos.{Color.RESET}")

    # Auditoría de Mejores Prácticas
    if diagnostico.mejores_practicas:
        print(f"\n  {Color.BOLD}{Color.CYAN}📐 AUDITORÍA DE MEJORES PRÁCTICAS UNIFI ({len(diagnostico.mejores_practicas)}){Color.RESET}")
        print(f"  {Color.DIM}{'─' * 56}{Color.RESET}")
        for bp in diagnostico.mejores_practicas:
            # Icono según cumplimiento
            if bp.cumple:
                icono = f"{Color.GREEN}✅"
                estado_linea = f"Cumple mejor práctica de Ubiquiti."
            else:
                icono = f"{Color.YELLOW}⚠️"
                estado_linea = f"Sugerencia de optimización pendiente."

            # Color según prioridad de recomendación
            colores_prioridad = {
                "alta": Color.RED,
                "media": Color.YELLOW,
                "baja": Color.CYAN,
            }
            color_prio = colores_prioridad.get(bp.prioridad, Color.WHITE)

            print(f"  {icono}  {Color.BOLD}{bp.regla}{Color.RESET}")
            print(f"      Estado actual: {Color.DIM}{bp.estado_actual}{Color.RESET}")
            print(f"      Auditoría    : {Color.BOLD}{estado_linea}{Color.RESET}")
            if not bp.cumple:
                print(f"      Recomendación: {Color.BOLD}{bp.recomendacion}{Color.RESET} (Prioridad: {color_prio}{bp.prioridad.upper()}{Color.RESET})")
            print()

    # Acciones recomendadas
    if diagnostico.acciones_recomendadas:
        print(f"\n  {Color.BOLD}{Color.MAGENTA}⚡ ACCIONES RECOMENDADAS ({len(diagnostico.acciones_recomendadas)}){Color.RESET}")
        print(f"  {Color.DIM}{'─' * 56}{Color.RESET}")
        for accion in diagnostico.acciones_recomendadas:
            # Colorear según prioridad
            colores_prioridad = {
                "critica": Color.RED,
                "alta": Color.YELLOW,
                "media": Color.CYAN,
                "baja": Color.GREEN,
            }
            color = colores_prioridad.get(accion.prioridad, Color.WHITE)
            icono_accion = {
                "reiniciar": "🔄",
                "monitorear": "👀",
                "ninguna": "✅",
            }
            icono = icono_accion.get(accion.accion, "❓")

            print(f"  {icono}  {Color.BOLD}{accion.dispositivo}{Color.RESET} ({accion.mac})")
            print(f"      Acción: {Color.BOLD}{accion.accion.upper()}{Color.RESET}  │  Prioridad: {color}{Color.BOLD}{accion.prioridad.upper()}{Color.RESET}")
            print(f"      Motivo: {accion.motivo}")
            print()

    # Observaciones adicionales
    if diagnostico.observaciones_adicionales:
        print(f"  {Color.BOLD}{Color.CYAN}💡 OBSERVACIONES ADICIONALES{Color.RESET}")
        print(f"  {Color.DIM}{'─' * 56}{Color.RESET}")
        for obs in diagnostico.observaciones_adicionales:
            print(f"  {Color.CYAN}  • {obs}{Color.RESET}")
    print()


# ============================================================================
# FUNCIÓN 4: EJECUTAR ACCIÓN CORRECTIVA EN LA RED
# ============================================================================

def ejecutar_accion(
    sesion: requests.Session,
    accion: str,
    mac_dispositivo: str,
    nombre_dispositivo: str,
) -> bool:
    """
    Ejecuta una acción correctiva sobre un dispositivo UniFi específico.

    Acciones soportadas:
    ┌─────────────┬──────────────────────────────────────────────────────────┐
    │ Acción      │ Descripción                                              │
    ├─────────────┼──────────────────────────────────────────────────────────┤
    │ reiniciar   │ Envía comando "restart" al dispositivo vía API.          │
    │             │ El dispositivo se reiniciará y volverá a conectarse      │
    │             │ automáticamente al controlador (~2-5 minutos).           │
    ├─────────────┼──────────────────────────────────────────────────────────┤
    │ monitorear  │ Registra el dispositivo para seguimiento. No ejecuta     │
    │             │ cambios en la red (acción informativa).                   │
    ├─────────────┼──────────────────────────────────────────────────────────┤
    │ ninguna     │ No se requiere acción. Dispositivo operando bien.        │
    └─────────────┴──────────────────────────────────────────────────────────┘

    Args:
        sesion: Sesión HTTP autenticada con el controlador.
        accion: Tipo de acción a ejecutar ("reiniciar", "monitorear", "ninguna").
        mac_dispositivo: Dirección MAC del dispositivo objetivo.
        nombre_dispositivo: Nombre legible del dispositivo (para logging).

    Returns:
        True si la acción se ejecutó con éxito, False en caso contrario.
    """
    accion = accion.lower().strip()

    if accion == "ninguna":
        imprimir_estado(
            f"'{nombre_dispositivo}' — Sin acción necesaria.",
            "ok"
        )
        return True

    if accion == "monitorear":
        imprimir_estado(
            f"'{nombre_dispositivo}' ({mac_dispositivo}) — Marcado para monitoreo continuo. "
            f"Revisar manualmente en la próxima iteración.",
            "warn"
        )
        return True

    if accion == "reiniciar":
        # ── MODO SIMULACIÓN (DRY RUN) ──
        if DRY_RUN:
            imprimir_estado(
                f"[SIMULACIÓN] Se habría enviado el comando de reinicio a '{nombre_dispositivo}' ({mac_dispositivo}).",
                "ok"
            )
            return True

        try:
            imprimir_estado(
                f"Enviando comando de reinicio a '{nombre_dispositivo}' ({mac_dispositivo})...",
                "accion"
            )

            # ── ENDPOINT: POST /cmd/devmgr ──
            # Este endpoint recibe comandos de gestión de dispositivos.
            # Payload para reiniciar:
            # {
            #   "cmd": "restart",           ← Comando de reinicio
            #   "mac": "aa:bb:cc:dd:ee:ff"  ← MAC del dispositivo objetivo
            # }
            #
            # Otros comandos disponibles en este endpoint:
            #   - "adopt"           → Adoptar un dispositivo pendiente
            #   - "force-provision" → Forzar re-provisión de configuración
            #   - "power-cycle"     → Ciclo de energía (solo switches PoE)
            #   - "set-locate"      → Activar LED de localización
            #   - "unset-locate"    → Desactivar LED de localización
            payload = {
                "cmd": "restart",
                "mac": mac_dispositivo,
            }

            respuesta = sesion.post(
                ENDPOINTS["comando_dispositivo"],
                json=payload,
                timeout=15,
            )

            if respuesta.status_code == 200:
                datos_resp = respuesta.json()
                if datos_resp.get("meta", {}).get("rc") == "ok":
                    imprimir_estado(
                        f"✓ Comando de reinicio enviado exitosamente a '{nombre_dispositivo}'. "
                        f"El dispositivo se reconectará en ~2-5 minutos.",
                        "ok"
                    )
                    return True
                else:
                    imprimir_estado(
                        f"El controlador rechazó el comando: {datos_resp}",
                        "error"
                    )
                    return False
            else:
                imprimir_estado(
                    f"Error al enviar comando. HTTP {respuesta.status_code}: {respuesta.text[:200]}",
                    "error"
                )
                return False

        except requests.exceptions.RequestException as e:
            imprimir_estado(
                f"Error de red al ejecutar acción sobre '{nombre_dispositivo}': {e}",
                "error"
            )
            return False

    # Acción no reconocida
    imprimir_estado(
        f"Acción '{accion}' no reconocida. Acciones válidas: reiniciar, monitorear, ninguna.",
        "warn"
    )
    return False


# ============================================================================
# FUNCIONES DE ESCRITURA: APLICACIÓN DE OPTIMIZACIONES DE CONFIGURACIÓN
# ============================================================================

def aplicar_optimizacion_wlan(
    sesion: requests.Session,
    ssid: str,
    parametro: str,
    valor: Union[bool, str],
) -> bool:
    """
    Modifica la configuración de una red inalámbrica (WLAN) específica en el controlador.

    Args:
        sesion: Sesión HTTP autenticada con el controlador.
        ssid: SSID/Nombre de la red WiFi a optimizar.
        parametro: Parámetro a modificar (ej: "fast_roaming", "wpa3", "multicast_enhance").
        valor: Nuevo valor a aplicar (bool o str).

    Returns:
        True si se aplicó con éxito, False en caso contrario.
    """
    imprimir_estado(f"Iniciando optimización WLAN para '{ssid}' (Parámetro: {parametro} -> {valor})...", "accion")
    
    if DRY_RUN:
        imprimir_estado(f"[SIMULACIÓN] WLAN '{ssid}': Se habría actualizado '{parametro}' a {valor}.", "ok")
        return True

    try:
        # 1. Buscar el _id correspondiente al SSID
        respuesta_list = sesion.get(ENDPOINTS["config_wlan"], timeout=15)
        if respuesta_list.status_code != 200:
            imprimir_estado(f"Error al listar WLANs para búsqueda. HTTP {respuesta_list.status_code}", "error")
            return False

        wlans = respuesta_list.json().get("data", [])
        wlan_obj = next((w for w in wlans if w.get("name") == ssid), None)

        if not wlan_obj or "_id" not in wlan_obj:
            imprimir_estado(f"No se encontró la red WiFi '{ssid}' en el controlador.", "error")
            return False

        wlan_id = wlan_obj["_id"]

        # 2. Construir el payload según el parámetro
        # Para hacer PUT en UniFi, es buena práctica enviar los campos existentes junto con la modificación
        payload = {}
        
        # Mapeo de parámetros del script a propiedades de UniFi
        mapeo_propiedades = {
            "fast_roaming": "fast_roaming_enabled",
            "wpa3": "wpa3_support",
            "pmf": "pmf_mode",
            "multicast_enhance": "multicast_enhance"
        }

        prop_key = mapeo_propiedades.get(parametro.lower())
        if not prop_key:
            imprimir_estado(f"Parámetro de optimización '{parametro}' no reconocido para WLAN.", "error")
            return False

        payload[prop_key] = valor
        
        # Regla especial: Si se activa WPA3, PMF debería configurarse como opcional
        if prop_key == "wpa3_support" and valor is True:
            payload["pmf_mode"] = "optional"

        # 3. Realizar la petición PUT de modificación
        # Endpoint: PUT /api/s/<site>/rest/wlanconf/<wlan_id>
        url_put = f"{ENDPOINTS['config_wlan']}/{wlan_id}"
        respuesta_put = sesion.put(url_put, json=payload, timeout=15)

        if respuesta_put.status_code == 200:
            datos_resp = respuesta_put.json()
            if datos_resp.get("meta", {}).get("rc") == "ok":
                imprimir_estado(f"✓ Optimización aplicada exitosamente a la red WiFi '{ssid}'!", "ok")
                return True
            else:
                imprimir_estado(f"El controlador rechazó la actualización: {datos_resp}", "error")
                return False
        else:
            imprimir_estado(f"Error al aplicar optimización. HTTP {respuesta_put.status_code}: {respuesta_put.text[:150]}", "error")
            return False

    except Exception as e:
        imprimir_estado(f"Error al intentar aplicar optimización WLAN en '{ssid}': {e}", "error")
        return False


def aplicar_optimizacion_lan(
    sesion: requests.Session,
    nombre_red: str,
    parametro: str,
    valor: Union[bool, str],
) -> bool:
    """
    Modifica la configuración de una red cableada/VLAN (LAN) específica en el controlador.

    Args:
        sesion: Sesión HTTP autenticada con el controlador.
        nombre_red: Nombre de la red local a optimizar.
        parametro: Parámetro a modificar (ej: "igmp_snooping", "upnp").
        valor: Nuevo valor a aplicar (bool o str).

    Returns:
        True si se aplicó con éxito, False en caso contrario.
    """
    imprimir_estado(f"Iniciando optimización LAN para '{nombre_red}' (Parámetro: {parametro} -> {valor})...", "accion")
    
    if DRY_RUN:
        imprimir_estado(f"[SIMULACIÓN] LAN '{nombre_red}': Se habría actualizado '{parametro}' a {valor}.", "ok")
        return True

    try:
        # 1. Buscar el _id correspondiente a la red LAN
        respuesta_list = sesion.get(ENDPOINTS["config_network"], timeout=15)
        if respuesta_list.status_code != 200:
            imprimir_estado(f"Error al listar redes LAN para búsqueda. HTTP {respuesta_list.status_code}", "error")
            return False

        networks = respuesta_list.json().get("data", [])
        net_obj = next((n for n in networks if n.get("name") == nombre_red), None)

        if not net_obj or "_id" not in net_obj:
            imprimir_estado(f"No se encontró la red LAN '{nombre_red}' en el controlador.", "error")
            return False

        net_id = net_obj["_id"]

        # 2. Construir el payload según el parámetro
        payload = {}
        
        # Mapeo de parámetros a propiedades de UniFi Network
        mapeo_propiedades = {
            "igmp_snooping": "igmp_snooping",
            "upnp": "upnp_enabled"
        }

        prop_key = mapeo_propiedades.get(parametro.lower())
        if not prop_key:
            imprimir_estado(f"Parámetro de optimización '{parametro}' no reconocido para LAN.", "error")
            return False

        payload[prop_key] = valor

        # 3. Realizar la petición PUT de modificación
        # Endpoint: PUT /api/s/<site>/rest/networkconf/<net_id>
        url_put = f"{ENDPOINTS['config_network']}/{net_id}"
        respuesta_put = sesion.put(url_put, json=payload, timeout=15)

        if respuesta_put.status_code == 200:
            datos_resp = respuesta_put.json()
            if datos_resp.get("meta", {}).get("rc") == "ok":
                imprimir_estado(f"✓ Optimización aplicada exitosamente a la red local '{nombre_red}'!", "ok")
                return True
            else:
                imprimir_estado(f"El controlador rechazó la actualización: {datos_resp}", "error")
                return False
        else:
            imprimir_estado(f"Error al aplicar optimización. HTTP {respuesta_put.status_code}: {respuesta_put.text[:150]}", "error")
            return False

    except Exception as e:
        imprimir_estado(f"Error al intentar aplicar optimización LAN en '{nombre_red}': {e}", "error")
        return False


# ============================================================================
# FLUJO PRINCIPAL: HUMAN-IN-THE-LOOP
# ============================================================================

def procesar_acciones_con_confirmacion(
    sesion: requests.Session,
    diagnostico: DiagnosticoRed,
):
    """
    Implementa el flujo Human-in-the-Loop para las acciones recomendadas.

    Para cada acción drástica (reiniciar), el script:
    1. Muestra los detalles de la acción al usuario.
    2. Pide confirmación manual por teclado (S/N).
    3. Solo ejecuta la acción si el usuario confirma explícitamente.

    Las acciones de tipo "monitorear" y "ninguna" se registran
    automáticamente sin requerir confirmación.
    """
    imprimir_seccion("EJECUCIÓN DE ACCIONES CORRECTIVAS", "🎯")

    acciones = diagnostico.acciones_recomendadas

    if not acciones:
        imprimir_estado("No hay acciones para ejecutar.", "ok")
        return

    # Separar acciones que requieren confirmación de las informativas
    acciones_drasticas = [a for a in acciones if a.accion.lower() == "reiniciar"]
    acciones_info = [a for a in acciones if a.accion.lower() != "reiniciar"]

    # Procesar acciones informativas automáticamente
    for accion in acciones_info:
        ejecutar_accion(sesion, accion.accion, accion.mac, accion.dispositivo)

    # Procesar acciones drásticas con confirmación
    if not acciones_drasticas:
        imprimir_estado("No hay acciones drásticas pendientes.", "ok")
        return

    print(f"\n  {Color.BG_YELLOW}{Color.BOLD} ⚠️  ACCIONES QUE REQUIEREN CONFIRMACIÓN MANUAL  {Color.RESET}\n")
    print(f"  {Color.YELLOW}Las siguientes acciones modificarán dispositivos de la red.")
    print(f"  Se requiere tu aprobación explícita antes de ejecutar cada una.{Color.RESET}\n")

    for i, accion in enumerate(acciones_drasticas, 1):
        print(f"  {Color.DIM}{'─' * 56}{Color.RESET}")
        print(f"  {Color.BOLD}Acción {i}/{len(acciones_drasticas)}{Color.RESET}")
        print(f"  {Color.WHITE}Dispositivo : {Color.BOLD}{accion.dispositivo}{Color.RESET}")
        print(f"  {Color.WHITE}MAC         : {accion.mac}{Color.RESET}")
        print(f"  {Color.WHITE}Acción      : {Color.RED}{Color.BOLD}🔄 REINICIAR{Color.RESET}")
        print(f"  {Color.WHITE}Prioridad   : {accion.prioridad.upper()}{Color.RESET}")
        print(f"  {Color.WHITE}Motivo      : {accion.motivo}{Color.RESET}")
        print()

        # ── Solicitar confirmación del usuario ──
        while True:
            try:
                respuesta = input(
                    f"  {Color.BOLD}{Color.YELLOW}¿Deseas reiniciar '{accion.dispositivo}'? "
                    f"(S/N): {Color.RESET}"
                ).strip().upper()

                if respuesta in ("S", "SI", "SÍ", "Y", "YES"):
                    ejecutar_accion(sesion, accion.accion, accion.mac, accion.dispositivo)
                    break
                elif respuesta in ("N", "NO"):
                    imprimir_estado(
                        f"Acción de reinicio OMITIDA para '{accion.dispositivo}' por decisión del usuario.",
                        "warn"
                    )
                    break
                else:
                    print(f"  {Color.DIM}  Por favor, responde S (Sí) o N (No).{Color.RESET}")
            except (KeyboardInterrupt, EOFError):
                print(f"\n\n  {Color.YELLOW}Operación cancelada por el usuario.{Color.RESET}")
                return

    print(f"\n  {Color.GREEN}{Color.BOLD}✅ Procesamiento de acciones finalizado.{Color.RESET}\n")


# ============================================================================
# FUNCIÓN PRINCIPAL
# ============================================================================

def main():
    """
    Flujo principal del Agente de IA para Optimización de Red UniFi.

    Secuencia de ejecución:
    ┌─────────────────────────────────────────────────────┐
    │ 1. Mostrar banner                                    │
    │ 2. Validar configuración del .env                    │
    │ 3. Conectar al controlador UniFi                     │
    │ 4. Obtener métricas de dispositivos                  │
    │ 5. Enviar métricas a Gemini AI para diagnóstico      │
    │ 6. Mostrar diagnóstico al usuario                    │
    │ 7. Solicitar confirmación para acciones drásticas     │
    │ 8. Ejecutar acciones aprobadas                        │
    │ 9. Cerrar sesión                                      │
    └─────────────────────────────────────────────────────┘
    """
    imprimir_banner()

    # ── Paso 1: Validar configuración ──
    imprimir_seccion("VALIDACIÓN DE CONFIGURACIÓN", "⚙️")

    errores_config = []
    if not UNIFI_USERNAME:
        errores_config.append("UNIFI_USERNAME no configurado en .env")
    if not UNIFI_PASSWORD:
        errores_config.append("UNIFI_PASSWORD no configurado en .env")
    if not GEMINI_API_KEY:
        errores_config.append("GEMINI_API_KEY no configurado en .env")

    if errores_config:
        for error in errores_config:
            imprimir_estado(error, "error")
        imprimir_estado(
            "Copia .env.example a .env y completa las credenciales.",
            "warn"
        )
        sys.exit(1)

    imprimir_estado(f"Host UniFi: {UNIFI_HOST}:{UNIFI_PORT}", "ok")
    imprimir_estado(f"Controlador: {UNIFI_CONTROLLER_TYPE.upper()}", "ok")
    imprimir_estado(f"Modelo IA: {GEMINI_MODEL}", "ok")
    imprimir_estado("Configuración validada ✓", "ok")

    # ── Paso 2: Conectar al controlador ──
    sesion = conectar_unifi()
    if not sesion:
        imprimir_estado("No se pudo establecer conexión. Abortando.", "error")
        sys.exit(1)

    try:
        # ── Paso 3: Obtener métricas ──
        metricas = obtener_metricas_red(sesion)
        if metricas is None:
            imprimir_estado("No se pudieron obtener las métricas. Abortando.", "error")
            sys.exit(1)

        # ── Paso 4: Obtener configuraciones de red ──
        configuraciones = obtener_configuraciones_red(sesion)
        if configuraciones is None:
            imprimir_estado("No se pudieron obtener las configuraciones de red. Continuando con datos parciales...", "warn")
            configuraciones = {"redes_wifi": [], "redes_lan": []}

        if len(metricas) == 0:
            imprimir_estado(
                "No se encontraron Access Points ni Switches. "
                "Verifica que el sitio sea correcto.",
                "warn"
            )
            sys.exit(0)

        # ── Paso 5: Analizar con IA ──
        diagnostico = analizar_con_ia(metricas, configuraciones)
        if not diagnostico:
            imprimir_estado("No se pudo obtener el diagnóstico de la IA. Abortando.", "error")
            sys.exit(1)

        # ── Paso 5: Ejecutar acciones con confirmación humana ──
        procesar_acciones_con_confirmacion(sesion, diagnostico)

    except KeyboardInterrupt:
        print(f"\n\n{Color.YELLOW}  ⚠  Ejecución interrumpida por el usuario (Ctrl+C).{Color.RESET}")

    finally:
        # Cerrar sesión con el controlador
        imprimir_seccion("CIERRE DE SESIÓN", "🔒")
        try:
            # Intentar cerrar sesión limpiamente
            # UDM: POST /api/auth/logout
            # CK:  POST /logout
            if UNIFI_CONTROLLER_TYPE == "udm":
                sesion.post(f"{BASE_URL}/api/auth/logout", timeout=5)
            else:
                sesion.post(f"{BASE_URL}/logout", timeout=5)
            imprimir_estado("Sesión cerrada correctamente.", "ok")
        except Exception:
            imprimir_estado("No se pudo cerrar la sesión (no crítico).", "warn")

        sesion.close()
        imprimir_estado("Agente finalizado.", "ok")
        print()


# ============================================================================
# PUNTO DE ENTRADA
# ============================================================================

if __name__ == "__main__":
    main()

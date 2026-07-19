"""
Configuración del agente cargada desde variables de entorno (.env).
"""

import os
import urllib3
from dotenv import load_dotenv

load_dotenv()

# --- Entorno ---
ENVIRONMENT = os.getenv("ENVIRONMENT", "development").lower()

# --- Controlador UniFi ---
UNIFI_HOST = os.getenv("UNIFI_HOST", "192.168.1.1")
UNIFI_PORT = os.getenv("UNIFI_PORT", "443")
UNIFI_USERNAME = os.getenv("UNIFI_USERNAME")
UNIFI_PASSWORD = os.getenv("UNIFI_PASSWORD")
UNIFI_SITE = os.getenv("UNIFI_SITE", "default")
UNIFI_CONTROLLER_TYPE = os.getenv("UNIFI_CONTROLLER_TYPE", "udm").lower()
UNIFI_VERIFY_SSL = os.getenv("UNIFI_VERIFY_SSL", "false").lower() == "true"
DRY_RUN = os.getenv("DRY_RUN", "false").lower() == "true"

# --- API de IA (Google Gemini) ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# --- Autenticación de la API Web ---
API_KEY = os.getenv("API_KEY")

# --- CORS ---
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:8000").split(",")

# --- Base de datos ---
DB_PATH = os.getenv("DB_PATH", "historial.db")

# --- Logging ---
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_FORMAT = os.getenv("LOG_FORMAT", "text").lower()
LOG_FILE = os.getenv("LOG_FILE", "unifi_agent.log")
LOG_SYSLOG_ADDRESS = os.getenv("LOG_SYSLOG_ADDRESS")
LOG_MAX_BYTES = int(os.getenv("LOG_MAX_BYTES", str(5 * 1024 * 1024)))
LOG_BACKUP_COUNT = int(os.getenv("LOG_BACKUP_COUNT", "5"))

# --- Backup ---
BACKUP_DIR = os.getenv("BACKUP_DIR", "backups")
BACKUP_RETENTION_DAYS = int(os.getenv("BACKUP_RETENTION_DAYS", "30"))
BACKUP_MAX_COUNT = int(os.getenv("BACKUP_MAX_COUNT", "50"))

# --- URLs derivadas del tipo de controlador ---
BASE_URL = f"https://{UNIFI_HOST}:{UNIFI_PORT}"

if UNIFI_CONTROLLER_TYPE == "udm":
    API_PREFIX = f"{BASE_URL}/proxy/network/api/s/{UNIFI_SITE}"
    LOGIN_URL = f"{BASE_URL}/api/auth/login"
else:
    API_PREFIX = f"{BASE_URL}/api/s/{UNIFI_SITE}"
    LOGIN_URL = f"{BASE_URL}/api/login"

ENDPOINTS = {
    "login": LOGIN_URL,
    "dispositivos": f"{API_PREFIX}/stat/device",
    "salud": f"{API_PREFIX}/stat/health",
    "comando_dispositivo": f"{API_PREFIX}/cmd/devmgr",
    "config_wlan": f"{API_PREFIX}/rest/wlanconf",
    "config_network": f"{API_PREFIX}/rest/networkconf",
}

# --- SSL: suprimir warnings solo cuando se deshabilita verificación ---
if not UNIFI_VERIFY_SSL:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

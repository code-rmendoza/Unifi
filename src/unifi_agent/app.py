"""
Punto de entrada del servidor web FastAPI.
Configura la aplicación, logging, métricas y monta los endpoints.
"""

import os
import time
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.templating import Jinja2Templates
from slowapi import Limiter
from slowapi.util import get_remote_address
import uvicorn

from unifi_agent.core import config
from unifi_agent.core.logging import setup_logging
from unifi_agent.api.routes import router, inicializar_db, set_api_key_manager, set_backup_manager
from unifi_agent.api.metrics import metrics_router, record_request
from unifi_agent.services.api_keys import crear_manager_desde_env
from unifi_agent.services.backup import BackupManager

# ============================================================================
# INICIALIZACIÓN DE LOGGING
# ============================================================================

setup_logging(
    log_level=config.LOG_LEVEL,
    log_file=config.LOG_FILE,
    log_format=config.LOG_FORMAT,
    syslog_address=config.LOG_SYSLOG_ADDRESS,
    max_bytes=config.LOG_MAX_BYTES,
    backup_count=config.LOG_BACKUP_COUNT,
)

# ============================================================================
# INICIALIZACIÓN DE FASTAPI
# ============================================================================

app_web = FastAPI(
    title="UniFi Network AI Agent",
    description="Panel de optimización inteligente con IA y Human-in-the-Loop para controladores UniFi",
    version="1.0.0",
)

# --- Rate Limiting ---
limiter = Limiter(key_func=get_remote_address)
app_web.state.limiter = limiter

# --- CORS ---
app_web.add_middleware(
    CORSMiddleware,
    allow_origins=config.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)

# --- Templates ---
TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
os.makedirs(TEMPLATES_DIR, exist_ok=True)
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# --- Montar routers ---
app_web.include_router(router)
app_web.include_router(metrics_router)


# ============================================================================
# MIDDLEWARE: MÉTRICAS DE LATENCIA
# ============================================================================

@app_web.middleware("http")
async def metrics_middleware(request: Request, call_next):
    """Registra métricas de cada petición HTTP."""
    start = time.time()
    response = await call_next(request)
    duration = time.time() - start

    record_request(
        method=request.method,
        endpoint=request.url.path,
        status=response.status_code,
        duration=duration,
    )
    return response


# ============================================================================
# ENDPOINT HOME (sirve el HTML)
# ============================================================================

@app_web.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Sirve la página web principal del agente."""
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"api_key": config.API_KEY or ""}
    )


# ============================================================================
# STARTUP / SHUTDOWN
# ============================================================================

@app_web.on_event("startup")
async def startup():
    """Inicialización al arrancar el servidor."""
    inicializar_db()

    # Inicializar gestores
    api_key_mgr = crear_manager_desde_env(config.DB_PATH)
    set_api_key_manager(api_key_mgr)

    backup_mgr = BackupManager(
        db_path=config.DB_PATH,
        backup_dir=config.BACKUP_DIR,
        retention_days=config.BACKUP_RETENTION_DAYS,
        max_backups=config.BACKUP_MAX_COUNT,
    )
    set_backup_manager(backup_mgr)

    # Backup automático al arrancar
    backup_mgr.crear_backup(motivo="startup")
    backup_mgr.limpiar_backups_antiguos()

    print("  🚀 Servidor UniFi Network AI Agent iniciado.")
    print("  🔗 Abre http://localhost:8000 en tu navegador.")
    print("  📊 Métricas en http://localhost:8000/metrics")
    print()


# ============================================================================
# PUNTO DE ARRANQUE
# ============================================================================

if __name__ == "__main__":
    uvicorn.run(app_web, host="0.0.0.0", port=8000)

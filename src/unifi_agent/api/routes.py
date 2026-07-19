"""
Endpoints de la API web FastAPI.
"""

import json
import time
import sqlite3
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.util import get_remote_address

from unifi_agent.core import config
from unifi_agent.core.logging import get_logger
from unifi_agent.services import unifi_client, ai_analyzer
from unifi_agent.services.api_keys import APIKeyManager
from unifi_agent.services.backup import BackupManager
from unifi_agent.api.metrics import (
    record_request, record_diagnostic, record_reboot,
    record_optimization, record_unifi_connection, record_ai_request,
)

logger = get_logger("UniFiAgent.routes")
router = APIRouter()
limiter = Limiter(key_func=get_remote_address)

# Managers (se inicializan en app startup)
_api_key_manager: APIKeyManager | None = None
_backup_manager: BackupManager | None = None


def set_api_key_manager(manager: APIKeyManager):
    global _api_key_manager
    _api_key_manager = manager


def set_backup_manager(manager: BackupManager):
    global _backup_manager
    _backup_manager = manager


# ============================================================================
# DEPENDENCY: VERIFICACIÓN DE API KEY
# ============================================================================

async def verify_api_key(request: Request):
    """Verifica la API key en el header X-API-Key."""
    # Primero intentar con el manager de BD
    if _api_key_manager:
        key = request.headers.get("X-API-Key")
        if key and _api_key_manager.validar_key(key):
            return
    # Fallback: verificar con .env
    if not config.API_KEY:
        return
    key = request.headers.get("X-API-Key")
    if key != config.API_KEY:
        raise HTTPException(status_code=401, detail="API key inválida o ausente. Envía el header 'X-API-Key'.")





# ============================================================================
# PERSISTENCIA SQLITE
# ============================================================================

def inicializar_db():
    """Crea la base de datos y la tabla de historial si no existen."""
    with sqlite3.connect(config.DB_PATH) as conn:
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


def guardar_diagnostico(diagnostico: Dict[str, Any], num_dispositivos: int, num_usuarios: int):
    """Guarda un registro de diagnóstico en la base de datos."""
    resumen = diagnostico.get("resumen_general", "")
    num_problemas = len(diagnostico.get("problemas_detectados", []))
    datos_completos = json.dumps(diagnostico, ensure_ascii=False)

    with sqlite3.connect(config.DB_PATH) as conn:
        conn.execute("""
            INSERT INTO diagnosticos (resumen_general, num_dispositivos, num_usuarios, num_problemas, datos_completos)
            VALUES (?, ?, ?, ?, ?)
        """, (resumen, num_dispositivos, num_usuarios, num_problemas, datos_completos))


def obtener_memoria_tendencias(limite: int = 5) -> str:
    """Recupera los últimos diagnósticos históricos para tendencias."""
    with sqlite3.connect(config.DB_PATH) as conn:
        registros = conn.execute("""
            SELECT timestamp, resumen_general, num_problemas
            FROM diagnosticos
            ORDER BY id DESC
            LIMIT ?
        """, (limite,)).fetchall()

    if not registros:
        return "No hay registros históricos de diagnósticos anteriores. Este es el primer análisis de la red."

    memoria_str = "HISTORIAL DE DIAGNÓSTICOS ANTERIORES (Para análisis de tendencias de salud):\n"
    for r in reversed(registros):
        timestamp_dt = datetime.strptime(r[0], "%Y-%m-%d %H:%M:%S")
        fecha_legible = timestamp_dt.strftime("%Y-%m-%d a las %H:%M:%S")
        memoria_str += f"- [{fecha_legible}] Problemas detectados: {r[2]}. Resumen: {r[1]}\n"

    return memoria_str


# ============================================================================
# MODELOS DE PETICIÓN
# ============================================================================

class RebootRequest(BaseModel):
    mac: str
    nombre: str


class OptimizationRequest(BaseModel):
    tipo_red: str
    nombre_red: str
    parametro: str
    valor: Any


# ============================================================================
# ENDPOINTS
# ============================================================================

@router.get("/health")
async def health_check():
    """Health check para monitoreo y load balancers."""
    db_ok = False
    try:
        with sqlite3.connect(config.DB_PATH) as conn:
            conn.execute("SELECT 1")
        db_ok = True
    except Exception:
        pass

    return {
        "status": "healthy" if db_ok else "degraded",
        "database": "ok" if db_ok else "error",
        "version": "1.0.0"
    }


@router.post("/api/diagnosticar")
@limiter.limit("5/minute")
async def diagnosticar(request: Request, _key: None = Depends(verify_api_key)):
    """Diagnóstico en tiempo real de la red UniFi."""
    sesion = unifi_client.conectar_unifi()
    if not sesion:
        raise HTTPException(
            status_code=500,
            detail="No se pudo conectar al controlador UniFi. Verifica host, puerto y credenciales."
        )

    try:
        metricas = unifi_client.obtener_metricas_red(sesion)
        if metricas is None:
            raise HTTPException(status_code=500, detail="Error al recopilar métricas de dispositivos UniFi.")

        configuraciones = unifi_client.obtener_configuraciones_red(sesion)
        if configuraciones is None:
            configuraciones = {"redes_wifi": [], "redes_lan": []}

        unifi_client.cerrar_sesion(sesion)

        memoria_tendencias = obtener_memoria_tendencias(limite=5)
        prompt_memoria = f"\n\n{memoria_tendencias}\n\nPor favor, ten en cuenta este historial para reportar si hay inestabilidades repetitivas o si la red ha mejorado respecto a análisis previos."

        diagnostico_obj = ai_analyzer.analizar_con_ia(metricas, configuraciones, prompt_memoria)
        if not diagnostico_obj:
            raise HTTPException(status_code=500, detail="Error en la generación del diagnóstico por Gemini AI.")

        diagnostico_dict = diagnostico_obj.model_dump()

        total_dispositivos = len(metricas)
        total_usuarios = sum(d.get("num_usuarios", 0) for d in metricas)

        guardar_diagnostico(diagnostico_dict, total_dispositivos, total_usuarios)

        return JSONResponse(content={
            "status": "success",
            "metricas": metricas,
            "configuraciones": configuraciones,
            "diagnostico": diagnostico_dict
        })

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error interno del servidor: {str(e)}")


@router.get("/api/historial")
async def historial():
    """Historial de diagnósticos guardados para tendencias."""
    try:
        with sqlite3.connect(config.DB_PATH) as conn:
            registros = conn.execute("""
                SELECT id, timestamp, num_dispositivos, num_usuarios, num_problemas, resumen_general, datos_completos
                FROM diagnosticos
                ORDER BY id DESC
                LIMIT 20
            """).fetchall()

        historial_list = []
        for r in registros:
            historial_list.append({
                "id": r[0],
                "timestamp": r[1],
                "num_dispositivos": r[2],
                "num_usuarios": r[3],
                "num_problemas": r[4],
                "resumen_general": r[5],
                "datos_completos": json.loads(r[6]) if r[6] else None
            })

        return JSONResponse(content={"status": "success", "historial": historial_list})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al leer historial: {str(e)}")


@router.post("/api/reiniciar")
@limiter.limit("2/minute")
async def reiniciar_dispositivo(request: Request, req: RebootRequest, _key: None = Depends(verify_api_key)):
    """Reiniciar un AP o Switch específico (Human-in-the-Loop)."""
    sesion = unifi_client.conectar_unifi()
    if not sesion:
        raise HTTPException(status_code=500, detail="No se pudo conectar al controlador UniFi para ejecutar el reinicio.")

    try:
        exito = unifi_client.ejecutar_accion(
            sesion=sesion, accion="reiniciar",
            mac_dispositivo=req.mac, nombre_dispositivo=req.nombre
        )

        unifi_client.cerrar_sesion(sesion)

        if exito:
            return {"status": "success", "message": f"Comando de reinicio enviado correctamente a '{req.nombre}'."}
        else:
            raise HTTPException(status_code=500, detail=f"El controlador rechazó el comando de reinicio para '{req.nombre}'.")

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al ejecutar reinicio: {str(e)}")


@router.post("/api/optimizar")
@limiter.limit("5/minute")
async def aplicar_optimizacion(request: Request, req: OptimizationRequest, _key: None = Depends(verify_api_key)):
    """Aplicar optimizaciones de configuración (Fast Roaming, IGMP, WPA3, etc.)"""
    sesion = unifi_client.conectar_unifi()
    if not sesion:
        raise HTTPException(status_code=500, detail="No se pudo conectar al controlador UniFi para aplicar optimizaciones.")

    try:
        exito = False
        tipo = req.tipo_red.lower().strip()

        if tipo == "wifi":
            exito = unifi_client.aplicar_optimizacion_wlan(
                sesion=sesion, ssid=req.nombre_red,
                parametro=req.parametro, valor=req.valor
            )
        elif tipo == "lan":
            exito = unifi_client.aplicar_optimizacion_lan(
                sesion=sesion, nombre_red=req.nombre_red,
                parametro=req.parametro, valor=req.valor
            )
        else:
            raise HTTPException(status_code=400, detail=f"Tipo de red '{req.tipo_red}' no válido. Usar 'wifi' o 'lan'.")

        unifi_client.cerrar_sesion(sesion)

        record_optimization(tipo_red=tipo, status="success" if exito else "error")

        if exito:
            return {"status": "success", "message": f"Optimización de '{req.parametro}' aplicada con éxito en '{req.nombre_red}'."}
        else:
            raise HTTPException(status_code=500, detail=f"El controlador rechazó la optimización de '{req.parametro}' en '{req.nombre_red}'.")

    except Exception as e:
        record_optimization(tipo_red=req.tipo_red, status="error")
        raise HTTPException(status_code=500, detail=f"Error al aplicar la optimización: {str(e)}")


# ============================================================================
# API KEY MANAGEMENT
# ============================================================================

class GenerateKeyRequest(BaseModel):
    nombre: str
    expira_dias: Optional[int] = None


@router.post("/api/keys")
async def generar_api_key(req: GenerateKeyRequest, _key: None = Depends(verify_api_key)):
    """Genera una nueva API key."""
    if not _api_key_manager:
        raise HTTPException(status_code=500, detail="Gestor de keys no inicializado.")
    result = _api_key_manager.generar_key(req.nombre, req.expira_dias)
    return JSONResponse(content={"status": "success", "data": result})


@router.get("/api/keys")
async def listar_api_keys(_key: None = Depends(verify_api_key)):
    """Lista todas las API keys (sin exponer hashes)."""
    if not _api_key_manager:
        raise HTTPException(status_code=500, detail="Gestor de keys no inicializado.")
    keys = _api_key_manager.listar_keys()
    return JSONResponse(content={"status": "success", "keys": keys})


@router.delete("/api/keys/{key_id}")
async def revocar_api_key(key_id: int, _key: None = Depends(verify_api_key)):
    """Revoca (desactiva) una API key."""
    if not _api_key_manager:
        raise HTTPException(status_code=500, detail="Gestor de keys no inicializado.")
    if _api_key_manager.revocar_key(key_id):
        return {"status": "success", "message": f"Key {key_id} revocada."}
    raise HTTPException(status_code=404, detail=f"Key {key_id} no encontrada.")


# ============================================================================
# BACKUP MANAGEMENT
# ============================================================================

@router.post("/api/backup")
async def crear_backup(_key: None = Depends(verify_api_key)):
    """Crea un backup manual de la base de datos."""
    if not _backup_manager:
        raise HTTPException(status_code=500, detail="Gestor de backups no inicializado.")
    path = _backup_manager.crear_backup(motivo="manual")
    if path:
        info = _backup_manager.obtener_info_db()
        return {"status": "success", "backup": path, "db_info": info}
    raise HTTPException(status_code=500, detail="Error al crear backup.")


@router.get("/api/backup")
async def listar_backups(_key: None = Depends(verify_api_key)):
    """Lista todos los backups disponibles."""
    if not _backup_manager:
        raise HTTPException(status_code=500, detail="Gestor de backups no inicializado.")
    backups = _backup_manager.listar_backups()
    info = _backup_manager.obtener_info_db()
    return JSONResponse(content={"status": "success", "backups": backups, "db_info": info})


@router.delete("/api/backup/cleanup")
async def limpiar_backups(_key: None = Depends(verify_api_key)):
    """Elimina backups antiguos según la política de retención."""
    if not _backup_manager:
        raise HTTPException(status_code=500, detail="Gestor de backups no inicializado.")
    eliminados = _backup_manager.limpiar_backups_antiguos()
    return {"status": "success", "eliminados": eliminados}

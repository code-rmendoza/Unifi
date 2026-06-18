"""
╔══════════════════════════════════════════════════════════════════════════════╗
║       AGENTE DE IA PARA OPTIMIZACIÓN DE RED UNIFI - WEB SERVER             ║
║       ────────────────────────────────────────────────────────             ║
║       Autor: Generado por Antigravity AI                                   ║
║       Versión: 1.0.0                                                       ║
║       Python: 3.10+                                                        ║
║                                                                            ║
║       Servidor web backend (FastAPI) para el panel interactivo,            ║
║       almacenamiento de memoria histórica (SQLite) y ejecución de          ║
║       acciones correctivas y optimizaciones en caliente.                   ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import os
import sys
import json
import sqlite3
from datetime import datetime
from typing import Optional, Dict, Any, List

import uvicorn
from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

# Importar funciones modulares del agente existente
import app

# ============================================================================
# INICIALIZACIÓN DE FASTAPI Y CONFIGURACIÓN
# ============================================================================

app_web = FastAPI(
    title="UniFi Network AI Agent",
    description="Panel de optimización inteligente con IA y Human-in-the-Loop para controladores UniFi",
    version="1.0.0"
)

# Base de datos SQLite local para la memoria de la IA
DB_PATH = "historial.db"

# Estructurar directorio de templates
TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
os.makedirs(TEMPLATES_DIR, exist_ok=True)
templates = Jinja2Templates(directory=TEMPLATES_DIR)


# ============================================================================
# PERSISTENCIA Y MEMORIA HISTÓRICA (SQLITE)
# ============================================================================

def inicializar_db():
    """Crea la base de datos y la tabla de historial si no existen."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS diagnosticos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            resumen_general TEXT,
            num_dispositivos INTEGER,
            num_usuarios INTEGER,
            num_problemas INTEGER,
            datos_completos TEXT  -- Almacena el JSON completo del diagnóstico
        )
    """)
    conn.commit()
    conn.close()


def guardar_diagnostico(diagnostico: Dict[str, Any], num_dispositivos: int, num_usuarios: int):
    """Guarda un registro de diagnóstico en la base de datos."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    resumen = diagnostico.get("resumen_general", "")
    num_problemas = len(diagnostico.get("problemas_detectados", []))
    datos_completos = json.dumps(diagnostico, ensure_ascii=False)
    
    cursor.execute("""
        INSERT INTO diagnosticos (resumen_general, num_dispositivos, num_usuarios, num_problemas, datos_completos)
        VALUES (?, ?, ?, ?, ?)
    """, (resumen, num_dispositivos, num_usuarios, num_problemas, datos_completos))
    
    conn.commit()
    conn.close()


def obtener_memoria_tendencias(limite: int = 5) -> str:
    """
    Recupera los últimos diagnósticos históricos para estructurar la memoria
    de tendencias que se le inyectará a Gemini.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT timestamp, resumen_general, num_problemas 
        FROM diagnosticos 
        ORDER BY id DESC 
        LIMIT ?
    """, (limite,))
    registros = cursor.fetchall()
    conn.close()

    if not registros:
        return "No hay registros históricos de diagnósticos anteriores. Este es el primer análisis de la red."

    memoria_str = "HISTORIAL DE DIAGNÓSTICOS ANTERIORES (Para análisis de tendencias de salud):\n"
    for r in reversed(registros):
        timestamp_dt = datetime.strptime(r[0], "%Y-%m-%d %H:%M:%S")
        fecha_legible = timestamp_dt.strftime("%Y-%m-%d a las %H:%M:%S")
        memoria_str += f"- [{fecha_legible}] Problemas detectados: {r[2]}. Resumen: {r[1]}\n"
    
    return memoria_str


# ============================================================================
# MODELOS DE PETICIÓN (INPUT SCHEMAS)
# ============================================================================

class RebootRequest(BaseModel):
    mac: str
    nombre: str

class OptimizationRequest(BaseModel):
    tipo_red: str       # "wifi" o "lan"
    nombre_red: str     # SSID o nombre de la red LAN
    parametro: str      # Parámetro a modificar (ej: "fast_roaming", "igmp_snooping", "upnp")
    valor: Any          # Nuevo valor (generalmente bool)


# ============================================================================
# ENDPOINTS DE LA APLICACIÓN WEB
# ============================================================================

@app_web.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Sirve la página web principal del agente."""
    return templates.TemplateResponse(request=request, name="index.html")


@app_web.post("/api/diagnosticar")
async def diagnosticar():
    """
    Realiza un diagnóstico en tiempo real de la red UniFi.
    Extrae métricas, configuraciones, inyecta memoria histórica,
    consulta a Gemini AI y guarda el resultado.
    """
    # 1. Conectar al controlador UniFi
    sesion = app.conectar_unifi()
    if not sesion:
        raise HTTPException(
            status_code=500, 
            detail="No se pudo conectar al controlador UniFi. Verifica host, puerto y credenciales."
        )

    try:
        # 2. Recopilar métricas de dispositivos
        metricas = app.obtener_metricas_red(sesion)
        if metricas is None:
            raise HTTPException(status_code=500, detail="Error al recopilar métricas de dispositivos UniFi.")

        # 3. Recopilar configuraciones de red
        configuraciones = app.obtener_configuraciones_red(sesion)
        if configuraciones is None:
            configuraciones = {"redes_wifi": [], "redes_lan": []}

        # 4. Cerrar sesión limpiamente con el controlador
        try:
            if app.UNIFI_CONTROLLER_TYPE == "udm":
                sesion.post(f"{app.BASE_URL}/api/auth/logout", timeout=5)
            else:
                sesion.post(f"{app.BASE_URL}/logout", timeout=5)
        except Exception:
            pass
        finally:
            sesion.close()

        # 5. Obtener memoria histórica de tendencias e inyectarla al prompt
        memoria_tendencias = obtener_memoria_tendencias(limite=5)
        
        # 6. Analizar con Gemini AI (Inyectando la memoria histórica)
        # Adaptamos temporalmente el prompt de app.py agregando la memoria
        prompt_memoria = f"\n\n{memoria_tendencias}\n\nPor favor, ten en cuenta este historial para reportar si hay inestabilidades repetitivas o si la red ha mejorado respecto a análisis previos."
        
        # Enviar los datos combinados a la IA
        diagnostico_obj = app.analizar_con_ia(metricas, configuraciones, prompt_memoria)
        if not diagnostico_obj:
            raise HTTPException(status_code=500, detail="Error en la generación del diagnóstico por Gemini AI.")

        # Convertir objeto Pydantic a diccionario
        diagnostico_dict = diagnostico_obj.model_dump()

        # Calcular totales para almacenamiento
        total_dispositivos = len(metricas)
        total_usuarios = sum(d.get("num_usuarios", 0) for d in metricas)

        # 7. Guardar el diagnóstico en SQLite (Memoria histórica)
        guardar_diagnostico(diagnostico_dict, total_dispositivos, total_usuarios)

        return JSONResponse(content={
            "status": "success",
            "metricas": metricas,
            "configuraciones": configuraciones,
            "diagnostico": diagnostico_dict
        })

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error interno del servidor: {str(e)}")


@app_web.get("/api/historial")
async def historial():
    """Retorna el historial de los diagnósticos guardados para graficar tendencias."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, timestamp, num_dispositivos, num_usuarios, num_problemas, resumen_general, datos_completos
            FROM diagnosticos 
            ORDER BY id DESC 
            LIMIT 20
        """)
        registros = cursor.fetchall()
        conn.close()

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


@app_web.post("/api/reiniciar")
async def reiniciar_dispositivo(req: RebootRequest):
    """Endpoint para reiniciar un AP o Switch específico con confirmación manual (Human-in-the-Loop)."""
    sesion = app.conectar_unifi()
    if not sesion:
        raise HTTPException(status_code=500, detail="No se pudo conectar al controlador UniFi para ejecutar el reinicio.")

    try:
        exito = app.ejecutar_accion(
            sesion=sesion,
            accion="reiniciar",
            mac_dispositivo=req.mac,
            nombre_dispositivo=req.nombre
        )
        
        # Cerrar sesión
        try:
            if app.UNIFI_CONTROLLER_TYPE == "udm":
                sesion.post(f"{app.BASE_URL}/api/auth/logout", timeout=5)
            else:
                sesion.post(f"{app.BASE_URL}/logout", timeout=5)
        except Exception:
            pass
        finally:
            sesion.close()

        if exito:
            return {"status": "success", "message": f"Comando de reinicio enviado correctamente a '{req.nombre}'."}
        else:
            raise HTTPException(status_code=500, detail=f"El controlador rechazó el comando de reinicio para '{req.nombre}'.")

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al ejecutar reinicio: {str(e)}")


@app_web.post("/api/optimizar")
async def aplicar_optimizacion(req: OptimizationRequest):
    """Endpoint para aplicar optimizaciones de configuración (Fast Roaming, IGMP Snooping, WPA3, etc.)"""
    sesion = app.conectar_unifi()
    if not sesion:
        raise HTTPException(status_code=500, detail="No se pudo conectar al controlador UniFi para aplicar optimizaciones.")

    try:
        exito = False
        tipo = req.tipo_red.lower().strip()
        
        if tipo == "wifi":
            exito = app.aplicar_optimizacion_wlan(
                sesion=sesion,
                ssid=req.nombre_red,
                parametro=req.parametro,
                valor=req.valor
            )
        elif tipo == "lan":
            exito = app.aplicar_optimizacion_lan(
                sesion=sesion,
                nombre_red=req.nombre_red,
                parametro=req.parametro,
                valor=req.valor
            )
        else:
            raise HTTPException(status_code=400, detail=f"Tipo de red '{req.tipo_red}' no válido. Usar 'wifi' o 'lan'.")

        # Cerrar sesión
        try:
            if app.UNIFI_CONTROLLER_TYPE == "udm":
                sesion.post(f"{app.BASE_URL}/api/auth/logout", timeout=5)
            else:
                sesion.post(f"{app.BASE_URL}/logout", timeout=5)
        except Exception:
            pass
        finally:
            sesion.close()

        if exito:
            return {"status": "success", "message": f"Optimización de '{req.parametro}' aplicada con éxito en '{req.nombre_red}'."}
        else:
            raise HTTPException(status_code=500, detail=f"El controlador rechazó la optimización de '{req.parametro}' en '{req.nombre_red}'.")

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al aplicar la optimización: {str(e)}")


# ============================================================================
# PUNTO DE ARRANQUE DEL SERVIDOR
# ============================================================================

if __name__ == "__main__":
    # Inicializar la base de datos al arrancar
    inicializar_db()
    print("  🚀 Inicializando servidor web UniFi Network AI Agent...")
    print("  🔗 Abre http://localhost:8000 en tu navegador web.")
    print()
    uvicorn.run(app_web, host="0.0.0.0", port=8000)

"""
Módulo de análisis de red con Inteligencia Artificial (Google Gemini).
"""

import json
import time
from datetime import datetime
from typing import Optional

from google import genai

from unifi_agent.core import config
from unifi_agent.core.models import DiagnosticoRed
from unifi_agent.core.utils import Color, imprimir_seccion, imprimir_estado


# ============================================================================
# ANÁLISIS CON INTELIGENCIA ARTIFICIAL (GEMINI)
# ============================================================================

def analizar_con_ia(
    datos_red: list[dict],
    config_red: dict,
    memoria_historial: Optional[str] = None,
) -> Optional[DiagnosticoRed]:
    """
    Envía métricas y configuraciones a Google Gemini para diagnóstico estructurado.
    """
    imprimir_seccion("ANÁLISIS CON INTELIGENCIA ARTIFICIAL", "🧠")

    if not config.GEMINI_API_KEY:
        imprimir_estado("La GEMINI_API_KEY no está configurada en el archivo .env", "error")
        return None

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
     * Desaconsejar que la potencia de transmisión (tx_power_mode) esté en 'Auto' o 'High' en todos los APs de forma generalizada.
3. ACCIONES RECOMENDADAS:
   - Sugerir 'reiniciar' solo ante fallos reales demostrados.
   - Sugerir 'monitorear' para alertas leves.
   - Sugerir 'ninguna' en estados estables.

Para cada regla de mejor práctica analizada:
- Indica el 'estado_actual'.
- Define 'cumple' en True o False.
- Explica la 'recomendación' técnica y su 'prioridad' (alta, media, baja).

SÉ CONCISO pero TÉCNICAMENTE PRECISO."""

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
    espera = 3

    for intento in range(1, intentos_max + 1):
        try:
            imprimir_estado(f"Conectando con modelo {config.GEMINI_MODEL} (Intento {intento}/{intentos_max})...", "info")

            cliente = genai.Client(api_key=config.GEMINI_API_KEY)

            respuesta = cliente.models.generate_content(
                model=config.GEMINI_MODEL,
                contents=prompt_usuario,
                config={
                    "system_instruction": prompt_sistema,
                    "response_mime_type": "application/json",
                    "response_schema": DiagnosticoRed,
                    "temperature": 0.3,
                },
            )

            diagnostico_json = json.loads(respuesta.text)
            diagnostico = DiagnosticoRed(**diagnostico_json)

            imprimir_estado("Análisis completado exitosamente ✓", "ok")

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
            es_error_temporal = any(
                kw in error_msg.upper()
                for kw in ["503", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED", "LIMIT"]
            )

            if es_error_temporal and intento < intentos_max:
                imprimir_estado(
                    f"API de Gemini sobrecargada. Esperando {espera}s antes de reintentar...",
                    "warn"
                )
                time.sleep(espera)
                espera *= 2
            else:
                if "API_KEY" in error_msg.upper() or "401" in error_msg or "403" in error_msg:
                    imprimir_estado("API Key de Gemini inválida o sin permisos.", "error")
                elif "model" in error_msg.lower() and "not found" in error_msg.lower():
                    imprimir_estado(f"El modelo '{config.GEMINI_MODEL}' no existe o no está disponible.", "error")
                else:
                    imprimir_estado(f"Error al comunicarse con Gemini: {e}", "error")
                return None


# ============================================================================
# MOSTRAR DIAGNÓSTICO EN CONSOLA
# ============================================================================

def _mostrar_diagnostico(diagnostico: DiagnosticoRed):
    """Imprime el diagnóstico de la IA con formato visual en consola."""

    print(f"\n  {Color.BOLD}{Color.WHITE}📋 RESUMEN GENERAL{Color.RESET}")
    print(f"  {Color.DIM}{'─' * 56}{Color.RESET}")
    for linea in diagnostico.resumen_general.split(". "):
        linea = linea.strip()
        if linea:
            print(f"  {Color.WHITE}  {linea}{'.' if not linea.endswith('.') else ''}{Color.RESET}")

    if diagnostico.problemas_detectados:
        print(f"\n  {Color.BOLD}{Color.YELLOW}⚠️  PROBLEMAS DE SALUD DETECTADOS ({len(diagnostico.problemas_detectados)}){Color.RESET}")
        print(f"  {Color.DIM}{'─' * 56}{Color.RESET}")
        for i, problema in enumerate(diagnostico.problemas_detectados, 1):
            print(f"  {Color.YELLOW}  {i}. {problema}{Color.RESET}")
    else:
        print(f"\n  {Color.GREEN}{Color.BOLD}✅ No se detectaron problemas de salud en los dispositivos.{Color.RESET}")

    if diagnostico.mejores_practicas:
        print(f"\n  {Color.BOLD}{Color.CYAN}📐 AUDITORÍA DE MEJORES PRÁCTICAS UNIFI ({len(diagnostico.mejores_practicas)}){Color.RESET}")
        print(f"  {Color.DIM}{'─' * 56}{Color.RESET}")
        for bp in diagnostico.mejores_practicas:
            if bp.cumple:
                icono = f"{Color.GREEN}✅"
                estado_linea = "Cumple mejor práctica de Ubiquiti."
            else:
                icono = f"{Color.YELLOW}⚠️"
                estado_linea = "Sugerencia de optimización pendiente."

            colores_prioridad = {"alta": Color.RED, "media": Color.YELLOW, "baja": Color.CYAN}
            color_prio = colores_prioridad.get(bp.prioridad, Color.WHITE)

            print(f"  {icono}  {Color.BOLD}{bp.regla}{Color.RESET}")
            print(f"      Estado actual: {Color.DIM}{bp.estado_actual}{Color.RESET}")
            print(f"      Auditoría    : {Color.BOLD}{estado_linea}{Color.RESET}")
            if not bp.cumple:
                print(f"      Recomendación: {Color.BOLD}{bp.recomendacion}{Color.RESET} (Prioridad: {color_prio}{bp.prioridad.upper()}{Color.RESET})")
            print()

    if diagnostico.acciones_recomendadas:
        print(f"\n  {Color.BOLD}{Color.MAGENTA}⚡ ACCIONES RECOMENDADAS ({len(diagnostico.acciones_recomendadas)}){Color.RESET}")
        print(f"  {Color.DIM}{'─' * 56}{Color.RESET}")
        for accion in diagnostico.acciones_recomendadas:
            colores_prioridad = {"critica": Color.RED, "alta": Color.YELLOW, "media": Color.CYAN, "baja": Color.GREEN}
            color = colores_prioridad.get(accion.prioridad, Color.WHITE)
            iconos = {"reiniciar": "🔄", "monitorear": "👀", "ninguna": "✅"}
            icono = iconos.get(accion.accion, "❓")

            print(f"  {icono}  {Color.BOLD}{accion.dispositivo}{Color.RESET} ({accion.mac})")
            print(f"      Acción: {Color.BOLD}{accion.accion.upper()}{Color.RESET}  │  Prioridad: {color}{Color.BOLD}{accion.prioridad.upper()}{Color.RESET}")
            print(f"      Motivo: {accion.motivo}")
            print()

    if diagnostico.observaciones_adicionales:
        print(f"  {Color.BOLD}{Color.CYAN}💡 OBSERVACIONES ADICIONALES{Color.RESET}")
        print(f"  {Color.DIM}{'─' * 56}{Color.RESET}")
        for obs in diagnostico.observaciones_adicionales:
            print(f"  {Color.CYAN}  • {obs}{Color.RESET}")
    print()

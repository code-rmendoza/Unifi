"""
Modulo CLI: interfaz de linea de comandos para el agente UniFi.
Ejecutar directamente: python -m unifi_agent
"""

import sys

from unifi_agent.core import config
from unifi_agent.core.models import DiagnosticoRed
from unifi_agent.services.unifi_client import (
    conectar_unifi, cerrar_sesion, obtener_metricas_red,
    obtener_configuraciones_red, ejecutar_accion,
)
from unifi_agent.services.ai_analyzer import analizar_con_ia
from unifi_agent.core.utils import (
    Color, imprimir_banner, imprimir_seccion, imprimir_estado,
)


# ============================================================================
# FLUJO HUMAN-IN-THE-LOOP (CLI)
# ============================================================================

def procesar_acciones_con_confirmacion(sesion, diagnostico: DiagnosticoRed):
    """Implementa el flujo Human-in-the-Loop para las acciones recomendadas."""
    imprimir_seccion("EJECUCIÓN DE ACCIONES CORRECTIVAS", "🎯")

    acciones = diagnostico.acciones_recomendadas

    if not acciones:
        imprimir_estado("No hay acciones para ejecutar.", "ok")
        return

    acciones_drasticas = [a for a in acciones if a.accion.lower() == "reiniciar"]
    acciones_info = [a for a in acciones if a.accion.lower() != "reiniciar"]

    for accion in acciones_info:
        ejecutar_accion(sesion, accion.accion, accion.mac, accion.dispositivo)

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
# PUNTO DE ENTRADA CLI
# ============================================================================

def main():
    """Flujo principal del Agente CLI."""
    imprimir_banner()

    imprimir_seccion("VALIDACIÓN DE CONFIGURACIÓN", "⚙️")

    errores_config = []
    if not config.UNIFI_USERNAME:
        errores_config.append("UNIFI_USERNAME no configurado en .env")
    if not config.UNIFI_PASSWORD:
        errores_config.append("UNIFI_PASSWORD no configurado en .env")
    if not config.GEMINI_API_KEY:
        errores_config.append("GEMINI_API_KEY no configurado en .env")

    if errores_config:
        for error in errores_config:
            imprimir_estado(error, "error")
        imprimir_estado("Copia .env.example a .env y completa las credenciales.", "warn")
        sys.exit(1)

    imprimir_estado(f"Host UniFi: {config.UNIFI_HOST}:{config.UNIFI_PORT}", "ok")
    imprimir_estado(f"Controlador: {config.UNIFI_CONTROLLER_TYPE.upper()}", "ok")
    imprimir_estado(f"Modelo IA: {config.GEMINI_MODEL}", "ok")
    imprimir_estado("Configuración validada ✓", "ok")

    sesion = conectar_unifi()
    if not sesion:
        imprimir_estado("No se pudo establecer conexión. Abortando.", "error")
        sys.exit(1)

    try:
        metricas = obtener_metricas_red(sesion)
        if metricas is None:
            imprimir_estado("No se pudieron obtener las métricas. Abortando.", "error")
            sys.exit(1)

        configuraciones = obtener_configuraciones_red(sesion)
        if configuraciones is None:
            imprimir_estado("No se pudieron obtener las configuraciones de red. Continuando con datos parciales...", "warn")
            configuraciones = {"redes_wifi": [], "redes_lan": []}

        if len(metricas) == 0:
            imprimir_estado("No se encontraron Access Points ni Switches. Verifica que el sitio sea correcto.", "warn")
            sys.exit(0)

        diagnostico = analizar_con_ia(metricas, configuraciones)
        if not diagnostico:
            imprimir_estado("No se pudo obtener el diagnóstico de la IA. Abortando.", "error")
            sys.exit(1)

        procesar_acciones_con_confirmacion(sesion, diagnostico)

    except KeyboardInterrupt:
        print(f"\n\n{Color.YELLOW}  ⚠  Ejecución interrumpida por el usuario (Ctrl+C).{Color.RESET}")

    finally:
        imprimir_seccion("CIERRE DE SESIÓN", "🔒")
        cerrar_sesion(sesion)
        imprimir_estado("Sesión cerrada.", "ok")
        imprimir_estado("Agente finalizado.", "ok")
        print()


if __name__ == "__main__":
    main()

"""
Cliente API para el controlador UniFi.
Conexión, obtención de métricas, configuraciones y ejecución de acciones.
"""

import json
import time
from datetime import datetime
from typing import Optional, Union

import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry
from pydantic import ValidationError

from unifi_agent.core import config
from unifi_agent.core.models import (
    UniFiAuthError, UniFiAPIError, UniFiConnectionError,
    MetricaDispositivo, ConfigWlan, ConfigNetwork,
)
from unifi_agent.core.utils import (
    Color, logger, formatear_uptime,
    imprimir_seccion, imprimir_estado,
)


# ============================================================================
# CERRAR SESIÓN
# ============================================================================

def cerrar_sesion(sesion: requests.Session):
    """Cierra la sesión HTTP con el controlador UniFi de forma segura."""
    try:
        if config.UNIFI_CONTROLLER_TYPE == "udm":
            sesion.post(f"{config.BASE_URL}/api/auth/logout", timeout=5)
        else:
            sesion.post(f"{config.BASE_URL}/logout", timeout=5)
    except Exception:
        pass
    finally:
        sesion.close()


# ============================================================================
# CONEXIÓN AL CONTROLADOR UNIFI
# ============================================================================

def conectar_unifi() -> Optional[requests.Session]:
    """
    Autentica con el controlador UniFi y devuelve una sesión HTTP activa.
    """
    imprimir_seccion("CONEXIÓN AL CONTROLADOR UNIFI", "🔐")
    imprimir_estado(f"Host: {config.UNIFI_HOST}:{config.UNIFI_PORT}", "info")
    imprimir_estado(f"Tipo de controlador: {config.UNIFI_CONTROLLER_TYPE.upper()}", "info")
    imprimir_estado(f"Sitio: {config.UNIFI_SITE}", "info")
    imprimir_estado(f"Verificación SSL: {'Sí' if config.UNIFI_VERIFY_SSL else 'No (autofirmado)'}", "info")

    if not config.UNIFI_USERNAME or not config.UNIFI_PASSWORD:
        imprimir_estado(
            "Las credenciales UNIFI_USERNAME y UNIFI_PASSWORD son obligatorias en .env",
            "error"
        )
        return None

    sesion = requests.Session()
    sesion.verify = config.UNIFI_VERIFY_SSL

    retries = Retry(
        total=3, backoff_factor=1,
        status_forcelist=[500, 502, 503, 504],
        raise_on_status=False
    )
    adapter = HTTPAdapter(max_retries=retries)
    sesion.mount("https://", adapter)
    sesion.mount("http://", adapter)

    payload_login = {
        "username": config.UNIFI_USERNAME,
        "password": config.UNIFI_PASSWORD,
    }

    try:
        imprimir_estado("Intentando autenticación...", "info")

        respuesta = sesion.post(
            config.ENDPOINTS["login"],
            json=payload_login,
            timeout=15,
        )

        if respuesta.status_code == 200:
            imprimir_estado("Autenticación exitosa ✓", "ok")

            csrf_token = respuesta.headers.get("X-CSRF-Token")
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
            f"Tiempo de conexión agotado al intentar alcanzar {config.UNIFI_HOST}:{config.UNIFI_PORT}",
            "error"
        )
        return None
    except requests.exceptions.ConnectionError as e:
        imprimir_estado(
            f"No se pudo conectar al controlador en {config.UNIFI_HOST}:{config.UNIFI_PORT}",
            "error"
        )
        return None
    except requests.exceptions.RequestException as e:
        imprimir_estado(f"Error inesperado de red durante la autenticación: {e}", "error")
        return None


# ============================================================================
# OBTENER MÉTRICAS DE LA RED
# ============================================================================

def obtener_metricas_red(sesion: requests.Session) -> Optional[list[dict]]:
    """Extrae métricas de salud de todos los dispositivos UniFi adoptados."""
    imprimir_seccion("RECOPILACIÓN DE MÉTRICAS DE RED", "📊")

    tipos_validos = {"uap": "Access Point", "usw": "Switch"}
    estados = {
        0: "desconectado", 1: "conectado", 2: "gestionando",
        4: "actualizando", 5: "provisionando", 6: "no adoptado", 7: "adoptando",
    }

    try:
        imprimir_estado("Consultando dispositivos adoptados...", "info")

        respuesta = sesion.get(config.ENDPOINTS["dispositivos"], timeout=15)

        if respuesta.status_code != 200:
            imprimir_estado(f"Error al consultar dispositivos. HTTP {respuesta.status_code}", "error")
            return None

        datos = respuesta.json()
        dispositivos_raw = datos.get("data", [])

        if not dispositivos_raw:
            imprimir_estado("No se encontraron dispositivos adoptados.", "warn")
            return []

        imprimir_estado(f"Se encontraron {len(dispositivos_raw)} dispositivo(s) en total.", "ok")

        metricas = []

        for dispositivo in dispositivos_raw:
            tipo_raw = dispositivo.get("type", "")
            if tipo_raw not in tipos_validos:
                continue

            sys_stats = dispositivo.get("system-stats", {})
            cpu = sys_stats.get("cpu", "N/A")
            mem = sys_stats.get("mem", "N/A")

            stat = dispositivo.get("stat", {})
            tx_bytes = dispositivo.get("tx_bytes", stat.get("tx_bytes", 0))
            rx_bytes = dispositivo.get("rx_bytes", stat.get("rx_bytes", 0))

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
                metrica_validada = MetricaDispositivo(**metrica)
                metricas.append(metrica_validada.model_dump())
            except ValidationError as ve:
                imprimir_estado(
                    f"Ignorando dispositivo '{metrica.get('nombre')}' ({metrica.get('mac')}) "
                    f"debido a datos inválidos en la API: {ve.errors()}",
                    "warn"
                )

        aps = [m for m in metricas if m["tipo"] == "Access Point"]
        switches = [m for m in metricas if m["tipo"] == "Switch"]

        imprimir_estado(f"Access Points detectados: {len(aps)}", "ok")
        imprimir_estado(f"Switches detectados: {len(switches)}", "ok")

        print(f"\n  {Color.WHITE}{Color.BOLD}{'Dispositivo':<25} {'Tipo':<15} {'Estado':<15} {'Satisf.':<10} {'Usuarios':<10}{Color.RESET}")
        print(f"  {'─' * 75}")

        for m in metricas:
            if m["estado"] == "conectado":
                color_estado = Color.GREEN
            elif m["estado"] == "desconectado":
                color_estado = Color.RED
            else:
                color_estado = Color.YELLOW

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
# OBTENER CONFIGURACIONES DE RED (WLAN y LAN)
# ============================================================================

def obtener_configuraciones_red(sesion: requests.Session) -> Optional[dict]:
    """Consulta las configuraciones de redes inalámbricas y cableadas."""
    imprimir_seccion("RECOPILACIÓN DE CONFIGURACIONES DE RED", "⚙️")

    redes_wifi = []
    redes_lan = []

    try:
        imprimir_estado("Consultando redes WiFi (WLAN)...", "info")
        respuesta_wlan = sesion.get(config.ENDPOINTS["config_wlan"], timeout=15)

        if respuesta_wlan.status_code == 200:
            datos_wlan = respuesta_wlan.json().get("data", [])
            imprimir_estado(f"Se encontraron {len(datos_wlan)} red(es) WiFi configurada(s).", "ok")

            for wlan in datos_wlan:
                try:
                    wlan_validada = ConfigWlan(**wlan)
                    redes_wifi.append(wlan_validada.model_dump())
                except ValidationError as ve:
                    ssid_name = wlan.get("name")
                    imprimir_estado(
                        f"Ignorando SSID '{ssid_name}' "
                        f"debido a discrepancias en el esquema: {ve.errors()}",
                        "warn"
                    )
        else:
            imprimir_estado(f"No se pudieron obtener redes WLAN. HTTP: {respuesta_wlan.status_code}", "warn")

        imprimir_estado("Consultando redes cableadas y VLANs (LAN)...", "info")
        respuesta_lan = sesion.get(config.ENDPOINTS["config_network"], timeout=15)

        if respuesta_lan.status_code == 200:
            datos_lan = respuesta_lan.json().get("data", [])
            imprimir_estado(f"Se encontraron {len(datos_lan)} red(es) LAN/VLAN configurada(s).", "ok")

            for lan in datos_lan:
                try:
                    lan_validada = ConfigNetwork(**lan)
                    redes_lan.append(lan_validada.model_dump())
                except ValidationError as ve:
                    lan_name = lan.get("name")
                    imprimir_estado(
                        f"Ignorando red LAN '{lan_name}' "
                        f"debido a discrepancias en el esquema: {ve.errors()}",
                        "warn"
                    )
        else:
            imprimir_estado(f"No se pudieron obtener redes LAN. HTTP: {respuesta_lan.status_code}", "warn")

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

        return {"redes_wifi": redes_wifi, "redes_lan": redes_lan}

    except requests.exceptions.RequestException as e:
        imprimir_estado(f"Error de red al obtener configuraciones: {e}", "error")
        return None
    except Exception as e:
        imprimir_estado(f"Error inesperado al recopilar configuraciones: {e}", "error")
        return None


# ============================================================================
# EJECUTAR ACCIÓN CORRECTIVA
# ============================================================================

def ejecutar_accion(
    sesion: requests.Session,
    accion: str,
    mac_dispositivo: str,
    nombre_dispositivo: str,
) -> bool:
    """Ejecuta una acción correctiva sobre un dispositivo UniFi específico."""
    accion = accion.lower().strip()

    if accion == "ninguna":
        imprimir_estado(f"'{nombre_dispositivo}' — Sin acción necesaria.", "ok")
        return True

    if accion == "monitorear":
        imprimir_estado(
            f"'{nombre_dispositivo}' ({mac_dispositivo}) — Marcado para monitoreo continuo.",
            "warn"
        )
        return True

    if accion == "reiniciar":
        if config.DRY_RUN:
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

            payload = {"cmd": "restart", "mac": mac_dispositivo}

            respuesta = sesion.post(
                config.ENDPOINTS["comando_dispositivo"],
                json=payload, timeout=15,
            )

            if respuesta.status_code == 200:
                datos_resp = respuesta.json()
                if datos_resp.get("meta", {}).get("rc") == "ok":
                    imprimir_estado(
                        f"✓ Comando de reinicio enviado exitosamente a '{nombre_dispositivo}'.",
                        "ok"
                    )
                    return True
                else:
                    imprimir_estado(f"El controlador rechazó el comando: {datos_resp}", "error")
                    return False
            else:
                imprimir_estado(
                    f"Error al enviar comando. HTTP {respuesta.status_code}: {respuesta.text[:200]}",
                    "error"
                )
                return False

        except requests.exceptions.RequestException as e:
            imprimir_estado(f"Error de red al ejecutar acción sobre '{nombre_dispositivo}': {e}", "error")
            return False

    imprimir_estado(
        f"Acción '{accion}' no reconocida. Acciones válidas: reiniciar, monitorear, ninguna.",
        "warn"
    )
    return False


# ============================================================================
# APLICAR OPTIMIZACIONES DE CONFIGURACIÓN
# ============================================================================

def aplicar_optimizacion_wlan(
    sesion: requests.Session,
    ssid: str,
    parametro: str,
    valor: Union[bool, str],
) -> bool:
    """Modifica la configuración de una red inalámbrica (WLAN) específica."""
    imprimir_estado(f"Iniciando optimización WLAN para '{ssid}' (Parámetro: {parametro} -> {valor})...", "accion")

    if config.DRY_RUN:
        imprimir_estado(f"[SIMULACIÓN] WLAN '{ssid}': Se habría actualizado '{parametro}' a {valor}.", "ok")
        return True

    try:
        respuesta_list = sesion.get(config.ENDPOINTS["config_wlan"], timeout=15)
        if respuesta_list.status_code != 200:
            imprimir_estado(f"Error al listar WLANs. HTTP {respuesta_list.status_code}", "error")
            return False

        wlans = respuesta_list.json().get("data", [])
        wlan_obj = next((w for w in wlans if w.get("name") == ssid), None)

        if not wlan_obj or "_id" not in wlan_obj:
            imprimir_estado(f"No se encontró la red WiFi '{ssid}' en el controlador.", "error")
            return False

        wlan_id = wlan_obj["_id"]

        mapeo_propiedades = {
            "fast_roaming": "fast_roaming_enabled",
            "wpa3": "wpa3_support",
            "pmf": "pmf_mode",
            "multicast_enhance": "multicast_enhance"
        }

        prop_key = mapeo_propiedades.get(parametro.lower())
        if not prop_key:
            imprimir_estado(f"Parámetro '{parametro}' no reconocido para WLAN.", "error")
            return False

        payload = {prop_key: valor}

        if prop_key == "wpa3_support" and valor is True:
            payload["pmf_mode"] = "optional"

        url_put = f"{config.ENDPOINTS['config_wlan']}/{wlan_id}"
        respuesta_put = sesion.put(url_put, json=payload, timeout=15)

        if respuesta_put.status_code == 200:
            datos_resp = respuesta_put.json()
            if datos_resp.get("meta", {}).get("rc") == "ok":
                imprimir_estado(f"✓ Optimización aplicada exitosamente a '{ssid}'!", "ok")
                return True
            else:
                imprimir_estado(f"El controlador rechazó la actualización: {datos_resp}", "error")
                return False
        else:
            imprimir_estado(f"Error al aplicar optimización. HTTP {respuesta_put.status_code}", "error")
            return False

    except Exception as e:
        imprimir_estado(f"Error al aplicar optimización WLAN en '{ssid}': {e}", "error")
        return False


def aplicar_optimizacion_lan(
    sesion: requests.Session,
    nombre_red: str,
    parametro: str,
    valor: Union[bool, str],
) -> bool:
    """Modifica la configuración de una red cableada/VLAN (LAN) específica."""
    imprimir_estado(f"Iniciando optimización LAN para '{nombre_red}' (Parámetro: {parametro} -> {valor})...", "accion")

    if config.DRY_RUN:
        imprimir_estado(f"[SIMULACIÓN] LAN '{nombre_red}': Se habría actualizado '{parametro}' a {valor}.", "ok")
        return True

    try:
        respuesta_list = sesion.get(config.ENDPOINTS["config_network"], timeout=15)
        if respuesta_list.status_code != 200:
            imprimir_estado(f"Error al listar redes LAN. HTTP {respuesta_list.status_code}", "error")
            return False

        networks = respuesta_list.json().get("data", [])
        net_obj = next((n for n in networks if n.get("name") == nombre_red), None)

        if not net_obj or "_id" not in net_obj:
            imprimir_estado(f"No se encontró la red LAN '{nombre_red}' en el controlador.", "error")
            return False

        net_id = net_obj["_id"]

        mapeo_propiedades = {
            "igmp_snooping": "igmp_snooping",
            "upnp": "upnp_enabled"
        }

        prop_key = mapeo_propiedades.get(parametro.lower())
        if not prop_key:
            imprimir_estado(f"Parámetro '{parametro}' no reconocido para LAN.", "error")
            return False

        payload = {prop_key: valor}

        url_put = f"{config.ENDPOINTS['config_network']}/{net_id}"
        respuesta_put = sesion.put(url_put, json=payload, timeout=15)

        if respuesta_put.status_code == 200:
            datos_resp = respuesta_put.json()
            if datos_resp.get("meta", {}).get("rc") == "ok":
                imprimir_estado(f"✓ Optimización aplicada exitosamente a '{nombre_red}'!", "ok")
                return True
            else:
                imprimir_estado(f"El controlador rechazó la actualización: {datos_resp}", "error")
                return False
        else:
            imprimir_estado(f"Error al aplicar optimización. HTTP {respuesta_put.status_code}", "error")
            return False

    except Exception as e:
        imprimir_estado(f"Error al aplicar optimización LAN en '{nombre_red}': {e}", "error")
        return False

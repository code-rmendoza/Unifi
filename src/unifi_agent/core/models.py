"""
Modelos Pydantic para validación de datos y esquemas de respuesta,
y excepciones personalizadas del agente.
"""

from typing import Optional, Union
from pydantic import BaseModel, Field


# ============================================================================
# EXCEPCIONES
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
    dispositivo: str
    mac: str
    accion: str
    motivo: str
    prioridad: str


class AnalisisMejoresPracticas(BaseModel):
    """Modelo para el análisis de mejores prácticas de la configuración."""
    regla: str
    estado_actual: str
    cumple: bool
    recomendacion: str
    prioridad: str


class DiagnosticoRed(BaseModel):
    """Modelo completo del diagnóstico de la IA con análisis de mejores prácticas."""
    resumen_general: str
    problemas_detectados: list[str]
    mejores_practicas: list[AnalisisMejoresPracticas]
    acciones_recomendadas: list[AccionRecomendada]
    observaciones_adicionales: list[str]

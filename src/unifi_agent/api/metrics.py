"""
Métricas de Prometheus para monitoreo de la aplicación.
"""

import time
from prometheus_client import (
    Counter, Histogram, Gauge, Info, generate_latest, CONTENT_TYPE_LATEST,
)
from fastapi import APIRouter, Response

metrics_router = APIRouter()

# ============================================================================
# MÉTRICAS
# ============================================================================

# Info de la aplicación
app_info = Info("unifi_agent", "Información del agente UniFi")
app_info.info({
    "version": "1.0.0",
    "description": "Agente de IA para optimización de red UniFi",
})

# Contadores
http_requests_total = Counter(
    "unifi_agent_http_requests_total",
    "Total de peticiones HTTP",
    ["method", "endpoint", "status"],
)

diagnostics_total = Counter(
    "unifi_agent_diagnostics_total",
    "Total de diagnósticos ejecutados",
    ["status"],
)

reboot_commands_total = Counter(
    "unifi_agent_reboot_commands_total",
    "Total de comandos de reinicio enviados",
    ["status"],
)

optimizations_total = Counter(
    "unifi_agent_optimizations_total",
    "Total de optimizaciones aplicadas",
    ["tipo_red", "status"],
)

unifi_connections_total = Counter(
    "unifi_agent_unifi_connections_total",
    "Total de conexiones al controlador UniFi",
    ["status"],
)

ai_requests_total = Counter(
    "unifi_agent_ai_requests_total",
    "Total de peticiones a Gemini AI",
    ["status"],
)

# Histogramas
http_request_duration_seconds = Histogram(
    "unifi_agent_http_request_duration_seconds",
    "Duración de peticiones HTTP en segundos",
    ["method", "endpoint"],
    buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0],
)

diagnostic_duration_seconds = Histogram(
    "unifi_agent_diagnostic_duration_seconds",
    "Duración de diagnósticos completos en segundos",
    buckets=[5.0, 10.0, 30.0, 60.0, 120.0, 300.0],
)

ai_response_duration_seconds = Histogram(
    "unifi_agent_ai_response_duration_seconds",
    "Duración de respuestas de Gemini AI en segundos",
    buckets=[1.0, 2.5, 5.0, 10.0, 30.0, 60.0],
)

# Gauges
active_sessions = Gauge(
    "unifi_agent_active_sessions",
    "Sesiones HTTP activas al controlador UniFi",
)

db_size_bytes = Gauge(
    "unifi_agent_db_size_bytes",
    "Tamaño de la base de datos SQLite en bytes",
)

diagnostic_history_count = Gauge(
    "unifi_agent_diagnostic_history_count",
    "Número de registros en el historial de diagnósticos",
)

# ============================================================================
# ENDPOINT DE MÉTRICAS
# ============================================================================

@metrics_router.get("/metrics")
async def metrics():
    """Endpoint de métricas para Prometheus."""
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )


# ============================================================================
# HELPERS PARA REGISTRAR MÉTRICAS
# ============================================================================

def record_request(method: str, endpoint: str, status: int, duration: float):
    """Registra una petición HTTP en las métricas."""
    http_requests_total.labels(method=method, endpoint=endpoint, status=str(status)).inc()
    http_request_duration_seconds.labels(method=method, endpoint=endpoint).observe(duration)


def record_diagnostic(status: str, duration: float):
    """Registra un diagnóstico ejecutado."""
    diagnostics_total.labels(status=status).inc()
    diagnostic_duration_seconds.observe(duration)


def record_reboot(status: str):
    """Registra un comando de reinicio."""
    reboot_commands_total.labels(status=status).inc()


def record_optimization(tipo_red: str, status: str):
    """Registra una optimización aplicada."""
    optimizations_total.labels(tipo_red=tipo_red, status=status).inc()


def record_unifi_connection(status: str):
    """Registra una conexión al controlador."""
    unifi_connections_total.labels(status=status).inc()


def record_ai_request(status: str, duration: float):
    """Registra una petición a Gemini AI."""
    ai_requests_total.labels(status=status).inc()
    ai_response_duration_seconds.observe(duration)

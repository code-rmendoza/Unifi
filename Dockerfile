# ============================================================================
# Dockerfile — UniFi Network AI Agent
# Multi-stage build para imagen final pequeña y segura.
# ============================================================================

# --- Stage 1: Instalar dependencias ---
FROM python:3.12-slim AS builder

WORKDIR /app

COPY pyproject.toml .
COPY src/ src/
RUN pip install --no-cache-dir --prefix=/install .

# --- Stage 2: Imagen final ---
FROM python:3.12-slim

WORKDIR /app

# Crear usuario no-root
RUN useradd --create-home --shell /bin/bash appuser

# Copiar dependencias instaladas
COPY --from=builder /install /usr/local

# Copiar código fuente
COPY src/ src/

# Dar permisos al usuario
RUN chown -R appuser:appuser /app

# Cambiar a usuario no-root
USER appuser

# Puerto de la aplicación
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

# Punto de entrada
CMD ["python", "-m", "unifi_agent.app"]

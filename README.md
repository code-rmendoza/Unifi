# UniFi Network AI Agent

Agente de IA para diagnóstico y optimización de redes UniFi, con panel web interactivo y modo CLI.

## Características

- Diagnóstico inteligente de red con Google Gemini
- Auditoría de mejores prácticas UniFi (WPA3, Fast Roaming, VLANs, IGMP)
- Acciones correctivas con Human-in-the-Loop (reiniciar dispositivos, cambiar configuración)
- Panel web interactivo con dashboard visual
- Memoria histórica de tendencias (SQLite)
- Modo CLI para diagnóstico rápido desde terminal
- Logging centralizado (JSON estructurado, syslog, rotación)
- Métricas Prometheus para monitoreo
- Backup automático de base de datos con retención configurable
- Gestión de API keys con rotación

## Requisitos

- Python 3.11+
- Controlador UniFi (UDM Pro, UDM SE, Cloud Key, o UniFi Network Application)
- API Key de Google Gemini (obtén en https://aistudio.google.com/apikey)

## Instalación

### Opción 1: Virtualenv (recomendado para desarrollo)

```bash
git clone <url-del-repositorio>
cd unifi

# Crear entorno virtual
python -m venv .venv
.venv\Scripts\activate        # Windows
source .venv/bin/activate     # Linux/Mac

# Instalar dependencias
pip install -r requirements.txt

# Configurar variables de entorno
cp .env.example .env
# Editar .env con tus credenciales
```

### Opción 2: pip install (recomendado para uso directo)

```bash
pip install -e .

# Ejecutar CLI
unifi-agent

# O ejecutar web
unifi-web
```

### Opción 3: Docker (recomendado para producción)

```bash
# Clonar y configurar
git clone <url-del-repositorio>
cd unifi
cp .env.example .env
# Editar .env con tus credenciales

# Construir y ejecutar
docker build -t unifi-agent .
docker run -d -p 8000:8000 --name unifi-agent --env-file .env unifi-agent
```

## Configuración

Todas las variables se configuran en el archivo `.env`. Copia `.env.example` como base.

### Controlador UniFi

| Variable | Descripción | Default |
|----------|-------------|---------|
| `UNIFI_HOST` | IP del controlador UniFi | `192.168.1.1` |
| `UNIFI_PORT` | Puerto HTTPS del controlador | `443` |
| `UNIFI_USERNAME` | Usuario local del controlador | *requerido* |
| `UNIFI_PASSWORD` | Contraseña del controlador | *requerido* |
| `UNIFI_SITE` | Nombre del sitio UniFi | `default` |
| `UNIFI_CONTROLLER_TYPE` | `udm` o `cloudkey` | `udm` |
| `UNIFI_VERIFY_SSL` | Verificar certificados SSL | `false` |
| `DRY_RUN` | Simular acciones sin ejecutar | `false` |

### IA y Autenticación

| Variable | Descripción | Default |
|----------|-------------|---------|
| `GEMINI_API_KEY` | API Key de Google Gemini | *requerido* |
| `GEMINI_MODEL` | Modelo de Gemini a usar | `gemini-2.5-flash` |
| `API_KEY` | Key para autenticar la API web | *requerido* |
| `ALLOWED_ORIGINS` | Dominios CORS permitidos | `http://localhost:8000` |

### Logging

| Variable | Descripción | Default |
|----------|-------------|---------|
| `LOG_LEVEL` | Nivel de log | `INFO` |
| `LOG_FORMAT` | `text` o `json` | `text` |
| `LOG_FILE` | Archivo de log | `unifi_agent.log` |
| `LOG_MAX_BYTES` | Tamaño máximo por archivo | `5242880` |
| `LOG_BACKUP_COUNT` | Backups de log a mantener | `5` |
| `LOG_SYSLOG_ADDRESS` | Syslog remoto (host:port) | *deshabilitado* |

### Backup y Base de Datos

| Variable | Descripción | Default |
|----------|-------------|---------|
| `DB_PATH` | Ruta de la BD SQLite | `historial.db` |
| `BACKUP_DIR` | Directorio de backups | `backups` |
| `BACKUP_RETENTION_DAYS` | Días de retención | `30` |
| `BACKUP_MAX_COUNT` | Máximo de backups | `50` |

## Uso

### Modo Web

```bash
python -m unifi_agent.app
# O si instalaste con pip install -e .
unifi-web
```

Abre http://localhost:8000 en tu navegador. Haz clic en "Ejecutar Diagnóstico IA" para analizar la red.

### Modo CLI

```bash
python -m unifi_agent
# O si instalaste con pip install -e .
unifi-agent
```

Ejecuta el diagnóstico completo desde la terminal con confirmación interactiva para acciones drásticas.

## API Endpoints

### Core

| Endpoint | Método | Auth | Rate Limit | Descripción |
|----------|--------|------|------------|-------------|
| `/` | GET | No | - | Panel web |
| `/health` | GET | No | - | Health check |
| `/metrics` | GET | No | - | Métricas Prometheus |
| `/api/historial` | GET | No | - | Últimos 20 diagnósticos |
| `/api/diagnosticar` | POST | Sí | 5/min | Ejecutar diagnóstico IA |
| `/api/reiniciar` | POST | Sí | 2/min | Reiniciar dispositivo |
| `/api/optimizar` | POST | Sí | 5/min | Aplicar optimización |

### Gestión de API Keys

| Endpoint | Método | Auth | Descripción |
|----------|--------|------|-------------|
| `/api/keys` | GET | Sí | Listar API keys |
| `/api/keys` | POST | Sí | Generar nueva API key |
| `/api/keys/{id}` | DELETE | Sí | Revocar API key |

### Gestión de Backups

| Endpoint | Método | Auth | Descripción |
|----------|--------|------|-------------|
| `/api/backup` | GET | Sí | Listar backups |
| `/api/backup` | POST | Sí | Crear backup manual |
| `/api/backup/cleanup` | DELETE | Sí | Limpiar backups antiguos |

Los endpoints protegidos requieren el header `X-API-Key`.

## Desarrollo

### Ejecutar tests

```bash
pytest
```

### Estructura del proyecto

```
src/unifi_agent/               # Paquete Python
├── __init__.py
├── __main__.py                # python -m unifi_agent
├── app.py                     # FastAPI server + middleware
├── cli.py                     # CLI con Human-in-the-Loop
├── core/                      # Config, modelos, utilidades
│   ├── config.py
│   ├── logging.py             # Logging centralizado (JSON/syslog)
│   ├── models.py
│   └── utils.py
├── services/                  # Lógica de negocio
│   ├── ai_analyzer.py
│   ├── api_keys.py            # Gestión de API keys
│   ├── backup.py              # Backup automático de SQLite
│   └── unifi_client.py
├── api/                       # Endpoints FastAPI
│   ├── metrics.py             # Métricas Prometheus
│   └── routes.py
└── templates/
    └── index.html
tests/                         # 47 tests unitarios
pyproject.toml                 # Build config + entry points
Dockerfile                     # Imagen Docker multi-stage
requirements.txt               # Dependencias fijadas
.env.example                   # Template de configuración
AUDIT_REPORT.md                # Reporte de auditoría técnica
```

## Reporte de Auditoría

Ver [AUDIT_REPORT.md](AUDIT_REPORT.md) para el reporte completo de las 4 fases de auditoría técnica.

## Licencia

Proyecto privado. Todos los derechos reservados.

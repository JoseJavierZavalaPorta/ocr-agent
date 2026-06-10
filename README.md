# OCR Agent

Sistema de procesamiento OCR offline para documentos históricos escaneados (1900–actualidad). Convierte PDFs escaneados a Markdown de alta fidelidad con corrección contextual por IA. Diseñado para operar completamente sin internet después de la instalación inicial.

---

## Instalación en un comando

> Máquina Ubuntu 22.04/24.04 con GPU AMD (RX 5090). Solo necesitas internet en este paso.

```bash
curl -fsSL https://raw.githubusercontent.com/JoseJavierZavalaPorta/ocr-agent/main/bootstrap.sh -o bootstrap.sh
chmod +x bootstrap.sh && ./bootstrap.sh
```

El script `bootstrap.sh` hace **todo automáticamente**:
1. Instala Git, Docker y Docker Compose
2. Instala el driver AMD ROCm
3. Detecta la versión GFX de tu GPU y configura el `.env`
4. Clona este repositorio
5. Construye y levanta los 5 servicios Docker
6. Descarga todos los modelos OCR (~18 GB)
7. Deja el sistema listo en `http://localhost:3000`

> El script es **reentrant**: si se interrumpe (incluyendo el reinicio obligatorio tras instalar ROCm), vuélvelo a ejecutar y continúa desde donde quedó.

---

## Características

- **Multi-motor inteligente**: el sistema analiza cada página y elige automáticamente el mejor motor OCR
  - **Surya OCR** — documentos impresos y tipografía antigua (GPU, motor principal)
  - **TrOCR** — manuscritos a mano (GPU, especializado en escritura cursiva)
  - **MinerU** — páginas con tablas complejas (CPU, alta fidelidad estructural)
  - **Tesseract** — fallback final ante cualquier falla
- **Corrección por IA**: Ollama + llama3.1:8b corrige errores OCR en contexto histórico en español
- **Operación offline**: una vez descargados los modelos (~18 GB), no se requiere internet
- **Alta resiliencia**: checkpointing por página — sobrevive apagados, suspensión y reinicios
- **Monitoreo en tiempo real**: dashboard web con WebSocket
- **Soporte AMD ROCm**: optimizado para RX 5090 (32 GB VRAM)

---

## Requisitos de Hardware

| Componente | Mínimo | Recomendado |
|---|---|---|
| GPU | AMD con ROCm (8 GB VRAM) | AMD RX 5090 (32 GB VRAM) |
| RAM | 16 GB | 32 GB |
| Almacenamiento | 50 GB libres | 200 GB+ SSD |
| OS | Ubuntu 22.04 / 24.04 | Ubuntu 22.04 LTS |

---

## Despliegue paso a paso (manual)

> Si usaste `bootstrap.sh` arriba, puedes saltarte toda esta sección.

### Paso 1 — Instalar driver AMD ROCm

> Ejecutar en la máquina destino con internet activo.

```bash
# Instalar dependencias del sistema
sudo apt-get update
sudo apt-get install -y wget gnupg2 curl

# Descargar e instalar el instalador de ROCm
wget https://repo.radeon.com/amdgpu-install/6.2/ubuntu/jammy/amdgpu-install_6.2.60200-1_all.deb
sudo apt-get install -y ./amdgpu-install_6.2.60200-1_all.deb

# Instalar ROCm con soporte OpenCL y HIP
sudo amdgpu-install -y --usecase=rocm,opencl,hip

# Añadir tu usuario a los grupos necesarios
sudo usermod -aG render,video $USER

# Reiniciar para que el driver tome efecto
sudo reboot
```

> **Verificación tras reiniciar:**
> ```bash
> rocminfo | grep -A2 "Agent 2"
> # Debe mostrar tu GPU (ej: gfx1200 para RX 5090)
> ```

---

### Paso 2 — Instalar Docker y Docker Compose

```bash
# Instalar Docker
curl -fsSL https://get.docker.com | sudo sh

# Añadir usuario al grupo docker
sudo usermod -aG docker $USER

# Aplicar cambio de grupo (o hacer logout/login)
newgrp docker

# Verificar instalación
docker --version
docker compose version
```

> Docker Compose v2 ya viene incluido con Docker >= 24. Si tienes una versión anterior:
> ```bash
> sudo apt-get install -y docker-compose-plugin
> ```

---

### Paso 3 — Instalar ROCm en Docker (plugin GPU)

```bash
# Instalar el plugin de GPU para Docker (necesario para pasar la GPU al container)
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -s -L https://repo.radeon.com/rocm/rocm.gpg.key | sudo apt-key add -
echo "deb [arch=amd64] https://repo.radeon.com/rocm/apt/6.2 $(lsb_release -cs) main" | sudo tee /etc/apt/sources.list.d/rocm.list
sudo apt-get update

# Verificar que Docker ve la GPU
docker run --rm --device=/dev/kfd --device=/dev/dri \
  --group-add video --group-add render \
  rocm/pytorch:rocm6.2_ubuntu22.04_py3.10_pytorch_2.3.0 \
  python3 -c "import torch; print('GPU disponible:', torch.cuda.is_available())"
# Debe imprimir: GPU disponible: True
```

---

### Paso 4 — Clonar el repositorio

```bash
git clone https://github.com/JoseJavierZavalaPorta/ocr-agent.git
cd ocr-agent
```

---

### Paso 5 — Configurar variables de entorno

```bash
cp .env.example .env
nano .env   # o usa tu editor favorito
```

Los parámetros más importantes a revisar:

```env
# === GPU AMD ===
# GFX version de tu GPU. Ejecuta: rocminfo | grep gfx
# RX 5090 (RDNA4)  → 12.0.0
# RX 7900 XTX      → 11.0.0
# RX 6900 XT       → 10.3.0
HSA_OVERRIDE_GFX_VERSION=12.0.0

# === Umbrales de calidad OCR ===
CONFIDENCE_THRESHOLD_PASS=0.80   # >= 80% = PASSED (verde)
CONFIDENCE_THRESHOLD_WARN=0.60   # 60-80% = WARNING (amarillo)
                                  # < 60%  = ERROR (rojo, revisar)

# === Modelo de corrección ===
OLLAMA_CORRECTION_MODEL=llama3.1:8b   # recomendado para español histórico
```

> **¿Cómo sé mi GFX version?**
> ```bash
> rocminfo | grep "Name:" | grep gfx
> # Ejemplo output: Name: gfx1200
> # → HSA_OVERRIDE_GFX_VERSION=12.0.0
> ```

---

### Paso 6 — Levantar el sistema

```bash
./setup.sh
```

El script hace automáticamente:

1. Verifica Docker, Docker Compose y ROCm
2. Detecta la versión GFX de tu GPU y actualiza `.env`
3. Crea los directorios de datos en `./volumes/`
4. Construye las imágenes Docker
5. Levanta los 5 servicios (backend, worker, frontend, redis, ollama)
6. Espera los health checks de cada servicio
7. **Pregunta si descargar los modelos ahora** (requiere internet en este paso)

> El script detecta si no hay GPU ROCm y levanta en modo CPU para poder verificar que la infraestructura funciona, aunque el OCR no usará GPU en ese modo.

---

### Paso 7 — Descargar modelos (única vez con internet)

Si respondiste **Sí** en el paso anterior, este paso ya se ejecutó. Si no, o si quieres hacerlo manualmente:

```bash
docker compose exec worker bash /app/download_models.sh
```

Esto descarga y cachea en `./volumes/models/`:

| Modelo | Motor | Tamaño aprox. |
|---|---|---|
| Surya OCR (detección + reconocimiento) | Surya | ~3 GB |
| Surya Layout (tablas, columnas) | Surya | ~2 GB |
| TrOCR large handwritten | TrOCR | ~2 GB |
| llama3.1:8b (q4_K_M) | Ollama | ~5 GB |
| MinerU models | MinerU | ~4 GB |
| Tesseract español | Tesseract | ~50 MB |

> **Total aproximado: 16–18 GB**. Una vez descargado, el directorio `./volumes/models/` puede llevarse a otra máquina (copiarlo) para no descargar de nuevo.

---

### Paso 8 — Verificar que todo funciona

```bash
# Ver estado de los servicios
docker compose ps

# Logs del worker (donde corre el OCR)
docker compose logs -f worker

# Ver si Ollama cargó el modelo
curl http://localhost:11434/api/tags
```

Abrir el navegador en: **http://localhost:3000**

Deberías ver el dashboard con:
- Header verde "GPU online" con el nombre de tu GPU
- "Ollama online" en verde
- Cola vacía lista para recibir documentos

---

## Uso

### Procesar un PDF

**Opción A — Carpeta automática (recomendado)**

Copia o mueve cualquier PDF a la carpeta de entrada:

```bash
cp mi_documento.pdf ./volumes/input/
```

El sistema lo detecta automáticamente en segundos y comienza a procesarlo. El resultado aparece en `./volumes/output/mi_documento.md`.

**Opción B — Subida desde el navegador**

En el dashboard (http://localhost:3000), arrastra el PDF al panel izquierdo o haz clic en el área de carga.

**Opción C — Rutas de red (NFS/SMB)**

Para vigilar una carpeta de red montada, añadir la ruta desde el dashboard en **Configurar → Carpetas vigiladas → Añadir**, o via API:

```bash
curl -X POST "http://localhost:8000/api/watcher/add-path?path=/mnt/mi-servidor/documentos"
```

---

### Monitorear el procesamiento

El dashboard en **http://localhost:3000** muestra en tiempo real:

- **Activos**: jobs en progreso con etapa actual (Preprocesando / OCR / Corrigiendo / Validando) y porcentaje por página
- **Completados**: jobs terminados con confianza promedio y enlace al Markdown generado
- **Errores**: páginas o documentos que necesitan revisión manual con descripción del problema
- **Configurar**: carpetas vigiladas, parámetros del pipeline, rutas de datos

---

### Archivos de salida

```
./volumes/
├── input/          ← PDFs de entrada (el watcher vigila esta carpeta)
├── output/         ← Markdowns generados (nombre_documento.md)
├── originals/      ← Copia del PDF original (nunca se modifica ni elimina)
├── db/             ← Base de datos SQLite con estado de todos los jobs
└── models/         ← Cache de modelos descargados (conservar para offline)
```

> El PDF original **nunca se elimina ni modifica**. Siempre queda una copia en `originals/`.

---

## Gestión del servicio

### Comandos útiles

```bash
# Ver todos los servicios
docker compose ps

# Logs en tiempo real
docker compose logs -f           # todos los servicios
docker compose logs -f worker    # solo el worker OCR
docker compose logs -f ollama    # solo Ollama

# Reiniciar un servicio específico
docker compose restart worker

# Parar todo (los datos en volumes/ se conservan)
docker compose down

# Parar y eliminar volumes (¡BORRA TODOS LOS DATOS!)
docker compose down -v

# Actualizar código del repositorio
git pull && docker compose build --parallel && docker compose up -d
```

### Comportamiento ante apagados

El sistema está diseñado para recuperarse automáticamente:

- Al reiniciar `docker compose up -d`, el worker detecta cualquier job que estaba en proceso y lo **reanuda desde la última página completada**
- Los modelos cargados en GPU se re-cargan automáticamente al arrancar el worker (warm-up)
- Redis persiste la cola con AOF (Append Only File) en `./volumes/redis/`
- El estado completo está en SQLite en `./volumes/db/ocr.db`

---

## Estructura del proyecto

```
ocr-agent/
├── setup.sh                        ← Setup desatendido (punto de entrada)
├── download_models.sh              ← Descarga de modelos (ejecutar con internet)
├── docker-compose.yml              ← Orquestación de servicios
├── .env.example                    ← Plantilla de configuración
├── backend/
│   ├── Dockerfile                  ← Imagen base: rocm/pytorch
│   ├── requirements.txt
│   ├── celery_worker.py            ← Definición de Celery + warm-up GPU
│   └── app/
│       ├── main.py                 ← FastAPI + lifespan (watcher + Redis listener)
│       ├── config.py               ← Settings desde .env
│       ├── database.py             ← SQLAlchemy + SQLite (WAL mode)
│       ├── models/job.py           ← ORM: Job, Page (estados, scores)
│       ├── pipeline/
│       │   ├── preprocessor.py     ← PDF → imágenes + deskew/denoise/CLAHE/Sauvola
│       │   ├── classifier.py       ← Routing agent: analiza imagen → elige motor
│       │   ├── ocr_engine.py       ← Surya, TrOCR, MinerU, Tesseract
│       │   ├── corrector.py        ← Corrección LLM vía Ollama (español histórico)
│       │   ├── validator.py        ← Score compuesto de calidad
│       │   └── pipeline.py         ← Orquestador con checkpointing por página
│       ├── services/
│       │   ├── file_watcher.py     ← Watchdog: detecta PDFs en carpetas
│       │   ├── job_manager.py      ← CRUD + recuperación de jobs interrumpidos
│       │   └── model_loader.py     ← Singleton: modelos cargados una sola vez en GPU
│       ├── tasks/ocr_tasks.py      ← Celery tasks (acks_late, retry, checkpointing)
│       └── api/
│           ├── routes.py           ← REST API (/jobs, /watcher, /config, /status)
│           └── websocket.py        ← WS manager + Redis pub/sub bridge
└── frontend/
    └── src/
        ├── components/
        │   ├── Dashboard.tsx       ← Layout principal + drag & drop
        │   ├── JobCard.tsx         ← Tarjeta de job con progreso
        │   ├── JobDetail.tsx       ← Detalle por página con scores
        │   ├── ConfigPanel.tsx     ← Gestión de rutas y parámetros
        │   └── Header.tsx          ← Estado GPU + Ollama en tiempo real
        ├── hooks/
        │   ├── useWebSocket.ts     ← Conexión WS con reconexión automática
        │   └── useJobs.ts          ← React Query para jobs
        └── services/api.ts         ← Cliente HTTP para la API
```

---

## Solución de problemas

### GPU no detectada en el container

```bash
# Verificar que los devices existen
ls -la /dev/kfd /dev/dri

# Verificar grupos del usuario
groups $USER
# Debe incluir: render video

# Reiniciar servicio Docker si es necesario
sudo systemctl restart docker
```

### Ollama no carga el modelo

```bash
# Ver logs de Ollama
docker compose logs ollama

# Verificar modelos descargados
curl http://localhost:11434/api/tags

# Re-descargar el modelo manualmente
docker compose exec ollama ollama pull llama3.1:8b
```

### Error "HSA_OVERRIDE_GFX_VERSION"

Para GPUs RDNA4 (RX 5090) que aún no están soportadas nativamente por ROCm:

```bash
# En .env, ajustar a la versión correcta
HSA_OVERRIDE_GFX_VERSION=12.0.0

# Reiniciar worker y ollama
docker compose restart worker ollama
```

### Job queda en estado QUEUED sin procesar

```bash
# Verificar que el worker esté corriendo
docker compose ps worker

# Ver logs del worker
docker compose logs --tail=50 worker

# Reiniciar worker (retoma jobs automáticamente)
docker compose restart worker
```

### Ver el estado de la base de datos

```bash
# Conectarse a SQLite directamente
docker compose exec backend python3 -c "
from app.database import SessionLocal
from app.models.job import Job
db = SessionLocal()
jobs = db.query(Job).order_by(Job.created_at.desc()).limit(10).all()
for j in jobs:
    print(f'{j.filename:40} | {j.status.value:15} | {j.processed_pages}/{j.total_pages} págs | conf={j.avg_confidence:.0%}')
"
```

---

## API REST

Documentación interactiva disponible en: **http://localhost:8000/docs**

| Método | Endpoint | Descripción |
|---|---|---|
| GET | `/api/jobs` | Lista todos los jobs |
| GET | `/api/jobs/{id}` | Detalle de un job con páginas |
| POST | `/api/jobs/{id}/retry` | Reintenta un job con error |
| DELETE | `/api/jobs/{id}` | Elimina un job (no el original) |
| POST | `/api/jobs/upload` | Sube un PDF directamente |
| GET | `/api/status` | Estado GPU, Ollama y cola |
| GET | `/api/watcher` | Carpetas vigiladas activas |
| POST | `/api/watcher/add-path` | Añade ruta a vigilar |
| GET | `/api/config` | Configuración actual del pipeline |
| WS | `/ws` | WebSocket de eventos en tiempo real |

---

## Licencia

MIT

# OCR Agent

Sistema de procesamiento OCR offline para documentos históricos escaneados. Convierte PDFs escaneados a Markdown con corrección contextual por IA. Opera completamente sin internet después de la instalación inicial.

---

## Instalación desde cero (PC formateada)

> Requisito previo: Ubuntu 22.04 / 24.04 instalado. Nada más.

```bash
sudo apt-get install -y git curl && \
git clone https://github.com/JoseJavierZavalaPorta/ocr-agent.git && \
cd ocr-agent && \
./install.sh
```

Ese único bloque hace todo:

| Paso | Qué instala |
|---|---|
| 1 | Docker Engine + Docker Compose |
| 2 | AMD ROCm (detecta si hay GPU AMD, sino omite) |
| 3 | Estructura de directorios |
| 4 | Imágenes Docker (ubuntu:22.04 + PyTorch CPU) |
| 5 | Modelos Ollama: `qwen2.5:32b` (~19 GB) + `minicpm-v` (~5.5 GB) |
| 6 | Modelos HuggingFace: Surya + TrOCR + MinerU (~8 GB) |

**Tiempo estimado:** 30-90 min según velocidad de internet (~35 GB de descarga).

> **GPU AMD**: si `/dev/kfd` existe en el host, el script lo detecta y no reinstala drivers. Ollama usará la GPU automáticamente.

> **PC destino sin acceso a internet**: usa el flujo de [offline/README.md](offline/README.md) — arma el paquete en una máquina con red y despliégalo desde un USB, sin `install.sh` ni descargas en destino.

---

## Uso

### Iniciar el sistema

```bash
# PDFs en ./volumes/input/ (carpeta por defecto)
./start.sh

# PDFs en una ruta personalizada
./start.sh /ruta/a/tus/documentos
```

`start.sh` limpia la base de datos, levanta todos los servicios y encola automáticamente todos los PDFs del directorio indicado.

### Monitorear

```bash
./status.sh      # estado de todos los jobs en tiempo real
./logs.sh        # logs del worker OCR
```

API interactiva: **http://localhost:8000/docs**

### Resultados

Los archivos se generan en `volumes/output/`:

- `nombre_documento.md` — texto extraído en Markdown
- `nombre_documento_reporte.txt` — confianza por página, motor usado, caracteres extraídos

### Recuperar tras apagado inesperado

```bash
./resume.sh [/ruta/a/tus/documentos]
```

`resume.sh` **no borra la base de datos** — conserva el progreso y re-encola solo los jobs interrumpidos.

---

## Requisitos de hardware

| Componente | Mínimo |
|---|---|
| OS | Ubuntu 22.04 / 24.04 |
| RAM | 32 GB (LLM corre en CPU) |
| Almacenamiento | 100 GB libres |
| GPU | AMD discreta (opcional — sin GPU todo corre en CPU, más lento) |

---

## Arquitectura

```
PDFs → API → Cola Redis → Worker → Markdown + Reporte TXT
                              ↓
               ┌──────────────────────────────┐
               │  Pipeline por página:        │
               │  1. Preprocesamiento (200DPI)│
               │  2. Clasificación doc_type   │
               │  3. OCR (motor óptimo)       │
               │  4. Corrección LLM           │
               │  5. Validación + score       │
               └──────────────────────────────┘
```

**Motores OCR** (el pipeline elige automáticamente):

| Motor | Cuándo se usa |
|---|---|
| **MinerU** | Tablas, layout complejo, texto impreso estructurado |
| **VisionEngine** (minicpm-v) | Manuscritos y formularios con poco texto (<80 palabras) |
| **TrOCR** | Manuscritos puros sin estructura de layout |
| **Surya** | Páginas impresas sin tablas |
| **Tesseract** | Fallback final si todos los anteriores fallan |

**Modelos:**

| Modelo | Uso | Tamaño |
|---|---|---|
| `qwen2.5:32b` | Corrección LLM contextual en español | ~19 GB |
| `minicpm-v` | OCR visual para manuscritos (VisionEngine) | ~5.5 GB |
| Surya OCR | Detección + reconocimiento de texto impreso | ~3 GB |
| TrOCR large | Manuscritos a mano | ~1.8 GB |
| MinerU / PDF-Extract-Kit | Layout, tablas, fórmulas | ~5 GB |

---

## Configuración

### Prompts y parámetros del pipeline

Editar **[backend/app/pipeline/constants.py](backend/app/pipeline/constants.py)** — archivo centralizado con todos los prompts y constantes:

```python
# Prompt para documentos impresos
PROMPT_CORRECTION_PRINTED = "..."

# Prompt para manuscritos (recetas, cartas, actas)
PROMPT_CORRECTION_HANDWRITING = "..."

# Prompt que ve el modelo de visión (minicpm-v) al analizar la imagen
PROMPT_VISION_OCR = "..."

# Umbral de palabras para activar VisionEngine en páginas mixtas
VISION_WORD_THRESHOLD = 80

# Temperatura del LLM de corrección
LLM_TEMPERATURE = 0.1
```

### Variables de entorno

Editar `.env` (creado desde `.env.example` en la instalación):

```env
# Umbrales de calidad
CONFIDENCE_THRESHOLD_PASS=0.80
CONFIDENCE_THRESHOLD_WARN=0.60

# Modelos Ollama
OLLAMA_CORRECTION_MODEL=qwen2.5:32b
OLLAMA_VISION_MODEL=minicpm-v

# AMD ROCm — consultar con: rocminfo | grep gfx
# RX 6000 → 10.3.0 | RX 7000 → 11.0.0 | RX 9000 → 12.0.0
HSA_OVERRIDE_GFX_VERSION=11.0.0

# Workers paralelos (aumentar si hay más RAM disponible)
CELERY_CONCURRENCY=2
```

---

## Estructura del proyecto

```
ocr-agent/
├── install.sh              ← Instalación desde cero (único comando necesario)
├── start.sh                ← Inicia el sistema (argumento: ruta de input)
├── resume.sh               ← Recuperación post-apagado sin perder progreso
├── logs.sh                 ← Logs en tiempo real del worker
├── status.sh               ← Estado de los jobs
├── download_models.sh      ← Re-descarga modelos HuggingFace (uso manual)
├── docker-compose.yml
├── .env.example            ← Plantilla de configuración (editar y renombrar a .env)
├── samples/                ← Documentos de prueba históricos
└── backend/
    ├── Dockerfile
    ├── requirements.txt
    └── app/
        ├── config.py
        └── pipeline/
            ├── constants.py    ← ★ PROMPTS Y PARÁMETROS (editar aquí)
            ├── classifier.py   ← Detecta tipo de página y elige motor OCR
            ├── ocr_engine.py   ← Implementación de cada motor OCR
            ├── corrector.py    ← Corrección LLM vía Ollama
            ├── validator.py    ← Score de calidad
            └── pipeline.py     ← Orquestador con checkpointing por página
```

---

## Documentos de prueba

En `samples/` hay documentos históricos para probar el sistema:

| Archivo | Tipo | Motor activado |
|---|---|---|
| `muestra_acta_1942.pdf` | Manuscrito | VisionEngine |
| `muestra_carta_1923.pdf` | Manuscrito | VisionEngine |
| `muestra_padron_1955.pdf` | Mixto (tablas) | MinerU |
| `DOCUMENTOPRUEBA1.pdf` | Manuscrito | VisionEngine |
| `DOCUMENTOPRUEBA2.pdf` | Mixto (receta) | VisionEngine |
| `documentoPrueba.pdf` | Censo 31 págs | MinerU + VisionEngine |

```bash
./start.sh ./samples
```

---

## API

| Método | Endpoint | Descripción |
|---|---|---|
| `GET` | `/api/jobs` | Lista todos los jobs y su estado |
| `GET` | `/api/jobs/{id}` | Detalle con páginas, scores y motores |
| `POST` | `/api/jobs/upload` | Sube un PDF directamente |
| `POST` | `/api/jobs/resume` | Re-encola jobs interrumpidos |
| `GET` | `/health` | Estado del sistema |

---

## Casos frecuentes

### El sistema se apagó a mitad del procesamiento

```bash
./resume.sh
```

Detecta automáticamente los jobs interrumpidos y los re-encola desde la última página completada. No reprocesa lo que ya estaba hecho.

### Tengo miles de documentos a procesar

```bash
# Primera vez — inicializa y encola todo
./start.sh /ruta/a/documentos

# Si se cae — reanuda sin reprocesar
./resume.sh /ruta/a/documentos
```

No usar `start.sh` para reanudar: limpia la base de datos y reprocesaría todo desde cero.
Para aumentar velocidad, subir `CELERY_CONCURRENCY` en `.env` (requiere más RAM).

### Quiero ajustar cómo corrige el LLM los manuscritos

Editar `backend/app/pipeline/constants.py`:

```python
PROMPT_CORRECTION_HANDWRITING = """..."""
```

Luego reconstruir la imagen:

```bash
docker compose build worker && docker compose up -d worker
```

### Quiero ajustar qué instrucción recibe el modelo de visión

Editar `backend/app/pipeline/constants.py`:

```python
PROMPT_VISION_OCR = "..."
```

Mismo proceso: `docker compose build worker && docker compose up -d worker`.

### El sistema detecta manuscrito donde hay texto impreso (o viceversa)

Ajustar `HANDWRITING_THRESHOLD` en `.env`. Valor más alto = más exigente para clasificar como manuscrito.

```env
HANDWRITING_THRESHOLD=0.85   # default
```

### Quiero procesar un nuevo tipo de documento (DNIs, contratos, etc.)

Actualizar los prompts en `constants.py` para incluir el vocabulario del nuevo dominio:

```python
PROMPT_CORRECTION_HANDWRITING = """...
Tienes conocimiento de:
- Formato DNI: número, apellidos, nombres, fecha nacimiento, vencimiento
..."""
```

### Agrego una GPU AMD discreta

Ollama la detecta automáticamente al arrancar — no se necesita cambiar nada. Los modelos `qwen2.5:32b` y `minicpm-v` se cargarán en VRAM y la inferencia será significativamente más rápida.

El worker OCR (Surya, TrOCR, MinerU) seguirá en CPU a menos que se cambie el Dockerfile a PyTorch ROCm.

Verificar que la GPU se detecta:

```bash
docker logs ocr-ollama | grep "inference compute"
```

### Quiero actualizar el código después de un `git pull`

```bash
git pull
docker compose build
docker compose up -d
```

### Re-descargar modelos HuggingFace (Surya, TrOCR, MinerU)

```bash
docker compose run --rm --no-deps \
  -e HF_HUB_OFFLINE=0 -e TRANSFORMERS_OFFLINE=0 \
  worker bash /app/download_models.sh
```

### Ver el reporte de calidad de un documento

```bash
cat volumes/output/nombre_documento_reporte.txt
```

Muestra confianza por página, motor OCR utilizado, caracteres extraídos y porcentaje de corrección del LLM.

---

## Resiliencia

| Mecanismo | Qué protege |
|---|---|
| Checkpointing por página en SQLite | Reanuda desde la última página completada |
| Celery `acks_late` | Si el worker muere, la tarea vuelve a la cola automáticamente |
| Redis AOF | La cola de tareas persiste en disco ante apagados |
| `restart: unless-stopped` | Los containers se levantan solos al reiniciar el SO |
| `resume.sh` | Re-encola jobs interrumpidos con un solo comando |

---

## Licencia

MIT

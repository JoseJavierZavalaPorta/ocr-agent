# OCR Agent

Sistema de procesamiento OCR offline para documentos históricos escaneados. Convierte PDFs escaneados a Markdown con corrección contextual por IA. Opera completamente sin internet después de la instalación inicial.

---

## Requisitos

| Componente | Mínimo |
|---|---|
| OS | Ubuntu 22.04 / 24.04 |
| RAM | 32 GB (los modelos LLM corren en CPU) |
| Almacenamiento | 100 GB libres |
| GPU | AMD (opcional — Ollama usa ROCm si está disponible, si no corre en CPU) |

---

## Instalación

> Solo necesitas internet en este paso. Una vez instalado, el sistema opera 100% offline.

```bash
git clone https://github.com/JoseJavierZavalaPorta/ocr-agent.git
cd ocr-agent
chmod +x install.sh
./install.sh
```

`install.sh` hace todo automáticamente:

1. Instala Docker Engine + Docker Compose
2. Detecta y configura AMD ROCm (si hay GPU AMD disponible)
3. Crea la estructura de directorios
4. Construye las imágenes Docker
5. Descarga modelos Ollama: `qwen2.5:32b` (~19 GB) y `minicpm-v` (~5.5 GB)
6. Descarga modelos HuggingFace: Surya, TrOCR, MinerU (~8 GB)

> **GPU AMD**: si `/dev/kfd` existe en el host, el script lo detecta y no reinstala drivers. Si la máquina no tiene GPU AMD, Ollama corre en CPU (más lento pero funcional).

---

## Uso

### Iniciar el sistema

```bash
# Con la carpeta de input por defecto (./volumes/input/)
./start.sh

# Con una ruta personalizada
./start.sh /ruta/a/tus/documentos
```

`start.sh` limpia la base de datos, levanta todos los servicios y encola automáticamente todos los PDFs del directorio indicado.

### Monitorear el progreso

```bash
./status.sh        # muestra estado de todos los jobs
./logs.sh          # logs en tiempo real del worker
```

O via API:
```bash
curl http://localhost:8000/api/jobs
```

### Recuperar tras un apagado inesperado

```bash
./resume.sh [/ruta/a/tus/documentos]
```

`resume.sh` **no borra la base de datos** — conserva el progreso ya completado y re-encola solo los jobs que quedaron interrumpidos.

---

## Arquitectura

```
PDFs → API → Cola Redis → Worker → Markdown
                              ↓
               ┌──────────────────────────┐
               │  Pipeline por página:    │
               │  1. Preprocesamiento     │
               │  2. Clasificación        │
               │  3. OCR (motor óptimo)   │
               │  4. Corrección LLM       │
               │  5. Validación           │
               └──────────────────────────┘
```

**Motores OCR** (el pipeline elige automáticamente según el tipo de página):

| Motor | Cuándo se usa |
|---|---|
| **MinerU** | Páginas con tablas, layout complejo, texto impreso |
| **VisionEngine** (minicpm-v) | Manuscritos y formularios escaneados con poco texto |
| **TrOCR** | Manuscritos puros sin layout estructurado |
| **Surya** | Páginas impresas sin tablas |
| **Tesseract** | Fallback final |

**Modelos:**

| Modelo | Uso | Tamaño |
|---|---|---|
| `qwen2.5:32b` | Corrección LLM contextual en español | ~19 GB |
| `minicpm-v` | OCR visual para manuscritos (VisionEngine) | ~5.5 GB |
| Surya OCR | Detección + reconocimiento de texto | ~3 GB |
| TrOCR large | Manuscritos a mano | ~1.8 GB |
| MinerU / PDF-Extract-Kit | Layout, tablas, fórmulas | ~5 GB |

---

## Estructura del proyecto

```
ocr-agent/
├── install.sh              ← Instalación completa desde cero
├── start.sh                ← Inicia el sistema (acepta ruta de input como argumento)
├── resume.sh               ← Recuperación post-apagado sin perder progreso
├── logs.sh                 ← Logs en tiempo real
├── status.sh               ← Estado de los jobs
├── download_models.sh      ← Re-descarga modelos HuggingFace (uso manual)
├── docker-compose.yml
├── .env.example            ← Plantilla de configuración
├── samples/                ← Documentos de prueba
├── backend/
│   ├── Dockerfile          ← ubuntu:22.04 + PyTorch CPU
│   ├── requirements.txt
│   └── app/
│       ├── config.py
│       ├── pipeline/
│       │   ├── classifier.py   ← Analiza la página y elige el motor OCR
│       │   ├── ocr_engine.py   ← Surya, TrOCR, MinerU, Tesseract, VisionEngine
│       │   ├── corrector.py    ← Corrección LLM vía Ollama
│       │   ├── validator.py    ← Score de calidad
│       │   └── pipeline.py     ← Orquestador con checkpointing por página
│       ├── services/
│       │   ├── job_manager.py  ← CRUD + recuperación de jobs interrumpidos
│       │   └── model_loader.py ← Singleton: modelos en memoria
│       └── api/routes.py       ← REST API
└── volumes/
    ├── input/      ← PDFs de entrada
    ├── output/     ← Markdowns generados
    ├── originals/  ← Copia del PDF original (nunca se modifica)
    ├── db/         ← SQLite con estado de jobs
    └── models/     ← Cache de modelos (conservar para modo offline)
```

---

## Configuración

Editar `.env` (creado automáticamente desde `.env.example` en la instalación):

```env
# Umbrales de calidad
CONFIDENCE_THRESHOLD_PASS=0.80   # >= 80% = aprobado
CONFIDENCE_THRESHOLD_WARN=0.60   # 60-80% = advertencia

# Modelos
OLLAMA_CORRECTION_MODEL=qwen2.5:32b
OLLAMA_VISION_MODEL=minicpm-v

# AMD ROCm (ajustar según GPU)
# Consultar con: rocminfo | grep gfx
# RX 6000 series → 10.3.0 | RX 7000 series → 11.0.0 | RX 9000 series → 12.0.0
HSA_OVERRIDE_GFX_VERSION=11.0.0

# Worker
CELERY_CONCURRENCY=2
```

---

## API

Documentación interactiva: **http://localhost:8000/docs**

| Método | Endpoint | Descripción |
|---|---|---|
| `GET` | `/api/jobs` | Lista todos los jobs |
| `GET` | `/api/jobs/{id}` | Detalle con páginas y scores |
| `POST` | `/api/jobs/upload` | Sube un PDF |
| `POST` | `/api/jobs/resume` | Re-encola jobs interrumpidos |
| `GET` | `/health` | Estado del sistema |

---

## Documentos de prueba

En la carpeta `samples/` hay documentos históricos para probar el sistema:

| Archivo | Tipo | Descripción |
|---|---|---|
| `muestra_acta_1942.pdf` | Manuscrito | Acta oficial manuscrita, 1942 |
| `muestra_carta_1923.pdf` | Manuscrito | Carta personal manuscrita, 1923 |
| `muestra_padron_1955.pdf` | Mixto | Padrón electoral con tablas, 1955 |
| `DOCUMENTOPRUEBA1.pdf` | Impreso | Documento impreso moderno |
| `DOCUMENTOPRUEBA2.pdf` | Manuscrito | Receta médica manuscrita |
| `documentoPrueba.pdf` | Mixto | Censo histórico, 31 páginas con tablas |

Para procesarlos:

```bash
./start.sh ./samples
```

---

## Resiliencia

El sistema está diseñado para sobrevivir apagados en cualquier momento:

- **Checkpointing por página**: cada página procesada se guarda inmediatamente en SQLite
- **Celery `acks_late`**: si el worker muere, la tarea vuelve a la cola
- **Redis AOF**: la cola persiste en disco
- **`resume.sh`**: detecta jobs interrumpidos y los re-encola sin reprocesar páginas ya completadas

---

## Licencia

MIT

"""
Entrypoint de Celery. Importado por el worker y por las tasks.
"""

import os

from celery import Celery
from app.config import get_settings
from app.services.model_loader import get_model_loader
from loguru import logger

settings = get_settings()

celery_app = Celery(
    "ocr_agent",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.tasks.ocr_tasks", "app.tasks.summary_tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    # Evitar pérdida de tareas en restart
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # Un prefetch = no tomar nueva tarea hasta terminar la actual (GPU bound)
    worker_prefetch_multiplier=1,
    # Persistencia de resultados
    result_expires=86400 * 7,
    # Colas separadas: OCR (pesado, CPU/RAM) vs resumen (solo llama a Ollama)
    task_routes={
        "app.tasks.ocr_tasks.process_job_task": {"queue": "ocr"},
        "app.tasks.summary_tasks.summarize_job_task": {"queue": "resumen"},
    },
    # Limite de tiempo por tarea: 2 horas máximo
    task_time_limit=7200,
    task_soft_time_limit=6600,
)


@celery_app.on_after_configure.connect
def warm_up_models(sender, **kwargs):
    """
    Carga los modelos OCR pesados (Surya/TrOCR/MinerU) al arrancar el worker.
    El worker de resumen (SKIP_MODEL_WARMUP=1) no los necesita — solo habla
    por HTTP con Ollama — así que se lo salta para no gastar RAM de más.
    """
    if os.environ.get("SKIP_MODEL_WARMUP") == "1":
        logger.info("SKIP_MODEL_WARMUP=1 — worker de resumen, no carga modelos OCR")
        return
    try:
        logger.info("Warm-up: cargando modelos OCR en GPU...")
        loader = get_model_loader()
        loader.load_all()
        logger.info("Modelos OCR listos para procesar")
    except Exception as e:
        logger.error(f"Error en warm-up de modelos: {e}")

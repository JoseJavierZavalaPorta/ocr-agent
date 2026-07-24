"""
Tareas Celery para procesamiento OCR en background.
El worker mantiene los modelos cargados entre tareas (warm).
"""

import asyncio
from loguru import logger

from celery_worker import celery_app
from app.database import SessionLocal
from app.models.job import JobStatus
from app.services.job_manager import job_manager
from app.services.model_loader import get_model_loader
from app.pipeline.pipeline import OCRPipeline
from app.api.websocket import broadcast_sync
from app.tasks.summary_tasks import summarize_job_task


@celery_app.task(
    bind=True,
    name="ocr.process_job",
    queue="ocr",
    max_retries=3,
    default_retry_delay=10,
    acks_late=True,        # El mensaje se confirma solo tras completar (evita pérdida)
    reject_on_worker_lost=True,
)
def process_job_task(self, job_id: str):
    """
    Tarea principal de procesamiento. Se puede interrumpir y reanudar
    porque el estado se guarda en SQLite por página.
    """
    logger.info(f"Iniciando tarea OCR para job {job_id}")

    db = SessionLocal()
    try:
        job = job_manager.get_job(db, job_id)
        if not job:
            logger.error(f"Job {job_id} no encontrado en BD")
            return

        if job.status == JobStatus.COMPLETED:
            logger.info(f"Job {job_id} ya completado, saltando")
            return

        # Marcar como en progreso
        job.status = JobStatus.QUEUED
        job.celery_task_id = self.request.id
        db.commit()

        # Notificar al frontend via WebSocket
        broadcast_sync({"type": "job_started", "job_id": job_id})

        # Cargar modelos (singleton — ya cargados en worker warm start)
        model_loader = get_model_loader()
        pipeline = OCRPipeline(model_loader)

        def on_progress(data: dict):
            data["type"] = "job_progress"
            broadcast_sync(data)

        # Ejecutar pipeline async dentro del worker síncrono
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(pipeline.process_job(job, db, on_progress=on_progress))
        finally:
            loop.close()

        broadcast_sync({"type": "job_finished", "job_id": job_id, "status": job.status.value})
        logger.info(f"Tarea completada para job {job_id}")

        # Encolar resumen + clasificación (cola separada, no bloquea OCR)
        if job.status in (JobStatus.COMPLETED, JobStatus.PARTIAL):
            summarize_job_task.apply_async(args=[job_id], queue="resumen")

    except Exception as exc:
        logger.error(f"Error en tarea OCR job {job_id}: {exc}")
        broadcast_sync({"type": "job_error", "job_id": job_id, "error": str(exc)})

        try:
            job = job_manager.get_job(db, job_id)
            if job and job.status not in (JobStatus.COMPLETED, JobStatus.PARTIAL):
                job.status = JobStatus.ERROR
                job.error_message = str(exc)[:500]
                db.commit()
        except Exception:
            pass

        raise self.retry(exc=exc, countdown=30) if self.request.retries < self.max_retries else exc

    finally:
        db.close()

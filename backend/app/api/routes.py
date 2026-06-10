import os
from pathlib import Path
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, BackgroundTasks
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models.job import JobStatus
from app.schemas.job import (
    JobSchema, JobSummarySchema, ConfigSchema,
    WatcherStatusSchema, SystemStatusSchema,
)
from app.services.job_manager import job_manager
from app.tasks.ocr_tasks import process_job_task

settings = get_settings()
router = APIRouter()

# Referencia global al watcher (se inyecta desde main.py)
_watcher = None


def set_watcher(w):
    global _watcher
    _watcher = w


# ── Jobs ──────────────────────────────────────────────────────────────────────

@router.get("/jobs", response_model=list[JobSummarySchema])
def list_jobs(
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    js = JobStatus(status) if status else None
    return job_manager.list_jobs(db, status=js, limit=limit, offset=offset)


@router.get("/jobs/{job_id}", response_model=JobSchema)
def get_job(job_id: str, db: Session = Depends(get_db)):
    job = job_manager.get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job no encontrado")
    return job


@router.post("/jobs/{job_id}/retry", response_model=JobSummarySchema)
def retry_job(job_id: str, db: Session = Depends(get_db)):
    job = job_manager.retry_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job no encontrado")
    process_job_task.apply_async(args=[job_id], queue="ocr")
    return job


@router.delete("/jobs/{job_id}", status_code=204)
def delete_job(job_id: str, db: Session = Depends(get_db)):
    if not job_manager.delete_job(db, job_id):
        raise HTTPException(status_code=404, detail="Job no encontrado")


@router.post("/jobs/upload", response_model=JobSummarySchema)
async def upload_pdf(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Sube un PDF directamente desde el navegador y lo encola."""
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Solo se aceptan archivos PDF")

    input_dir = Path(settings.input_path)
    input_dir.mkdir(parents=True, exist_ok=True)
    dest = input_dir / file.filename

    # Evitar colisión
    counter = 1
    while dest.exists():
        stem = Path(file.filename).stem
        dest = input_dir / f"{stem}_{counter}.pdf"
        counter += 1

    content = await file.read()
    dest.write_bytes(content)

    job = job_manager.create_job(db, str(dest))
    process_job_task.apply_async(args=[job.id], queue="ocr")
    return job


# ── Watcher ───────────────────────────────────────────────────────────────────

@router.get("/watcher", response_model=WatcherStatusSchema)
def watcher_status():
    if _watcher is None:
        return WatcherStatusSchema(watching=False, paths=[], pending_files=0)
    pending = len(list(Path(settings.input_path).glob("*.pdf")))
    return WatcherStatusSchema(
        watching=_watcher.is_running,
        paths=_watcher.watched_paths,
        pending_files=pending,
    )


@router.post("/watcher/add-path")
def add_watch_path(path: str):
    if _watcher is None:
        raise HTTPException(status_code=503, detail="Watcher no inicializado")
    _watcher.watch(path)
    return {"watching": path}


# ── Configuración ─────────────────────────────────────────────────────────────

@router.get("/config", response_model=ConfigSchema)
def get_config():
    return ConfigSchema(
        input_path=settings.input_path,
        output_path=settings.output_path,
        originals_path=settings.originals_path,
        confidence_threshold_pass=settings.confidence_threshold_pass,
        confidence_threshold_warn=settings.confidence_threshold_warn,
        handwriting_threshold=settings.handwriting_threshold,
        layout_complexity_threshold=settings.layout_complexity_threshold,
        pdf_extraction_dpi=settings.pdf_extraction_dpi,
        surya_batch_size=settings.surya_batch_size,
        ollama_correction_model=settings.ollama_correction_model,
        celery_concurrency=settings.celery_concurrency,
    )


# ── Estado del sistema ────────────────────────────────────────────────────────

@router.get("/status", response_model=SystemStatusSchema)
async def system_status(db: Session = Depends(get_db)):
    gpu_available = False
    gpu_name = None
    vram_total = None
    vram_free = None

    try:
        import torch
        if torch.cuda.is_available():
            gpu_available = True
            gpu_name = torch.cuda.get_device_name(0)
            mem = torch.cuda.mem_get_info(0)
            vram_free = round(mem[0] / 1024**3, 1)
            vram_total = round(mem[1] / 1024**3, 1)
    except Exception:
        pass

    ollama_online = False
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"{settings.ollama_url}/api/tags")
            ollama_online = r.status_code == 200
    except Exception:
        pass

    active = db.query(
        __import__("app.models.job", fromlist=["Job"]).Job
    ).filter(
        __import__("app.models.job", fromlist=["Job"]).Job.status.in_([
            JobStatus.QUEUED, JobStatus.PREPROCESSING,
            JobStatus.OCR, JobStatus.CORRECTING, JobStatus.VALIDATING,
        ])
    ).count()

    return SystemStatusSchema(
        gpu_available=gpu_available,
        gpu_name=gpu_name,
        gpu_vram_total_gb=vram_total,
        gpu_vram_free_gb=vram_free,
        ollama_online=ollama_online,
        models_loaded=[],
        queue_size=0,
        active_jobs=active,
    )


@router.get("/health")
def health():
    return {"status": "ok"}

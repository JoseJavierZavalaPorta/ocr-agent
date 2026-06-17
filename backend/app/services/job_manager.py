import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session
from loguru import logger

from app.config import get_settings
from app.models.job import Job, Page, JobStatus, PageStatus
from app.database import SessionLocal

settings = get_settings()


def _utcnow():
    return datetime.now(timezone.utc)


class JobManager:

    def create_job(self, db: Session, file_path: str) -> Job:
        """Crea un nuevo job y mueve el archivo a originals/."""
        src = Path(file_path)
        if not src.exists():
            raise FileNotFoundError(f"Archivo no encontrado: {file_path}")

        # Mover a originals para no modificar el original.
        # Si el archivo ya está en originals (upload directo via API), no copiar.
        originals_dir = Path(settings.originals_path)
        originals_dir.mkdir(parents=True, exist_ok=True)

        if src.parent.resolve() == originals_dir.resolve():
            dest = src
            logger.info(f"Archivo ya en originals: {dest}")
        else:
            dest = originals_dir / src.name
            # Evitar colisión de nombres
            counter = 1
            while dest.exists():
                stem = src.stem
                dest = originals_dir / f"{stem}_{counter}{src.suffix}"
                counter += 1
            shutil.copy2(str(src), str(dest))
            logger.info(f"Archivo copiado a originals: {dest}")

        job = Job(
            filename=src.name,
            original_path=str(dest),
            file_size_bytes=os.path.getsize(str(dest)),
            status=JobStatus.PENDING,
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        logger.info(f"Job creado: {job.id} para {job.filename}")
        return job

    def get_job(self, db: Session, job_id: str) -> Optional[Job]:
        return db.query(Job).filter(Job.id == job_id).first()

    def list_jobs(
        self,
        db: Session,
        status: Optional[JobStatus] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Job]:
        q = db.query(Job)
        if status:
            q = q.filter(Job.status == status)
        return q.order_by(Job.created_at.desc()).offset(offset).limit(limit).all()

    def retry_job(self, db: Session, job_id: str) -> Optional[Job]:
        """Resetea páginas en error para permitir re-procesamiento."""
        job = self.get_job(db, job_id)
        if not job:
            return None

        # Resetear páginas con error
        for page in job.pages:
            if page.status == PageStatus.ERROR:
                page.status = PageStatus.PENDING
                page.error_message = None
                page.corrected_text = None
                page.raw_ocr_text = None

        job.status = JobStatus.PENDING
        job.error_message = None
        job.updated_at = _utcnow()
        db.commit()
        logger.info(f"Job {job_id} reseteado para reintento")
        return job

    def delete_job(self, db: Session, job_id: str) -> bool:
        """Elimina el job y su MD de salida (NO el original)."""
        job = self.get_job(db, job_id)
        if not job:
            return False

        if job.output_path and Path(job.output_path).exists():
            Path(job.output_path).unlink()

        db.delete(job)
        db.commit()
        logger.info(f"Job {job_id} eliminado")
        return True

    def recover_interrupted_jobs(self, db: Session) -> list[str]:
        """
        Al arrancar el worker, detecta jobs que estaban procesándose
        y los re-encola para reanudar desde el último checkpoint.
        """
        interrupted_statuses = [
            JobStatus.QUEUED,
            JobStatus.PREPROCESSING,
            JobStatus.OCR,
            JobStatus.CORRECTING,
            JobStatus.VALIDATING,
        ]
        jobs = db.query(Job).filter(Job.status.in_(interrupted_statuses)).all()

        recovered = []
        for job in jobs:
            job.status = JobStatus.QUEUED
            job.updated_at = _utcnow()
            recovered.append(job.id)
            logger.info(f"Job {job.id} ({job.filename}) recuperado para reanudar")

        if recovered:
            db.commit()
            logger.info(f"Recuperados {len(recovered)} jobs interrumpidos")

        return recovered


job_manager = JobManager()

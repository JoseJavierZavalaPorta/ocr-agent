"""
Tarea Celery de resumen ejecutivo + clasificación. Cola separada ("resumen"),
concurrencia baja — no compite por CPU/RAM con la cola de OCR. Se dispara
automáticamente al terminar cada job de OCR (ver ocr_tasks.py).
"""

import asyncio
from pathlib import Path

from loguru import logger

from celery_worker import celery_app
from app.database import SessionLocal
from app.models.job import JobStatus, SummaryStatus
from app.services.job_manager import job_manager
from app.services.categories import load_categories, CategoriesConfigError
from app.services.summarizer import DocumentSummarizer, SummarizerError
from app.services.excel_report import regenerate_excel
from app.config import get_settings

settings = get_settings()


def _write_summary_md(job_filename: str, resumen: str, top5: list[dict]) -> str:
    stem = Path(job_filename).stem
    output_dir = Path(settings.output_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{stem}_resumen.md"

    lines = [f"# Resumen ejecutivo — {job_filename}\n", resumen.strip(), "\n\n## Clasificación (top 5)\n"]
    for rank, item in enumerate(top5, start=1):
        lines.append(
            f"{rank}. **{item['categoria']}** (score: {item['score']:.2f}) — {item['justificacion']}"
        )

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)


@celery_app.task(
    bind=True,
    name="resumen.summarize_job",
    queue="resumen",
    max_retries=3,
    default_retry_delay=15,
    acks_late=True,
    reject_on_worker_lost=True,
)
def summarize_job_task(self, job_id: str):
    logger.info(f"Iniciando resumen/clasificación para job {job_id}")

    db = SessionLocal()
    try:
        job = job_manager.get_job(db, job_id)
        if not job:
            logger.error(f"Job {job_id} no encontrado en BD (resumen)")
            return

        if job.summary_status == SummaryStatus.COMPLETED:
            logger.info(f"Job {job_id} ya tiene resumen, saltando")
            return

        if not job.output_path or not Path(job.output_path).exists():
            job.summary_status = SummaryStatus.ERROR
            job.summary_error = f"No existe el .md de salida para resumir: {job.output_path}"
            db.commit()
            logger.error(job.summary_error)
            return

        job.summary_status = SummaryStatus.PROCESSING
        db.commit()

        try:
            categorias = load_categories()
        except CategoriesConfigError as e:
            job.summary_status = SummaryStatus.ERROR
            job.summary_error = str(e)
            db.commit()
            logger.error(f"Job {job_id}: {e}")
            return  # error de configuración, no de infraestructura — no reintentar

        md_text = Path(job.output_path).read_text(encoding="utf-8")

        summarizer = DocumentSummarizer()
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(summarizer.summarize_and_classify(md_text, categorias))
        finally:
            loop.run_until_complete(summarizer.close())
            loop.close()

        summary_path = _write_summary_md(job.filename, result["resumen_ejecutivo"], result["clasificacion_top5"])

        import json
        job.summary_md_path = summary_path
        job.classification_json = json.dumps(
            {"resumen_ejecutivo": result["resumen_ejecutivo"], "clasificacion_top5": result["clasificacion_top5"]},
            ensure_ascii=False,
        )
        job.summary_status = SummaryStatus.COMPLETED
        job.summary_error = None
        db.commit()
        logger.info(f"Job {job_id}: resumen/clasificación completados")

    except SummarizerError as e:
        job = job_manager.get_job(db, job_id)
        if job:
            job.summary_status = SummaryStatus.ERROR
            job.summary_error = str(e)[:2000]
            db.commit()
        logger.error(f"Job {job_id}: fallo de resumen/clasificación: {e}")

    except Exception as exc:
        logger.error(f"Error inesperado en resumen job {job_id}: {exc}")
        try:
            job = job_manager.get_job(db, job_id)
            if job:
                job.summary_status = SummaryStatus.ERROR
                job.summary_error = str(exc)[:2000]
                db.commit()
        except Exception:
            pass
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=15)

    finally:
        try:
            regenerate_excel(db)
        except Exception as e:
            logger.error(f"No se pudo regenerar el Excel para job {job_id}: {e}")
        db.close()

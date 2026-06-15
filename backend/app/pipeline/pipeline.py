"""
Orquestador principal del pipeline OCR.
Procesa un PDF completo con checkpointing por página.
"""

import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

import numpy as np
from loguru import logger
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.job import Job, Page, JobStatus, PageStatus, DocType, OcrEngine
from app.pipeline.preprocessor import DocumentPreprocessor
from app.pipeline.classifier import DocumentClassifier
from app.pipeline.ocr_engine import SuryaEngine, TrOCREngine, MinerUEngine, TesseractFallback
from app.pipeline.corrector import LLMCorrector
from app.pipeline.validator import QualityValidator
from app.services.model_loader import ModelLoader

settings = get_settings()


def _utcnow():
    return datetime.now(timezone.utc)


class OCRPipeline:
    def __init__(self, model_loader: ModelLoader):
        self.preprocessor = DocumentPreprocessor(dpi=settings.pdf_extraction_dpi)
        self.classifier = DocumentClassifier()
        self.validator = QualityValidator()
        self.corrector = LLMCorrector()
        self.model_loader = model_loader
        self._tesseract = TesseractFallback()

    async def process_job(
        self,
        job: Job,
        db: Session,
        on_progress: Optional[Callable[[dict], None]] = None,
    ) -> Job:
        """
        Procesa un job completo. Retoma desde la última página completada
        si el job fue interrumpido.
        """
        pdf_path = job.original_path
        if not pdf_path or not Path(pdf_path).exists():
            self._fail_job(job, db, f"Archivo no encontrado: {pdf_path}")
            return job

        logger.info(f"Iniciando pipeline para job {job.id}: {job.filename}")
        self._set_job_status(job, db, JobStatus.PREPROCESSING)
        self._emit(on_progress, {"job_id": job.id, "stage": "preprocessing", "message": "Extrayendo páginas del PDF"})

        try:
            # Extraer todas las páginas como imágenes
            raw_images = self.preprocessor.pdf_to_images(pdf_path)
        except Exception as e:
            self._fail_job(job, db, f"Error extrayendo PDF: {e}")
            return job

        total_pages = len(raw_images)
        if job.total_pages == 0:
            job.total_pages = total_pages
            db.commit()

        # Detectar páginas ya procesadas (checkpoint)
        completed_pages = {p.page_number for p in job.pages if p.status == PageStatus.COMPLETED}
        logger.info(f"Job {job.id}: {total_pages} páginas, {len(completed_pages)} ya procesadas")

        # Preprocess + classify todas las páginas primero
        processed_imgs = []
        analyses = []

        for i, raw_img in enumerate(raw_images):
            if i in completed_pages:
                processed_imgs.append(None)
                analyses.append(None)
                continue

            img = self.preprocessor.preprocess_page(raw_img)
            analysis = self.classifier.analyze(img)
            processed_imgs.append(img)
            analyses.append(analysis)

        # Asegurar que existan registros de página en BD
        existing_page_nums = {p.page_number for p in job.pages}
        for i in range(total_pages):
            if i not in existing_page_nums:
                page = Page(
                    job_id=job.id,
                    page_number=i,
                    status=PageStatus.PENDING,
                )
                db.add(page)
        db.commit()
        db.refresh(job)

        # Cargar modelos necesarios
        engines_needed = {
            analyses[i].recommended_engine
            for i in range(total_pages)
            if analyses[i] is not None
        }
        self.model_loader.ensure_loaded(engines_needed)

        # Procesar página a página
        self._set_job_status(job, db, JobStatus.OCR)

        for page_obj in sorted(job.pages, key=lambda p: p.page_number):
            i = page_obj.page_number
            if page_obj.status == PageStatus.COMPLETED:
                continue

            img = processed_imgs[i]
            analysis = analyses[i]
            if img is None or analysis is None:
                continue

            self._emit(on_progress, {
                "job_id": job.id,
                "stage": "ocr",
                "page": i + 1,
                "total_pages": total_pages,
                "engine": analysis.recommended_engine.value,
                "doc_type": analysis.doc_type.value,
            })

            try:
                await self._process_page(page_obj, img, analysis, pdf_path, db)
            except Exception as e:
                logger.error(f"Error en página {i} del job {job.id}: {e}")
                page_obj.status = PageStatus.ERROR
                page_obj.error_message = str(e)[:500]
                db.commit()

            # Actualizar stats del job
            job.processed_pages = sum(
                1 for p in job.pages if p.status in (PageStatus.COMPLETED, PageStatus.ERROR)
            )
            db.commit()

        # Generar Markdown final
        self._set_job_status(job, db, JobStatus.VALIDATING)
        self._emit(on_progress, {"job_id": job.id, "stage": "assembling"})

        output_path = self._assemble_markdown(job, db)
        job.output_path = output_path

        # Calcular stats finales
        completed = [p for p in job.pages if p.status == PageStatus.COMPLETED]
        errors = [p for p in job.pages if p.status == PageStatus.ERROR]

        job.passed_pages = sum(1 for p in completed if p.confidence >= settings.confidence_threshold_pass)
        job.warning_pages = sum(
            1 for p in completed
            if settings.confidence_threshold_warn <= p.confidence < settings.confidence_threshold_pass
        )
        job.error_pages = len(errors)
        job.avg_confidence = (
            float(sum(p.confidence for p in completed) / len(completed)) if completed else 0.0
        )

        final_status = JobStatus.COMPLETED if not errors else (
            JobStatus.PARTIAL if completed else JobStatus.ERROR
        )
        self._set_job_status(job, db, final_status)
        job.completed_at = _utcnow()
        db.commit()

        self._emit(on_progress, {
            "job_id": job.id,
            "stage": "completed",
            "status": final_status.value,
            "avg_confidence": job.avg_confidence,
            "output_path": output_path,
        })

        logger.info(f"Job {job.id} finalizado: {final_status.value}, confianza_promedio={job.avg_confidence:.2f}")
        return job

    async def _process_page(
        self,
        page_obj: Page,
        img: np.ndarray,
        analysis,
        pdf_path: str,
        db: Session,
    ):
        page_obj.status = PageStatus.OCR
        page_obj.doc_type = analysis.doc_type
        page_obj.ocr_engine = analysis.recommended_engine
        page_obj.handwriting_score = analysis.handwriting_score
        page_obj.print_quality = analysis.print_quality
        page_obj.layout_complexity = analysis.layout_complexity
        page_obj.degradation_level = analysis.degradation_level
        db.commit()

        pil_img = self.preprocessor.numpy_to_pil(img, mode="RGB")
        engine = analysis.recommended_engine

        # Etapa OCR
        ocr_result = None
        if engine == OcrEngine.TROCR:
            ocr_result = self.model_loader.trocr.ocr_image(pil_img)
        elif engine == OcrEngine.MINERU:
            ocr_result = self.model_loader.mineru.ocr_pdf_page(pdf_path, page_obj.page_number)
            if ocr_result is None:
                # Fallback a Surya si MinerU falla
                ocr_result = self.model_loader.surya.ocr_image(pil_img)
        else:  # SURYA por defecto
            try:
                ocr_result = self.model_loader.surya.ocr_image(pil_img)
            except (TimeoutError, Exception) as e:
                logger.warning(f"Surya falló ({type(e).__name__}: {e}), usando Tesseract fallback")
                ocr_result = None

        if ocr_result is None or not ocr_result.text.strip():
            # Último fallback: Tesseract
            ocr_result = self._tesseract.ocr_image(pil_img)

        page_obj.raw_ocr_text = ocr_result.text
        page_obj.ocr_engine = ocr_result.engine
        page_obj.status = PageStatus.CORRECTING
        db.commit()

        # Etapa corrección LLM
        is_hw = analysis.doc_type == DocType.HANDWRITTEN
        corrected_text, correction_ratio = await self.corrector.correct(
            ocr_result.text, is_handwriting=is_hw
        )
        page_obj.corrected_text = corrected_text
        page_obj.correction_ratio = correction_ratio
        page_obj.status = PageStatus.VALIDATING
        db.commit()

        # Etapa validación
        val = self.validator.validate(
            corrected_text,
            ocr_conf=ocr_result.confidence,
            correction_ratio=correction_ratio,
            page_img_shape=(img.shape[0], img.shape[1]),
        )
        page_obj.confidence = val.composite_score
        if not val.passed and not val.is_warning:
            page_obj.status = PageStatus.ERROR
            page_obj.error_message = f"Calidad insuficiente: {val.details}"
        else:
            page_obj.status = PageStatus.COMPLETED
        db.commit()

    def _assemble_markdown(self, job: Job, db: Session) -> str:
        """Combina todas las páginas en un Markdown estructurado."""
        pages = sorted(job.pages, key=lambda p: p.page_number)
        md_parts = [f"# {job.filename}\n\n"]
        md_parts.append(f"*Procesado: {_utcnow().strftime('%Y-%m-%d %H:%M')} | "
                        f"Páginas: {job.total_pages} | "
                        f"Confianza promedio: {job.avg_confidence:.0%}*\n\n---\n\n")

        for page in pages:
            text = page.corrected_text or page.raw_ocr_text or ""
            if text.strip():
                md_parts.append(text.strip())
                md_parts.append("\n\n")
            if page.status == PageStatus.ERROR:
                md_parts.append(f"> ⚠️ **Página {page.page_number + 1}**: {page.error_message}\n\n")

        output_dir = Path(settings.output_path)
        output_dir.mkdir(parents=True, exist_ok=True)
        stem = Path(job.filename).stem
        output_path = str(output_dir / f"{stem}.md")

        with open(output_path, "w", encoding="utf-8") as f:
            f.write("".join(md_parts))

        logger.info(f"Markdown guardado: {output_path}")
        return output_path

    def _set_job_status(self, job: Job, db: Session, status: JobStatus):
        job.status = status
        job.updated_at = _utcnow()
        db.commit()

    def _fail_job(self, job: Job, db: Session, message: str):
        job.status = JobStatus.ERROR
        job.error_message = message
        job.updated_at = _utcnow()
        db.commit()
        logger.error(f"Job {job.id} fallido: {message}")

    def _emit(self, callback: Optional[Callable], data: dict):
        if callback:
            try:
                callback(data)
            except Exception:
                pass

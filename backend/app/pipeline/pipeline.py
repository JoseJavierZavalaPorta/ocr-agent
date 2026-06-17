"""
Orquestador principal del pipeline OCR.
Procesa un PDF completo con checkpointing por página.
"""

import os
import re
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
from app.pipeline.ocr_engine import SuryaEngine, TrOCREngine, MinerUEngine, TesseractFallback, VisionEngine
from app.pipeline.corrector import LLMCorrector
from app.pipeline.validator import QualityValidator
from app.services.model_loader import ModelLoader

settings = get_settings()


def _utcnow():
    return datetime.now(timezone.utc)


def _mineru_has_tables(text: str) -> bool:
    """MinerU produjo HTML de tablas estructuradas."""
    return bool(re.search(r'<(table|tr|td|th)\b', text, re.IGNORECASE))


def _mineru_has_real_text(text: str) -> bool:
    """MinerU extrajo texto real más allá de referencias de imagen markdown."""
    cleaned = re.sub(r'!\[[^\]]*\]\([^)]*\)', '', text)
    return len(cleaned.strip()) > 30


def _mineru_word_count(text: str) -> int:
    """Palabras en el texto de MinerU (sin contar imagen markdown ni formato)."""
    cleaned = re.sub(r'!\[[^\]]*\]\([^)]*\)', '', text)
    cleaned = re.sub(r'[#*`\[\]|]', ' ', cleaned)
    return len(cleaned.split())


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

        # Cargar modelos necesarios. Surya siempre se incluye: es el fallback
        # universal cuando TrOCR o MinerU no producen texto útil.
        engines_needed = {
            analyses[i].recommended_engine
            for i in range(total_pages)
            if analyses[i] is not None
        }
        engines_needed.add(OcrEngine.SURYA)
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

        # Calcular stats finales antes de ensamblar el MD (para que aparezca en la cabecera)
        self._set_job_status(job, db, JobStatus.VALIDATING)

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
        db.commit()

        # Generar Markdown final (ya con avg_confidence calculado)
        self._emit(on_progress, {"job_id": job.id, "stage": "assembling"})
        output_path = self._assemble_markdown(job, db)
        job.output_path = output_path

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

        logger.info(
            f"[PÁGINA {page_obj.page_number + 1}] "
            f"doc_type={analysis.doc_type.value} | "
            f"engine={engine.value} | "
            f"handwriting={analysis.handwriting_score:.3f} | "
            f"quality={analysis.print_quality:.3f} | "
            f"layout={analysis.layout_complexity:.3f} | "
            f"degradation={analysis.degradation_level:.3f}"
        )

        # Etapa OCR
        # VisionEngine para dos casos:
        # 1. engine=TROCR (manuscrito puro, layout bajo) → Vision reemplaza TrOCR
        # 2. engine=MINERU + MIXED/HW sin tablas HTML → Vision supera a MinerU para cursiva
        ocr_result = None
        vision = self.model_loader.vision
        if engine == OcrEngine.TROCR and vision.is_available():
            logger.info(f"[PÁGINA {page_obj.page_number + 1}] Usando VisionEngine ({vision.model})")
            ocr_result = vision.ocr_image(pil_img)
            if not ocr_result or not ocr_result.text.strip() or len(ocr_result.text.strip()) < 20:
                logger.warning(f"[PÁGINA {page_obj.page_number + 1}] VisionEngine sin resultado útil — fallback a TrOCR")
                ocr_result = None

        if ocr_result is not None:
            pass  # VisionEngine tuvo éxito
        elif engine == OcrEngine.TROCR:
            try:
                ocr_result = self.model_loader.trocr.ocr_image(pil_img)
            except (TimeoutError, Exception) as e:
                logger.warning(f"TrOCR falló ({type(e).__name__}: {e}), usando Tesseract fallback")
                ocr_result = None
        elif engine == OcrEngine.MINERU:
            ocr_result = self.model_loader.mineru.ocr_pdf_page(pdf_path, page_obj.page_number)
            is_hw_type = analysis.doc_type in (DocType.HANDWRITTEN, DocType.MIXED)

            # Para MIXED/HANDWRITTEN sin tablas y con texto escaso (< 80 palabras):
            # VisionEngine supera a MinerU para formularios/recetas escaneadas.
            # Si MinerU ya extrajo mucho texto (≥80 palabras), está funcionando bien → no sobreescribir.
            # Referencia: una receta médica tiene ~30 palabras; una página de texto completa tiene 200+.
            _mineru_words = _mineru_word_count(ocr_result.text) if ocr_result else 0
            if is_hw_type and vision.is_available() and (
                ocr_result is None
                or (not _mineru_has_tables(ocr_result.text) and _mineru_words < 80)
            ):
                logger.info(
                    f"[PÁGINA {page_obj.page_number + 1}] "
                    f"MIXED/HW sin tablas → VisionEngine ({vision.model})"
                )
                v_result = vision.ocr_image(pil_img)
                if v_result and len(v_result.text.strip()) >= 20:
                    ocr_result = v_result

            # Fallback si MinerU (y Vision si se intentó) no produjeron texto real
            if ocr_result is None or (
                ocr_result.engine == OcrEngine.MINERU
                and not _mineru_has_real_text(ocr_result.text)
            ):
                logger.warning(
                    f"[PÁGINA {page_obj.page_number + 1}] MinerU sin texto real "
                    f"(solo imágenes o vacío) — fallback TrOCR/Surya"
                )
                fallback = None
                if analysis.handwriting_score >= settings.handwriting_threshold * 0.7:
                    try:
                        fallback = self.model_loader.trocr.ocr_image(pil_img)
                    except Exception as e:
                        logger.warning(f"TrOCR fallback falló: {e}")
                if fallback is None or len(fallback.text.strip()) < 20:
                    fallback = self.model_loader.surya.ocr_image(pil_img)
                ocr_result = fallback
        else:  # SURYA por defecto
            try:
                ocr_result = self.model_loader.surya.ocr_image(pil_img)
            except (TimeoutError, Exception) as e:
                logger.warning(f"Surya falló ({type(e).__name__}: {e}), usando Tesseract fallback")
                ocr_result = None

        # Si TrOCR devolvió muy poco texto, intentar con Surya antes de Tesseract
        if ocr_result is not None and engine == OcrEngine.TROCR and len(ocr_result.text.strip()) < 50:
            logger.warning(
                f"[PÁGINA {page_obj.page_number + 1}] TrOCR devolvió solo "
                f"{len(ocr_result.text.strip())} chars — intentando Surya como secundario"
            )
            try:
                surya_result = self.model_loader.surya.ocr_image(pil_img)
                if surya_result and len(surya_result.text.strip()) > len(ocr_result.text.strip()):
                    ocr_result = surya_result
            except Exception as e:
                logger.warning(f"Surya secundario falló: {e}")

        if ocr_result is None or not ocr_result.text.strip():
            # Último fallback: Tesseract
            ocr_result = self._tesseract.ocr_image(pil_img)

        page_obj.raw_ocr_text = ocr_result.text
        page_obj.ocr_engine = ocr_result.engine
        page_obj.status = PageStatus.CORRECTING
        db.commit()

        logger.info(
            f"[PÁGINA {page_obj.page_number + 1}] OCR completado | "
            f"engine_real={ocr_result.engine.value} | "
            f"ocr_confidence={ocr_result.confidence:.3f} | "
            f"chars={len(ocr_result.text.strip())}"
        )

        # Etapa corrección LLM
        # Skip LLM solo cuando MinerU produjo HTML de tablas estructuradas.
        # Casos donde se corre LLM: Surya, TrOCR, Tesseract, y también cuando
        # MinerU tuvo fallback (imagen sin texto) o extrajo texto sin tablas HTML.
        if ocr_result.engine == OcrEngine.MINERU and _mineru_has_tables(ocr_result.text):
            corrected_text = ocr_result.text
            correction_ratio = 0.0
            logger.info(
                f"[PÁGINA {page_obj.page_number + 1}] LLM omitido (MinerU+tablas) | "
                f"chars={len(corrected_text.strip())}"
            )
        else:
            # MIXED también usa prompt de manuscrito: recetas, cartas, formularios
            # con contenido mixto impreso+manuscrito se benefician del prompt médico/histórico.
            is_hw = analysis.doc_type in (DocType.HANDWRITTEN, DocType.MIXED)
            corrected_text, correction_ratio = await self.corrector.correct(
                ocr_result.text, is_handwriting=is_hw
            )
            logger.info(
                f"[PÁGINA {page_obj.page_number + 1}] LLM completado | "
                f"correction_ratio={correction_ratio:.3f} | "
                f"chars_corregidos={len(corrected_text.strip())}"
            )
        page_obj.corrected_text = corrected_text
        page_obj.correction_ratio = correction_ratio
        page_obj.status = PageStatus.VALIDATING
        db.commit()

        # Etapa validación
        val = self.validator.validate(
            corrected_text,
            ocr_confidence=ocr_result.confidence,
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
        md_parts.append(
            f"*Procesado: {_utcnow().strftime('%Y-%m-%d %H:%M UTC')} | "
            f"Páginas: {job.total_pages} | "
            f"Confianza promedio: {job.avg_confidence:.0%}*\n\n"
        )

        _engine_label = {
            OcrEngine.SURYA: "Surya",
            OcrEngine.TROCR: "TrOCR",
            OcrEngine.MINERU: "MinerU",
            OcrEngine.TESSERACT: "Tesseract",
            OcrEngine.VISION: "Vision",
        }
        _status_icon = {
            PageStatus.COMPLETED: "✅",
            PageStatus.ERROR: "❌",
        }

        for page in pages:
            num = page.page_number + 1
            engine = _engine_label.get(page.ocr_engine, "?")
            conf = f"{page.confidence:.0%}" if page.confidence else "—"
            icon = _status_icon.get(page.status, "⚠️")

            md_parts.append(f"\n\n---\n\n")
            md_parts.append(
                f"<!-- pág. {num}/{job.total_pages} | motor: {engine} | "
                f"confianza: {conf} | {icon} -->\n\n"
            )

            text = page.corrected_text or page.raw_ocr_text or ""
            if text.strip():
                md_parts.append(text.strip())
                md_parts.append("\n\n")

            if page.status == PageStatus.ERROR:
                md_parts.append(
                    f"> **[Página {num} — calidad insuficiente]** "
                    f"Motor: {engine} | Confianza: {conf} | "
                    f"{page.error_message or 'Error desconocido'}\n\n"
                )

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

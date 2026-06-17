from dataclasses import dataclass
from app.config import get_settings
from loguru import logger

settings = get_settings()


@dataclass
class ValidationResult:
    passed: bool
    is_warning: bool
    composite_score: float
    ocr_confidence: float
    correction_ratio: float
    text_density: float
    details: str


class QualityValidator:
    """
    Valida la calidad del resultado OCR usando score compuesto.
    No requiere LLM — es determinístico y rápido.
    """

    def validate(
        self,
        corrected_text: str,
        ocr_confidence: float,
        correction_ratio: float,
        page_img_shape: tuple[int, int],
    ) -> ValidationResult:

        text_density = self._compute_text_density(corrected_text, page_img_shape)
        composite = self._composite_score(ocr_confidence, correction_ratio, text_density)

        passed = composite >= settings.confidence_threshold_pass
        is_warning = (
            not passed and composite >= settings.confidence_threshold_warn
        )

        details = self._build_details(
            composite, ocr_confidence, correction_ratio, text_density
        )
        logger.info(f"Validación: score={composite:.2f} passed={passed} warning={is_warning}")

        return ValidationResult(
            passed=passed,
            is_warning=is_warning,
            composite_score=composite,
            ocr_confidence=ocr_confidence,
            correction_ratio=correction_ratio,
            text_density=text_density,
            details=details,
        )

    def _compute_text_density(self, text: str, shape: tuple[int, int]) -> float:
        """
        Palabras por página — detecta páginas en blanco o casi vacías.
        Documentos cortos legítimos (recetas, IDs, formularios) tienen floor 0.50
        para no penalizarlos por su brevedad natural.
        """
        if not text or not text.strip():
            return 0.0
        words = len(text.split())
        if words < 10:
            # Muy pocas palabras: podría ser página casi vacía
            return min(0.45, words / 10.0)
        # Documento con contenido real: mínimo 0.50 independientemente del largo
        # (recetas, DNI, formularios cortos son documentos válidos)
        return max(0.50, min(1.0, words / 250.0))

    def _composite_score(
        self,
        ocr_conf: float,
        correction_ratio: float,
        text_density: float,
    ) -> float:
        """
        Score compuesto ponderado:
        - ocr_confidence (40%): confianza del motor OCR
        - correction_penalty (30%): penaliza correcciones masivas solo cuando el OCR era inseguro
        - text_density (30%): página sin texto = problema

        La penalidad de corrección depende de la confianza OCR:
        - OCR seguro (≥0.75) + LLM cambió mucho = normalización válida de manuscrito garbled → penalizar poco
        - OCR inseguro + LLM cambió mucho = LLM inventando sobre base débil → penalizar más
        """
        if ocr_conf >= 0.75:
            # OCR confiable: el LLM normalizó texto semánticamente garbled pero bien capturado
            correction_penalty = max(0.55, 1.0 - correction_ratio * 0.5)
        else:
            # OCR inseguro: correcciones masivas son sospechosas
            correction_penalty = max(0.35, 1.0 - correction_ratio * 1.0)

        composite = (
            ocr_conf * 0.40
            + correction_penalty * 0.30
            + text_density * 0.30
        )
        return min(1.0, max(0.0, composite))

    def _build_details(
        self,
        composite: float,
        ocr_conf: float,
        correction_ratio: float,
        text_density: float,
    ) -> str:
        parts = [
            f"score_compuesto={composite:.2f}",
            f"confianza_ocr={ocr_conf:.2f}",
            f"ratio_corrección={correction_ratio:.2f}",
            f"densidad_texto={text_density:.2f}",
        ]
        if composite < settings.confidence_threshold_warn:
            parts.append("ACCIÓN: revisar manualmente")
        elif composite < settings.confidence_threshold_pass:
            parts.append("ACCIÓN: verificar resultado")
        return " | ".join(parts)

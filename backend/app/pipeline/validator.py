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
        logger.debug(f"Validación: score={composite:.2f} passed={passed} warning={is_warning}")

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
        """Palabras por área de página — páginas vacías tienen densidad 0."""
        if not text or not text.strip():
            return 0.0
        words = len(text.split())
        area_factor = (shape[0] * shape[1]) / (400 * 400)  # normalizado a 400x400
        density = words / (area_factor * 50 + 1)
        return min(1.0, density)

    def _composite_score(
        self,
        ocr_conf: float,
        correction_ratio: float,
        text_density: float,
    ) -> float:
        """
        Score compuesto ponderado:
        - ocr_confidence (40%): confianza del motor OCR
        - correction_penalty (30%): penaliza correcciones masivas (>50% = dudoso)
        - text_density (30%): página sin texto = problema
        """
        correction_penalty = max(0.0, 1.0 - correction_ratio * 1.5)
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

import cv2
import numpy as np
from dataclasses import dataclass
from app.models.job import DocType, OcrEngine
from app.config import get_settings

settings = get_settings()


@dataclass
class PageAnalysis:
    handwriting_score: float
    print_quality: float
    layout_complexity: float
    degradation_level: float
    doc_type: DocType
    recommended_engine: OcrEngine


class DocumentClassifier:
    """
    Analiza cada página y determina el tipo de documento + motor OCR óptimo.
    Usa análisis heurístico de imagen para máximo rendimiento (no requiere LLM).
    """

    def analyze(self, img: np.ndarray) -> PageAnalysis:
        handwriting_score = self._score_handwriting(img)
        print_quality = self._score_print_quality(img)
        layout_complexity = self._score_layout_complexity(img)
        degradation = self._score_degradation(img)

        doc_type = self._classify_type(handwriting_score, print_quality)
        engine = self._select_engine(
            handwriting_score, print_quality, layout_complexity, degradation
        )

        return PageAnalysis(
            handwriting_score=handwriting_score,
            print_quality=print_quality,
            layout_complexity=layout_complexity,
            degradation_level=degradation,
            doc_type=doc_type,
            recommended_engine=engine,
        )

    def _score_handwriting(self, img: np.ndarray) -> float:
        """
        Score de manuscrito basado en:
        - Alta varianza en ancho de trazos (escritura irregular)
        - Distribución asimétrica de componentes conectados
        - Ausencia de alineación regular (vs texto impreso)
        """
        _, binary = cv2.threshold(img, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        num_labels, _, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)

        if num_labels < 10:
            return 0.1

        areas = stats[1:, cv2.CC_STAT_AREA]
        widths = stats[1:, cv2.CC_STAT_WIDTH]
        heights = stats[1:, cv2.CC_STAT_HEIGHT]

        # Coeficiente de variación del área → manuscrito tiene alta varianza
        area_cv = float(np.std(areas) / (np.mean(areas) + 1e-8))

        # Aspect ratio varianza → texto impreso tiene ratios regulares
        valid = (heights > 5) & (heights < img.shape[0] * 0.5)
        if np.sum(valid) < 5:
            return 0.2
        ar = widths[valid].astype(float) / (heights[valid].astype(float) + 1e-8)
        ar_cv = float(np.std(ar) / (np.mean(ar) + 1e-8))

        # Texto impreso tiene espaciado horizontal muy regular
        x_positions = stats[1:, cv2.CC_STAT_LEFT][valid]
        if len(x_positions) > 5:
            x_gaps = np.diff(np.sort(x_positions))
            spacing_cv = float(np.std(x_gaps) / (np.mean(x_gaps) + 1e-8))
        else:
            spacing_cv = 1.0

        # Combinar: alta varianza = más probable manuscrito
        raw = (area_cv * 0.4 + ar_cv * 0.3 + spacing_cv * 0.3) / 3.0
        return min(1.0, max(0.0, raw))

    def _score_print_quality(self, img: np.ndarray) -> float:
        """Sharpness via Laplacian variance + dynamic range."""
        lap_var = float(cv2.Laplacian(img, cv2.CV_64F).var())
        sharpness = min(1.0, lap_var / 800.0)

        # Dynamic range: documentos buenos tienen buen contraste
        p5, p95 = float(np.percentile(img, 5)), float(np.percentile(img, 95))
        dynamic_range = min(1.0, (p95 - p5) / 200.0)

        return (sharpness * 0.6 + dynamic_range * 0.4)

    def _score_layout_complexity(self, img: np.ndarray) -> float:
        """Detecta líneas de tabla horizontales/verticales."""
        _, binary = cv2.threshold(img, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

        h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(40, img.shape[1] // 20), 1))
        h_lines = cv2.morphologyEx(binary, cv2.MORPH_OPEN, h_kernel)

        v_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(40, img.shape[0] // 20)))
        v_lines = cv2.morphologyEx(binary, cv2.MORPH_OPEN, v_kernel)

        total_px = img.shape[0] * img.shape[1]
        table_density = (cv2.countNonZero(h_lines) + cv2.countNonZero(v_lines)) / (total_px + 1e-8)

        # Detectar columnas múltiples via análisis de proyección vertical
        proj = np.sum(binary, axis=0)
        valleys = np.sum(proj < proj.mean() * 0.2)
        column_score = min(1.0, valleys / (img.shape[1] * 0.3))

        return min(1.0, table_density * 80 + column_score * 0.3)

    def _score_degradation(self, img: np.ndarray) -> float:
        """
        Estima nivel de degradación: documentos muy viejos tienen
        bajo contraste, manchas, zonas quemadas.
        """
        mean = float(img.mean())
        std = float(img.std())

        # Imagen muy pálida (desteñida) o muy oscura (quemada)
        brightness_score = 1.0 - min(1.0, abs(mean - 128) / 100.0)

        # Bajo contraste
        contrast_score = min(1.0, std / 60.0)

        # Ruido de fondo (manchas en papel antiguo)
        _, binary = cv2.threshold(img, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        num_labels, _, stats, _ = cv2.connectedComponentsWithStats(binary)
        if num_labels > 1:
            tiny_noise = np.sum(stats[1:, cv2.CC_STAT_AREA] < 10)
            noise_ratio = min(1.0, tiny_noise / max(num_labels, 1))
        else:
            noise_ratio = 0.0

        degradation = 1.0 - (brightness_score * 0.4 + contrast_score * 0.4) + noise_ratio * 0.2
        return min(1.0, max(0.0, degradation))

    def _classify_type(self, hw_score: float, quality: float) -> DocType:
        if hw_score > settings.handwriting_threshold:
            return DocType.HANDWRITTEN
        if hw_score > 0.35:
            return DocType.MIXED
        return DocType.PRINTED

    def _select_engine(
        self,
        hw_score: float,
        quality: float,
        layout: float,
        degradation: float,
    ) -> OcrEngine:
        # Manuscrito → TrOCR especializado en escritura a mano
        if hw_score >= settings.handwriting_threshold:
            return OcrEngine.TROCR

        # Layout complejo (tablas densas) + buena calidad → MinerU (CPU pero mejor tabla)
        if layout >= settings.layout_complexity_threshold and quality >= 0.5:
            return OcrEngine.MINERU

        # Por defecto: Surya (Marker) — mejor para documentos históricos impresos en AMD ROCm
        return OcrEngine.SURYA

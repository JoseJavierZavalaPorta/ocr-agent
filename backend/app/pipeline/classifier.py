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
        """
        Detecta complejidad de layout: tablas, múltiples columnas.
        Usa tres señales independientes para ser robusto ante tablas
        parciales, líneas cortas y bordes finos.
        """
        _, binary = cv2.threshold(img, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        h, w = img.shape

        # ── Señal 1: líneas horizontales/verticales a múltiples escalas ──────
        # Escalas pequeñas (1/8, 1/15, 1/30 del lado) capturan tablas
        # parciales que la escala única 1/20 se pierde.
        line_score = 0.0
        for scale in [8, 15, 30]:
            h_len = max(20, w // scale)
            v_len = max(20, h // scale)
            hk = cv2.getStructuringElement(cv2.MORPH_RECT, (h_len, 1))
            vk = cv2.getStructuringElement(cv2.MORPH_RECT, (1, v_len))
            h_lines = cv2.morphologyEx(binary, cv2.MORPH_OPEN, hk)
            v_lines = cv2.morphologyEx(binary, cv2.MORPH_OPEN, vk)
            density = (cv2.countNonZero(h_lines) + cv2.countNonZero(v_lines)) / (h * w + 1e-8)
            line_score = max(line_score, min(1.0, density * 60))

        # ── Señal 2: celdas rectangulares (contornos anidados) ───────────────
        # Las tablas tienen muchos rectángulos cerrados; el texto normal no.
        cell_score = 0.0
        contours, hierarchy = cv2.findContours(binary, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
        if hierarchy is not None and len(contours) > 0:
            rect_cells = 0
            for i, cnt in enumerate(contours):
                area = cv2.contourArea(cnt)
                if area < 500 or area > h * w * 0.25:
                    continue
                peri = cv2.arcLength(cnt, True)
                approx = cv2.approxPolyDP(cnt, 0.04 * peri, True)
                if len(approx) == 4:  # contorno rectangular = probable celda
                    rect_cells += 1
            cell_score = min(1.0, rect_cells / 8.0)  # 8+ celdas → score=1

        # ── Señal 3: regularidad de proyección horizontal (filas de texto) ───
        # Las tablas tienen filas de texto con separación uniforme.
        proj_h = np.sum(binary, axis=1).astype(float)
        text_rows = proj_h > proj_h.max() * 0.05
        transitions = int(np.sum(np.diff(text_rows.astype(int)) != 0))
        row_score = min(1.0, transitions / 30.0)  # 30+ transiciones → denso

        # Combinar: la señal más fuerte domina (tabla detectada por cualquier vía)
        return float(max(line_score * 0.5 + cell_score * 0.5, cell_score, line_score * 0.7 + row_score * 0.3))

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
        # MinerU: layout complejo (tablas, columnas, formularios estructurados).
        # No se filtra por hw_score: si MinerU produce solo imágenes o texto
        # garbled, el pipeline hace fallback automático (ver pipeline.py).
        if layout >= settings.layout_complexity_threshold and quality >= 0.5:
            return OcrEngine.MINERU

        # TrOCR: manuscrito sin estructura de layout claro Y con baja calidad
        # de impresión. Alta print_quality (> 0.65) indica texto impreso nítido
        # (DNI, formularios impresos) que Surya maneja mejor que TrOCR.
        if layout < 0.20 and hw_score >= settings.handwriting_threshold and quality < 0.65:
            return OcrEngine.TROCR

        # Surya: documentos impresos, mixtos o degradados.
        return OcrEngine.SURYA

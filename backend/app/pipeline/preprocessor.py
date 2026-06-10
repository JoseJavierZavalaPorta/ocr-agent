import cv2
import numpy as np
from PIL import Image
from pathlib import Path
from loguru import logger
import fitz  # PyMuPDF


class DocumentPreprocessor:
    """Extrae imágenes de PDFs y aplica correcciones de calidad para OCR."""

    def __init__(self, dpi: int = 400):
        self.dpi = dpi
        self._scale = dpi / 72.0

    def pdf_to_images(self, pdf_path: str) -> list[np.ndarray]:
        """Convierte cada página del PDF a imagen numpy en escala de grises."""
        doc = fitz.open(pdf_path)
        images = []
        mat = fitz.Matrix(self._scale, self._scale)

        for page_num in range(len(doc)):
            page = doc[page_num]
            pix = page.get_pixmap(matrix=mat, colorspace=fitz.csGRAY)
            img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)
            images.append(img.copy())

        doc.close()
        logger.debug(f"Extraídas {len(images)} páginas de {pdf_path} a {self.dpi} DPI")
        return images

    def preprocess_page(self, img: np.ndarray) -> np.ndarray:
        """Pipeline de preprocesamiento para mejorar calidad antes del OCR."""
        img = self._deskew(img)
        img = self._remove_border_noise(img)
        img = self._denoise(img)
        img = self._enhance_contrast(img)
        img = self._binarize(img)
        return img

    def _deskew(self, img: np.ndarray) -> np.ndarray:
        """Corrige rotación usando análisis de líneas Hough."""
        edges = cv2.Canny(img, 50, 150, apertureSize=3)
        lines = cv2.HoughLines(edges, 1, np.pi / 180, threshold=150)
        if lines is None:
            return img

        angles = []
        for rho, theta in lines[:, 0]:
            angle = (theta * 180 / np.pi) - 90
            if abs(angle) < 30:
                angles.append(angle)

        if not angles or len(angles) < 3:
            return img

        median_angle = float(np.median(angles))
        if abs(median_angle) < 0.3:
            return img

        h, w = img.shape
        center = (w // 2, h // 2)
        M = cv2.getRotationMatrix2D(center, median_angle, 1.0)
        corrected = cv2.warpAffine(img, M, (w, h), flags=cv2.INTER_CUBIC, borderValue=255)
        logger.debug(f"Deskew aplicado: {median_angle:.2f}°")
        return corrected

    def _remove_border_noise(self, img: np.ndarray) -> np.ndarray:
        """Elimina ruido de bordes típico de escaneos."""
        h, w = img.shape
        margin = int(min(h, w) * 0.01)
        if margin < 5:
            return img
        img[:margin, :] = 255
        img[-margin:, :] = 255
        img[:, :margin] = 255
        img[:, -margin:] = 255
        return img

    def _denoise(self, img: np.ndarray) -> np.ndarray:
        """Reduce ruido preservando bordes de texto."""
        return cv2.fastNlMeansDenoising(img, h=10, templateWindowSize=7, searchWindowSize=21)

    def _enhance_contrast(self, img: np.ndarray) -> np.ndarray:
        """CLAHE para mejorar contraste local (documentos degradados)."""
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        return clahe.apply(img)

    def _binarize(self, img: np.ndarray) -> np.ndarray:
        """Binarización adaptativa Sauvola, óptima para documentos históricos."""
        try:
            from skimage.filters import threshold_sauvola
            threshold = threshold_sauvola(img, window_size=25, k=0.2)
            binary = (img > threshold).astype(np.uint8) * 255
            return binary
        except Exception:
            # Fallback a Otsu
            _, binary = cv2.threshold(img, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            return binary

    def numpy_to_pil(self, img: np.ndarray, mode: str = "RGB") -> Image.Image:
        """Convierte numpy array a PIL Image."""
        if len(img.shape) == 2:
            pil = Image.fromarray(img, mode="L")
        else:
            pil = Image.fromarray(img)
        if mode != pil.mode:
            pil = pil.convert(mode)
        return pil

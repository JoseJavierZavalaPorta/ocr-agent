import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional
import numpy as np
from PIL import Image
from loguru import logger

from app.models.job import OcrEngine
from app.config import get_settings

settings = get_settings()


class OCRResult:
    def __init__(self, text: str, confidence: float, engine: OcrEngine, metadata: dict = None):
        self.text = text
        self.confidence = confidence
        self.engine = engine
        self.metadata = metadata or {}


class SuryaEngine:
    """Motor principal: Surya OCR (base de Marker). Optimizado para ROCm AMD."""

    def __init__(self, models_path: str):
        self.models_path = models_path
        self._det_model = None
        self._det_processor = None
        self._rec_model = None
        self._rec_processor = None
        self._layout_model = None
        self._layout_processor = None
        self._loaded = False

    def load(self):
        if self._loaded:
            return
        import torch

        cache = f"{self.models_path}/huggingface"
        os.environ.setdefault("HF_HOME", cache)

        # CPU por defecto: GPU AMD iGPU causa page fault al cargar modelos grandes.
        # Activar GPU con SURYA_DEVICE=cuda si se tiene GPU discreta con suficiente VRAM.
        requested = os.environ.get("SURYA_DEVICE", "cpu")
        device = requested if torch.cuda.is_available() else "cpu"
        logger.info(f"Cargando Surya en device: {device}")

        # surya 0.6.x cambió el path del módulo de detección
        try:
            from surya.model.detection.segformer import load_model as load_det, load_processor as load_det_proc
        except ImportError:
            try:
                from surya.model.detection.model import load_model as load_det, load_processor as load_det_proc
            except ImportError:
                from surya.model.detection import load_model as load_det, load_processor as load_det_proc

        from surya.model.recognition.model import load_model as load_rec
        from surya.model.recognition.processor import load_processor as load_rec_proc

        # surya 0.6.x: SuryaOCRConfig.__init__ exige kwarg "encoder" pero
        # transformers lo llama sin args en to_diff_dict() → KeyError.
        # Silenciar logs INFO de transformers durante la carga para evitar el bug.
        import transformers as _hf
        _hf.logging.set_verbosity_error()
        self._det_processor = load_det_proc()
        self._det_model = load_det().to(device)
        self._rec_model = load_rec().to(device)
        self._rec_processor = load_rec_proc()
        _hf.logging.set_verbosity_warning()
        self._loaded = True
        logger.info("Surya OCR cargado correctamente")

    def ocr_image(self, img_pil: Image.Image, langs: list[str] = None) -> OCRResult:
        from surya.ocr import run_ocr

        langs = langs or ["es", "en"]
        results = run_ocr(
            [img_pil],
            [langs],
            self._det_model,
            self._det_processor,
            self._rec_model,
            self._rec_processor,
        )

        page_result = results[0]
        lines = []
        confidences = []

        for line in page_result.text_lines:
            lines.append(line.text)
            confidences.append(line.confidence if hasattr(line, "confidence") else 0.9)

        text = "\n".join(lines)
        avg_conf = float(np.mean(confidences)) if confidences else 0.0
        return OCRResult(text=text, confidence=avg_conf, engine=OcrEngine.SURYA)


class TrOCREngine:
    """Motor especializado en manuscritos. microsoft/trocr-large-handwritten."""

    def __init__(self, models_path: str):
        self.models_path = models_path
        self._processor = None
        self._model = None
        self._device = None
        self._loaded = False

    def load(self):
        if self._loaded:
            return
        import torch
        from transformers import TrOCRProcessor, VisionEncoderDecoderModel

        cache = f"{self.models_path}/huggingface"
        # Usar CPU por defecto: la GPU AMD/ROCm causa page faults con TrOCR
        # en configuraciones con iGPU. Activar con TROCR_DEVICE=cuda si se desea.
        requested = os.environ.get("TROCR_DEVICE", "cpu")
        self._device = requested if torch.cuda.is_available() else "cpu"
        logger.info(f"Cargando TrOCR en device: {self._device}")

        self._processor = TrOCRProcessor.from_pretrained(
            "microsoft/trocr-large-handwritten", cache_dir=cache
        )
        model = VisionEncoderDecoderModel.from_pretrained(
            "microsoft/trocr-large-handwritten", cache_dir=cache
        )
        try:
            self._model = model.to(self._device)
        except Exception as e:
            logger.warning(f"No se pudo mover TrOCR a {self._device}: {e}. Usando CPU.")
            self._device = "cpu"
            self._model = model.to("cpu")
        self._model.eval()
        self._loaded = True
        logger.info(f"TrOCR cargado en {self._device}")

    def ocr_image(self, img_pil: Image.Image) -> OCRResult:
        import torch

        rgb = img_pil.convert("RGB")
        pixel_values = self._processor(images=rgb, return_tensors="pt").pixel_values.to(self._device)

        with torch.no_grad():
            generated_ids = self._model.generate(
                pixel_values,
                max_new_tokens=512,
                num_beams=4,
                early_stopping=True,
            )

        text = self._processor.batch_decode(generated_ids, skip_special_tokens=True)[0]

        # TrOCR no devuelve confianza directamente; estimar por longitud de salida
        confidence = min(0.95, len(text.strip()) / 200.0) if text.strip() else 0.1
        return OCRResult(text=text, confidence=confidence, engine=OcrEngine.TROCR)


class MinerUEngine:
    """
    Motor para páginas con tablas complejas. Usa magic-pdf CLI.
    Funciona en CPU (PaddleOCR); se usa solo cuando Surya no es suficiente.
    """

    def __init__(self, models_path: str):
        self.models_path = models_path
        self._available: Optional[bool] = None

    def is_available(self) -> bool:
        if self._available is None:
            try:
                result = subprocess.run(
                    ["magic-pdf", "--version"],
                    capture_output=True,
                    timeout=10,
                )
                self._available = result.returncode == 0
            except Exception:
                self._available = False
        return self._available

    def load(self):
        if not self.is_available():
            logger.warning("MinerU (magic-pdf) no disponible, se usará Surya como fallback")

    def ocr_pdf_page(self, pdf_path: str, page_num: int) -> Optional[OCRResult]:
        """Extrae una página del PDF y la procesa con MinerU."""
        if not self.is_available():
            return None

        try:
            import fitz

            # Extraer página como PDF temporal
            doc = fitz.open(pdf_path)
            single = fitz.open()
            single.insert_pdf(doc, from_page=page_num, to_page=page_num)
            doc.close()

            with tempfile.TemporaryDirectory() as tmpdir:
                tmp_pdf = os.path.join(tmpdir, "page.pdf")
                single.save(tmp_pdf)
                single.close()

                out_dir = os.path.join(tmpdir, "output")
                os.makedirs(out_dir, exist_ok=True)

                result = subprocess.run(
                    ["magic-pdf", "-p", tmp_pdf, "-o", out_dir, "-m", "ocr"],
                    capture_output=True,
                    text=True,
                    timeout=300,
                    env={**os.environ, "MINERU_MODELS_DIR": self.models_path},
                )

                if result.returncode != 0:
                    logger.warning(f"MinerU error en página {page_num}: {result.stderr[:200]}")
                    return None

                # Buscar el MD generado
                md_files = list(Path(out_dir).rglob("*.md"))
                if not md_files:
                    return None

                text = md_files[0].read_text(encoding="utf-8")
                return OCRResult(text=text, confidence=0.85, engine=OcrEngine.MINERU)

        except Exception as e:
            logger.error(f"MinerU falló para página {page_num}: {e}")
            return None


class TesseractFallback:
    """Fallback CPU cuando todos los motores fallan."""

    def ocr_image(self, img_pil: Image.Image, lang: str = "spa+eng") -> OCRResult:
        try:
            import pytesseract
            text = pytesseract.image_to_string(img_pil, lang=lang, config="--psm 3")
            confidence = 0.5 if text.strip() else 0.1
            return OCRResult(text=text, confidence=confidence, engine=OcrEngine.TESSERACT)
        except Exception as e:
            logger.error(f"Tesseract falló: {e}")
            return OCRResult(text="", confidence=0.0, engine=OcrEngine.TESSERACT)

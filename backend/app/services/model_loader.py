"""
Singleton que carga y cachea los modelos ML en GPU.
Los modelos se cargan UNA VEZ al iniciar el worker y se reutilizan.
"""

import threading
from typing import Set
from loguru import logger

from app.models.job import OcrEngine
from app.pipeline.ocr_engine import SuryaEngine, TrOCREngine, MinerUEngine
from app.config import get_settings

settings = get_settings()

_instance: "ModelLoader | None" = None
_lock = threading.Lock()


class ModelLoader:
    def __init__(self):
        models_path = settings.models_path
        self.surya = SuryaEngine(models_path)
        self.trocr = TrOCREngine(models_path)
        self.mineru = MinerUEngine(models_path)
        self._loaded: Set[OcrEngine] = set()

    def ensure_loaded(self, engines: Set[OcrEngine]):
        """Carga solo los motores requeridos para el job actual."""
        for engine in engines:
            if engine in self._loaded:
                continue
            self._load_engine(engine)

    def load_all(self):
        """Carga todos los motores al arrancar el worker (warm start)."""
        for engine in [OcrEngine.SURYA, OcrEngine.TROCR, OcrEngine.MINERU]:
            self._load_engine(engine)

    def _load_engine(self, engine: OcrEngine):
        try:
            if engine == OcrEngine.SURYA:
                self.surya.load()
            elif engine == OcrEngine.TROCR:
                self.trocr.load()
            elif engine == OcrEngine.MINERU:
                self.mineru.load()
            self._loaded.add(engine)
            logger.info(f"Engine {engine.value} listo")
        except Exception as e:
            logger.error(f"No se pudo cargar engine {engine.value}: {e}")


def get_model_loader() -> ModelLoader:
    """Retorna la instancia singleton del ModelLoader."""
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                logger.info("Inicializando ModelLoader (primera vez)...")
                _instance = ModelLoader()
    return _instance

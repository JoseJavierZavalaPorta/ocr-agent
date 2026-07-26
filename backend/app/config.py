from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Infraestructura
    redis_url: str = "redis://redis:6379/0"
    ollama_url: str = "http://ollama:11434"
    database_url: str = "sqlite:////data/db/ocr.db"
    api_secret_key: str = "dev-secret-key"

    # Rutas
    input_path: str = "/data/input"
    output_path: str = "/data/output"
    originals_path: str = "/data/originals"
    models_path: str = "/data/models"

    # Pipeline OCR
    confidence_threshold_pass: float = 0.80
    confidence_threshold_warn: float = 0.60
    handwriting_threshold: float = 0.60
    layout_complexity_threshold: float = 0.40
    pdf_extraction_dpi: int = 300
    surya_batch_size: int = 8

    # Modelos Ollama — por defecto un único VLM (qwen2.5vl:32b) hace OCR de
    # imágenes, corrección de texto y resumen/clasificación. Se puede separar
    # vía .env (ej. qwen2.5vl:7b visión + qwen2.5:32b corrección) en GPU chica.
    ollama_correction_model: str = "qwen2.5vl:32b"
    ollama_vision_model: str = "qwen2.5vl:32b"

    # Celery
    celery_concurrency: int = 2


@lru_cache
def get_settings() -> Settings:
    return Settings()

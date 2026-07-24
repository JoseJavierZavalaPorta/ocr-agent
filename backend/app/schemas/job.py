from pydantic import BaseModel, ConfigDict
from datetime import datetime
from typing import Optional
from app.models.job import JobStatus, PageStatus, DocType, OcrEngine, SummaryStatus


class PageSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    job_id: str
    page_number: int
    status: PageStatus
    doc_type: DocType
    ocr_engine: Optional[OcrEngine]
    handwriting_score: float
    print_quality: float
    layout_complexity: float
    degradation_level: float
    raw_ocr_text: Optional[str]
    corrected_text: Optional[str]
    confidence: float
    correction_ratio: float
    error_message: Optional[str]
    created_at: datetime
    updated_at: datetime


class JobSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    filename: str
    original_path: Optional[str]
    output_path: Optional[str]
    status: JobStatus
    total_pages: int
    processed_pages: int
    passed_pages: int
    warning_pages: int
    error_pages: int
    avg_confidence: float
    file_size_bytes: int
    error_message: Optional[str]
    summary_status: SummaryStatus
    summary_md_path: Optional[str]
    summary_error: Optional[str]
    classification_json: Optional[str]
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime]
    pages: list[PageSchema] = []


class JobSummarySchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    filename: str
    status: JobStatus
    total_pages: int
    processed_pages: int
    avg_confidence: float
    error_message: Optional[str]
    summary_status: SummaryStatus
    summary_md_path: Optional[str]
    summary_error: Optional[str]
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime]


class ConfigSchema(BaseModel):
    input_path: str
    output_path: str
    originals_path: str
    confidence_threshold_pass: float
    confidence_threshold_warn: float
    handwriting_threshold: float
    layout_complexity_threshold: float
    pdf_extraction_dpi: int
    surya_batch_size: int
    ollama_correction_model: str
    celery_concurrency: int


class WatcherStatusSchema(BaseModel):
    watching: bool
    paths: list[str]
    pending_files: int


class SystemStatusSchema(BaseModel):
    gpu_available: bool
    gpu_name: Optional[str]
    gpu_vram_total_gb: Optional[float]
    gpu_vram_free_gb: Optional[float]
    ollama_online: bool
    models_loaded: list[str]
    queue_size: int
    active_jobs: int

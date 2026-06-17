from sqlalchemy import Column, String, Integer, Float, DateTime, Text, ForeignKey, Enum as SAEnum
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
import enum
import uuid

from app.database import Base


class JobStatus(str, enum.Enum):
    PENDING = "PENDING"
    QUEUED = "QUEUED"
    PREPROCESSING = "PREPROCESSING"
    OCR = "OCR"
    CORRECTING = "CORRECTING"
    VALIDATING = "VALIDATING"
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    ERROR = "ERROR"


class PageStatus(str, enum.Enum):
    PENDING = "PENDING"
    PREPROCESSING = "PREPROCESSING"
    OCR = "OCR"
    CORRECTING = "CORRECTING"
    VALIDATING = "VALIDATING"
    COMPLETED = "COMPLETED"
    ERROR = "ERROR"


class DocType(str, enum.Enum):
    PRINTED = "printed"
    TYPEWRITER = "typewriter"
    HANDWRITTEN = "handwritten"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class OcrEngine(str, enum.Enum):
    SURYA = "surya"
    TROCR = "trocr"
    MINERU = "mineru"
    TESSERACT = "tesseract"
    VISION = "vision"


def _utcnow():
    return datetime.now(timezone.utc)


class Job(Base):
    __tablename__ = "jobs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    filename = Column(String(512), nullable=False, index=True)
    original_path = Column(String(1024))
    output_path = Column(String(1024))
    status = Column(SAEnum(JobStatus), default=JobStatus.PENDING, nullable=False, index=True)

    total_pages = Column(Integer, default=0)
    processed_pages = Column(Integer, default=0)
    passed_pages = Column(Integer, default=0)
    warning_pages = Column(Integer, default=0)
    error_pages = Column(Integer, default=0)

    avg_confidence = Column(Float, default=0.0)
    file_size_bytes = Column(Integer, default=0)

    celery_task_id = Column(String(128), nullable=True)
    error_message = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    pages = relationship("Page", back_populates="job", cascade="all, delete-orphan", order_by="Page.page_number")


class Page(Base):
    __tablename__ = "pages"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id = Column(String(36), ForeignKey("jobs.id"), nullable=False, index=True)
    page_number = Column(Integer, nullable=False)

    status = Column(SAEnum(PageStatus), default=PageStatus.PENDING, nullable=False)
    doc_type = Column(SAEnum(DocType), default=DocType.UNKNOWN)
    ocr_engine = Column(SAEnum(OcrEngine), nullable=True)

    # Scores del routing agent
    handwriting_score = Column(Float, default=0.0)
    print_quality = Column(Float, default=0.0)
    layout_complexity = Column(Float, default=0.0)
    degradation_level = Column(Float, default=0.0)

    # Resultados OCR
    raw_ocr_text = Column(Text, nullable=True)
    corrected_text = Column(Text, nullable=True)
    confidence = Column(Float, default=0.0)
    correction_ratio = Column(Float, default=0.0)  # % de texto modificado por LLM

    error_message = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    job = relationship("Job", back_populates="pages")

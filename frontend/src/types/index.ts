export type JobStatus =
  | 'PENDING' | 'QUEUED' | 'PREPROCESSING' | 'OCR'
  | 'CORRECTING' | 'VALIDATING' | 'COMPLETED' | 'PARTIAL' | 'ERROR'

export type PageStatus =
  | 'PENDING' | 'PREPROCESSING' | 'OCR'
  | 'CORRECTING' | 'VALIDATING' | 'COMPLETED' | 'ERROR'

export type DocType = 'printed' | 'typewriter' | 'handwritten' | 'mixed' | 'unknown'
export type OcrEngine = 'surya' | 'trocr' | 'mineru' | 'tesseract'

export interface Page {
  id: string
  job_id: string
  page_number: number
  status: PageStatus
  doc_type: DocType
  ocr_engine: OcrEngine | null
  handwriting_score: number
  print_quality: number
  layout_complexity: number
  degradation_level: number
  raw_ocr_text: string | null
  corrected_text: string | null
  confidence: number
  correction_ratio: number
  error_message: string | null
  created_at: string
  updated_at: string
}

export interface Job {
  id: string
  filename: string
  original_path: string | null
  output_path: string | null
  status: JobStatus
  total_pages: number
  processed_pages: number
  passed_pages: number
  warning_pages: number
  error_pages: number
  avg_confidence: number
  file_size_bytes: number
  error_message: string | null
  created_at: string
  updated_at: string
  completed_at: string | null
  pages: Page[]
}

export interface JobSummary {
  id: string
  filename: string
  status: JobStatus
  total_pages: number
  processed_pages: number
  avg_confidence: number
  error_message: string | null
  created_at: string
  updated_at: string
  completed_at: string | null
}

export interface SystemStatus {
  gpu_available: boolean
  gpu_name: string | null
  gpu_vram_total_gb: number | null
  gpu_vram_free_gb: number | null
  ollama_online: boolean
  models_loaded: string[]
  queue_size: number
  active_jobs: number
}

export interface WatcherStatus {
  watching: boolean
  paths: string[]
  pending_files: number
}

export interface WsEvent {
  type: 'job_started' | 'job_progress' | 'job_finished' | 'job_error'
  job_id: string
  stage?: string
  page?: number
  total_pages?: number
  engine?: string
  doc_type?: string
  status?: string
  avg_confidence?: number
  error?: string
  message?: string
}

import { useJob } from '../hooks/useJobs'
import { StatusBadge } from './common/StatusBadge'
import { ProgressBar } from './common/ProgressBar'
import { LoadingSpinner } from './common/LoadingSpinner'
import { X, PenLine, Type, Layout, AlertTriangle, CheckCircle2 } from 'lucide-react'
import type { Page } from '../types'
import clsx from 'clsx'

interface Props {
  jobId: string
  onClose: () => void
}

const engineLabels: Record<string, string> = {
  surya: 'Surya OCR',
  trocr: 'TrOCR (manuscrito)',
  mineru: 'MinerU',
  tesseract: 'Tesseract',
}

const docTypeIcons: Record<string, JSX.Element> = {
  handwritten: <PenLine className="w-3.5 h-3.5" />,
  typewriter:  <Type className="w-3.5 h-3.5" />,
  printed:     <Layout className="w-3.5 h-3.5" />,
  mixed:       <Layout className="w-3.5 h-3.5" />,
  unknown:     <Layout className="w-3.5 h-3.5" />,
}

function PageRow({ page }: { page: Page }) {
  const conf = page.confidence
  const confColor = conf >= 0.8 ? 'text-emerald-400' : conf >= 0.6 ? 'text-amber-400' : 'text-red-400'

  return (
    <div className="border border-surface-border rounded-lg p-3 text-xs">
      <div className="flex items-center justify-between gap-2 mb-2">
        <div className="flex items-center gap-2">
          <span className="text-muted font-mono">p.{page.page_number + 1}</span>
          <StatusBadge status={page.status} size="sm" />
          <span className="flex items-center gap-1 text-muted">
            {docTypeIcons[page.doc_type] ?? docTypeIcons.unknown}
            {page.doc_type}
          </span>
          {page.ocr_engine && (
            <span className="text-accent/70">{engineLabels[page.ocr_engine] ?? page.ocr_engine}</span>
          )}
        </div>
        <span className={clsx('font-mono font-medium', confColor)}>
          {(conf * 100).toFixed(0)}%
        </span>
      </div>

      {page.status === 'COMPLETED' && (
        <ProgressBar value={conf * 100} color={conf >= 0.8 ? 'success' : conf >= 0.6 ? 'warning' : 'error'} size="sm" />
      )}

      {page.status === 'ERROR' && page.error_message && (
        <p className="mt-1 text-red-400 flex items-center gap-1">
          <AlertTriangle className="w-3 h-3 flex-shrink-0" />
          {page.error_message}
        </p>
      )}

      {page.corrected_text && (
        <details className="mt-2">
          <summary className="cursor-pointer text-accent/80 hover:text-accent">Ver texto corregido</summary>
          <pre className="mt-1 p-2 bg-surface rounded font-mono text-[10px] text-slate-300 whitespace-pre-wrap max-h-40 overflow-y-auto">
            {page.corrected_text.slice(0, 800)}
            {page.corrected_text.length > 800 && '...'}
          </pre>
        </details>
      )}
    </div>
  )
}

export function JobDetail({ jobId, onClose }: Props) {
  const { data: job, isLoading } = useJob(jobId)

  if (isLoading) return (
    <div className="flex items-center justify-center h-40">
      <LoadingSpinner />
    </div>
  )

  if (!job) return null

  const progress = job.total_pages > 0 ? (job.processed_pages / job.total_pages) * 100 : 0

  return (
    <div className="bg-surface-card border border-surface-border rounded-xl overflow-hidden flex flex-col h-full">
      {/* Header */}
      <div className="px-5 py-4 border-b border-surface-border flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-white font-semibold text-sm truncate">{job.filename}</p>
          <div className="flex items-center gap-2 mt-1">
            <StatusBadge status={job.status} />
            <span className="text-xs text-muted">{job.total_pages} páginas</span>
            {job.avg_confidence > 0 && (
              <span className="text-xs text-muted">· {(job.avg_confidence * 100).toFixed(0)}% confianza</span>
            )}
          </div>
        </div>
        <button onClick={onClose} className="text-muted hover:text-white transition-colors flex-shrink-0">
          <X className="w-4 h-4" />
        </button>
      </div>

      {/* Stats */}
      <div className="px-5 py-3 border-b border-surface-border">
        <div className="grid grid-cols-3 gap-3 text-center">
          {[
            { label: 'Pasaron', value: job.passed_pages, color: 'text-emerald-400' },
            { label: 'Advertencia', value: job.warning_pages, color: 'text-amber-400' },
            { label: 'Error', value: job.error_pages, color: 'text-red-400' },
          ].map(s => (
            <div key={s.label} className="bg-surface rounded-lg py-2">
              <p className={`text-xl font-bold ${s.color}`}>{s.value}</p>
              <p className="text-xs text-muted">{s.label}</p>
            </div>
          ))}
        </div>
        <div className="mt-3">
          <div className="flex justify-between text-xs text-muted mb-1">
            <span>Progreso</span>
            <span>{job.processed_pages} / {job.total_pages}</span>
          </div>
          <ProgressBar value={progress} showLabel />
        </div>
      </div>

      {/* Pages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-2">
        {job.pages.length === 0 && (
          <p className="text-center text-muted text-sm py-8">Procesando páginas…</p>
        )}
        {job.pages.map(page => <PageRow key={page.id} page={page} />)}
      </div>

      {/* Output link */}
      {job.output_path && (
        <div className="px-5 py-3 border-t border-surface-border">
          <div className="flex items-center gap-2 text-xs">
            <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
            <span className="text-muted">Salida:</span>
            <span className="text-accent font-mono truncate">{job.output_path}</span>
          </div>
        </div>
      )}
    </div>
  )
}

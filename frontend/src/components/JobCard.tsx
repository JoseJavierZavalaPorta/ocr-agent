import { FileText, RotateCcw, Trash2, ChevronRight } from 'lucide-react'
import { StatusBadge } from './common/StatusBadge'
import { ProgressBar } from './common/ProgressBar'
import { useRetryJob, useDeleteJob } from '../hooks/useJobs'
import type { JobSummary } from '../types'

interface Props {
  job: JobSummary
  onSelect: (id: string) => void
  isSelected: boolean
}

const ACTIVE_STATUSES = new Set(['QUEUED', 'PREPROCESSING', 'OCR', 'CORRECTING', 'VALIDATING'])

function confidenceColor(c: number): 'success' | 'warning' | 'error' {
  if (c >= 0.8) return 'success'
  if (c >= 0.6) return 'warning'
  return 'error'
}

function fmt(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 ** 2).toFixed(1)} MB`
}

export function JobCard({ job, onSelect, isSelected }: Props) {
  const retry = useRetryJob()
  const del = useDeleteJob()
  const isActive = ACTIVE_STATUSES.has(job.status)
  const progress = job.total_pages > 0 ? (job.processed_pages / job.total_pages) * 100 : 0

  return (
    <div
      onClick={() => onSelect(job.id)}
      className={`
        group rounded-xl border cursor-pointer transition-all duration-150
        ${isSelected
          ? 'border-accent bg-surface-hover'
          : 'border-surface-border bg-surface-card hover:border-accent/40 hover:bg-surface-hover'
        }
      `}
    >
      <div className="p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-start gap-3 min-w-0 flex-1">
            <div className="mt-0.5 w-8 h-8 rounded-lg bg-surface-border flex items-center justify-center flex-shrink-0">
              <FileText className="w-4 h-4 text-muted" />
            </div>
            <div className="min-w-0">
              <p className="text-white text-sm font-medium truncate">{job.filename}</p>
              <p className="text-muted text-xs mt-0.5">
                {job.total_pages} págs · {new Date(job.created_at).toLocaleString('es-PE')}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2 flex-shrink-0">
            <StatusBadge status={job.status} size="sm" />
            <ChevronRight className="w-4 h-4 text-muted group-hover:text-accent transition-colors" />
          </div>
        </div>

        {isActive && (
          <div className="mt-3">
            <ProgressBar value={progress} color="accent" size="sm" showLabel />
          </div>
        )}

        {job.status === 'COMPLETED' && (
          <div className="mt-3">
            <ProgressBar
              value={job.avg_confidence * 100}
              color={confidenceColor(job.avg_confidence)}
              size="sm"
              showLabel
            />
            <p className="text-xs text-muted mt-1">Confianza promedio</p>
          </div>
        )}

        {job.status === 'ERROR' && job.error_message && (
          <p className="mt-2 text-xs text-red-400 truncate">{job.error_message}</p>
        )}
      </div>

      <div className="px-4 pb-3 flex items-center justify-end gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
        {(job.status === 'ERROR' || job.status === 'PARTIAL') && (
          <button
            onClick={e => { e.stopPropagation(); retry.mutate(job.id) }}
            className="flex items-center gap-1 text-xs text-accent hover:text-accent-light transition-colors px-2 py-1 rounded-lg hover:bg-accent/10"
          >
            <RotateCcw className="w-3 h-3" /> Reintentar
          </button>
        )}
        <button
          onClick={e => { e.stopPropagation(); if (confirm('¿Eliminar este job?')) del.mutate(job.id) }}
          className="flex items-center gap-1 text-xs text-muted hover:text-error transition-colors px-2 py-1 rounded-lg hover:bg-error/10"
        >
          <Trash2 className="w-3 h-3" /> Eliminar
        </button>
      </div>
    </div>
  )
}

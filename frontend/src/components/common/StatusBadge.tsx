import clsx from 'clsx'
import type { JobStatus, PageStatus } from '../../types'

type Status = JobStatus | PageStatus

const styles: Record<string, string> = {
  PENDING:       'bg-slate-700 text-slate-300',
  QUEUED:        'bg-blue-900/60 text-blue-300',
  PREPROCESSING: 'bg-indigo-900/60 text-indigo-300',
  OCR:           'bg-violet-900/60 text-violet-300',
  CORRECTING:    'bg-purple-900/60 text-purple-300',
  VALIDATING:    'bg-sky-900/60 text-sky-300',
  COMPLETED:     'bg-emerald-900/60 text-emerald-300',
  PARTIAL:       'bg-amber-900/60 text-amber-300',
  ERROR:         'bg-red-900/60 text-red-300',
}

const labels: Record<string, string> = {
  PENDING:       'Pendiente',
  QUEUED:        'En cola',
  PREPROCESSING: 'Preprocesando',
  OCR:           'OCR',
  CORRECTING:    'Corrigiendo',
  VALIDATING:    'Validando',
  COMPLETED:     'Completado',
  PARTIAL:       'Parcial',
  ERROR:         'Error',
}

interface Props {
  status: Status
  size?: 'sm' | 'md'
}

export function StatusBadge({ status, size = 'md' }: Props) {
  return (
    <span className={clsx(
      'inline-flex items-center rounded-full font-medium',
      size === 'sm' ? 'px-2 py-0.5 text-xs' : 'px-2.5 py-1 text-xs',
      styles[status] ?? 'bg-slate-700 text-slate-300',
    )}>
      {labels[status] ?? status}
    </span>
  )
}

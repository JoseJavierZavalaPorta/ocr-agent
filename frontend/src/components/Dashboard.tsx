import { useState, useCallback, useRef } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useJobs, useUploadPdf } from '../hooks/useJobs'
import { useWebSocket } from '../hooks/useWebSocket'
import { JobCard } from './JobCard'
import { JobDetail } from './JobDetail'
import { ConfigPanel } from './ConfigPanel'
import { LoadingSpinner } from './common/LoadingSpinner'
import { Upload, Settings, List, AlertTriangle, CheckCircle2, Clock, RefreshCw } from 'lucide-react'
import clsx from 'clsx'
import type { WsEvent } from '../types'

type Tab = 'active' | 'completed' | 'errors' | 'config'

const tabs: { id: Tab; label: string; icon: JSX.Element }[] = [
  { id: 'active',    label: 'Activos',     icon: <Clock className="w-4 h-4" /> },
  { id: 'completed', label: 'Completados', icon: <CheckCircle2 className="w-4 h-4" /> },
  { id: 'errors',    label: 'Errores',     icon: <AlertTriangle className="w-4 h-4" /> },
  { id: 'config',    label: 'Configurar',  icon: <Settings className="w-4 h-4" /> },
]

const STATUS_MAP: Record<Tab, string | undefined> = {
  active:    undefined,
  completed: 'COMPLETED',
  errors:    'ERROR',
  config:    undefined,
}

export function Dashboard() {
  const [tab, setTab] = useState<Tab>('active')
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null)
  const [isDragging, setIsDragging] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const qc = useQueryClient()

  const activeJobs = useJobs(undefined)
  const completedJobs = useJobs('COMPLETED')
  const errorJobs = useJobs('ERROR')

  const upload = useUploadPdf()

  // WebSocket: invalidar queries cuando llegan eventos
  const handleWsEvent = useCallback((event: WsEvent) => {
    qc.invalidateQueries({ queryKey: ['jobs'] })
    if (selectedJobId === event.job_id) {
      qc.invalidateQueries({ queryKey: ['job', event.job_id] })
    }
  }, [qc, selectedJobId])

  useWebSocket(handleWsEvent)

  const handleFiles = (files: FileList | null) => {
    if (!files) return
    Array.from(files).forEach(f => {
      if (f.name.endsWith('.pdf')) upload.mutate(f)
    })
  }

  const jobsForTab = () => {
    if (tab === 'active') return activeJobs.data?.filter(j => !['COMPLETED', 'ERROR'].includes(j.status)) ?? []
    if (tab === 'completed') return completedJobs.data ?? []
    if (tab === 'errors') return errorJobs.data ?? []
    return []
  }

  const isLoading = activeJobs.isLoading || completedJobs.isLoading || errorJobs.isLoading

  return (
    <div className="flex flex-1 overflow-hidden">
      {/* Sidebar */}
      <aside className="w-80 border-r border-surface-border flex flex-col bg-surface-card">
        {/* Tabs */}
        <div className="flex border-b border-surface-border px-2 pt-2">
          {tabs.map(t => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={clsx(
                'flex items-center gap-1.5 px-3 py-2 text-xs font-medium rounded-t-lg transition-colors',
                tab === t.id
                  ? 'text-white bg-surface border border-b-surface border-surface-border'
                  : 'text-muted hover:text-white',
              )}
            >
              {t.icon}
              {t.label}
              {t.id === 'active' && activeJobs.data && (
                <span className="ml-1 px-1.5 py-0.5 rounded-full bg-accent/20 text-accent text-[10px]">
                  {activeJobs.data.filter(j => !['COMPLETED', 'ERROR'].includes(j.status)).length}
                </span>
              )}
            </button>
          ))}
        </div>

        {/* Upload drop zone */}
        {tab !== 'config' && (
          <div
            onDragOver={e => { e.preventDefault(); setIsDragging(true) }}
            onDragLeave={() => setIsDragging(false)}
            onDrop={e => {
              e.preventDefault()
              setIsDragging(false)
              handleFiles(e.dataTransfer.files)
            }}
            onClick={() => fileInputRef.current?.click()}
            className={clsx(
              'mx-3 mt-3 rounded-xl border-2 border-dashed cursor-pointer transition-all text-center py-3',
              isDragging
                ? 'border-accent bg-accent/10'
                : 'border-surface-border hover:border-accent/50 hover:bg-surface-hover',
            )}
          >
            {upload.isPending
              ? <div className="flex items-center justify-center gap-2"><LoadingSpinner size="sm" /><span className="text-xs text-muted">Subiendo…</span></div>
              : <div className="flex items-center justify-center gap-2">
                  <Upload className="w-3.5 h-3.5 text-muted" />
                  <span className="text-xs text-muted">Arrastra PDFs o haz clic</span>
                </div>
            }
          </div>
        )}
        <input
          ref={fileInputRef}
          type="file"
          accept=".pdf"
          multiple
          className="hidden"
          onChange={e => handleFiles(e.target.files)}
        />

        {/* Job list */}
        <div className="flex-1 overflow-y-auto p-3 space-y-2">
          {tab === 'config' && <ConfigPanel />}
          {tab !== 'config' && isLoading && (
            <div className="flex justify-center py-8"><LoadingSpinner /></div>
          )}
          {tab !== 'config' && !isLoading && jobsForTab().length === 0 && (
            <div className="flex flex-col items-center justify-center py-12 text-muted text-xs gap-2">
              <List className="w-8 h-8 opacity-30" />
              <span>Sin jobs en esta sección</span>
            </div>
          )}
          {tab !== 'config' && jobsForTab().map(job => (
            <JobCard
              key={job.id}
              job={job}
              onSelect={setSelectedJobId}
              isSelected={selectedJobId === job.id}
            />
          ))}
        </div>
      </aside>

      {/* Main panel */}
      <main className="flex-1 overflow-y-auto p-6">
        {selectedJobId ? (
          <JobDetail
            jobId={selectedJobId}
            onClose={() => setSelectedJobId(null)}
          />
        ) : (
          <div className="flex flex-col items-center justify-center h-full text-muted">
            <div className="w-20 h-20 rounded-2xl bg-surface-card border border-surface-border flex items-center justify-center mb-4">
              <RefreshCw className="w-8 h-8 opacity-30" />
            </div>
            <p className="text-sm font-medium text-slate-400">Selecciona un job para ver el detalle</p>
            <p className="text-xs mt-1">o arrastra un PDF al panel izquierdo para procesarlo</p>
          </div>
        )}
      </main>
    </div>
  )
}

import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getConfig, getWatcherStatus, addWatchPath } from '../services/api'
import { FolderOpen, Plus, RefreshCw } from 'lucide-react'
import { LoadingSpinner } from './common/LoadingSpinner'

export function ConfigPanel() {
  const [newPath, setNewPath] = useState('')
  const qc = useQueryClient()

  const { data: config, isLoading: loadingConfig } = useQuery({
    queryKey: ['config'],
    queryFn: getConfig,
  })

  const { data: watcher, isLoading: loadingWatcher } = useQuery({
    queryKey: ['watcher'],
    queryFn: getWatcherStatus,
    refetchInterval: 10000,
  })

  const addPath = useMutation({
    mutationFn: addWatchPath,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['watcher'] })
      setNewPath('')
    },
  })

  if (loadingConfig || loadingWatcher) return (
    <div className="flex justify-center py-8"><LoadingSpinner /></div>
  )

  return (
    <div className="space-y-6 p-5">
      <section>
        <h3 className="text-white font-semibold text-sm mb-3 flex items-center gap-2">
          <FolderOpen className="w-4 h-4 text-accent" />
          Carpetas vigiladas
        </h3>

        <div className="space-y-2">
          {watcher?.paths.map(path => (
            <div key={path} className="flex items-center gap-2 px-3 py-2 bg-surface rounded-lg text-xs font-mono text-slate-300">
              <div className={`w-2 h-2 rounded-full flex-shrink-0 ${watcher.watching ? 'bg-emerald-400 animate-pulse' : 'bg-muted'}`} />
              {path}
            </div>
          ))}

          <div className="flex gap-2 mt-2">
            <input
              value={newPath}
              onChange={e => setNewPath(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && newPath && addPath.mutate(newPath)}
              placeholder="/ruta/a/carpeta"
              className="flex-1 bg-surface border border-surface-border rounded-lg px-3 py-2 text-xs text-white placeholder-muted focus:outline-none focus:border-accent font-mono"
            />
            <button
              onClick={() => newPath && addPath.mutate(newPath)}
              disabled={!newPath || addPath.isPending}
              className="px-3 py-2 bg-accent hover:bg-accent-hover text-white rounded-lg text-xs flex items-center gap-1 disabled:opacity-50 transition-colors"
            >
              {addPath.isPending ? <RefreshCw className="w-3 h-3 animate-spin" /> : <Plus className="w-3 h-3" />}
              Añadir
            </button>
          </div>
          <p className="text-xs text-muted">También se pueden poner rutas NFS/SMB ya montadas en el servidor.</p>
        </div>
      </section>

      <section>
        <h3 className="text-white font-semibold text-sm mb-3">Parámetros del pipeline</h3>
        <div className="space-y-2 text-xs">
          {config && Object.entries({
            'DPI extracción': config.pdf_extraction_dpi,
            'Umbral confianza (PASS)': `${(config.confidence_threshold_pass * 100).toFixed(0)}%`,
            'Umbral confianza (WARN)': `${(config.confidence_threshold_warn * 100).toFixed(0)}%`,
            'Umbral manuscrito': `${(config.handwriting_threshold * 100).toFixed(0)}%`,
            'Umbral layout complejo': `${(config.layout_complexity_threshold * 100).toFixed(0)}%`,
            'Modelo corrección': config.ollama_correction_model,
            'Workers Celery': config.celery_concurrency,
          }).map(([k, v]) => (
            <div key={k} className="flex justify-between py-1.5 border-b border-surface-border last:border-0">
              <span className="text-muted">{k}</span>
              <span className="text-slate-300 font-mono">{String(v)}</span>
            </div>
          ))}
        </div>
        <p className="text-xs text-muted mt-3">Para cambiar parámetros edita el archivo <code className="text-accent">.env</code> y reinicia el servicio.</p>
      </section>

      <section>
        <h3 className="text-white font-semibold text-sm mb-3">Rutas de datos</h3>
        <div className="space-y-2 text-xs font-mono">
          {config && Object.entries({
            'Entrada': config.input_path,
            'Salida': config.output_path,
            'Originales': config.originals_path,
          }).map(([k, v]) => (
            <div key={k} className="flex justify-between py-1.5 border-b border-surface-border last:border-0">
              <span className="text-muted font-sans">{k}</span>
              <span className="text-accent">{v}</span>
            </div>
          ))}
        </div>
      </section>
    </div>
  )
}

import { useQuery } from '@tanstack/react-query'
import { getSystemStatus } from '../services/api'
import { Cpu, Wifi, WifiOff, Zap } from 'lucide-react'

export function Header() {
  const { data: status } = useQuery({
    queryKey: ['system-status'],
    queryFn: getSystemStatus,
    refetchInterval: 15000,
  })

  return (
    <header className="bg-surface-card border-b border-surface-border px-6 py-3 flex items-center justify-between">
      <div className="flex items-center gap-3">
        <div className="w-8 h-8 rounded-lg bg-accent flex items-center justify-center">
          <Zap className="w-4 h-4 text-white" />
        </div>
        <div>
          <h1 className="text-white font-semibold text-sm leading-none">OCR Agent</h1>
          <p className="text-muted text-xs mt-0.5">Procesamiento offline de documentos</p>
        </div>
      </div>

      <div className="flex items-center gap-4 text-xs">
        {status?.gpu_available ? (
          <div className="flex items-center gap-1.5 text-emerald-400">
            <Cpu className="w-3.5 h-3.5" />
            <span>{status.gpu_name ?? 'GPU'}</span>
            {status.gpu_vram_free_gb != null && (
              <span className="text-muted">
                ({status.gpu_vram_free_gb}GB libre / {status.gpu_vram_total_gb}GB)
              </span>
            )}
          </div>
        ) : (
          <div className="flex items-center gap-1.5 text-muted">
            <Cpu className="w-3.5 h-3.5" />
            <span>Sin GPU</span>
          </div>
        )}

        <div className={`flex items-center gap-1.5 ${
          status === undefined ? 'text-muted' :
          status.ollama_online ? 'text-emerald-400' : 'text-red-400'
        }`}>
          {status?.ollama_online ? <Wifi className="w-3.5 h-3.5" /> : <WifiOff className="w-3.5 h-3.5" />}
          <span>Ollama {status === undefined ? '…' : status.ollama_online ? 'online' : 'offline'}</span>
        </div>

        {status?.active_jobs != null && status.active_jobs > 0 && (
          <div className="flex items-center gap-1.5 text-amber-400">
            <div className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse" />
            <span>{status.active_jobs} activo{status.active_jobs > 1 ? 's' : ''}</span>
          </div>
        )}
      </div>
    </header>
  )
}

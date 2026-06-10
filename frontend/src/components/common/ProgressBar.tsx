import clsx from 'clsx'

interface Props {
  value: number      // 0-100
  color?: 'accent' | 'success' | 'warning' | 'error'
  size?: 'sm' | 'md'
  showLabel?: boolean
}

const colorMap = {
  accent:  'bg-accent',
  success: 'bg-success',
  warning: 'bg-warning',
  error:   'bg-error',
}

export function ProgressBar({ value, color = 'accent', size = 'md', showLabel = false }: Props) {
  const pct = Math.min(100, Math.max(0, value))
  return (
    <div className="flex items-center gap-2 w-full">
      <div className={clsx(
        'flex-1 rounded-full bg-surface-border overflow-hidden',
        size === 'sm' ? 'h-1.5' : 'h-2',
      )}>
        <div
          className={clsx('h-full rounded-full transition-all duration-500', colorMap[color])}
          style={{ width: `${pct}%` }}
        />
      </div>
      {showLabel && (
        <span className="text-xs text-muted w-9 text-right font-mono">{pct.toFixed(0)}%</span>
      )}
    </div>
  )
}

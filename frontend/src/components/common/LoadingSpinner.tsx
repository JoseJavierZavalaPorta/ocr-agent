import clsx from 'clsx'

export function LoadingSpinner({ size = 'md' }: { size?: 'sm' | 'md' | 'lg' }) {
  return (
    <div className={clsx(
      'animate-spin rounded-full border-2 border-surface-border border-t-accent',
      size === 'sm' && 'w-4 h-4',
      size === 'md' && 'w-6 h-6',
      size === 'lg' && 'w-10 h-10',
    )} />
  )
}

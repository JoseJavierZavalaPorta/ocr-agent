import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getJobs, getJob, retryJob, deleteJob, uploadPdf } from '../services/api'

export function useJobs(status?: string) {
  return useQuery({
    queryKey: ['jobs', status],
    queryFn: () => getJobs(status),
    refetchInterval: 5000,
  })
}

export function useJob(id: string | null) {
  return useQuery({
    queryKey: ['job', id],
    queryFn: () => getJob(id!),
    enabled: !!id,
    refetchInterval: 3000,
  })
}

export function useRetryJob() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: retryJob,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['jobs'] }),
  })
}

export function useDeleteJob() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: deleteJob,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['jobs'] }),
  })
}

export function useUploadPdf() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: uploadPdf,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['jobs'] }),
  })
}

import axios from 'axios'
import type { Job, JobSummary, SystemStatus, WatcherStatus } from '../types'

const api = axios.create({ baseURL: '/api' })

export const getJobs = (status?: string): Promise<JobSummary[]> =>
  api.get('/jobs', { params: { status, limit: 100 } }).then(r => r.data)

export const getJob = (id: string): Promise<Job> =>
  api.get(`/jobs/${id}`).then(r => r.data)

export const retryJob = (id: string): Promise<JobSummary> =>
  api.post(`/jobs/${id}/retry`).then(r => r.data)

export const deleteJob = (id: string): Promise<void> =>
  api.delete(`/jobs/${id}`)

export const uploadPdf = (file: File): Promise<JobSummary> => {
  const form = new FormData()
  form.append('file', file)
  return api.post('/jobs/upload', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  }).then(r => r.data)
}

export const getSystemStatus = (): Promise<SystemStatus> =>
  api.get('/status').then(r => r.data)

export const getWatcherStatus = (): Promise<WatcherStatus> =>
  api.get('/watcher').then(r => r.data)

export const addWatchPath = (path: string): Promise<unknown> =>
  api.post('/watcher/add-path', null, { params: { path } }).then(r => r.data)

export const getConfig = () =>
  api.get('/config').then(r => r.data)

import axios from 'axios'
import type {
  Project,
  CostEstimate,
  AnalysisResult,
  DrawingType,
} from '../types'

const api = axios.create({
  baseURL: '/api',
  timeout: 300_000, // 5分（大量ページの解析に対応）
})

export const projectsApi = {
  create: async (name: string): Promise<Project> => {
    const { data } = await api.post('/projects', { name })
    return data
  },

  list: async (): Promise<Project[]> => {
    const { data } = await api.get('/projects')
    return data
  },

  get: async (id: string): Promise<Project> => {
    const { data } = await api.get(`/projects/${id}`)
    return data
  },

  uploadFiles: async (
    projectId: string,
    files: File[],
    typeMap: Record<string, DrawingType>
  ): Promise<{ uploaded: { file_id: string; filename: string }[] }> => {
    const formData = new FormData()
    files.forEach((f) => formData.append('files', f))
    formData.append('drawing_types', JSON.stringify(typeMap))
    const { data } = await api.post(`/projects/${projectId}/files`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    return data
  },

  estimate: async (projectId: string): Promise<CostEstimate> => {
    const { data } = await api.post(`/projects/${projectId}/estimate`)
    return data
  },

  analyze: async (projectId: string): Promise<{ message: string }> => {
    const { data } = await api.post(`/projects/${projectId}/analyze`)
    return data
  },

  getResults: async (projectId: string): Promise<AnalysisResult> => {
    const { data } = await api.get(`/projects/${projectId}/results`)
    return data
  },

  annotatedPdfUrl: (projectId: string, fileId: string): string =>
    `/api/projects/${projectId}/files/${fileId}/annotated`,
}

export const pollStatus = async (
  projectId: string,
  onStatus: (status: string) => void,
  intervalMs = 3000
): Promise<AnalysisResult> => {
  return new Promise((resolve, reject) => {
    const timer = setInterval(async () => {
      try {
        const project = await projectsApi.get(projectId)
        onStatus(project.status)
        if (project.status === 'done') {
          clearInterval(timer)
          const results = await projectsApi.getResults(projectId)
          resolve(results)
        } else if (project.status === 'error') {
          clearInterval(timer)
          reject(new Error('解析中にエラーが発生しました'))
        }
      } catch (err) {
        clearInterval(timer)
        reject(err)
      }
    }, intervalMs)
  })
}

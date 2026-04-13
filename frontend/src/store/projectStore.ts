import { create } from 'zustand'
import type { Project, CostEstimate, AnalysisResult, DrawingType } from '../types'

interface ProjectStore {
  // 現在作業中のプロジェクト
  currentProject: Project | null
  costEstimate: CostEstimate | null
  analysisResult: AnalysisResult | null
  analysisStatus: string | null

  // 選択中のファイル・ページ
  selectedFileId: string | null
  selectedPage: number

  // UI状態
  showCostModal: boolean
  isLoading: boolean

  // アクション
  setCurrentProject: (p: Project | null) => void
  setCostEstimate: (e: CostEstimate | null) => void
  setAnalysisResult: (r: AnalysisResult | null) => void
  setAnalysisStatus: (s: string | null) => void
  setSelectedFileId: (id: string | null) => void
  setSelectedPage: (page: number) => void
  setShowCostModal: (show: boolean) => void
  setIsLoading: (loading: boolean) => void
  reset: () => void
}

export const useProjectStore = create<ProjectStore>((set) => ({
  currentProject: null,
  costEstimate: null,
  analysisResult: null,
  analysisStatus: null,
  selectedFileId: null,
  selectedPage: 0,
  showCostModal: false,
  isLoading: false,

  setCurrentProject: (p) => set({ currentProject: p }),
  setCostEstimate: (e) => set({ costEstimate: e }),
  setAnalysisResult: (r) => set({ analysisResult: r }),
  setAnalysisStatus: (s) => set({ analysisStatus: s }),
  setSelectedFileId: (id) => set({ selectedFileId: id, selectedPage: 0 }),
  setSelectedPage: (page) => set({ selectedPage: page }),
  setShowCostModal: (show) => set({ showCostModal: show }),
  setIsLoading: (loading) => set({ isLoading: loading }),
  reset: () =>
    set({
      currentProject: null,
      costEstimate: null,
      analysisResult: null,
      analysisStatus: null,
      selectedFileId: null,
      selectedPage: 0,
      showCostModal: false,
      isLoading: false,
    }),
}))

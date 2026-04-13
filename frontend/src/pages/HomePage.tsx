import { useState } from 'react'
import { toast } from 'react-hot-toast'
import { PlusCircle, FolderOpen, Activity } from 'lucide-react'
import { projectsApi } from '../utils/api'
import type { DrawingType } from '../types'

interface Props {
  onProjectReady: (projectId: string) => void
}

interface FileEntry {
  file: File
  drawingType: DrawingType
}

export function HomePage({ onProjectReady }: Props) {
  const [projectName, setProjectName] = useState('')
  const [isCreating, setIsCreating] = useState(false)

  const handleCreate = async () => {
    if (!projectName.trim()) {
      toast.error('プロジェクト名を入力してください')
      return
    }
    setIsCreating(true)
    try {
      const project = await projectsApi.create(projectName.trim())
      toast.success('プロジェクトを作成しました')
      onProjectReady(project.id)
    } catch {
      toast.error('プロジェクトの作成に失敗しました')
    } finally {
      setIsCreating(false)
    }
  }

  return (
    <div className="min-h-screen bg-dark-bg flex flex-col items-center justify-center px-4">
      <div className="w-full max-w-lg">
        {/* ヘッダー */}
        <div className="text-center mb-10">
          <div className="flex items-center justify-center gap-3 mb-3">
            <Activity className="text-accent-blue" size={32} />
            <h1 className="text-2xl font-bold text-dark-text">AI検図システム</h1>
          </div>
          <p className="text-dark-muted text-sm">
            蒸気タービン起動盤図面の整合性・ロジックを AI で自動確認します
          </p>
        </div>

        {/* 新規プロジェクト */}
        <div className="bg-dark-card border border-dark-border rounded-xl p-6">
          <h2 className="text-dark-text font-semibold mb-4 flex items-center gap-2">
            <PlusCircle size={18} className="text-accent-blue" />
            新規検図プロジェクト
          </h2>
          <div className="space-y-3">
            <input
              type="text"
              placeholder="プロジェクト名（例: 〇〇発電所 起動盤 Rev.A）"
              value={projectName}
              onChange={(e) => setProjectName(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleCreate()}
              className="w-full bg-dark-surface border border-dark-border rounded-lg px-3 py-2.5 text-dark-text placeholder-dark-muted focus:outline-none focus:border-accent-blue text-sm"
            />
            <button
              onClick={handleCreate}
              disabled={isCreating || !projectName.trim()}
              className="w-full py-2.5 rounded-lg bg-accent-blue text-white font-medium hover:bg-blue-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors text-sm"
            >
              {isCreating ? '作成中…' : 'プロジェクトを作成'}
            </button>
          </div>
        </div>

        <p className="text-center text-dark-muted text-xs mt-6">
          Powered by Google Gemini 1.5 Flash
        </p>
      </div>
    </div>
  )
}

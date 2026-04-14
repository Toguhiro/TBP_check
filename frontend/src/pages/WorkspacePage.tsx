import { useState, useEffect } from 'react'
import { toast } from 'react-hot-toast'
import { ArrowLeft, Loader2, RotateCcw } from 'lucide-react'
import { FileUploader } from '../components/FileUploader'
import { CostModal } from '../components/CostModal'
import { PdfViewer } from '../components/PdfViewer'
import { ResultPanel } from '../components/ResultPanel'
import { projectsApi, pollStatus } from '../utils/api'
import type { DrawingType, CostEstimate, AnalysisResult, DrawingFile } from '../types'

interface FileEntry {
  file: File
  drawingType: DrawingType
}

type Stage = 'upload' | 'cost_confirm' | 'analyzing' | 'result'

interface Props {
  projectId: string
  onBack: () => void
}

// localStorageキー（プロジェクト別に保存）
const cacheKey = (pid: string) => `tbp_result_${pid}`

export function WorkspacePage({ projectId, onBack }: Props) {
  const [stage, setStage] = useState<Stage>('upload')
  const [isLoading, setIsLoading] = useState(false)
  const [costEstimate, setCostEstimate] = useState<CostEstimate | null>(null)
  const [analysisResult, setAnalysisResult] = useState<AnalysisResult | null>(null)
  const [analysisStatus, setAnalysisStatus] = useState<string>('')
  const [files, setFiles] = useState<DrawingFile[]>([])
  const [selectedFileId, setSelectedFileId] = useState<string | null>(null)
  const [selectedPage, setSelectedPage] = useState(0)
  const [highlightRect, setHighlightRect] = useState<[number, number, number, number] | null>(null)
  const [hasCached, setHasCached] = useState(false)

  // 起動時にキャッシュ確認
  useEffect(() => {
    try {
      const raw = localStorage.getItem(cacheKey(projectId))
      if (raw) setHasCached(true)
    } catch { /* ignore */ }
  }, [projectId])

  const fileMap: Record<string, string> = Object.fromEntries(
    files.map((f) => [f.id, f.filename])
  )

  const selectedFile = files.find((f) => f.id === selectedFileId)

  // 解析完了後に結果をキャッシュ保存
  const saveCache = (result: AnalysisResult, fileList: DrawingFile[]) => {
    try {
      localStorage.setItem(cacheKey(projectId), JSON.stringify({ result, files: fileList }))
      setHasCached(true)
    } catch { /* ignore */ }
  }

  // キャッシュから前回の結果を復元
  const loadFromCache = async () => {
    try {
      const raw = localStorage.getItem(cacheKey(projectId))
      if (!raw) return
      const { result, files: cachedFiles } = JSON.parse(raw)
      setAnalysisResult(result)
      setFiles(cachedFiles)
      if (cachedFiles.length > 0) setSelectedFileId(cachedFiles[0].id)
      setStage('result')
      toast.success('前回の解析結果を読み込みました')
    } catch {
      toast.error('キャッシュの読み込みに失敗しました')
    }
  }

  const handleUpload = async (entries: FileEntry[]) => {
    setIsLoading(true)
    try {
      const typeMap: Record<string, DrawingType> = {}
      entries.forEach((e) => (typeMap[e.file.name] = e.drawingType))

      await projectsApi.uploadFiles(projectId, entries.map((e) => e.file), typeMap)

      const estimate = await projectsApi.estimate(projectId)
      setCostEstimate(estimate)

      const project = await projectsApi.get(projectId)
      setFiles(project.files)
      if (project.files.length > 0) setSelectedFileId(project.files[0].id)

      setStage('cost_confirm')
      toast.success('コスト見積もりが完了しました')
    } catch {
      toast.error('アップロードまたはコスト推定に失敗しました')
    } finally {
      setIsLoading(false)
    }
  }

  const handleConfirmAnalysis = async () => {
    setStage('analyzing')
    try {
      await projectsApi.analyze(projectId)
      toast('解析を開始しました…', { icon: '⚙️' })

      const result = await pollStatus(projectId, (status) => {
        setAnalysisStatus(status)
      })

      setAnalysisResult(result)
      const project = await projectsApi.get(projectId)
      setFiles(project.files)
      saveCache(result, project.files)
      setStage('result')
      toast.success('解析が完了しました')
    } catch {
      toast.error('解析に失敗しました')
      setStage('cost_confirm')
    }
  }

  const statusLabel: Record<string, string> = {
    extracting: 'PDF テキスト抽出中…',
    analyzing: 'AI が解析中…',
    confirmed: '確認済み',
    done: '完了',
    error: 'エラーが発生しました',
  }

  return (
    <div className="h-screen flex flex-col bg-dark-bg text-dark-text">
      {/* ヘッダー */}
      <header className="flex items-center gap-3 px-4 py-3 bg-dark-surface border-b border-dark-border shrink-0">
        <button onClick={onBack} className="text-dark-muted hover:text-dark-text transition-colors">
          <ArrowLeft size={20} />
        </button>
        <h1 className="text-sm font-semibold text-dark-text">AI 検図システム</h1>
        <span className="text-dark-muted text-xs">/ {projectId.slice(0, 8)}</span>

        {/* 前回の結果を再読み込みボタン */}
        {hasCached && stage === 'upload' && (
          <button
            onClick={loadFromCache}
            className="ml-auto flex items-center gap-1.5 text-xs px-3 py-1.5 rounded border border-dark-border text-dark-muted hover:text-dark-text hover:border-accent-blue transition-colors"
          >
            <RotateCcw size={12} />
            前回の結果を表示
          </button>
        )}
      </header>

      {/* メインコンテンツ */}
      {stage === 'upload' && (
        <div className="flex-1 flex items-start justify-center p-8 overflow-auto">
          <div className="w-full max-w-2xl">
            <h2 className="text-dark-text font-semibold mb-4">図面 PDF をアップロード</h2>
            <FileUploader onSubmit={handleUpload} isLoading={isLoading} />
          </div>
        </div>
      )}

      {stage === 'cost_confirm' && costEstimate && (
        <div className="flex-1 flex">
          <div className="flex-1 overflow-hidden">
            {selectedFile && (
              <PdfViewer
                url={`/api/projects/${projectId}/files/${selectedFile.id}/original`}
                currentPage={selectedPage}
                onPageChange={setSelectedPage}
                filename={selectedFile.filename}
                projectId={projectId}
                fileId={selectedFile.id}
                highlightRect={highlightRect}
              />
            )}
          </div>
          <CostModal
            estimate={costEstimate}
            onConfirm={handleConfirmAnalysis}
            onCancel={() => setStage('upload')}
          />
        </div>
      )}

      {stage === 'analyzing' && (
        <div className="flex-1 flex flex-col items-center justify-center gap-4">
          <Loader2 className="animate-spin text-accent-blue" size={48} />
          <p className="text-dark-text font-medium">
            {statusLabel[analysisStatus] ?? '処理中…'}
          </p>
          <p className="text-dark-muted text-sm">ページ数によっては数分かかる場合があります</p>
        </div>
      )}

      {stage === 'result' && analysisResult && (
        <div className="flex-1 flex overflow-hidden">
          {/* ファイル選択サイドバー */}
          <div className="w-48 bg-dark-surface border-r border-dark-border flex flex-col">
            <p className="text-xs font-semibold text-dark-muted px-3 py-2 uppercase tracking-wide border-b border-dark-border">
              図面ファイル
            </p>
            <div className="flex-1 overflow-y-auto">
              {files.map((f) => (
                <button
                  key={f.id}
                  onClick={() => { setSelectedFileId(f.id); setSelectedPage(0); setHighlightRect(null) }}
                  className={`w-full text-left px-3 py-2 text-xs truncate transition-colors ${
                    selectedFileId === f.id
                      ? 'bg-dark-card text-dark-text border-l-2 border-accent-blue'
                      : 'text-dark-muted hover:text-dark-text hover:bg-dark-card/50'
                  }`}
                >
                  {f.filename}
                </button>
              ))}
            </div>
            {/* 再解析ボタン */}
            <button
              onClick={() => setStage('upload')}
              className="flex items-center gap-1.5 text-xs px-3 py-2 text-dark-muted hover:text-dark-text border-t border-dark-border transition-colors"
            >
              <RotateCcw size={11} /> 新しく解析
            </button>
          </div>

          {/* PDFビューア */}
          <div className="flex-1 overflow-hidden">
            {selectedFile && (
              <PdfViewer
                url={
                  selectedFile.annotated_path
                    ? `/api/projects/${projectId}/files/${selectedFile.id}/annotated`
                    : `/api/projects/${projectId}/files/${selectedFile.id}/original`
                }
                currentPage={selectedPage}
                onPageChange={setSelectedPage}
                filename={selectedFile.filename}
                projectId={projectId}
                fileId={selectedFile.id}
                highlightRect={highlightRect}
              />
            )}
          </div>

          {/* 結果パネル */}
          <div className="w-80 overflow-hidden">
            <ResultPanel
              result={analysisResult}
              projectId={projectId}
              fileMap={fileMap}
              onSelectFile={(fid, page, rect) => {
                setSelectedFileId(fid)
                setSelectedPage(page)
                setHighlightRect(rect ?? null)
              }}
            />
          </div>
        </div>
      )}
    </div>
  )
}

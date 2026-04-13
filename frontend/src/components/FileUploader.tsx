import { useCallback, useState } from 'react'
import { useDropzone } from 'react-dropzone'
import { Upload, X, FileText } from 'lucide-react'
import type { DrawingType } from '../types'
import { DRAWING_TYPE_LABELS } from '../types'

interface FileEntry {
  file: File
  drawingType: DrawingType
}

interface Props {
  onSubmit: (entries: FileEntry[]) => void
  isLoading: boolean
}

export function FileUploader({ onSubmit, isLoading }: Props) {
  const [entries, setEntries] = useState<FileEntry[]>([])

  const onDrop = useCallback((accepted: File[]) => {
    const newEntries = accepted
      .filter((f) => f.name.toLowerCase().endsWith('.pdf'))
      .map((f) => ({ file: f, drawingType: 'unknown' as DrawingType }))
    setEntries((prev) => {
      const existing = new Set(prev.map((e) => e.file.name))
      return [...prev, ...newEntries.filter((e) => !existing.has(e.file.name))]
    })
  }, [])

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: { 'application/pdf': ['.pdf'] },
    multiple: true,
  })

  const updateType = (filename: string, type: DrawingType) => {
    setEntries((prev) =>
      prev.map((e) => (e.file.name === filename ? { ...e, drawingType: type } : e))
    )
  }

  const remove = (filename: string) => {
    setEntries((prev) => prev.filter((e) => e.file.name !== filename))
  }

  return (
    <div className="space-y-4">
      {/* ドロップゾーン */}
      <div
        {...getRootProps()}
        className={`border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-colors ${
          isDragActive
            ? 'border-accent-blue bg-accent-blue/10'
            : 'border-dark-border hover:border-dark-muted'
        }`}
      >
        <input {...getInputProps()} />
        <Upload className="mx-auto mb-3 text-dark-muted" size={36} />
        <p className="text-dark-text font-medium">
          PDFをドラッグ＆ドロップ
        </p>
        <p className="text-dark-muted text-sm mt-1">
          またはクリックしてファイルを選択（複数可）
        </p>
      </div>

      {/* ファイルリスト */}
      {entries.length > 0 && (
        <div className="space-y-2">
          {entries.map((entry) => (
            <div
              key={entry.file.name}
              className="flex items-center gap-3 bg-dark-card border border-dark-border rounded-lg px-3 py-2"
            >
              <FileText size={16} className="text-dark-muted shrink-0" />
              <span className="text-dark-text text-sm flex-1 truncate">
                {entry.file.name}
              </span>
              <select
                value={entry.drawingType}
                onChange={(e) => updateType(entry.file.name, e.target.value as DrawingType)}
                className="bg-dark-surface border border-dark-border text-dark-text text-xs rounded px-2 py-1 focus:outline-none focus:border-accent-blue"
              >
                {(Object.entries(DRAWING_TYPE_LABELS) as [DrawingType, string][]).map(
                  ([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  )
                )}
              </select>
              <button
                onClick={() => remove(entry.file.name)}
                className="text-dark-muted hover:text-accent-red transition-colors"
              >
                <X size={14} />
              </button>
            </div>
          ))}
        </div>
      )}

      {/* 送信ボタン */}
      {entries.length > 0 && (
        <button
          onClick={() => onSubmit(entries)}
          disabled={isLoading}
          className="w-full py-2.5 rounded-lg bg-accent-blue text-white font-medium hover:bg-blue-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {isLoading
            ? 'アップロード中…'
            : `${entries.length} 件アップロード & コスト見積もり`}
        </button>
      )}
    </div>
  )
}

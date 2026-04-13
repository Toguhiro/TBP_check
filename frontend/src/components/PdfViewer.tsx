import { useState } from 'react'
import { Document, Page, pdfjs } from 'react-pdf'
import { ChevronLeft, ChevronRight, Download, ZoomIn, ZoomOut } from 'lucide-react'
import 'react-pdf/dist/Page/AnnotationLayer.css'
import 'react-pdf/dist/Page/TextLayer.css'

// PDF.js ワーカー設定
pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  'pdfjs-dist/build/pdf.worker.min.mjs',
  import.meta.url,
).toString()

interface Props {
  url: string
  currentPage: number
  onPageChange: (page: number) => void
  filename: string
  projectId: string
  fileId: string
}

export function PdfViewer({ url, currentPage, onPageChange, filename, projectId, fileId }: Props) {
  const [numPages, setNumPages] = useState<number>(0)
  const [scale, setScale] = useState(1.2)
  const [loading, setLoading] = useState(true)

  const onDocumentLoad = ({ numPages }: { numPages: number }) => {
    setNumPages(numPages)
    setLoading(false)
  }

  const goTo = (page: number) => {
    const clamped = Math.max(0, Math.min(numPages - 1, page))
    onPageChange(clamped)
  }

  return (
    <div className="flex flex-col h-full bg-dark-bg">
      {/* ツールバー */}
      <div className="flex items-center gap-2 px-4 py-2 bg-dark-surface border-b border-dark-border">
        <span className="text-dark-text text-sm font-medium truncate flex-1">{filename}</span>

        {/* ページナビ */}
        <button
          onClick={() => goTo(currentPage - 1)}
          disabled={currentPage === 0}
          className="p-1 text-dark-muted hover:text-dark-text disabled:opacity-30 transition-colors"
        >
          <ChevronLeft size={18} />
        </button>
        <span className="text-dark-muted text-sm min-w-[60px] text-center">
          {numPages > 0 ? `${currentPage + 1} / ${numPages}` : '—'}
        </span>
        <button
          onClick={() => goTo(currentPage + 1)}
          disabled={currentPage >= numPages - 1}
          className="p-1 text-dark-muted hover:text-dark-text disabled:opacity-30 transition-colors"
        >
          <ChevronRight size={18} />
        </button>

        <div className="w-px h-5 bg-dark-border mx-1" />

        {/* ズーム */}
        <button
          onClick={() => setScale((s) => Math.max(0.5, s - 0.2))}
          className="p-1 text-dark-muted hover:text-dark-text transition-colors"
        >
          <ZoomOut size={16} />
        </button>
        <span className="text-dark-muted text-xs w-10 text-center">
          {Math.round(scale * 100)}%
        </span>
        <button
          onClick={() => setScale((s) => Math.min(3.0, s + 0.2))}
          className="p-1 text-dark-muted hover:text-dark-text transition-colors"
        >
          <ZoomIn size={16} />
        </button>

        <div className="w-px h-5 bg-dark-border mx-1" />

        {/* ダウンロード（アノテーション済みPDF） */}
        <a
          href={`/api/projects/${projectId}/files/${fileId}/annotated`}
          download={`annotated_${filename}`}
          className="p-1 text-dark-muted hover:text-accent-blue transition-colors"
          title="アノテーション済みPDFをダウンロード"
        >
          <Download size={16} />
        </a>
      </div>

      {/* PDFレンダリングエリア */}
      <div className="flex-1 overflow-auto flex justify-center bg-dark-bg pt-4 pb-8">
        {loading && (
          <div className="flex items-center text-dark-muted text-sm mt-20">読み込み中…</div>
        )}
        <Document
          file={url}
          onLoadSuccess={onDocumentLoad}
          onLoadError={() => setLoading(false)}
          loading=""
        >
          <Page
            pageIndex={currentPage}
            scale={scale}
            renderAnnotationLayer={true}
            renderTextLayer={true}
            className="shadow-2xl"
          />
        </Document>
      </div>
    </div>
  )
}

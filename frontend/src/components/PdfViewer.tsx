import { useState, useRef, useEffect, useCallback } from 'react'
import { Document, Page, pdfjs } from 'react-pdf'
import { ChevronLeft, ChevronRight, Download, ZoomIn, ZoomOut } from 'lucide-react'
import 'react-pdf/dist/Page/AnnotationLayer.css'
import 'react-pdf/dist/Page/TextLayer.css'

pdfjs.GlobalWorkerOptions.workerSrc = '/pdf.worker.min.mjs'

interface Props {
  url: string
  currentPage: number
  onPageChange: (page: number) => void
  filename: string
  projectId: string
  fileId: string
  highlightRect?: [number, number, number, number] | null  // PDF座標 [x0,y0,x1,y1]
}

export function PdfViewer({ url, currentPage, onPageChange, filename, projectId, fileId, highlightRect }: Props) {
  const [numPages, setNumPages] = useState<number>(0)
  const [scale, setScale] = useState(1.0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const [containerWidth, setContainerWidth] = useState<number>(800)

  // PDF のオリジナルサイズ（react-pdf が報告するポイント単位）
  const [origSize, setOrigSize] = useState<{ w: number; h: number } | null>(null)
  // ページ wrapper div の実レンダリングサイズ（ResizeObserver で計測）
  const pageWrapperRef = useRef<HTMLDivElement>(null)
  const [renderedSize, setRenderedSize] = useState<{ w: number; h: number } | null>(null)

  // ハイライト点滅制御
  const [hlVisible, setHlVisible] = useState(true)

  // container 幅の監視
  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const obs = new ResizeObserver(([entry]) => {
      setContainerWidth(entry.contentRect.width)
    })
    obs.observe(el)
    return () => obs.disconnect()
  }, [])

  // ページ wrapper の実サイズ監視（ズーム変更・ページ切替後も正確に取得）
  const updateRenderedSize = useCallback(() => {
    const wrapper = pageWrapperRef.current
    if (!wrapper) return
    // canvas 要素を探して CSS 表示サイズを取得
    const canvas = wrapper.querySelector('canvas')
    if (canvas) {
      setRenderedSize({ w: canvas.offsetWidth, h: canvas.offsetHeight })
    } else {
      // canvas が存在しない場合は wrapper 自体のサイズを使用
      const rect = wrapper.getBoundingClientRect()
      if (rect.width > 0) setRenderedSize({ w: rect.width, h: rect.height })
    }
  }, [])

  useEffect(() => {
    if (!pageWrapperRef.current) return
    const obs = new ResizeObserver(updateRenderedSize)
    obs.observe(pageWrapperRef.current)
    return () => obs.disconnect()
  }, [updateRenderedSize])

  // ハイライトが変わったら点滅
  useEffect(() => {
    if (!highlightRect) return
    setHlVisible(true)
    let count = 0
    const interval = setInterval(() => {
      setHlVisible((v) => !v)
      count++
      if (count > 8) clearInterval(interval)
    }, 300)
    return () => clearInterval(interval)
  }, [highlightRect])

  const onDocumentLoad = ({ numPages }: { numPages: number }) => {
    setNumPages(numPages)
    setLoading(false)
    setError(null)
  }

  const goTo = (page: number) => {
    const clamped = Math.max(0, Math.min(numPages - 1, page))
    onPageChange(clamped)
  }

  const renderWidth = containerWidth * scale

  // ハイライト overlay：renderedSize（canvas 実 CSS サイズ）÷ origSize（PDF ポイント）でスケール計算
  const renderOverlay = () => {
    if (!highlightRect || !origSize || !hlVisible) return null

    const dispW = renderedSize?.w ?? renderWidth
    const dispH = renderedSize?.h ?? (renderWidth * origSize.h / origSize.w)

    // 縦横独立スケール（PDFが回転格納されている場合も正確に対応）
    const sx = dispW / origSize.w
    const sy = dispH / origSize.h

    const [x0, y0, x1, y1] = highlightRect
    const left   = Math.round(x0 * sx)
    const top    = Math.round(y0 * sy)
    const width  = Math.max(6, Math.round((x1 - x0) * sx))
    const height = Math.max(6, Math.round((y1 - y0) * sy))

    return (
      <div
        style={{
          position: 'absolute',
          left, top, width, height,
          border: '3px solid #ff2222',
          backgroundColor: 'rgba(255, 50, 50, 0.30)',
          pointerEvents: 'none',
          zIndex: 20,
          borderRadius: 3,
          boxShadow: '0 0 0 3px rgba(255,34,34,0.4), 0 0 12px rgba(255,34,34,0.3)',
        }}
      />
    )
  }

  return (
    <div className="flex flex-col h-full bg-dark-bg">
      {/* ツールバー */}
      <div className="flex items-center gap-2 px-4 py-2 bg-dark-surface border-b border-dark-border">
        <span className="text-dark-text text-sm font-medium truncate flex-1">{filename}</span>

        <button onClick={() => goTo(currentPage - 1)} disabled={currentPage === 0}
          className="p-1 text-dark-muted hover:text-dark-text disabled:opacity-30 transition-colors">
          <ChevronLeft size={18} />
        </button>
        <span className="text-dark-muted text-sm min-w-[60px] text-center">
          {numPages > 0 ? `${currentPage + 1} / ${numPages}` : '—'}
        </span>
        <button onClick={() => goTo(currentPage + 1)} disabled={currentPage >= numPages - 1}
          className="p-1 text-dark-muted hover:text-dark-text disabled:opacity-30 transition-colors">
          <ChevronRight size={18} />
        </button>

        <div className="w-px h-5 bg-dark-border mx-1" />

        <button onClick={() => setScale((s) => Math.max(0.3, s - 0.2))}
          className="p-1 text-dark-muted hover:text-dark-text transition-colors">
          <ZoomOut size={16} />
        </button>
        <span className="text-dark-muted text-xs w-10 text-center">{Math.round(scale * 100)}%</span>
        <button onClick={() => setScale((s) => Math.min(3.0, s + 0.2))}
          className="p-1 text-dark-muted hover:text-dark-text transition-colors">
          <ZoomIn size={16} />
        </button>

        <div className="w-px h-5 bg-dark-border mx-1" />

        <a href={`/api/projects/${projectId}/files/${fileId}/annotated`}
          download={`annotated_${filename}`}
          className="p-1 text-dark-muted hover:text-accent-blue transition-colors"
          title="アノテーション済みPDFをダウンロード">
          <Download size={16} />
        </a>
      </div>

      {/* PDFレンダリングエリア */}
      <div ref={containerRef} className="flex-1 overflow-auto flex justify-center bg-dark-bg pt-4 pb-8">
        {loading && (
          <div className="flex items-center text-dark-muted text-sm mt-20">読み込み中…</div>
        )}
        {error && (
          <div className="flex flex-col items-center text-red-400 text-sm mt-20 gap-2">
            <p>PDF読み込みエラー:</p>
            <p className="text-xs text-dark-muted max-w-md text-center break-all">{error}</p>
          </div>
        )}
        <Document
          file={url}
          onLoadSuccess={onDocumentLoad}
          onLoadError={(err) => { setLoading(false); setError(String(err?.message ?? err)) }}
          loading=""
        >
          <div ref={pageWrapperRef} style={{ position: 'relative', display: 'inline-block' }}>
            <Page
              pageIndex={currentPage}
              width={renderWidth}
              renderAnnotationLayer={true}
              renderTextLayer={true}
              className="shadow-2xl"
              onLoadSuccess={(page) => {
                setOrigSize({ w: page.originalWidth, h: page.originalHeight })
              }}
              onRenderSuccess={() => {
                // レンダリング完了後に実サイズを取得（少し遅延して確実に）
                requestAnimationFrame(updateRenderedSize)
              }}
            />
            {renderOverlay()}
          </div>
        </Document>
      </div>
    </div>
  )
}

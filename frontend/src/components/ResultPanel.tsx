import { useState } from 'react'
import { AlertCircle, AlertTriangle, CheckCircle, HelpCircle, Download } from 'lucide-react'
import type { AnalysisResult, CheckResult } from '../types'
import { CHECK_TYPE_LABELS } from '../types'

interface Props {
  result: AnalysisResult
  projectId: string
  fileMap: Record<string, string> // file_id → filename
  onSelectFile: (fileId: string, page: number, rect?: [number, number, number, number] | null) => void
}

type Tab = 'errors' | 'warnings' | 'ok' | 'uncertain'

export function ResultPanel({ result, projectId, fileMap, onSelectFile }: Props) {
  const [activeTab, setActiveTab] = useState<Tab>('errors')

  const errors = result.check_results.filter((r) => r.severity === 'error')
  const warnings = result.check_results.filter((r) => r.severity === 'warning')
  const ok = result.check_results.filter((r) => r.severity === 'ok')
  const { uncertain_items: uncertain } = result

  const { cost } = result
  const formatTokens = (n: number) => n.toLocaleString()
  const formatCost = (n: number) =>
    n < 0.01 ? `$${n.toFixed(4)}` : `$${n.toFixed(3)}`

  return (
    <div className="h-full flex flex-col bg-dark-surface border-l border-dark-border">
      {/* コスト表示 */}
      <div className="px-4 py-3 bg-dark-card border-b border-dark-border">
        <p className="text-xs font-semibold text-dark-muted uppercase tracking-wide mb-2">
          解析コスト（有料換算）
        </p>
        <div className="text-xs text-dark-muted space-y-0.5">
          <div className="flex justify-between">
            <span>入力</span>
            <span className="text-dark-text">{formatTokens(cost.actual_input_tokens)} tokens</span>
          </div>
          <div className="flex justify-between">
            <span>出力</span>
            <span className="text-dark-text">{formatTokens(cost.actual_output_tokens)} tokens</span>
          </div>
          <div className="flex justify-between pt-1 border-t border-dark-border mt-1">
            <span>合計コスト</span>
            <span className="text-accent-yellow font-semibold text-sm">
              {formatCost(cost.actual_cost_usd)}
            </span>
          </div>
        </div>
        <p className="text-xs text-dark-muted mt-1 leading-tight">{cost.free_tier_note}</p>
      </div>

      {/* タブ */}
      <div className="flex border-b border-dark-border">
        <TabBtn active={activeTab === 'errors'} onClick={() => setActiveTab('errors')} color="red">
          <AlertCircle size={12} /> エラー {errors.length}
        </TabBtn>
        <TabBtn active={activeTab === 'warnings'} onClick={() => setActiveTab('warnings')} color="orange">
          <AlertTriangle size={12} /> 警告 {warnings.length}
        </TabBtn>
        <TabBtn active={activeTab === 'ok'} onClick={() => setActiveTab('ok')} color="green">
          <CheckCircle size={12} /> 確認済 {ok.length}
        </TabBtn>
        <TabBtn active={activeTab === 'uncertain'} onClick={() => setActiveTab('uncertain')} color="yellow">
          <HelpCircle size={12} /> 不明 {uncertain.length}
        </TabBtn>
      </div>

      {/* 結果リスト */}
      <div className="flex-1 overflow-y-auto">
        {activeTab === 'errors' && (
          <ResultList
            items={errors}
            fileMap={fileMap}
            onSelect={onSelectFile}
            colorClass="border-l-accent-red"
          />
        )}
        {activeTab === 'warnings' && (
          <ResultList
            items={warnings}
            fileMap={fileMap}
            onSelect={onSelectFile}
            colorClass="border-l-accent-orange"
          />
        )}
        {activeTab === 'ok' && (
          <ResultList
            items={ok}
            fileMap={fileMap}
            onSelect={onSelectFile}
            colorClass="border-l-accent-green"
          />
        )}
        {activeTab === 'uncertain' && (
          <div className="p-2 space-y-2">
            {uncertain.length === 0 && (
              <p className="text-dark-muted text-sm p-4 text-center">なし</p>
            )}
            {uncertain.map((u, i) => (
              <div
                key={i}
                className="bg-dark-card border border-dark-border border-l-4 border-l-accent-yellow rounded p-3 cursor-pointer hover:bg-dark-border/30"
                onClick={() => u.file_id && onSelectFile(u.file_id, u.page, u.rect ?? null)}
              >
                <p className="text-xs font-mono text-accent-yellow">{u.text}</p>
                <p className="text-xs text-dark-muted mt-1">{u.reason}</p>
                <p className="text-xs text-dark-muted mt-0.5">
                  {u.file_id && fileMap[u.file_id] ? fileMap[u.file_id] : ''} p.{u.page + 1}
                </p>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* ダウンロードリンク */}
      <div className="p-3 border-t border-dark-border">
        <a
          href={`/api/projects/${projectId}/results/csv`}
          className="flex items-center gap-2 text-xs text-dark-muted hover:text-dark-text transition-colors"
        >
          <Download size={12} /> CSVレポートダウンロード
        </a>
      </div>
    </div>
  )
}

function TabBtn({
  active,
  onClick,
  children,
  color,
}: {
  active: boolean
  onClick: () => void
  children: React.ReactNode
  color: 'red' | 'orange' | 'green' | 'yellow'
}) {
  const colorMap = {
    red: 'text-accent-red',
    orange: 'text-accent-orange',
    green: 'text-accent-green',
    yellow: 'text-accent-yellow',
  }
  return (
    <button
      onClick={onClick}
      className={`flex-1 flex items-center justify-center gap-1 px-2 py-2 text-xs transition-colors ${
        active
          ? `${colorMap[color]} border-b-2 border-current bg-dark-card`
          : 'text-dark-muted hover:text-dark-text'
      }`}
    >
      {children}
    </button>
  )
}

function ResultList({
  items,
  fileMap,
  onSelect,
  colorClass,
}: {
  items: CheckResult[]
  fileMap: Record<string, string>
  onSelect: (fileId: string, page: number, rect?: [number, number, number, number] | null) => void
  colorClass: string
}) {
  if (items.length === 0) {
    return <p className="text-dark-muted text-sm p-4 text-center">なし</p>
  }

  return (
    <div className="p-2 space-y-2">
      {items.map((item) => (
        <div
          key={item.id}
          className={`bg-dark-card border border-dark-border border-l-4 ${colorClass} rounded p-3 cursor-pointer hover:bg-dark-border/30`}
          onClick={() => {
            if (item.file_id && item.page_number != null) {
              onSelect(item.file_id, item.page_number, item.location_rect ?? null)
            }
          }}
        >
          <div className="flex items-start justify-between gap-2">
            <span className="text-xs font-semibold text-dark-muted uppercase">
              {CHECK_TYPE_LABELS[item.check_type] ?? item.check_type}
            </span>
            {item.file_id && (
              <span className="text-xs text-dark-muted truncate max-w-[120px]">
                {fileMap[item.file_id] ?? item.file_id}
                {item.page_number != null ? ` p.${item.page_number + 1}` : ''}
              </span>
            )}
          </div>
          <p className="text-sm text-dark-text mt-1 leading-snug">{item.message}</p>
        </div>
      ))}
    </div>
  )
}

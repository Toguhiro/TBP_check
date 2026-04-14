import { useState } from 'react'
import { AlertCircle, AlertTriangle, CheckCircle, HelpCircle, Download } from 'lucide-react'
import type { AnalysisResult, CheckResult } from '../types'
import { CHECK_TYPE_LABELS } from '../types'

interface Props {
  result: AnalysisResult
  projectId: string
  fileMap: Record<string, string>
  onSelectFile: (fileId: string, page: number, rect?: [number, number, number, number] | null) => void
}

type Tab = 'errors' | 'warnings' | 'ok' | 'uncertain'

// 色定数（Tailwindに依存しない直書き）
const C = {
  bg:       '#22263a',  // dark-card
  bgHover:  '#2e3350',  // dark-border
  border:   '#2e3350',
  surface:  '#1a1d27',  // dark-surface
  text:     '#f1f5f9',  // ほぼ白 → メイン説明文
  label:    '#cbd5e1',  // やや明るいグレー → チェック種別
  sub:      '#94a3b8',  // 薄めグレー → ファイル名等
  muted:    '#64748b',  // かなり薄い → 補足
  red:      '#ef4444',
  orange:   '#f97316',
  green:    '#22c55e',
  yellow:   '#eab308',
  blue:     '#3b82f6',
}

export function ResultPanel({ result, projectId, fileMap, onSelectFile }: Props) {
  const [activeTab, setActiveTab] = useState<Tab>('errors')

  const errors   = result.check_results.filter((r) => r.severity === 'error')
  const warnings = result.check_results.filter((r) => r.severity === 'warning')
  const ok       = result.check_results.filter((r) => r.severity === 'ok')
  const { uncertain_items: uncertain } = result

  const { cost } = result
  const formatTokens = (n: number) => n.toLocaleString()
  const formatCost   = (n: number) => n < 0.01 ? `$${n.toFixed(4)}` : `$${n.toFixed(3)}`

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', background: C.surface, borderLeft: `1px solid ${C.border}` }}>
      {/* コスト表示 */}
      <div style={{ padding: '12px 16px', background: C.bg, borderBottom: `1px solid ${C.border}` }}>
        <p style={{ fontSize: 11, fontWeight: 600, color: C.sub, textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 8 }}>
          解析コスト（有料換算）
        </p>
        <div style={{ fontSize: 12, color: C.sub }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 2 }}>
            <span>入力</span>
            <span style={{ color: C.text }}>{formatTokens(cost.actual_input_tokens)} tokens</span>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
            <span>出力</span>
            <span style={{ color: C.text }}>{formatTokens(cost.actual_output_tokens)} tokens</span>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', borderTop: `1px solid ${C.border}`, paddingTop: 6 }}>
            <span>合計コスト</span>
            <span style={{ color: C.yellow, fontWeight: 700, fontSize: 14 }}>{formatCost(cost.actual_cost_usd)}</span>
          </div>
        </div>
        <p style={{ fontSize: 11, color: C.muted, marginTop: 4 }}>{cost.free_tier_note}</p>
      </div>

      {/* タブ */}
      <div style={{ display: 'flex', borderBottom: `1px solid ${C.border}` }}>
        <TabBtn active={activeTab === 'errors'}   onClick={() => setActiveTab('errors')}   color={C.red}    icon={<AlertCircle size={12}/>}   label={`エラー ${errors.length}`}   />
        <TabBtn active={activeTab === 'warnings'} onClick={() => setActiveTab('warnings')} color={C.orange} icon={<AlertTriangle size={12}/>} label={`警告 ${warnings.length}`}  />
        <TabBtn active={activeTab === 'ok'}       onClick={() => setActiveTab('ok')}       color={C.green}  icon={<CheckCircle size={12}/>}   label={`確認済 ${ok.length}`}       />
        <TabBtn active={activeTab === 'uncertain'}onClick={() => setActiveTab('uncertain')}color={C.yellow} icon={<HelpCircle size={12}/>}    label={`不明 ${uncertain.length}`}  />
      </div>

      {/* 結果リスト */}
      <div style={{ flex: 1, overflowY: 'auto' }}>
        {activeTab === 'errors'   && <ResultList items={errors}   fileMap={fileMap} onSelect={onSelectFile} accentColor={C.red}    />}
        {activeTab === 'warnings' && <ResultList items={warnings} fileMap={fileMap} onSelect={onSelectFile} accentColor={C.orange} />}
        {activeTab === 'ok'       && <ResultList items={ok}       fileMap={fileMap} onSelect={onSelectFile} accentColor={C.green}  />}
        {activeTab === 'uncertain' && (
          <div style={{ padding: 8 }}>
            {uncertain.length === 0 && (
              <p style={{ color: C.sub, fontSize: 13, textAlign: 'center', padding: 16 }}>なし</p>
            )}
            {uncertain.map((u, i) => (
              <div
                key={i}
                onClick={() => u.file_id && onSelectFile(u.file_id, u.page, u.rect ?? null)}
                style={{
                  background: C.bg,
                  border: `1px solid ${C.border}`,
                  borderLeft: `4px solid ${C.yellow}`,
                  borderRadius: 4,
                  padding: 12,
                  marginBottom: 8,
                  cursor: 'pointer',
                }}
                onMouseEnter={e => (e.currentTarget.style.background = C.bgHover)}
                onMouseLeave={e => (e.currentTarget.style.background = C.bg)}
              >
                <p style={{ fontSize: 12, fontFamily: 'monospace', color: C.yellow, fontWeight: 700 }}>{u.text}</p>
                <p style={{ fontSize: 12, color: C.text, marginTop: 4 }}>{u.reason}</p>
                <p style={{ fontSize: 11, color: C.sub, marginTop: 2 }}>
                  {u.file_id && fileMap[u.file_id] ? fileMap[u.file_id] : ''} p.{u.page + 1}
                </p>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* CSVダウンロード */}
      <div style={{ padding: '10px 12px', borderTop: `1px solid ${C.border}` }}>
        <a
          href={`/api/projects/${projectId}/results/csv`}
          style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: C.sub, textDecoration: 'none' }}
          onMouseEnter={e => (e.currentTarget.style.color = C.text)}
          onMouseLeave={e => (e.currentTarget.style.color = C.sub)}
        >
          <Download size={12} /> CSVレポートダウンロード
        </a>
      </div>
    </div>
  )
}

function TabBtn({
  active, onClick, color, icon, label,
}: {
  active: boolean
  onClick: () => void
  color: string
  icon: React.ReactNode
  label: string
}) {
  return (
    <button
      onClick={onClick}
      style={{
        flex: 1,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 4,
        padding: '8px 4px',
        fontSize: 11,
        border: 'none',
        borderBottom: active ? `2px solid ${color}` : '2px solid transparent',
        background: active ? '#22263a' : 'transparent',
        color: active ? color : '#64748b',
        cursor: 'pointer',
        transition: 'color 0.15s',
      }}
    >
      {icon} {label}
    </button>
  )
}

function ResultList({
  items,
  fileMap,
  onSelect,
  accentColor,
}: {
  items: CheckResult[]
  fileMap: Record<string, string>
  onSelect: (fileId: string, page: number, rect?: [number, number, number, number] | null) => void
  accentColor: string
}) {
  if (items.length === 0) {
    return <p style={{ color: '#64748b', fontSize: 13, textAlign: 'center', padding: 16 }}>なし</p>
  }

  return (
    <div style={{ padding: 8 }}>
      {items.map((item) => (
        <div
          key={item.id}
          onClick={() => {
            if (item.file_id && item.page_number != null) {
              onSelect(item.file_id, item.page_number, item.location_rect ?? null)
            }
          }}
          style={{
            background: '#22263a',
            border: `1px solid #2e3350`,
            borderLeft: `4px solid ${accentColor}`,
            borderRadius: 4,
            padding: 12,
            marginBottom: 8,
            cursor: item.file_id ? 'pointer' : 'default',
          }}
          onMouseEnter={e => { if (item.file_id) e.currentTarget.style.background = '#2e3350' }}
          onMouseLeave={e => { e.currentTarget.style.background = '#22263a' }}
        >
          <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 8, marginBottom: 6 }}>
            <span style={{ fontSize: 11, fontWeight: 700, color: '#cbd5e1', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
              {CHECK_TYPE_LABELS[item.check_type] ?? item.check_type}
            </span>
            {item.file_id && (
              <span style={{ fontSize: 11, color: '#94a3b8', maxWidth: 130, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {fileMap[item.file_id] ?? item.file_id}
                {item.page_number != null ? ` p.${item.page_number + 1}` : ''}
              </span>
            )}
          </div>
          {/* メイン説明文：白・太字で確実に目立たせる */}
          <p style={{ fontSize: 13, fontWeight: 600, color: '#f1f5f9', lineHeight: 1.5, margin: 0 }}>
            {item.message}
          </p>
        </div>
      ))}
    </div>
  )
}

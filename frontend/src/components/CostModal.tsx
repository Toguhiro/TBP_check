import type { CostEstimate } from '../types'

interface Props {
  estimate: CostEstimate
  onConfirm: () => void
  onCancel: () => void
}

export function CostModal({ estimate, onConfirm, onCancel }: Props) {
  const formatTokens = (n: number) => n.toLocaleString()
  const formatCost = (n: number) =>
    n < 0.01 ? `$${n.toFixed(4)}` : `$${n.toFixed(3)}`

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70">
      <div className="bg-dark-card border border-dark-border rounded-xl shadow-2xl w-full max-w-md p-6">
        <h2 className="text-lg font-semibold text-dark-text mb-4 flex items-center gap-2">
          <span className="text-accent-yellow">⚠</span> 解析前コスト確認
        </h2>

        <div className="space-y-2 text-sm text-dark-muted mb-6">
          <Row label="対象ファイル" value={`${estimate.file_count} 件`} />
          <Row label="総ページ数" value={`${estimate.total_pages} ページ`} />
          <hr className="border-dark-border my-3" />
          <Row
            label="推定入力トークン"
            value={`約 ${formatTokens(estimate.estimated_input_tokens)}`}
          />
          <Row
            label="推定出力トークン"
            value={`約 ${formatTokens(estimate.estimated_output_tokens)}`}
          />
          <hr className="border-dark-border my-3" />
          <Row
            label="推定コスト"
            value={formatCost(estimate.estimated_cost_usd)}
            highlight
          />
          <p className="text-xs text-dark-muted mt-2 leading-relaxed">
            ※ {estimate.free_tier_note}
          </p>
        </div>

        <div className="flex gap-3 justify-end">
          <button
            onClick={onCancel}
            className="px-4 py-2 rounded-lg border border-dark-border text-dark-muted hover:text-dark-text hover:border-dark-text transition-colors text-sm"
          >
            キャンセル
          </button>
          <button
            onClick={onConfirm}
            className="px-5 py-2 rounded-lg bg-accent-blue text-white font-medium hover:bg-blue-600 transition-colors text-sm"
          >
            解析を実行
          </button>
        </div>
      </div>
    </div>
  )
}

function Row({
  label,
  value,
  highlight = false,
}: {
  label: string
  value: string
  highlight?: boolean
}) {
  return (
    <div className="flex justify-between">
      <span>{label}</span>
      <span className={highlight ? 'text-accent-yellow font-semibold text-base' : 'text-dark-text'}>
        {value}
      </span>
    </div>
  )
}

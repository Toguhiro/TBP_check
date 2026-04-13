# 蒸気タービン起動盤図面 AI検図システム

電気図面（外形図・部品図・内部部品配置図・単線結線図・展開接続図・シーケンスロジック図）の整合性・ロジックを AI で自動確認するWEBアプリ。

## 技術スタック

| 層 | 技術 |
|---|---|
| フロントエンド | React 18 + TypeScript + Tailwind CSS（ダークUI） |
| バックエンド | Python 3.11 + FastAPI |
| PDF 抽出 | pdfplumber + PyMuPDF |
| OCR | Tesseract（日本語+英語）→ Azure Form Recognizer（フォールバック）|
| AI 解析 | Google Gemini 1.5 Flash |
| DB | SQLite（試作）→ PostgreSQL（本番移行容易）|
| インフラ | AWS EC2 + Docker Compose + Nginx |

## セットアップ

### 1. 環境変数設定

```bash
cp .env.example .env
# .env を編集して GEMINI_API_KEY を設定
```

### 2. 本番起動（Docker）

```bash
docker compose up -d --build
```

`http://<EC2のIP>` でアクセスできます。

### 3. 開発環境起動

```bash
docker compose -f docker-compose.dev.yml up
```

- フロントエンド: http://localhost:3000
- バックエンド API: http://localhost:8000
- API ドキュメント: http://localhost:8000/docs

## 検図項目

| チェック | 内容 |
|---|---|
| Tag.No 整合 | 全図面でTag.Noと機器名称が一致しているか |
| 顧客名称 | 全シートの表題欄で顧客名が一致しているか |
| リレー参照 | コイルと接点の参照先シートが整合しているか |
| 単線↔展開接続 | 両図面でTag.No・接続が一致しているか |
| 電気諸元 | 電圧・電流値がJIS規格に適合しているか |
| 遮断器定格 | JIS C 8201準拠の標準定格かどうか |
| ロジック整合 | シーケンス・インターロック論理の矛盾 |

## アノテーション凡例

| 色 | 意味 |
|---|---|
| 黄色 | 確認済み（正常） |
| 赤色 | エラー（修正必要） |
| オレンジ | 警告・AI判断困難（要手動確認） |
| 青色 | リレー参照ハイパーリンク |

## ブランチ戦略

- `main`: 本番
- `develop`: 開発統合
- `feature/*`: 機能追加

## 将来の拡張

- Claude API への切り替え（`AIEngine` 抽象クラスで差し替え可能）
- Azure OCR フォールバックの有効化
- Ollama + ローカル LLM（GPU インスタンス利用時）
- ユーザー認証（社内ユーザー管理）

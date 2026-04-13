@echo off
echo AI検図システム 開発サーバー起動中...

start "Backend" cmd /k "cd /d %~dp0backend && venv\Scripts\python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"
timeout /t 3 /nobreak >nul
start "Frontend" cmd /k "cd /d %~dp0frontend && npm run dev -- --host 0.0.0.0"

echo.
echo バックエンド: http://localhost:8000
echo フロントエンド: http://localhost:3000
echo API ドキュメント: http://localhost:8000/docs
echo.
echo 各ウィンドウを閉じるとサーバーが停止します。

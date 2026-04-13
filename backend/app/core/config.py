from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache
from pathlib import Path
from dotenv import load_dotenv

# .env を常に上書きでロード（override=True で既存 os.environ より優先）
_ENV_FILE = Path(__file__).parent.parent.parent / ".env"
load_dotenv(dotenv_path=str(_ENV_FILE), override=True, encoding="utf-8")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    app_name: str = "Drawing Checker API"
    debug: bool = False

    # AI Engine: "claude" or "gemini"
    ai_engine: str = "gemini"

    # Claude API
    anthropic_api_key: str = ""
    claude_model: str = "claude-haiku-4-5-20251001"

    # Claude pricing (USD per 1M tokens)
    claude_input_price_per_1m: float = 0.80
    claude_output_price_per_1m: float = 4.00

    # Gemini API
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"
    gemini_input_price_per_1m: float = 0.10
    gemini_output_price_per_1m: float = 0.40

    # Active pricing aliases
    @property
    def input_price_per_1m(self) -> float:
        return self.claude_input_price_per_1m if self.ai_engine == "claude" else self.gemini_input_price_per_1m

    @property
    def output_price_per_1m(self) -> float:
        return self.claude_output_price_per_1m if self.ai_engine == "claude" else self.gemini_output_price_per_1m

    # Storage
    upload_dir: str = "C:/Users/N9635793/Desktop/Claude Code/drawing-checker/data/uploads"
    output_dir: str = "C:/Users/N9635793/Desktop/Claude Code/drawing-checker/data/outputs"

    # 解析ページ範囲（プロトタイプ用、0-indexed）
    analysis_page_start: int = 0   # 開始ページ（0=先頭）
    analysis_page_end: int = 20    # 終了ページ（exclusive）

    # OCR
    tesseract_cmd: str = "tesseract"
    ocr_text_threshold: int = 50
    ocr_confidence_threshold: float = 60.0

    # Azure Form Recognizer (optional fallback)
    azure_form_recognizer_endpoint: str = ""
    azure_form_recognizer_key: str = ""

    # DB
    database_url: str = "sqlite+aiosqlite:///./drawing_checker.db"

    # CORS
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:80"]


@lru_cache()
def get_settings() -> Settings:
    return Settings()

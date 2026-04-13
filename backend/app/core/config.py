from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    app_name: str = "Drawing Checker API"
    debug: bool = False

    # Gemini API
    gemini_api_key: str = ""
    gemini_model: str = "gemini-1.5-flash"

    # Gemini pricing (USD per 1M tokens) — used for cost display even in free tier
    gemini_input_price_per_1m: float = 0.075
    gemini_output_price_per_1m: float = 0.300

    # Storage
    upload_dir: str = "/tmp/drawing_checker/uploads"
    output_dir: str = "/tmp/drawing_checker/outputs"

    # OCR
    tesseract_cmd: str = "tesseract"
    ocr_text_threshold: int = 50  # characters per page; below this → OCR needed
    ocr_confidence_threshold: float = 60.0  # below this → Azure fallback

    # Azure Form Recognizer (optional fallback)
    azure_form_recognizer_endpoint: str = ""
    azure_form_recognizer_key: str = ""

    # DB
    database_url: str = "sqlite+aiosqlite:///./drawing_checker.db"

    # CORS
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:80"]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    return Settings()

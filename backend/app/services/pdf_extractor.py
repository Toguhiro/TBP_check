"""
PDFテキスト・座標抽出サービス
pdfplumber でテキスト/表/座標を抽出し、必要に応じてOCRを実行する
"""
import os
import base64
import logging
from pathlib import Path
from typing import Optional
import pdfplumber
import fitz  # PyMuPDF
from PIL import Image
import io

from app.core.config import get_settings
from app.services.text_normalizer import normalize_text

logger = logging.getLogger(__name__)
settings = get_settings()

# Tesseractのパスが環境変数で設定されている場合
try:
    import pytesseract
    if settings.tesseract_cmd and settings.tesseract_cmd != "tesseract":
        pytesseract.pytesseract.tesseract_cmd = settings.tesseract_cmd
    TESSERACT_AVAILABLE = True
except ImportError:
    TESSERACT_AVAILABLE = False
    logger.warning("pytesseract not available, OCR disabled")


class PageData:
    """1ページ分の抽出データ"""
    def __init__(self, page_number: int):
        self.page_number = page_number
        self.raw_text: str = ""
        self.normalized_text: str = ""
        self.words: list[dict] = []       # [{text, x0, y0, x1, y1, fontsize}]
        self.tables: list[list] = []      # pdfplumber tables
        self.ocr_used: str = "none"       # none / tesseract / azure
        self.image_base64: Optional[str] = None  # page rendered as PNG for AI

    def to_dict(self) -> dict:
        return {
            "page_number": self.page_number,
            "normalized_text": self.normalized_text,
            "words": self.words,
            "tables": self.tables,
            "ocr_used": self.ocr_used,
        }


def extract_pdf(pdf_path: str, render_images: bool = True) -> list[PageData]:
    """
    PDFから全ページのテキスト・座標・画像を抽出する
    render_images=True: Gemini送信用にページ画像も生成する
    """
    results: list[PageData] = []

    with pdfplumber.open(pdf_path) as pdf:
        doc = fitz.open(pdf_path)

        for i, page in enumerate(pdf.pages):
            page_data = PageData(page_number=i)

            # --- テキスト抽出 ---
            raw_text = page.extract_text(x_tolerance=3, y_tolerance=3) or ""

            # 単語レベル（座標付き）
            words = page.extract_words(
                x_tolerance=3,
                y_tolerance=3,
                keep_blank_chars=False,
                use_text_flow=True,
            )
            page_data.words = [
                {
                    "text": w["text"],
                    "x0": w["x0"], "y0": w["top"],
                    "x1": w["x1"], "y1": w["bottom"],
                }
                for w in words
            ]

            # 表抽出
            tables = page.extract_tables()
            page_data.tables = tables if tables else []

            # OCR判定
            if len(raw_text.strip()) < settings.ocr_text_threshold:
                raw_text = _run_ocr(page, doc[i], page_data)
            else:
                page_data.ocr_used = "none"

            page_data.raw_text = raw_text
            page_data.normalized_text = normalize_text(raw_text)

            # ページ画像生成（Gemini送信用）
            if render_images:
                page_data.image_base64 = _render_page_image(doc[i])

            results.append(page_data)

        doc.close()

    return results


def _run_ocr(plumber_page, fitz_page, page_data: PageData) -> str:
    """Tesseract OCRを実行。失敗時はAzureへフォールバック"""
    if not TESSERACT_AVAILABLE:
        return ""

    try:
        # fitz でページ画像化（高解像度）
        mat = fitz.Matrix(2.0, 2.0)  # 2x拡大
        pix = fitz_page.get_pixmap(matrix=mat)
        img_bytes = pix.tobytes("png")
        img = Image.open(io.BytesIO(img_bytes))

        result = pytesseract.image_to_data(
            img,
            lang="jpn+eng",
            output_type=pytesseract.Output.DICT,
        )
        texts = []
        for j, conf in enumerate(result["conf"]):
            try:
                conf_val = float(conf)
            except (ValueError, TypeError):
                continue
            if conf_val >= settings.ocr_confidence_threshold:
                word = result["text"][j].strip()
                if word:
                    texts.append(word)

        page_data.ocr_used = "tesseract"
        extracted = " ".join(texts)

        # 信頼スコアが低すぎる場合はAzureへ
        avg_conf = _average_confidence(result)
        if avg_conf < settings.ocr_confidence_threshold and settings.azure_form_recognizer_key:
            extracted = _run_azure_ocr(img_bytes, page_data) or extracted

        return extracted

    except Exception as e:
        logger.error(f"OCR failed on page: {e}")
        return ""


def _average_confidence(ocr_data: dict) -> float:
    confs = [float(c) for c in ocr_data["conf"] if str(c).lstrip("-").isdigit() and float(c) >= 0]
    return sum(confs) / len(confs) if confs else 0.0


def _run_azure_ocr(img_bytes: bytes, page_data: PageData) -> Optional[str]:
    """Azure Form Recognizer (Read API) でOCRを実行"""
    try:
        from azure.ai.formrecognizer import DocumentAnalysisClient
        from azure.core.credentials import AzureKeyCredential

        client = DocumentAnalysisClient(
            endpoint=settings.azure_form_recognizer_endpoint,
            credential=AzureKeyCredential(settings.azure_form_recognizer_key),
        )
        poller = client.begin_analyze_document("prebuilt-read", img_bytes)
        result = poller.result()
        lines = [line.content for page in result.pages for line in page.lines]
        page_data.ocr_used = "azure"
        return "\n".join(lines)
    except Exception as e:
        logger.error(f"Azure OCR failed: {e}")
        return None


def _render_page_image(fitz_page) -> str:
    """ページをPNGに変換してBase64エンコードして返す"""
    mat = fitz.Matrix(1.5, 1.5)
    pix = fitz_page.get_pixmap(matrix=mat)
    img_bytes = pix.tobytes("png")
    return base64.b64encode(img_bytes).decode("utf-8")


def estimate_tokens_for_pages(pages: list[PageData]) -> dict:
    """
    ページデータからGemini APIのトークン数を推定する
    テキスト: 約4文字/token（日本語混在は3文字/token）
    画像: 約1000 tokens/page (Gemini 1.5 Flash の画像トークン推定)
    """
    total_text_chars = sum(len(p.normalized_text) for p in pages)
    # 日本語混在のため保守的に3文字/token
    text_tokens = int(total_text_chars / 3)
    # 画像トークン: 各ページ約1000 tokens
    image_tokens = len(pages) * 1000
    # システムプロンプト分
    system_tokens = 2000

    input_tokens = text_tokens + image_tokens + system_tokens
    # 出力は入力の約25%と推定
    output_tokens = int(input_tokens * 0.25)

    return {
        "estimated_input_tokens": input_tokens,
        "estimated_output_tokens": output_tokens,
    }

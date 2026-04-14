"""
PDFテキスト・座標抽出サービス
pdfplumber でテキスト/表/座標を抽出し、必要に応じてOCRを実行する

Phase 1: NFKC正規化・ブロック行分割・種別分類 (classify_line / classify_block)
         タイトルブロック分離 (x > TITLE_BLOCK_X)
"""
import os
import re
import base64
import logging
import unicodedata
from pathlib import Path
from typing import Optional
import pdfplumber
import fitz  # PyMuPDF
from PIL import Image
import io

from app.core.config import get_settings
from app.services.text_normalizer import normalize_text

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Phase 1 定数・正規表現パターン
# --------------------------------------------------------------------------- #
TITLE_BLOCK_X = 740.0   # x > 740 はタイトルブロック固定領域（回路解析から除外）

# 行種別判定パターン
XREF_PAT     = re.compile(r'^<([0-9A-Z\-]+)>$')                           # <09A>
TAG_PAT      = re.compile(
    r'^[0-9]{2,3}[A-Z]{1,5}[0-9]?(-[0-9]+)?$'   # 88X, 43AT, 3-65T（文字含む）
    r'|^[0-9]{2,3}-[0-9]+$'                        # 51-1, 27-2（ANSI番号-要素番号）
)
CIRCUIT_PAT  = re.compile(r'^[0-9]{4,7}$')                                # 0911, 121011
RELAY_PAT    = re.compile(r'^(MY|H3|SRD|MK|LY|G2R)[0-9A-Z\-]+$')        # MY4ZN-D2
TERMINAL_PAT = re.compile(r'^[●○]?[0-9]{1,2}$')                           # 端子番号（1〜2桁）


# --------------------------------------------------------------------------- #
# Phase 1 共通関数
# --------------------------------------------------------------------------- #
def normalize_nfkc(text: str) -> str:
    """NFKC正規化: 全角英数→半角、トリミング"""
    return unicodedata.normalize('NFKC', text.strip())


def classify_line(text: str) -> str:
    """
    1行を種別に分類する

    Returns:
        'cross_ref'  : クロスリファレンス  <09A>
        'tag_no'     : Tag.No              88X, 51-1
        'circuit_no' : 回路番号            0911, 121011
        'relay_model': リレー型番          MY4ZN-D2
        'terminal_no': 端子番号            1, 2, ●
        'text'       : その他テキスト
    """
    if XREF_PAT.match(text):     return 'cross_ref'
    if TAG_PAT.match(text):      return 'tag_no'
    if CIRCUIT_PAT.match(text):  return 'circuit_no'
    if RELAY_PAT.match(text):    return 'relay_model'
    if TERMINAL_PAT.match(text): return 'terminal_no'
    return 'text'


def classify_block(
    block_text: str,
    x0: float, y0: float, x1: float, y1: float,
) -> list[dict]:
    """
    1ブロックを行分割して種別ごとのエントリリストを返す。
    NFKC正規化をここで適用する。

    Returns:
        [{'text': str, 'kind': str, 'rect': [x0, y0, x1, y1]}, ...]
    """
    results = []
    for line in normalize_nfkc(block_text).split('\n'):
        line = line.strip()
        if not line:
            continue
        results.append({
            'text': line,
            'kind': classify_line(line),
            'rect': [x0, y0, x1, y1],
        })
    return results


# --------------------------------------------------------------------------- #
# Tesseract セットアップ
# --------------------------------------------------------------------------- #
try:
    import pytesseract
    _s = get_settings()
    if _s.tesseract_cmd and _s.tesseract_cmd != "tesseract":
        pytesseract.pytesseract.tesseract_cmd = _s.tesseract_cmd
    TESSERACT_AVAILABLE = True
except ImportError:
    TESSERACT_AVAILABLE = False
    logger.warning("pytesseract not available, OCR disabled")


# --------------------------------------------------------------------------- #
# PageData
# --------------------------------------------------------------------------- #
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

        # Phase 1 additions
        self.classified_lines: list[dict] = []    # 回路エリア行分類結果
        self.title_block_lines: list[dict] = []   # タイトルブロック行分類結果
        self.page_width: float = 1191.0           # ページ幅 (px)
        self.page_height: float = 842.0           # ページ高さ (px, A3横デフォルト)

    def to_dict(self) -> dict:
        return {
            "page_number": self.page_number,
            "normalized_text": self.normalized_text,
            "words": self.words,
            "tables": self.tables,
            "ocr_used": self.ocr_used,
            "classified_lines": self.classified_lines,
            "title_block_lines": self.title_block_lines,
        }


# --------------------------------------------------------------------------- #
# メイン抽出関数
# --------------------------------------------------------------------------- #
def extract_pdf(pdf_path: str, render_images: bool = True) -> list[PageData]:
    """
    PDFから全ページのテキスト・座標・画像を抽出する

    Phase 1 処理:
    - fitz.get_text('blocks') でブロック単位テキスト＋座標を取得
    - classify_block() で行分割・種別判定（NFKC正規化含む）
    - x > TITLE_BLOCK_X のブロックはタイトルブロックとして分離

    render_images=True: AI送信用にページ画像も生成する
    """
    results: list[PageData] = []

    with pdfplumber.open(pdf_path) as pdf:
        doc = fitz.open(pdf_path)

        for i, page in enumerate(pdf.pages):
            page_data = PageData(page_number=i)
            fitz_page = doc[i]

            # ページ寸法取得
            page_data.page_width = fitz_page.rect.width
            page_data.page_height = fitz_page.rect.height

            # ---------------------------------------------------------------- #
            # Phase 1: fitz ブロック抽出・行分類
            # fitz と pdfplumber を同一ドキュメントから使うことで座標系を統一
            # ---------------------------------------------------------------- #
            raw_blocks = fitz_page.get_text('blocks')
            for block in raw_blocks:
                # block = (x0, y0, x1, y1, text, block_no, block_type)
                if len(block) < 7:
                    continue
                x0, y0, x1, y1, text, _block_no, block_type = block[:7]
                if block_type != 0 or not text.strip():
                    continue  # 画像ブロックや空ブロックはスキップ

                classified = classify_block(text, x0, y0, x1, y1)
                if x0 > TITLE_BLOCK_X:
                    page_data.title_block_lines.extend(classified)
                else:
                    page_data.classified_lines.extend(classified)

            # ---------------------------------------------------------------- #
            # 従来テキスト抽出（AI送信用・表示用）
            # ---------------------------------------------------------------- #
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
            s = get_settings()
            if len(raw_text.strip()) < s.ocr_text_threshold:
                raw_text = _run_ocr(page, fitz_page, page_data)
            else:
                page_data.ocr_used = "none"

            page_data.raw_text = raw_text
            page_data.normalized_text = normalize_text(raw_text)

            # ページ画像生成（AI送信用）
            if render_images:
                page_data.image_base64 = _render_page_image(fitz_page)

            results.append(page_data)

        doc.close()

    return results


# --------------------------------------------------------------------------- #
# OCR（内部関数）
# --------------------------------------------------------------------------- #
def _run_ocr(plumber_page, fitz_page, page_data: PageData) -> str:
    """Tesseract OCRを実行。失敗時はAzureへフォールバック"""
    if not TESSERACT_AVAILABLE:
        return ""

    try:
        mat = fitz.Matrix(2.0, 2.0)
        pix = fitz_page.get_pixmap(matrix=mat)
        img_bytes = pix.tobytes("png")
        img = Image.open(io.BytesIO(img_bytes))

        result = pytesseract.image_to_data(
            img,
            lang="jpn+eng",
            output_type=pytesseract.Output.DICT,
        )
        s = get_settings()
        texts = []
        for j, conf in enumerate(result["conf"]):
            try:
                conf_val = float(conf)
            except (ValueError, TypeError):
                continue
            if conf_val >= s.ocr_confidence_threshold:
                word = result["text"][j].strip()
                if word:
                    texts.append(word)

        page_data.ocr_used = "tesseract"
        extracted = " ".join(texts)

        avg_conf = _average_confidence(result)
        if avg_conf < s.ocr_confidence_threshold and s.azure_form_recognizer_key:
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

        s = get_settings()
        client = DocumentAnalysisClient(
            endpoint=s.azure_form_recognizer_endpoint,
            credential=AzureKeyCredential(s.azure_form_recognizer_key),
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


# --------------------------------------------------------------------------- #
# コスト推定
# --------------------------------------------------------------------------- #
def estimate_tokens_for_pages(pages: list[PageData]) -> dict:
    """
    ページデータからAPIのトークン数を推定する
    テキスト: 約4文字/token（日本語混在は3文字/token）
    画像: 約1000 tokens/page
    """
    total_text_chars = sum(len(p.normalized_text) for p in pages)
    text_tokens = int(total_text_chars / 3)
    image_tokens = len(pages) * 1000
    system_tokens = 2000

    input_tokens = text_tokens + image_tokens + system_tokens
    output_tokens = int(input_tokens * 0.25)

    return {
        "estimated_input_tokens": input_tokens,
        "estimated_output_tokens": output_tokens,
    }

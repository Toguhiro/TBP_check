"""
テキスト正規化モジュール
全角/半角、改行、スペースの混在を統一する
"""
import unicodedata
import re


# 計装タグ: TE-0K-121, TE-0K-121A, CV-101-1 など
INSTRUMENT_TAG_PATTERN = re.compile(
    r'\b([A-Z]{1,3})\s*[-\u30fc]\s*([0-9A-Z]{1,4})\s*[-\u30fc]\s*([0-9]{1,4}[A-Z]?(?:[-\u30fc][0-9A-Z]+)?)\b',
    re.IGNORECASE
)

# ANSIデバイス番号系リレー: 88X, 51-1, 27, 86G など
ANSI_RELAY_PATTERN = re.compile(
    r'\b([0-9]{1,3}[A-Z]{0,2})(?:\s*[-/]\s*([0-9A-Z]+))?\b'
)


def normalize_text(text: str) -> str:
    """
    PDFから抽出したテキストを正規化する
    1. NFKC正規化（全角→半角）
    2. 改行・タブ→スペース
    3. 連続スペース削除
    4. Tag.No内の余分なスペース削除
    """
    if not text:
        return ""

    # NFKC: 全角英数字・記号 → 半角、全角スペース → 半角スペース
    text = unicodedata.normalize("NFKC", text)

    # 改行・タブをスペースに統一
    text = re.sub(r"[\r\n\t]+", " ", text)

    # 連続スペース → 1スペース
    text = re.sub(r" {2,}", " ", text)

    # Tag.No・デバイス番号内のスペース除去
    # 例: "88 X" → "88X",  "TE- 0K -121" → "TE-0K-121"
    text = re.sub(r"(?<=[A-Z0-9])\s+(?=[-])", "", text)
    text = re.sub(r"(?<=[-])\s+(?=[A-Z0-9])", "", text)
    text = re.sub(r"(?<=[0-9])\s+(?=[A-Z]\b)", "", text)

    return text.strip()


def normalize_tag_no(tag: str) -> str:
    """Tag.Noを正規化して比較用キーを返す"""
    tag = unicodedata.normalize("NFKC", tag).upper().strip()
    # すべての空白とダッシュ類を正規化
    tag = re.sub(r"[\s\u30fc\u2015\u2212\uff0d]+", "-", tag)
    tag = re.sub(r"-{2,}", "-", tag)
    return tag.strip("-")


def extract_tag_nos(text: str) -> list[dict]:
    """
    テキストから全Tag.Noを抽出する
    Returns: [{"tag": "TE-0K-121", "raw": "TE－0K－121", "type": "instrument"}, ...]
    """
    normalized = normalize_text(text)
    results = []
    seen = set()

    # 計装タグ
    for m in INSTRUMENT_TAG_PATTERN.finditer(normalized):
        raw = m.group(0)
        tag = normalize_tag_no(raw)
        if tag and tag not in seen:
            seen.add(tag)
            results.append({"tag": tag, "raw": raw, "type": "instrument",
                             "span": (m.start(), m.end())})

    # ANSIデバイス番号（計装タグと重複しないもの）
    for m in ANSI_RELAY_PATTERN.finditer(normalized):
        raw = m.group(0)
        tag = normalize_tag_no(raw)
        if tag and tag not in seen and len(tag) <= 8:
            # 純粋な数字のみは除外（ページ番号等と混同を避ける）
            if re.search(r"[A-Z]", tag):
                seen.add(tag)
                results.append({"tag": tag, "raw": raw, "type": "ansi_relay",
                                 "span": (m.start(), m.end())})

    return results


def extract_customer_name(text: str) -> str | None:
    """
    表題欄から顧客名を抽出する（ヒューリスティック）
    '顧客', '発注者', 'CLIENT', 'CUSTOMER' 等のキーワード周辺を検索
    """
    normalized = normalize_text(text)
    patterns = [
        r"(?:顧客|発注者|CLIENT|CUSTOMER|得意先)\s*[：:]\s*(.+?)(?:\s{2,}|$)",
        r"(?:顧客名|発注者名)\s*[：:]\s*(.+?)(?:\s{2,}|$)",
    ]
    for pattern in patterns:
        m = re.search(pattern, normalized, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return None


def normalize_for_comparison(value: str) -> str:
    """2値を比較するための正規化（大文字化、空白除去）"""
    value = unicodedata.normalize("NFKC", value).upper().strip()
    value = re.sub(r"\s+", " ", value)
    return value

"""
AI解析エンジン（Claude API / Google Gemini 切り替え対応）
抽象クラス AIEngine を継承して実装する
"""
import json
import base64
import logging
from abc import ABC, abstractmethod
from typing import Optional

from app.core.config import get_settings
from app.services.pdf_extractor import PageData

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# 抽象AIエンジン（Claude APIへの切り替えはこのクラスを継承して実装する）
# --------------------------------------------------------------------------- #
class AIEngine(ABC):
    @abstractmethod
    async def analyze_page(
        self,
        page_data: PageData,
        drawing_type: str,
        context: Optional[dict] = None,
    ) -> dict:
        """1ページを解析し、エンティティ・ロジック情報・不明箇所を返す"""
        ...

    @abstractmethod
    async def cross_check(
        self,
        all_entities: list[dict],
        drawing_types: dict[str, str],
    ) -> dict:
        """全ファイルのエンティティを横断チェックする"""
        ...

    def get_usage(self) -> dict:
        return {"input_tokens": 0, "output_tokens": 0}


# --------------------------------------------------------------------------- #
# Gemini 実装
# --------------------------------------------------------------------------- #
_PAGE_ANALYSIS_PROMPT = """
あなたは電気・計装の専門家です。
以下の電気図面（{drawing_type}）の1ページについて、構造化された情報を抽出・分析してください。

【抽出してほしい情報】
1. entities: 図面内の全 Tag.No・機器名称リスト
   - tag: 正規化されたTag.No（例: "TE-0K-121", "88X"）
   - name: 機器名称または説明
   - device_type: "relay" | "transformer" | "breaker" | "ct" | "vt" | "indicator" | "switch" | "other"
   - rect: 位置情報 [x0, y0, x1, y1]（わかる場合のみ）
   - reference_sheet: 参照先シート番号（リレー接点・コイル等）

2. customer_name: 表題欄から読み取れる顧客名（なければ null）

3. electrical_specs: 検出した電気諸元
   - value: 数値
   - unit: "V" | "A" | "kA" | "kVA" | "Hz" など
   - context: 説明文

4. logic_elements: シーケンス・ロジック要素（展開接続図・シーケンスロジック図のみ）
   - element_type: "coil" | "no_contact" | "nc_contact" | "timer" | "logic_gate"
   - tag: 関連Tag.No
   - condition: 励磁条件・論理条件

5. uncertain_items: 意味が不明・分類困難な要素のリスト
   - text: 対象テキスト
   - reason: 不明・分類困難な理由

【重要な注意】
- 全角/半角が混在している可能性があります
- テキストに改行やスペースが含まれる場合があります（例："TE\n-0K\n-121" → "TE-0K-121"）
- 意味が取れないものは confident: false として uncertain_items に含めてください
- 全部を確認するよりも、確信のある情報だけを返す方が望ましい

ページテキスト:
```
{page_text}
```

JSONのみ返答してください（コードブロック不要）:
{{
  "entities": [...],
  "customer_name": "...",
  "electrical_specs": [...],
  "logic_elements": [...],
  "uncertain_items": [...]
}}
"""

def _parse_json_response(text: str) -> dict:
    """JSONレスポンスをパースする（共通処理）"""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    text = text.strip().rstrip("```")
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        logger.warning(f"JSON parse failed: {e}\nRaw: {text[:500]}")
        return {"entities": [], "customer_name": None,
                "electrical_specs": [], "logic_elements": [],
                "uncertain_items": [{"text": text[:200], "reason": "JSON解析失敗"}]}


_CROSS_CHECK_PROMPT = """
あなたは電気・計装の専門家です。
複数の電気図面から抽出されたエンティティ情報を横断的にチェックしてください。

【チェック項目】
1. tag_consistency: 同一Tag.Noの機器名称が全図面で一致しているか
2. customer_name: 全シートで顧客名が一致しているか
3. relay_cross_ref: リレーコイルと接点の参照先シートが整合しているか
4. single_vs_expanded: 単線結線図と展開接続図でTag.No・接続が一致しているか
5. logic_integrity: シーケンスロジックの論理矛盾（インターロック等）

エンティティデータ（JSON）:
{entities_json}

図面種別マッピング（file_id → drawing_type）:
{drawing_types_json}

以下のJSON形式で返答してください:
{{
  "issues": [
    {{
      "check_type": "tag_consistency",
      "severity": "error" | "warning" | "ok",
      "message": "...",
      "affected_tags": [...],
      "affected_files": [...],
      "detail": {{}}
    }}
  ],
  "uncertain_items": [
    {{
      "text": "...",
      "reason": "..."
    }}
  ]
}}
"""


# --------------------------------------------------------------------------- #
# Claude 実装
# --------------------------------------------------------------------------- #
class ClaudeEngine(AIEngine):
    def __init__(self):
        s = get_settings()
        if not s.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY is not set in .env")
        import anthropic
        self._client = anthropic.AsyncAnthropic(api_key=s.anthropic_api_key)
        self._model = s.claude_model
        self._total_input_tokens = 0
        self._total_output_tokens = 0

    async def analyze_page(
        self,
        page_data: PageData,
        drawing_type: str,
        context: Optional[dict] = None,
    ) -> dict:
        drawing_type_label = {
            "external": "外形図",
            "parts": "部品図",
            "internal_layout": "内部部品配置図",
            "single_line": "単線結線図",
            "expanded": "展開接続図",
            "sequence_logic": "シーケンスロジック図",
            "unknown": "不明",
        }.get(drawing_type, drawing_type)

        prompt = _PAGE_ANALYSIS_PROMPT.format(
            drawing_type=drawing_type_label,
            page_text=page_data.normalized_text[:8000],
        )

        content: list = []
        if page_data.image_base64:
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": page_data.image_base64,
                },
            })
        content.append({"type": "text", "text": prompt})

        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=8192,
                messages=[{"role": "user", "content": content}],
            )
            self._total_input_tokens += response.usage.input_tokens
            self._total_output_tokens += response.usage.output_tokens
            return self._parse_json_response(response.content[0].text)
        except Exception as e:
            logger.error(f"Claude analyze_page error: {e}")
            return {"entities": [], "customer_name": None,
                    "electrical_specs": [], "logic_elements": [],
                    "uncertain_items": [{"text": str(e), "reason": "APIエラー"}]}

    async def cross_check(
        self,
        all_entities: list[dict],
        drawing_types: dict[str, str],
    ) -> dict:
        prompt = _CROSS_CHECK_PROMPT.format(
            entities_json=json.dumps(all_entities, ensure_ascii=False, indent=2)[:12000],
            drawing_types_json=json.dumps(drawing_types, ensure_ascii=False),
        )

        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}],
            )
            self._total_input_tokens += response.usage.input_tokens
            self._total_output_tokens += response.usage.output_tokens
            return self._parse_json_response(response.content[0].text)
        except Exception as e:
            logger.error(f"Claude cross_check error: {e}")
            return {"issues": [], "uncertain_items": [{"text": str(e), "reason": "APIエラー"}]}

    def get_usage(self) -> dict:
        return {
            "input_tokens": self._total_input_tokens,
            "output_tokens": self._total_output_tokens,
        }

    @staticmethod
    def _parse_json_response(text: str) -> dict:
        return _parse_json_response(text)


class GeminiEngine(AIEngine):
    def __init__(self):
        s = get_settings()
        if not s.gemini_api_key:
            raise ValueError("GEMINI_API_KEY is not set in .env")
        from google import genai
        self._client = genai.Client(api_key=s.gemini_api_key)
        self._model = s.gemini_model
        self._total_input_tokens = 0
        self._total_output_tokens = 0

    async def analyze_page(
        self,
        page_data: PageData,
        drawing_type: str,
        context: Optional[dict] = None,
    ) -> dict:
        drawing_type_label = {
            "external": "外形図",
            "parts": "部品図",
            "internal_layout": "内部部品配置図",
            "single_line": "単線結線図",
            "expanded": "展開接続図",
            "sequence_logic": "シーケンスロジック図",
            "unknown": "不明",
        }.get(drawing_type, drawing_type)

        prompt = _PAGE_ANALYSIS_PROMPT.format(
            drawing_type=drawing_type_label,
            page_text=page_data.normalized_text[:8000],
        )

        contents: list = [prompt]
        if page_data.image_base64:
            from google.genai import types
            contents = [
                types.Part.from_bytes(
                    data=base64.b64decode(page_data.image_base64),
                    mime_type="image/png",
                ),
                prompt,
            ]

        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=contents,
            )
            self._accumulate_usage(response)
            return _parse_json_response(response.text)
        except Exception as e:
            logger.error(f"Gemini analyze_page error: {e}")
            return {"entities": [], "customer_name": None,
                    "electrical_specs": [], "logic_elements": [],
                    "uncertain_items": [{"text": str(e), "reason": "APIエラー"}]}

    async def cross_check(
        self,
        all_entities: list[dict],
        drawing_types: dict[str, str],
    ) -> dict:
        prompt = _CROSS_CHECK_PROMPT.format(
            entities_json=json.dumps(all_entities, ensure_ascii=False, indent=2)[:12000],
            drawing_types_json=json.dumps(drawing_types, ensure_ascii=False),
        )

        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=prompt,
            )
            self._accumulate_usage(response)
            return _parse_json_response(response.text)
        except Exception as e:
            logger.error(f"Gemini cross_check error: {e}")
            return {"issues": [], "uncertain_items": [{"text": str(e), "reason": "APIエラー"}]}

    def _accumulate_usage(self, response):
        try:
            usage = response.usage_metadata
            self._total_input_tokens += usage.prompt_token_count or 0
            self._total_output_tokens += usage.candidates_token_count or 0
        except Exception:
            pass

    def get_usage(self) -> dict:
        return {
            "input_tokens": self._total_input_tokens,
            "output_tokens": self._total_output_tokens,
        }

def create_ai_engine() -> AIEngine:
    """設定に基づいてAIエンジンのインスタンスを返す"""
    s = get_settings()
    if s.ai_engine == "claude":
        return ClaudeEngine()
    return GeminiEngine()


def calculate_cost(input_tokens: int, output_tokens: int) -> float:
    """トークン数からコストを計算する（USD）"""
    s = get_settings()
    input_cost = (input_tokens / 1_000_000) * s.input_price_per_1m
    output_cost = (output_tokens / 1_000_000) * s.output_price_per_1m
    return round(input_cost + output_cost, 6)

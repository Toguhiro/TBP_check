"""
検図ルールエンジン（ルールベース部分）
AIの結果を補完・検証するルールを実装する

Phase 2:
  build_xref_map()     : xref→Tag照合マップ（全ページ横断）
  parse_coil_table()   : コイルテーブル構造化
  check_mccb_rating()  : 遮断器定格 JIS 適合チェック
"""
import re
import logging
from collections import defaultdict
from typing import Optional
from app.services.text_normalizer import normalize_tag_no, normalize_for_comparison

# Phase 2 用（pdf_extractor と同じパターン）
_XREF_PAT    = re.compile(r'^<([0-9A-Z\-]+)>$')
_RELAY_PAT   = re.compile(r'^(MY|H3|SRD|MK|LY|G2R)[0-9A-Z\-]+$')
_MCCB_PAT    = re.compile(r'(\d+)P\s*(\d+)AF\s*/\s*(\d+)AT', re.IGNORECASE)
_TAG_PAT     = re.compile(
    r'^[0-9]{2,3}[A-Z]{1,5}[0-9]?(-[0-9]+)?$'
    r'|^[0-9]{2,3}-[0-9]+$'
)

logger = logging.getLogger(__name__)

# JIS C 8201準拠 一般的な遮断器定格電流（A）
STANDARD_BREAKER_RATINGS = [1, 2, 3, 4, 6, 10, 13, 15, 16, 20, 25, 30, 32, 40, 50, 63, 100, 125, 160, 200, 250, 315, 400, 500, 630, 800, 1000, 1250, 1600, 2000, 2500, 3200]

# 標準電圧（V）
STANDARD_VOLTAGES = [6, 12, 24, 48, 100, 110, 200, 220, 380, 400, 440, 3300, 6600, 11000, 22000, 66000]

# ANSIデバイス番号の既知リスト
KNOWN_ANSI_DEVICES = {
    "21": "距離継電器", "25": "同期確認リレー", "27": "不足電圧リレー",
    "32": "電力方向リレー", "40": "界磁喪失リレー", "46": "逆相電流リレー",
    "47": "逆相電圧リレー", "49": "熱動継電器", "50": "瞬時過電流リレー",
    "51": "限時過電流リレー", "52": "交流遮断器", "59": "過電圧リレー",
    "63": "圧力継電器", "64": "地絡検出リレー", "67": "方向性過電流リレー",
    "74": "警報リレー", "76": "過電流DCリレー", "81": "周波数リレー",
    "85": "搬送波またはパイロットリレー", "86": "ロックアウトリレー",
    "87": "差動保護リレー", "88": "補助リレー", "89": "断路器",
    "94": "トリッピングリレー",
}


class CheckIssue:
    def __init__(self, check_type: str, severity: str, message: str,
                 file_id: Optional[str] = None, page_number: Optional[int] = None,
                 location_rect: Optional[list] = None, detail: Optional[dict] = None):
        self.check_type = check_type
        self.severity = severity
        self.message = message
        self.file_id = file_id
        self.page_number = page_number
        self.location_rect = location_rect
        self.detail = detail or {}

    def to_dict(self) -> dict:
        return {
            "check_type": self.check_type,
            "severity": self.severity,
            "message": self.message,
            "file_id": self.file_id,
            "page_number": self.page_number,
            "location_rect": self.location_rect,
            "detail": self.detail,
        }


# --------------------------------------------------------------------------- #
# Phase 2: テキスト構造化ルールベース処理
# --------------------------------------------------------------------------- #

# JIS C 8201 遮断器定格テーブル: {AF: [許容AT値, ...]}
JIS_MCCB_TABLE: dict[int, list[int]] = {
    225: [100, 125, 150, 175, 200, 225],
    100: [15, 20, 30, 40, 50, 60, 75, 100],
    50:  [10, 15, 20, 30, 40, 50],
    30:  [10, 15, 20, 30],
    20:  [10, 15, 20],
}


def build_xref_map(all_page_classified: list[list[dict]]) -> dict[str, dict]:
    """
    全ページの classified_lines を受け取り、
    xref の参照先ページを解決するマップを返す。

    Args:
        all_page_classified: [[{text, kind, rect}, ...], ...]  (ページ順)

    Returns:
        {
            '09A': {'resolved': True,  'pages': [12, 35]},
            '49H': {'resolved': False, 'pages': []},
        }
    """
    # tag_no の出現ページを収集
    tag_pages: dict[str, list[int]] = defaultdict(list)
    for pg_idx, entities in enumerate(all_page_classified):
        for e in entities:
            if e.get('kind') == 'tag_no':
                tag_pages[e['text']].append(pg_idx + 1)

    # xref の参照先を解決
    xref_map: dict[str, dict] = {}
    for pg_idx, entities in enumerate(all_page_classified):
        for e in entities:
            if e.get('kind') != 'cross_ref':
                continue
            m = _XREF_PAT.match(e['text'])
            if not m:
                continue
            ref = m.group(1)
            if ref not in xref_map:
                pages = tag_pages.get(ref, [])
                xref_map[ref] = {
                    'resolved': len(pages) > 0,
                    'pages': sorted(set(pages)),
                    'source_page': pg_idx + 1,
                    'rect': e.get('rect'),
                }

    resolved = sum(1 for v in xref_map.values() if v['resolved'])
    total = len(xref_map)
    logger.info(f"xref_map: {resolved}/{total} resolved ({100*resolved//total if total else 0}%)")
    return xref_map


def parse_coil_table(entities: list[dict], page_height: float = 842.0) -> list[dict]:
    """
    1ページの classified_lines からコイルテーブルを構造化する。
    リレー型番が出現する最小y座標をテーブル開始境界とする。

    Returns:
        [
            {
                'tag': '2TX',
                'model': 'MY4ZN-D2',
                'contacts': [
                    {'terminal': '9',  'xref': '09B', 'type': 'a'},
                    {'terminal': '10', 'xref': '09B', 'type': 'b'},
                ],
            },
            ...
        ]
    """
    relay_entries = [e for e in entities if e.get('kind') == 'relay_model' and e.get('rect')]
    if not relay_entries:
        return []

    result = []
    used_tag_ys: set = set()

    for relay_e in relay_entries:
        rx0 = relay_e['rect'][0]
        ry  = relay_e['rect'][1]

        # 同じ x 列（±80px）、y ±70px 以内の tag_no を探す
        nearby_tags = [
            e for e in entities
            if e.get('kind') == 'tag_no'
            and e.get('rect')
            and abs(e['rect'][0] - rx0) < 80
            and abs(e['rect'][1] - ry) < 70
            and e['rect'][1] not in used_tag_ys
        ]
        nearby_tags.sort(key=lambda e: abs(e['rect'][1] - ry))
        tag_text = ''
        if nearby_tags:
            tag_text = nearby_tags[0]['text']
            used_tag_ys.add(nearby_tags[0]['rect'][1])

        # 端子番号（コイルシンボル周辺 x=rx0±100、y ±50px）
        terminals = [
            e for e in entities
            if e.get('kind') == 'terminal_no'
            and e.get('rect')
            and abs(e['rect'][0] - rx0) < 100
            and abs(e['rect'][1] - ry) < 50
        ]
        b_contact_terminals = [t['text'] for t in terminals if '●' in t['text']]

        if relay_e['text'] or tag_text:
            result.append({
                'tag':           tag_text,
                'model':         relay_e['text'],
                'rect':          relay_e.get('rect'),
                'contacts':      [],  # 接点は回路エリアの cross_ref から別途取得
                'has_b_contact': len(b_contact_terminals) > 0,
            })

    return result


def check_mccb_rating(af: int, at: int) -> bool:
    """JIS C 8201 準拠の遮断器定格チェック"""
    return at in JIS_MCCB_TABLE.get(af, [])


def extract_mccb_specs(classified_lines: list[dict]) -> list[dict]:
    """
    classified_lines テキストから MCCB 定格を抽出して JIS チェックを実施する。
    例: '3P 225AF/125AT' を検出

    Returns:
        [{'poles': 3, 'af': 225, 'at': 125, 'jis_ok': True, 'rect': [...]}]
    """
    results = []
    for e in classified_lines:
        text = e.get('text', '')
        m = _MCCB_PAT.search(text)
        if not m:
            continue
        poles = int(m.group(1))
        af = int(m.group(2))
        at = int(m.group(3))
        results.append({
            'poles': poles,
            'af': af,
            'at': at,
            'jis_ok': check_mccb_rating(af, at),
            'rect': e.get('rect'),
            'raw_text': text,
        })
    return results


def run_rule_checks(project_entities: list[dict]) -> list[CheckIssue]:
    """
    全ファイルのエンティティに対してルールベースチェックを実行する
    project_entities: [{"file_id": ..., "page": ..., "entities": [...], "customer_name": ..., "electrical_specs": [...]}]
    """
    issues = []

    issues.extend(_check_tag_no_consistency(project_entities))
    issues.extend(_check_customer_name_consistency(project_entities))
    issues.extend(_check_relay_cross_references(project_entities))
    issues.extend(_check_electrical_specs(project_entities))

    return issues


def _check_tag_no_consistency(project_entities: list[dict]) -> list[CheckIssue]:
    """同一Tag.Noが異なる機器名称で使われていないか確認"""
    issues = []
    # tag → [(name, file_id, page, rect)]
    tag_map: dict[str, list[tuple]] = defaultdict(list)

    for item in project_entities:
        for entity in item.get("entities", []):
            tag = normalize_tag_no(entity.get("tag", ""))
            name = normalize_for_comparison(entity.get("name", ""))
            if tag and name:
                tag_map[tag].append((name, item["file_id"], item["page"], entity.get("rect")))

    for tag, occurrences in tag_map.items():
        names = set(o[0] for o in occurrences)
        if len(names) > 1:
            detail = {
                "tag": tag,
                "occurrences": [
                    {"name": o[0], "file_id": o[1], "page": o[2]} for o in occurrences
                ],
            }
            issues.append(CheckIssue(
                check_type="tag_consistency",
                severity="error",
                message=f"Tag.No '{tag}' が複数の異なる機器名称で使用されています: {', '.join(names)}",
                detail=detail,
            ))

    return issues


def _check_customer_name_consistency(project_entities: list[dict]) -> list[CheckIssue]:
    """全シートで顧客名が一致しているか確認"""
    issues = []
    customer_names = []

    for item in project_entities:
        name = item.get("customer_name")
        if name:
            customer_names.append((normalize_for_comparison(name), item["file_id"], item["page"]))

    if not customer_names:
        return issues

    first_name = customer_names[0][0]
    mismatches = [(n, fid, pg) for n, fid, pg in customer_names if n != first_name]

    if mismatches:
        detail = {
            "expected": first_name,
            "mismatches": [{"name": m[0], "file_id": m[1], "page": m[2]} for m in mismatches],
        }
        issues.append(CheckIssue(
            check_type="customer_name",
            severity="error",
            message=f"顧客名称が統一されていません。基準: '{first_name}'",
            detail=detail,
        ))
    else:
        issues.append(CheckIssue(
            check_type="customer_name",
            severity="ok",
            message=f"顧客名称は全シートで一致しています: '{first_name}'",
        ))

    return issues


def _check_relay_cross_references(project_entities: list[dict]) -> list[CheckIssue]:
    """
    リレーコイルと接点の参照整合性チェック
    - コイルが定義されているリレーの接点参照先が正しいか
    - 接点が参照しているリレーのコイルが存在するか
    """
    issues = []
    coils: dict[str, dict] = {}      # tag → {file_id, page, rect}
    contacts: list[dict] = []        # [{tag, ref_sheet, file_id, page, rect}]

    for item in project_entities:
        for entity in item.get("entities", []):
            if entity.get("device_type") == "relay":
                tag = normalize_tag_no(entity.get("tag", ""))
                if not tag:
                    continue
                for logic_el in item.get("logic_elements", []):
                    if normalize_tag_no(logic_el.get("tag", "")) == tag:
                        if logic_el.get("element_type") == "coil":
                            coils[tag] = {"file_id": item["file_id"], "page": item["page"]}
                        elif logic_el.get("element_type") in ("no_contact", "nc_contact"):
                            contacts.append({
                                "tag": tag,
                                "ref_sheet": logic_el.get("condition", ""),
                                "file_id": item["file_id"],
                                "page": item["page"],
                            })

    # 接点が参照するリレーのコイルが存在するか確認
    for contact in contacts:
        tag = contact["tag"]
        if tag and tag not in coils:
            issues.append(CheckIssue(
                check_type="relay_cross_ref",
                severity="error",
                message=f"リレー '{tag}' の接点が参照されていますが、コイル定義が見つかりません",
                file_id=contact["file_id"],
                page_number=contact["page"],
                detail={"tag": tag, "contact_location": contact},
            ))

    # コイルが定義されているが接点が1つもないリレー（警告レベル）
    contact_tags = set(c["tag"] for c in contacts)
    for tag, coil_info in coils.items():
        if tag not in contact_tags:
            issues.append(CheckIssue(
                check_type="relay_cross_ref",
                severity="warning",
                message=f"リレー '{tag}' のコイルが定義されていますが、接点の参照が見つかりません",
                file_id=coil_info["file_id"],
                page_number=coil_info["page"],
                detail={"tag": tag},
            ))

    return issues


def _check_electrical_specs(project_entities: list[dict]) -> list[CheckIssue]:
    """電気諸元の妥当性チェック（JISベース）"""
    issues = []

    for item in project_entities:
        for spec in item.get("electrical_specs", []):
            try:
                value = float(spec.get("value", 0))
                unit = str(spec.get("unit", "")).upper()
                context = spec.get("context", "")
            except (ValueError, TypeError):
                continue

            # 電圧チェック
            if unit == "V" and value > 0:
                if not _is_near_standard(value, STANDARD_VOLTAGES, tolerance=0.15):
                    issues.append(CheckIssue(
                        check_type="electrical_spec",
                        severity="warning",
                        message=f"非標準電圧値の可能性: {value}V — 確認してください（'{context}'）",
                        file_id=item["file_id"],
                        page_number=item["page"],
                        detail={"value": value, "unit": unit, "context": context},
                    ))

            # 遮断器定格電流チェック
            if unit == "A" and "遮断" in context or "CB" in context.upper() or "MCCB" in context.upper():
                if value > 0 and value not in STANDARD_BREAKER_RATINGS:
                    issues.append(CheckIssue(
                        check_type="breaker_rating",
                        severity="warning",
                        message=f"JIS C 8201 非標準の遮断器定格電流: {value}A（'{context}'）",
                        file_id=item["file_id"],
                        page_number=item["page"],
                        detail={"value": value, "standard_values": STANDARD_BREAKER_RATINGS},
                    ))

    return issues


def _is_near_standard(value: float, standards: list, tolerance: float = 0.1) -> bool:
    return any(abs(value - s) / max(s, 1) <= tolerance for s in standards)


def get_ansi_device_name(device_number: str) -> Optional[str]:
    """ANSIデバイス番号から機器名称を返す"""
    num = re.match(r"^([0-9]+)", device_number.strip())
    if num:
        return KNOWN_ANSI_DEVICES.get(num.group(1))
    return None

"""
検図ルールエンジン（ルールベース部分）
AIの結果を補完・検証するルールを実装する
"""
import re
import logging
from collections import defaultdict
from typing import Optional
from app.services.text_normalizer import normalize_tag_no, normalize_for_comparison

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

"""
PDFアノテーション生成サービス（PyMuPDF）
- 黄色ハイライト: 正常確認済み
- 赤色ハイライト + コメント: エラー
- オレンジ色ハイライト: AI判断困難（要手動確認）
- 内部ハイパーリンク: リレーコイル ↔ 接点
"""
import logging
import os
import uuid
from pathlib import Path
from typing import Optional
import fitz  # PyMuPDF

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# アノテーション色定義
COLOR_OK = (1.0, 0.95, 0.0)        # 黄色: 正常
COLOR_ERROR = (1.0, 0.15, 0.15)    # 赤色: エラー
COLOR_WARNING = (1.0, 0.55, 0.0)   # オレンジ: 警告・AI不明
COLOR_INFO = (0.0, 0.5, 1.0)       # 青: 情報（参照リンク）


def annotate_pdf(
    input_path: str,
    annotations_by_page: dict[int, list[dict]],
    links_by_page: dict[int, list[dict]],
    output_dir: str,
) -> str:
    """
    PDFにアノテーションを付与して保存する

    annotations_by_page: {page_index: [{rect, color, message, check_type}]}
    links_by_page: {page_index: [{from_rect, target_page, target_x, target_y, label}]}
    """
    os.makedirs(output_dir, exist_ok=True)
    output_filename = f"annotated_{uuid.uuid4().hex[:8]}_{Path(input_path).name}"
    output_path = os.path.join(output_dir, output_filename)

    doc = fitz.open(input_path)

    for page_idx in range(len(doc)):
        page = doc[page_idx]

        # アノテーション追加
        for ann in annotations_by_page.get(page_idx, []):
            _add_annotation(page, ann)

        # ハイパーリンク追加
        for link in links_by_page.get(page_idx, []):
            _add_link(page, link)

    doc.save(output_path)
    doc.close()

    return output_path


def _add_annotation(page: fitz.Page, ann: dict):
    """ページにアノテーションを追加する"""
    rect_data = ann.get("rect")
    if not rect_data or len(rect_data) != 4:
        return

    try:
        rect = fitz.Rect(rect_data)
        color_name = ann.get("color", "yellow")
        color = {
            "yellow": COLOR_OK,
            "red": COLOR_ERROR,
            "orange": COLOR_WARNING,
            "blue": COLOR_INFO,
        }.get(color_name, COLOR_OK)

        # ハイライト追加
        highlight = page.add_highlight_annot(rect)
        highlight.set_colors(stroke=color)
        highlight.set_opacity(0.4)

        # エラー・警告にはポップアップコメントも追加
        message = ann.get("message", "")
        if message and color_name in ("red", "orange"):
            check_type = ann.get("check_type", "")
            label = {"red": "[エラー]", "orange": "[要確認]"}.get(color_name, "")
            highlight.set_info(
                content=f"{label} {check_type}: {message}",
                title="AI検図システム",
            )

        highlight.update()

    except Exception as e:
        logger.warning(f"Failed to add annotation: {e}, rect={rect_data}")


def _add_link(page: fitz.Page, link: dict):
    """ページ内ハイパーリンクを追加する（リレー参照）"""
    from_rect = link.get("from_rect")
    target_page = link.get("target_page")
    if from_rect is None or target_page is None:
        return

    try:
        rect = fitz.Rect(from_rect)
        target_x = link.get("target_x", 0)
        target_y = link.get("target_y", 0)

        page.insert_link({
            "kind": fitz.LINK_GOTO,
            "from": rect,
            "page": target_page,
            "to": fitz.Point(target_x, target_y),
        })

        # リンクの視覚的マーカー（細い青枠）
        page.draw_rect(rect, color=COLOR_INFO, width=0.8)

        # リンクラベルを追加
        label = link.get("label", "")
        if label:
            page.insert_text(
                fitz.Point(rect.x0, rect.y0 - 2),
                label,
                fontsize=6,
                color=COLOR_INFO,
            )
    except Exception as e:
        logger.warning(f"Failed to add link: {e}")


def build_annotations_from_results(
    page_count: int,
    check_results: list[dict],
    page_entities: list[dict],
) -> tuple[dict, dict]:
    """
    チェック結果とエンティティ情報からアノテーションデータを構築する
    Returns: (annotations_by_page, links_by_page)
    """
    annotations_by_page: dict[int, list[dict]] = {i: [] for i in range(page_count)}
    links_by_page: dict[int, list[dict]] = {i: [] for i in range(page_count)}

    # エラー・警告のアノテーション
    for result in check_results:
        page_num = result.get("page_number")
        rect = result.get("location_rect")
        if page_num is not None and rect:
            severity = result.get("severity", "ok")
            color = {"error": "red", "warning": "orange", "ok": "yellow", "uncertain": "orange"}.get(severity, "yellow")
            annotations_by_page[page_num].append({
                "rect": rect,
                "color": color,
                "message": result.get("message", ""),
                "check_type": result.get("check_type", ""),
            })

    # 確認済み（エラーのないエンティティ）は黄色
    error_rects = set()
    for r in check_results:
        if r.get("location_rect") and r.get("severity") in ("error", "warning"):
            error_rects.add(tuple(r["location_rect"]))

    for entity_info in page_entities:
        page_num = entity_info.get("page")
        for entity in entity_info.get("entities", []):
            rect = entity.get("rect")
            if rect and tuple(rect) not in error_rects and page_num is not None:
                annotations_by_page[page_num].append({
                    "rect": rect,
                    "color": "yellow",
                    "message": f"確認済み: {entity.get('tag', '')} {entity.get('name', '')}",
                    "check_type": "verified",
                })

    # AI判断困難（オレンジ）- rect がある場合のみアノテーション
    for entity_info in page_entities:
        page_num = entity_info.get("page")
        for uncertain in entity_info.get("uncertain_items", []):
            rect = uncertain.get("rect")
            if page_num is not None and rect and len(rect) == 4:
                annotations_by_page[page_num].append({
                    "rect": rect,
                    "color": "orange",
                    "message": f"要手動確認: {uncertain.get('text', '')} — {uncertain.get('reason', '')}",
                    "check_type": "uncertain",
                })

    return annotations_by_page, links_by_page


def build_relay_links(
    page_count: int,
    coil_locations: dict[str, dict],
    contact_locations: list[dict],
) -> dict[int, list[dict]]:
    """
    リレーコイル ↔ 接点 のハイパーリンクを構築する
    coil_locations: {tag: {page, rect}}
    contact_locations: [{tag, page, rect}]
    """
    links_by_page: dict[int, list[dict]] = {i: [] for i in range(page_count)}

    for contact in contact_locations:
        tag = contact.get("tag")
        if not tag or tag not in coil_locations:
            continue

        coil = coil_locations[tag]
        contact_page = contact.get("page")
        contact_rect = contact.get("rect")
        coil_page = coil.get("page")
        coil_rect = coil.get("rect")

        if contact_page is not None and contact_rect:
            # 接点 → コイルへのリンク
            links_by_page[contact_page].append({
                "from_rect": contact_rect,
                "target_page": coil_page,
                "target_x": coil_rect[0] if coil_rect else 0,
                "target_y": coil_rect[1] if coil_rect else 0,
                "label": f"→{tag}コイル",
            })

        if coil_page is not None and coil_rect:
            # コイル → 接点へのリンク
            links_by_page[coil_page].append({
                "from_rect": coil_rect,
                "target_page": contact_page,
                "target_x": contact_rect[0] if contact_rect else 0,
                "target_y": contact_rect[1] if contact_rect else 0,
                "label": f"→{tag}接点",
            })

    return links_by_page

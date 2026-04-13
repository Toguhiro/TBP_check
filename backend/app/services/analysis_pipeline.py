"""
検図パイプライン全体のオーケストレーション
Step1: PDF抽出 → Step2: OCR → Step2.5: コスト推定 → Step3: AI解析
→ Step4: ルールチェック → Step4.5: ファイル間整合 → Step5: アノテーション生成
"""
import os
import uuid
import logging
from pathlib import Path

from app.core.config import get_settings
from app.services.pdf_extractor import extract_pdf, estimate_tokens_for_pages, PageData
from app.services.ai_engine import create_ai_engine, calculate_cost
from app.services.rule_engine import run_rule_checks
from app.services.annotator import (
    annotate_pdf,
    build_annotations_from_results,
    build_relay_links,
)

logger = logging.getLogger(__name__)


async def estimate_project_cost(files: list[dict]) -> dict:
    """
    解析前のコスト推定
    files: [{"path": str, "drawing_type": str, "file_id": str}]
    """
    total_input_tokens = 0
    total_output_tokens = 0
    total_pages = 0

    for f in files:
        pages = extract_pdf(f["path"], render_images=False)
        total_pages += len(pages)
        estimate = estimate_tokens_for_pages(pages)
        total_input_tokens += estimate["estimated_input_tokens"]
        total_output_tokens += estimate["estimated_output_tokens"]

    # クロスチェック用プロンプト分を追加
    total_input_tokens += 5000
    total_output_tokens += 2000

    cost = calculate_cost(total_input_tokens, total_output_tokens)

    return {
        "file_count": len(files),
        "total_pages": total_pages,
        "estimated_input_tokens": total_input_tokens,
        "estimated_output_tokens": total_output_tokens,
        "estimated_cost_usd": cost,
    }


async def run_analysis(files: list[dict]) -> dict:
    """
    フルパイプラインを実行する
    files: [{"path": str, "drawing_type": str, "file_id": str, "filename": str}]
    Returns: {
        "check_results": [...],
        "uncertain_items": [...],
        "annotated_files": {file_id: annotated_path},
        "usage": {input_tokens, output_tokens, cost_usd},
        "page_entities": [...],
    }
    """
    ai_engine = create_ai_engine()
    all_page_entities: list[dict] = []
    file_page_data: dict[str, list[PageData]] = {}
    drawing_types: dict[str, str] = {}

    # --- Step 1-3: 各ファイルのPDF抽出とAI解析 ---
    for f in files:
        file_id = f["file_id"]
        drawing_type = f.get("drawing_type", "unknown")
        drawing_types[file_id] = drawing_type

        logger.info(f"Extracting: {f['filename']}")
        pages = extract_pdf(f["path"], render_images=True)
        file_page_data[file_id] = pages

        # 解析ページ範囲（設定で変更可能）
        s = get_settings()
        start = s.analysis_page_start
        end = s.analysis_page_end
        pages_to_analyze = pages[start:end]
        logger.info(f"  Analyzing pages {start+1}–{min(end, len(pages))} of {len(pages)}")

        for page in pages_to_analyze:
            logger.info(f"  AI analyzing page {page.page_number}...")
            ai_result = await ai_engine.analyze_page(page, drawing_type)

            all_page_entities.append({
                "file_id": file_id,
                "page": page.page_number,
                "entities": ai_result.get("entities", []),
                "customer_name": ai_result.get("customer_name"),
                "electrical_specs": ai_result.get("electrical_specs", []),
                "logic_elements": ai_result.get("logic_elements", []),
                "uncertain_items": ai_result.get("uncertain_items", []),
            })

    # --- Step 4: ルールベースチェック ---
    logger.info("Running rule checks...")
    rule_issues = run_rule_checks(all_page_entities)
    check_results = [issue.to_dict() for issue in rule_issues]

    # --- Step 4.5: AI横断チェック ---
    logger.info("Running AI cross-check...")
    cross_result = await ai_engine.cross_check(all_page_entities, drawing_types)
    for issue in cross_result.get("issues", []):
        check_results.append({
            "check_type": issue.get("check_type", "cross_check"),
            "severity": issue.get("severity", "warning"),
            "message": issue.get("message", ""),
            "file_id": None,
            "page_number": None,
            "location_rect": None,
            "detail": {
                "affected_tags": issue.get("affected_tags", []),
                "affected_files": issue.get("affected_files", []),
            },
        })

    all_uncertain = []
    for ep in all_page_entities:
        for u in ep.get("uncertain_items", []):
            all_uncertain.append({
                "file_id": ep["file_id"],
                "page": ep["page"],
                **u,
            })
    all_uncertain.extend(cross_result.get("uncertain_items", []))

    # --- Step 5: アノテーション付きPDF生成 ---
    logger.info("Generating annotated PDFs...")
    annotated_files: dict[str, str] = {}
    settings = get_settings()
    os.makedirs(settings.output_dir, exist_ok=True)

    for f in files:
        file_id = f["file_id"]
        pages = file_page_data[file_id]
        page_count = len(pages)

        # このファイルに関連するチェック結果だけ抽出
        file_results = [r for r in check_results if r.get("file_id") == file_id]
        file_entities = [ep for ep in all_page_entities if ep["file_id"] == file_id]

        annotations_by_page, links_by_page = build_annotations_from_results(
            page_count, file_results, file_entities
        )

        # リレーリンク構築
        coil_locations = {}
        contact_locations = []
        for ep in all_page_entities:
            for logic_el in ep.get("logic_elements", []):
                tag = logic_el.get("tag", "")
                rect = logic_el.get("rect")
                if logic_el.get("element_type") == "coil":
                    coil_locations[tag] = {"page": ep["page"], "rect": rect, "file_id": ep["file_id"]}
                elif logic_el.get("element_type") in ("no_contact", "nc_contact"):
                    contact_locations.append({"tag": tag, "page": ep["page"], "rect": rect, "file_id": ep["file_id"]})

        relay_links = build_relay_links(page_count, coil_locations, contact_locations)
        # links_by_pageとマージ
        for pg, lnks in relay_links.items():
            links_by_page[pg].extend(lnks)

        annotated_path = annotate_pdf(
            f["path"],
            annotations_by_page,
            links_by_page,
            settings.output_dir,
        )
        annotated_files[file_id] = annotated_path

    # --- コスト集計 ---
    usage = ai_engine.get_usage()
    cost_usd = calculate_cost(usage["input_tokens"], usage["output_tokens"])

    return {
        "check_results": check_results,
        "uncertain_items": all_uncertain,
        "annotated_files": annotated_files,
        "usage": {
            "input_tokens": usage["input_tokens"],
            "output_tokens": usage["output_tokens"],
            "cost_usd": cost_usd,
        },
        "page_entities": all_page_entities,
    }

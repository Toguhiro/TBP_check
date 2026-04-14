"""
検図パイプライン全体のオーケストレーション

Phase 1: PDF抽出・正規化・行分類 (pdf_extractor.py)
Phase 2: テキスト構造化（xrefマップ・コイルテーブル・MCCB）(rule_engine.py)
Phase 2.5: 配線パス解析・回路グラフ構築 (WirePathAnalyzer)
Phase 3 / AI: 構造化済みデータを Claude に渡して最終判定
"""
import os
import logging
from collections import defaultdict
from typing import Optional

import fitz  # PyMuPDF

from app.core.config import get_settings
from app.services.pdf_extractor import extract_pdf, estimate_tokens_for_pages, PageData
from app.services.ai_engine import create_ai_engine, calculate_cost
from app.services.rule_engine import (
    run_rule_checks,
    build_xref_map,
    parse_coil_table,
    extract_mccb_specs,
    CheckIssue,
)
from app.services.annotator import (
    annotate_pdf,
    build_annotations_from_results,
    build_relay_links,
)

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Phase 2.5: 配線パス解析
# --------------------------------------------------------------------------- #
SNAP = 18   # px 許容誤差（シンボルと配線位置ズレ吸収）

# 回路エリアの境界（タイトルブロック除外・余白除外）
WIRE_X_MIN = 130.0
WIRE_X_MAX = 740.0
WIRE_Y_MIN = 77.0
WIRE_Y_MAX = 850.0


class WirePathAnalyzer:
    """
    PDFのベクタパスオブジェクトから配線を抽出し、
    直列グループ（AND）・並列分岐（OR）を検出して回路グラフを構築する。
    """

    def __init__(self):
        self.all_wires: list[dict] = []        # 全ページ全配線
        self.serial_groups: list[dict] = []    # AND グループ
        self.branch_points: list[dict] = []    # OR 分岐点

    # ------------------------------------------------------------------ #
    # 配線抽出
    # ------------------------------------------------------------------ #
    def extract_wires(
        self,
        fitz_page: fitz.Page,
        page_idx: int,
        x_min: float = WIRE_X_MIN,
        x_max: float = WIRE_X_MAX,
        y_min: float = WIRE_Y_MIN,
        y_max: float = WIRE_Y_MAX,
    ) -> list[dict]:
        """
        1ページから回路エリア内の線分を抽出する。

        Returns:
            [{x1, y1, x2, y2, horiz, vert, page}]
        """
        wires = []
        for path in fitz_page.get_drawings():
            for item in path.get('items', []):
                if item[0] != 'l':      # 直線のみ（'l'=line）
                    continue
                p1, p2 = item[1], item[2]
                # 回路エリア内にある線分のみ
                if not (x_min < p1.x < x_max and y_min < p1.y < y_max and
                        x_min < p2.x < x_max and y_min < p2.y < y_max):
                    continue
                wires.append({
                    'x1': p1.x, 'y1': p1.y,
                    'x2': p2.x, 'y2': p2.y,
                    'horiz': abs(p2.y - p1.y) < 3,   # 水平線
                    'vert':  abs(p2.x - p1.x) < 3,   # 垂直線
                    'page':  page_idx,
                })
        return wires

    # ------------------------------------------------------------------ #
    # 直列グループ検出（AND 論理）
    # ------------------------------------------------------------------ #
    def build_serial_groups(
        self,
        wires: list[dict],
        symbols: list[dict],
        page_idx: int,
    ) -> list[dict]:
        """
        水平線上にあるシンボルを収集して直列接続グループを検出する。
        回路論理では AND 条件に対応。

        Args:
            wires:   extract_wires() の結果
            symbols: classified_lines から取得した {text, kind, rect} のリスト
        """
        groups = []
        h_wires = [w for w in wires if w['horiz']]

        for w in h_wires:
            x_lo = min(w['x1'], w['x2'])
            x_hi = max(w['x1'], w['x2'])
            wy   = w['y1']

            on_wire = [
                s for s in symbols
                if (s.get('rect') and
                    x_lo - SNAP <= s['rect'][0] <= x_hi + SNAP and
                    abs(s['rect'][1] - wy) < SNAP)
            ]
            if len(on_wire) >= 2:
                groups.append({
                    'wire_y':  round(wy, 1),
                    'x_range': (round(x_lo, 1), round(x_hi, 1)),
                    'symbols': [s['text'] for s in sorted(on_wire, key=lambda s: s['rect'][0])],
                    'kinds':   [s['kind'] for s in sorted(on_wire, key=lambda s: s['rect'][0])],
                    'logic':   'AND',
                    'page':    page_idx,
                })
        return groups

    # ------------------------------------------------------------------ #
    # 並列分岐点検出（OR 論理）
    # ------------------------------------------------------------------ #
    def find_branch_points(
        self,
        wires: list[dict],
        page_idx: int,
    ) -> list[dict]:
        """
        垂直線が水平線と交差する点を並列分岐（OR）として検出する。
        """
        branch_points = []
        v_wires = [w for w in wires if w['vert']]
        h_wires = [w for w in wires if w['horiz']]

        for vw in v_wires:
            vx     = vw['x1']
            vy_min = min(vw['y1'], vw['y2'])
            vy_max = max(vw['y1'], vw['y2'])

            crossing = [
                w for w in h_wires
                if abs(w['y1'] - vy_min) > 5        # 端点ではない
                and abs(w['y1'] - vy_max) > 5
                and vy_min < w['y1'] < vy_max        # 垂直線の範囲内
                and min(w['x1'], w['x2']) <= vx <= max(w['x1'], w['x2'])
            ]
            if crossing:
                branch_points.append({
                    'x':          round(vx, 1),
                    'y_range':    (round(vy_min, 1), round(vy_max, 1)),
                    'crossing_y': [round(w['y1'], 1) for w in crossing],
                    'logic':      'OR',
                    'page':       page_idx,
                })
        return branch_points

    # ------------------------------------------------------------------ #
    # 全図面回路グラフ構築
    # ------------------------------------------------------------------ #
    def build_circuit_graph(
        self,
        pages: list[PageData],
        xref_map: dict,
        coil_tables: list[dict],
        pdf_path: str,
    ) -> dict:
        """
        全ページの配線データ＋xref_map＋coil_tables を統合して
        回路グラフを構築する。

        Returns:
            {
                'nodes':          {tag: {pages, kind}},
                'edges':          [{from, to, via, resolved}],
                'serial_groups':  [...],  AND条件
                'branch_points':  [...],  OR条件
                'coil_tables':    [...],
                'unresolved':     [...],  未解決 xref
            }
        """
        doc = fitz.open(pdf_path)
        all_serial: list[dict] = []
        all_branch: list[dict] = []
        all_wires:  list[dict] = []

        for page in pages:
            pg_idx = page.page_number
            if pg_idx >= len(doc):
                continue

            fitz_page = doc[pg_idx]
            wires = self.extract_wires(fitz_page, pg_idx)
            all_wires.extend(wires)

            # 接点・タグ等のシンボル（tag_no と cross_ref のみ配線解析対象）
            symbols = [
                e for e in page.classified_lines
                if e.get('kind') in ('tag_no', 'cross_ref', 'relay_model')
            ]

            groups = self.build_serial_groups(wires, symbols, pg_idx)
            all_serial.extend(groups)

            branches = self.find_branch_points(wires, pg_idx)
            all_branch.extend(branches)

        doc.close()

        self.all_wires     = all_wires
        self.serial_groups = all_serial
        self.branch_points = all_branch

        # ノード（Tag.No → 出現ページ）
        nodes: dict[str, dict] = defaultdict(lambda: {'pages': [], 'kind': 'unknown'})
        for page in pages:
            for e in page.classified_lines:
                if e.get('kind') == 'tag_no':
                    nodes[e['text']]['pages'].append(page.page_number + 1)
                    nodes[e['text']]['kind'] = 'tag'

        # エッジ（xref 解決済みのコイル↔接点対応）
        edges: list[dict] = []
        for ref, info in xref_map.items():
            edges.append({
                'from':     ref,
                'to_pages': info['pages'],
                'via':      f'xref_{ref}',
                'resolved': info['resolved'],
                'source_page': info.get('source_page'),
            })

        # 未解決 xref
        unresolved = [
            {'xref': ref, 'source_page': info.get('source_page')}
            for ref, info in xref_map.items()
            if not info['resolved']
        ]

        logger.info(
            f"Circuit graph built: nodes={len(nodes)}, edges={len(edges)}, "
            f"serial={len(all_serial)}, branch={len(all_branch)}, "
            f"wires={len(all_wires)}, unresolved={len(unresolved)}"
        )

        return {
            'nodes':         dict(nodes),
            'edges':         edges,
            'serial_groups': all_serial,
            'branch_points': all_branch,
            'coil_tables':   coil_tables,
            'unresolved':    unresolved,
        }


# --------------------------------------------------------------------------- #
# コスト推定（事前確認フロー）
# --------------------------------------------------------------------------- #
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

    total_input_tokens += 5000   # クロスチェック用プロンプト分
    total_output_tokens += 2000

    cost = calculate_cost(total_input_tokens, total_output_tokens)

    return {
        "file_count": len(files),
        "total_pages": total_pages,
        "estimated_input_tokens": total_input_tokens,
        "estimated_output_tokens": total_output_tokens,
        "estimated_cost_usd": cost,
    }


# --------------------------------------------------------------------------- #
# メイン解析パイプライン
# --------------------------------------------------------------------------- #
async def run_analysis(files: list[dict]) -> dict:
    """
    フルパイプラインを実行する

    files: [{"path": str, "drawing_type": str, "file_id": str, "filename": str}]

    Returns:
        {
            "check_results":   [...],
            "uncertain_items": [...],
            "annotated_files": {file_id: annotated_path},
            "usage":           {input_tokens, output_tokens, cost_usd},
            "page_entities":   [...],
        }
    """
    ai_engine = create_ai_engine()
    wire_analyzer = WirePathAnalyzer()

    all_page_entities: list[dict] = []
    file_page_data: dict[str, list[PageData]] = {}
    drawing_types: dict[str, str] = {}

    # ------------------------------------------------------------------ #
    # Phase 1: 全ファイル PDF 抽出・行分類
    # ------------------------------------------------------------------ #
    all_classified_by_file: dict[str, list[list[dict]]] = {}   # file_id → [page_lines, ...]

    for f in files:
        file_id      = f["file_id"]
        drawing_type = f.get("drawing_type", "unknown")
        drawing_types[file_id] = drawing_type

        logger.info(f"[Phase1] Extracting: {f['filename']}")
        pages = extract_pdf(f["path"], render_images=True)
        file_page_data[file_id] = pages

        all_classified_by_file[file_id] = [p.classified_lines for p in pages]

        s = get_settings()
        start = s.analysis_page_start
        end   = s.analysis_page_end
        logger.info(f"  Pages {start+1}–{min(end, len(pages))} of {len(pages)} will be analyzed")

    # ------------------------------------------------------------------ #
    # Phase 2: テキスト構造化（xref マップ・コイルテーブル・MCCB）
    # ------------------------------------------------------------------ #
    logger.info("[Phase2] Building xref map and coil tables...")

    # 全ファイルの classified_lines を解析範囲分だけフラット化
    s = get_settings()
    all_classified_flat: list[list[dict]] = []
    for f in files:
        pages = file_page_data[f["file_id"]]
        for pg in pages[s.analysis_page_start:s.analysis_page_end]:
            all_classified_flat.append(pg.classified_lines)

    xref_map = build_xref_map(all_classified_flat)

    # コイルテーブル・MCCB 定格チェック（ファイル・ページごと）
    coil_tables_all: list[dict] = []
    mccb_issues: list[CheckIssue] = []

    for f in files:
        file_id = f["file_id"]
        pages   = file_page_data[file_id]
        for pg in pages[s.analysis_page_start:s.analysis_page_end]:
            coils = parse_coil_table(pg.classified_lines, pg.page_height)
            for coil in coils:
                coil['file_id']  = file_id
                coil['page']     = pg.page_number
                coil_tables_all.append(coil)

            # MCCB 定格チェック
            mccb_specs = extract_mccb_specs(pg.classified_lines)
            for spec in mccb_specs:
                if not spec['jis_ok']:
                    mccb_issues.append(CheckIssue(
                        check_type="breaker_rating",
                        severity="warning",
                        message=(f"JIS C 8201 非標準の遮断器定格: "
                                 f"{spec['poles']}P {spec['af']}AF/{spec['at']}AT"),
                        file_id=file_id,
                        page_number=pg.page_number,
                        location_rect=spec.get('rect'),
                        detail={'af': spec['af'], 'at': spec['at'],
                                'jis_mccb_table_af': spec['af']},
                    ))

    # 未解決 xref を uncertain_items へ（後で追加）
    # 単線結線図のみの場合はクロスリファレンス不要なのでスキップ
    all_single_line = all(dt == 'single_line' for dt in drawing_types.values())
    xref_unresolved_items: list[dict] = []
    if not all_single_line:
        for ref, info in xref_map.items():
            if not info['resolved']:
                xref_unresolved_items.append({
                    'text':   f'<{ref}>',
                    'reason': f'参照先 Tag.No "{ref}" が図面内に見つかりません（解析ページ範囲外の可能性）',
                    'page':   info.get('source_page', 0) - 1,  # 0-indexed
                })

    # ------------------------------------------------------------------ #
    # Phase 2.5: 配線パス解析・回路グラフ構築
    # ------------------------------------------------------------------ #
    logger.info("[Phase2.5] Building circuit graph from wire paths...")

    circuit_graphs: dict[str, dict] = {}
    for f in files:
        file_id = f["file_id"]
        pages   = file_page_data[file_id]
        pages_to_analyze = pages[s.analysis_page_start:s.analysis_page_end]

        file_coil_tables = [ct for ct in coil_tables_all if ct.get('file_id') == file_id]
        graph = wire_analyzer.build_circuit_graph(
            pages_to_analyze,
            xref_map,
            file_coil_tables,
            f["path"],
        )
        circuit_graphs[file_id] = graph

    # ------------------------------------------------------------------ #
    # Phase 3 / AI: 構造化データを Claude に渡す
    # ------------------------------------------------------------------ #
    logger.info("[Phase3/AI] Running AI analysis with circuit graph...")

    for f in files:
        file_id      = f["file_id"]
        drawing_type = drawing_types[file_id]
        pages        = file_page_data[file_id]
        graph        = circuit_graphs[file_id]

        pages_to_analyze = pages[s.analysis_page_start:s.analysis_page_end]
        for page in pages_to_analyze:
            logger.info(f"  AI analyzing page {page.page_number + 1}...")
            ai_result = await ai_engine.analyze_page(
                page,
                drawing_type,
                context={'circuit_graph': graph, 'xref_map': xref_map},
            )

            # classified_lines から location_rect を補完
            # AI が rect を返さない場合、対応する classified_line から取得
            for entity in ai_result.get("entities", []):
                if not entity.get("rect"):
                    entity["rect"] = _find_rect_for_tag(
                        entity.get("tag", ""), page.classified_lines
                    )

            all_page_entities.append({
                "file_id":          file_id,
                "page":             page.page_number,
                "entities":         ai_result.get("entities", []),
                "customer_name":    ai_result.get("customer_name"),
                "electrical_specs": ai_result.get("electrical_specs", []),
                "logic_elements":   ai_result.get("logic_elements", []),
                "uncertain_items":  ai_result.get("uncertain_items", []),
            })

    # ------------------------------------------------------------------ #
    # ルールベースチェック
    # ------------------------------------------------------------------ #
    logger.info("[Rule] Running rule checks...")
    rule_issues = run_rule_checks(all_page_entities)
    rule_issues.extend(mccb_issues)   # Phase 2 の MCCB チェック結果を追加

    # xref 整合チェック（Phase 2 の xref_map から生成）
    # 単線結線図はクロスリファレンスを記載しない図面種別なのでスキップ
    non_single_line_files = [
        fid for fid, dt in drawing_types.items() if dt != 'single_line'
    ]
    if non_single_line_files:
        xref_check_issues = _check_xref_consistency(xref_map)
        rule_issues.extend(xref_check_issues)
    else:
        logger.info("[Rule] xref check skipped: all files are single_line drawing type")

    check_results = [issue.to_dict() for issue in rule_issues]

    # ------------------------------------------------------------------ #
    # AI 横断チェック
    # ------------------------------------------------------------------ #
    logger.info("[AI] Running cross-file check...")
    cross_result = await ai_engine.cross_check(all_page_entities, drawing_types)
    for issue in cross_result.get("issues", []):
        check_results.append({
            "check_type":    issue.get("check_type", "cross_check"),
            "severity":      issue.get("severity", "warning"),
            "message":       issue.get("message", ""),
            "file_id":       None,
            "page_number":   None,
            "location_rect": None,
            "detail": {
                "affected_tags":  issue.get("affected_tags", []),
                "affected_files": issue.get("affected_files", []),
            },
        })

    # ------------------------------------------------------------------ #
    # uncertain_items 集計
    # ------------------------------------------------------------------ #
    all_uncertain = []
    for ep in all_page_entities:
        for u in ep.get("uncertain_items", []):
            all_uncertain.append({
                "file_id": ep["file_id"],
                "page":    ep["page"],
                **u,
            })
    all_uncertain.extend(cross_result.get("uncertain_items", []))
    # 未解決 xref を uncertain_items に追加（file_id なし扱い）
    for item in xref_unresolved_items[:20]:   # 多すぎる場合は先頭20件
        all_uncertain.append({
            "file_id": None,
            **item,
        })

    # ------------------------------------------------------------------ #
    # アノテーション付き PDF 生成
    # ------------------------------------------------------------------ #
    logger.info("[Annotate] Generating annotated PDFs...")
    annotated_files: dict[str, str] = {}
    settings = get_settings()
    os.makedirs(settings.output_dir, exist_ok=True)

    for f in files:
        file_id    = f["file_id"]
        pages      = file_page_data[file_id]
        page_count = len(pages)

        file_results  = [r for r in check_results if r.get("file_id") == file_id]
        file_entities = [ep for ep in all_page_entities if ep["file_id"] == file_id]

        annotations_by_page, links_by_page = build_annotations_from_results(
            page_count, file_results, file_entities
        )

        coil_locations: dict = {}
        contact_locations: list = []
        for ep in all_page_entities:
            for logic_el in ep.get("logic_elements", []):
                tag  = logic_el.get("tag", "")
                rect = logic_el.get("rect")
                if logic_el.get("element_type") == "coil":
                    coil_locations[tag] = {
                        "page": ep["page"], "rect": rect, "file_id": ep["file_id"]
                    }
                elif logic_el.get("element_type") in ("no_contact", "nc_contact"):
                    contact_locations.append({
                        "tag": tag, "page": ep["page"],
                        "rect": rect, "file_id": ep["file_id"]
                    })

        # コイルテーブルから取得した接点情報でリレーリンクを補完
        for ct in coil_tables_all:
            if ct.get('file_id') != file_id:
                continue
            tag = ct.get('tag', '')
            if tag and ct.get('rect'):
                coil_locations.setdefault(tag, {
                    'page': ct['page'], 'rect': ct['rect'], 'file_id': file_id
                })
            for contact in ct.get('contacts', []):
                if contact.get('rect'):
                    contact_locations.append({
                        'tag': tag, 'page': ct['page'],
                        'rect': contact['rect'], 'file_id': file_id
                    })

        relay_links = build_relay_links(page_count, coil_locations, contact_locations)
        for pg, lnks in relay_links.items():
            links_by_page[pg].extend(lnks)

        annotated_path = annotate_pdf(
            f["path"],
            annotations_by_page,
            links_by_page,
            settings.output_dir,
        )
        annotated_files[file_id] = annotated_path

    # ------------------------------------------------------------------ #
    # コスト集計
    # ------------------------------------------------------------------ #
    usage    = ai_engine.get_usage()
    cost_usd = calculate_cost(usage["input_tokens"], usage["output_tokens"])

    return {
        "check_results":   check_results,
        "uncertain_items": all_uncertain,
        "annotated_files": annotated_files,
        "usage": {
            "input_tokens":  usage["input_tokens"],
            "output_tokens": usage["output_tokens"],
            "cost_usd":      cost_usd,
        },
        "page_entities": all_page_entities,
    }


# --------------------------------------------------------------------------- #
# ヘルパー関数
# --------------------------------------------------------------------------- #
def _find_rect_for_tag(tag: str, classified_lines: list[dict]) -> Optional[list]:
    """AI が rect を返せなかった場合、classified_lines からタグの rect を補完する"""
    if not tag:
        return None
    for e in classified_lines:
        if e.get('text') == tag and e.get('rect'):
            return e['rect']
    return None


def _check_xref_consistency(xref_map: dict) -> list[CheckIssue]:
    """
    xref_map から未解決クロスリファレンスを CheckIssue として生成する。
    未解決件数が多すぎる場合は警告レベルに留める。
    """
    issues: list[CheckIssue] = []
    unresolved = [(ref, info) for ref, info in xref_map.items() if not info['resolved']]

    total = len(xref_map)
    n_unresolved = len(unresolved)

    if total > 0:
        rate = n_unresolved / total
        severity = "error" if rate < 0.3 else "warning"  # 未解決が30%未満ならエラー扱い
    else:
        return issues

    if n_unresolved > 0:
        # 代表的な未解決 xref を最大10件リスト化
        sample = [ref for ref, _ in unresolved[:10]]
        issues.append(CheckIssue(
            check_type="relay_cross_ref",
            severity=severity,
            message=(f"クロスリファレンス未解決: {n_unresolved}/{total} 件 "
                     f"（例: {', '.join(sample)}{'...' if n_unresolved > 10 else ''}）"),
            detail={
                'unresolved_count': n_unresolved,
                'total_count': total,
                'sample_unresolved': sample,
            },
        ))

    return issues

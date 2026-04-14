#!/usr/bin/env python3
"""
PDF分類可視化ツール（診断用）

各要素を以下の種別に分類して直接色付けした診断PDFを生成する:

  テキスト:
    赤   - Tag.No        (88X, 51-1, 43AT など)
    青   - クロスリファレンス (<09A> など)
    紫   - 回路番号       (0911, 121011 など)
    緑   - リレー型番     (MY4ZN, H3CR など)
    黄橙 - 端子番号       (1, 2, ●1 など)
    灰   - その他テキスト
    水色 - タイトルブロック / 参照行

  線分:
    シアン   - 水平配線 (long horizontal)
    青       - 垂直配線 (long vertical)
    オレンジ - シンボル構成線 (短い線・図形)

使い方:
  cd drawing-checker/backend
  python ../tools/classify_viz.py <入力PDF> [出力PDF]
"""
import sys
import re
import unicodedata
from pathlib import Path
import fitz  # PyMuPDF

# ── 分類定数 ───────────────────────────────────────────────────────────────
TITLE_BLOCK_X = 700.0   # raw_x > 700 → タイトルブロック・右欄
TITLE_BLOCK_Y = 1100.0  # raw_y > 1100 → 参照行（最下段）
WIRE_MIN_LEN  = 18.0    # これ以上の長さを配線と見なす (pt)
ANGLE_THRESH  = 2.0     # 水平・垂直判定の許容ずれ (pt)

XREF_PAT     = re.compile(r'^<([0-9A-Z\-]+)>$')
TAG_PAT      = re.compile(
    r'^[0-9]{2,3}[A-Z]{1,5}[0-9]?(-[0-9]+)?$'
    r'|^[0-9]{2,3}-[0-9]+$'
)
CIRCUIT_PAT  = re.compile(r'^[0-9]{4,7}$')
RELAY_PAT    = re.compile(r'^(MY|H3|SRD|MK|LY|G2R|H3CR|RH|SY|PF)[0-9A-Z\-]+$')
TERMINAL_PAT = re.compile(r'^[●○]?[0-9]{1,2}$')

# ── 色定義 (RGB 0.0-1.0) ─────────────────────────────────────────────────
C = {
    'tag_no':      (1.0,  0.15, 0.0),    # 赤
    'cross_ref':   (0.0,  0.45, 1.0),    # 青
    'circuit_no':  (0.55, 0.0,  0.85),   # 紫
    'relay_model': (0.0,  0.72, 0.15),   # 緑
    'terminal_no': (0.85, 0.55, 0.0),    # 黄橙
    'text':        (0.45, 0.45, 0.45),   # 灰
    'title_block': (0.1,  0.6,  0.75),   # 水色
    'wire_h':      (0.0,  0.78, 0.78),   # シアン
    'wire_v':      (0.0,  0.45, 0.9),    # 青
    'symbol_line': (1.0,  0.42, 0.0),    # オレンジ
}

LEGEND_ITEMS = [
    ('tag_no',      'Tag.No  (88X, 51-1, 43AT…)'),
    ('cross_ref',   'クロスリファレンス  (<09A>…)'),
    ('circuit_no',  '回路番号  (0911, 121011…)'),
    ('relay_model', 'リレー型番  (MY4ZN, H3CR…)'),
    ('terminal_no', '端子番号  (1, 2, ●1…)'),
    ('text',        'その他テキスト'),
    ('title_block', 'タイトルブロック / 参照行'),
    ('wire_h',      '水平配線（横線）'),
    ('wire_v',      '垂直配線（縦線）'),
    ('symbol_line', 'シンボル線（短い線・図形）'),
]


# ── テキスト分類 ────────────────────────────────────────────────────────────
def normalize(text: str) -> str:
    return unicodedata.normalize('NFKC', text.strip())

def classify_text(text: str, raw_x: float, raw_y: float) -> str:
    if raw_x > TITLE_BLOCK_X or raw_y > TITLE_BLOCK_Y:
        return 'title_block'
    t = normalize(text)
    if not t:               return 'text'
    if XREF_PAT.match(t):  return 'cross_ref'
    if TAG_PAT.match(t):   return 'tag_no'
    if CIRCUIT_PAT.match(t): return 'circuit_no'
    if RELAY_PAT.match(t): return 'relay_model'
    if TERMINAL_PAT.match(t): return 'terminal_no'
    return 'text'


# ── 線分分類 ────────────────────────────────────────────────────────────────
def classify_line(p1: fitz.Point, p2: fitz.Point) -> str:
    dx = abs(p2.x - p1.x)
    dy = abs(p2.y - p1.y)
    length = (dx**2 + dy**2) ** 0.5

    # タイトルブロック内
    if min(p1.x, p2.x) > TITLE_BLOCK_X:
        return 'title_block'

    if dy <= ANGLE_THRESH and dx >= WIRE_MIN_LEN:
        return 'wire_h'
    if dx <= ANGLE_THRESH and dy >= WIRE_MIN_LEN:
        return 'wire_v'
    return 'symbol_line'

def classify_rect(r: fitz.Rect) -> str:
    if r.x0 > TITLE_BLOCK_X:
        return 'title_block'
    return 'symbol_line'


# ── ページ処理 ──────────────────────────────────────────────────────────────
def process_page(page: fitz.Page) -> dict:
    """ページに分類色をオーバードローする。統計を返す"""
    stats = {k: 0 for k in C}

    # ── 1. ベクタパス（配線・シンボル線） ───────────────────────────────────
    drawings = page.get_drawings()
    for d in drawings:
        orig_w = d.get('width') or 0.5
        draw_w = max(orig_w * 1.4, 1.2)

        for seg in d.get('items', []):
            stype = seg[0]

            if stype == 'l':  # 直線
                p1, p2 = seg[1], seg[2]
                kind = classify_line(p1, p2)
                color = C[kind]
                page.draw_line(p1, p2, color=color, width=draw_w)
                stats[kind] += 1

            elif stype == 'c':  # ベジェ曲線
                p1, cp1, cp2, p2 = seg[1], seg[2], seg[3], seg[4]
                kind = 'symbol_line'
                if min(p1.x, p2.x) > TITLE_BLOCK_X:
                    kind = 'title_block'
                color = C[kind]
                page.draw_bezier(p1, cp1, cp2, p2, color=color, width=draw_w)
                stats[kind] += 1

            elif stype == 're':  # 矩形
                r = seg[1]
                kind = classify_rect(r)
                color = C[kind]
                page.draw_rect(r, color=color, fill=color,
                               fill_opacity=0.12, width=max(orig_w, 0.8))
                stats[kind] += 1

            elif stype == 'qu':  # 四角形（クワッド）
                kind = 'symbol_line'
                color = C[kind]
                q = seg[1]
                pts = [q.ul, q.ur, q.lr, q.ll, q.ul]
                for i in range(len(pts)-1):
                    page.draw_line(pts[i], pts[i+1], color=color, width=draw_w)
                stats[kind] += 1

    # ── 2. テキスト ─────────────────────────────────────────────────────────
    # raw座標系で取得（get_drawings()と同一座標系）
    blocks = page.get_text('rawdict')['blocks']
    for blk in blocks:
        if blk.get('type') != 0:
            continue
        bx0 = blk['bbox'][0]
        by0 = blk['bbox'][1]

        for line in blk.get('lines', []):
            # ライン全体のテキストで種別判定
            chars_text = ''.join(
                ch.get('c', '') for span in line.get('spans', [])
                for ch in span.get('chars', [])
            )
            line_text = normalize(chars_text)
            kind = classify_text(line_text, bx0, by0)
            color = C[kind]
            stats[kind] += 1

            # 文字単位でタイトな背景色を塗る
            for span in line.get('spans', []):
                for ch in span.get('chars', []):
                    if not ch.get('c', '').strip():
                        continue
                    r = fitz.Rect(ch['bbox'])
                    if r.is_empty or r.width < 0.5 or r.height < 0.5:
                        continue
                    # 少し拡張して読みやすく
                    r = r + (-0.5, -0.5, 0.5, 0.5)
                    page.draw_rect(r, color=None, fill=color,
                                   fill_opacity=0.35, width=0)
                    # 下線で種別強調
                    page.draw_line(
                        fitz.Point(r.x0, r.y1 - 0.3),
                        fitz.Point(r.x1, r.y1 - 0.3),
                        color=color, width=0.8
                    )

    return stats


# ── 凡例をピクセル画像上に描画 ──────────────────────────────────────────────
def draw_legend_on_pixmap(pix: fitz.Pixmap, stats: dict):
    """
    レンダリング済みピクセルマップの右下に凡例を描く（PIL使用）。
    display座標系なので回転の心配なし。
    """
    from PIL import Image, ImageDraw, ImageFont
    import io

    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    draw = ImageDraw.Draw(img, "RGBA")

    # フォント（サイズ）
    try:
        font_title = ImageFont.truetype("C:/Windows/Fonts/meiryo.ttc", 14)
        font_item  = ImageFont.truetype("C:/Windows/Fonts/meiryo.ttc", 12)
    except Exception:
        font_title = ImageFont.load_default()
        font_item  = font_title

    ITEMS_PER_COL = 5
    ROW_H   = 20
    BOX_SZ  = 12
    COL_W   = 260
    PAD     = 10

    n_cols    = (len(LEGEND_ITEMS) + ITEMS_PER_COL - 1) // ITEMS_PER_COL
    legend_w  = n_cols * COL_W + PAD * 2
    legend_h  = ITEMS_PER_COL * ROW_H + PAD * 2 + 20  # +20 for title

    # 右下に配置
    lx = pix.width  - legend_w - 10
    ly = pix.height - legend_h - 10

    # 背景
    draw.rectangle([lx, ly, lx + legend_w, ly + legend_h],
                   fill=(15, 15, 25, 210), outline=(100, 100, 120, 255), width=1)

    # タイトル
    draw.text((lx + PAD, ly + PAD), "分類凡例 / Legend",
              font=font_title, fill=(235, 235, 235, 255))

    for i, (kind, label) in enumerate(LEGEND_ITEMS):
        col = i // ITEMS_PER_COL
        row = i % ITEMS_PER_COL
        ix = lx + PAD + col * COL_W
        iy = ly + PAD + 20 + row * ROW_H

        # RGB 0-1 → 0-255
        r, g, b = C[kind]
        rgb = (int(r*255), int(g*255), int(b*255))

        draw.rectangle([ix, iy + 2, ix + BOX_SZ, iy + BOX_SZ + 2],
                       fill=rgb + (220,))
        n = stats.get(kind, 0)
        draw.text((ix + BOX_SZ + 5, iy), f"{label} ({n})",
                  font=font_item, fill=(220, 220, 220, 255))

    # Pixmapに戻す（PIL Image → PNG bytes → fitz.Pixmap）
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return fitz.Pixmap(buf.read())


# ── メイン ─────────────────────────────────────────────────────────────────
def main():
    if len(sys.argv) < 2:
        print("使い方: python classify_viz.py <input.pdf> [output.pdf]")
        sys.exit(1)

    input_path = Path(sys.argv[1])
    if len(sys.argv) > 2:
        output_path = Path(sys.argv[2])
    else:
        output_path = input_path.parent / f"classified_{input_path.stem}.pdf"

    print(f"入力: {input_path}")
    src_doc = fitz.open(str(input_path))
    out_doc = fitz.open()
    print(f"ページ数: {len(src_doc)}")

    total_stats = {k: 0 for k in C}

    for i in range(len(src_doc)):
        print(f"  ページ {i+1}/{len(src_doc)} 処理中...", end="", flush=True)

        page = src_doc[i]

        # 1) 元ページに分類色をオーバードロー
        stats = process_page(page)
        for k, v in stats.items():
            total_stats[k] += v

        # 2) 2倍解像度でラスタライズ（回転も自動適用される）
        mat = fitz.Matrix(2, 2)
        pix = page.get_pixmap(matrix=mat, alpha=False)

        # 3) PIL で凡例を右下に追加
        pix = draw_legend_on_pixmap(pix, stats)

        # 4) 新ドキュメントに画像ページとして追加
        img_page = out_doc.new_page(width=pix.width / 2, height=pix.height / 2)
        img_page.insert_image(img_page.rect, pixmap=pix)

        print(f" 完了")

    out_doc.save(str(output_path))
    src_doc.close()
    out_doc.close()

    print(f"\n出力: {output_path}")
    print("\n分類統計:")
    for kind, label in LEGEND_ITEMS:
        n = total_stats.get(kind, 0)
        bar = '#' * min(n // 5, 40)
        print(f"  {label[:35]:<35} {n:4d}  {bar}")


if __name__ == '__main__':
    main()

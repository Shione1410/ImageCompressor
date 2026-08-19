from __future__ import annotations

MM_PER_INCH = 25.4

# 日本で一般的に使われる用紙寸法（mm）
PAPER_SIZES_MM = {
    "L判": (89.0, 127.0),
    "はがき": (100.0, 148.0),
    "A4": (210.0, 297.0),
    "A3": (297.0, 420.0),
}

# アプリ内で採用する印刷品質の目安。
# 「標準」「高画質」は余裕を持たせた判定値としている。
PRINT_PPI_REQUIREMENTS = {
    "最低画質（容量優先）": 150,
    "標準": 240,
    "高画質": 300,
}

# 印刷用途では容量目標より画質を優先し、固定JPEG品質で保存する。
PRINT_JPEG_QUALITY = {
    "最低画質（容量優先）": 75,
    "標準": 88,
    "高画質": 95,
}


def effective_ppi(width_px: int, height_px: int, paper_name: str) -> float:
    """画像の向きを用紙の向きに合わせ、用紙全体に収める前提の実効ppiを返す。"""
    if paper_name not in PAPER_SIZES_MM:
        raise ValueError(f"未対応の印刷サイズです: {paper_name}")
    if width_px <= 0 or height_px <= 0:
        raise ValueError("画像サイズが不正です。")

    paper_w_mm, paper_h_mm = PAPER_SIZES_MM[paper_name]
    px_short, px_long = sorted((width_px, height_px))
    mm_short, mm_long = sorted((paper_w_mm, paper_h_mm))

    ppi_short = px_short / (mm_short / MM_PER_INCH)
    ppi_long = px_long / (mm_long / MM_PER_INCH)
    return min(ppi_short, ppi_long)


def evaluate_print(width_px: int, height_px: int, paper_name: str, quality_name: str) -> tuple[bool, float, int]:
    if quality_name not in PRINT_PPI_REQUIREMENTS:
        raise ValueError(f"未対応の印刷品質です: {quality_name}")
    ppi = effective_ppi(width_px, height_px, paper_name)
    required = PRINT_PPI_REQUIREMENTS[quality_name]
    return round(ppi) >= required, ppi, required

from __future__ import annotations

import io
from pathlib import Path
from PIL import Image, ImageOps, UnidentifiedImageError
from pillow_heif import register_heif_opener
from models import CompressionResult, CompressionStatus

register_heif_opener()
SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic", ".heif"}


def _prepare_image(image: Image.Image) -> Image.Image:
    image = ImageOps.exif_transpose(image)
    if image.mode in ("RGBA", "LA"):
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, "white")
        background.paste(rgba, mask=rgba.getchannel("A"))
        return background
    if image.mode == "P":
        if "transparency" in image.info:
            rgba = image.convert("RGBA")
            background = Image.new("RGB", rgba.size, "white")
            background.paste(rgba, mask=rgba.getchannel("A"))
            return background
        return image.convert("RGB")
    if image.mode not in ("RGB", "L"):
        return image.convert("RGB")
    return image


def _encode_jpeg(image: Image.Image, quality: int) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=quality, optimize=True, progressive=True)
    return buffer.getvalue()


def _failed(input_path: str, original_bytes: int, message: str) -> CompressionResult:
    return CompressionResult(
        CompressionStatus.FAILED, input_path, None, original_bytes, None, None, message
    )


def _load_image(input_path: str) -> tuple[Path, int, Image.Image] | CompressionResult:
    input_file = Path(input_path)
    original_bytes = input_file.stat().st_size if input_file.exists() else 0

    if not input_file.exists():
        return _failed(input_path, 0, "入力ファイルが見つかりません。")
    if input_file.suffix.lower() not in SUPPORTED_EXTENSIONS:
        return _failed(input_path, original_bytes, f"未対応形式です: {input_file.suffix}")

    try:
        with Image.open(input_file) as opened:
            image = _prepare_image(opened)
            image.load()
        return input_file, original_bytes, image
    except UnidentifiedImageError:
        return _failed(input_path, original_bytes, "画像として読み込めません。ファイルが壊れている可能性があります。")
    except PermissionError:
        return _failed(input_path, original_bytes, "ファイルの読み込み権限がありません。")
    except OSError as exc:
        return _failed(input_path, original_bytes, f"画像の読み込みでエラーが発生しました: {exc}")
    except Exception as exc:
        return _failed(input_path, original_bytes, f"予期しない読み込みエラーが発生しました: {exc}")


def compress_image(
    input_path: str,
    output_path: str,
    target_bytes: int,
    min_quality: int = 30,
    max_quality: int = 95,
) -> CompressionResult:
    """指定容量以下になる範囲で、可能な限り高いJPEG品質を探索する。"""
    loaded = _load_image(input_path)
    if isinstance(loaded, CompressionResult):
        return loaded

    _, original_bytes, image = loaded
    width, height = image.size

    if target_bytes <= 0:
        return _failed(input_path, original_bytes, "目標容量は1バイト以上で指定してください。")
    if not 1 <= min_quality <= max_quality <= 100:
        return _failed(input_path, original_bytes, "JPEG画質の設定値が不正です。")

    try:
        low, high = min_quality, max_quality
        best_data, best_quality = None, None

        while low <= high:
            quality = (low + high) // 2
            encoded = _encode_jpeg(image, quality)
            if len(encoded) <= target_bytes:
                best_data, best_quality = encoded, quality
                low = quality + 1
            else:
                high = quality - 1

        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        if best_data is not None:
            output_file.write_bytes(best_data)
            output_size = len(best_data)
            if output_size > original_bytes:
                return CompressionResult(
                    CompressionStatus.WARNING, input_path, str(output_file), original_bytes,
                    output_size, best_quality,
                    "JPEGへ変換しましたが、元画像より容量が増加しました。", width, height
                )
            return CompressionResult(
                CompressionStatus.SUCCESS, input_path, str(output_file), original_bytes,
                output_size, best_quality, "目標容量以下で保存しました。", width, height
            )

        minimum_data = _encode_jpeg(image, min_quality)
        output_file.write_bytes(minimum_data)
        return CompressionResult(
            CompressionStatus.WARNING, input_path, str(output_file), original_bytes,
            len(minimum_data), min_quality,
            "最低画質でも目標容量以下になりませんでした。", width, height
        )
    except PermissionError:
        return _failed(input_path, original_bytes, "保存先への書き込み権限がありません。")
    except OSError as exc:
        return _failed(input_path, original_bytes, f"保存処理でエラーが発生しました: {exc}")
    except Exception as exc:
        return _failed(input_path, original_bytes, f"予期しない保存エラーが発生しました: {exc}")


def compress_image_at_quality(
    input_path: str,
    output_path: str,
    quality: int,
    label: str = "指定画質",
) -> CompressionResult:
    """容量目標を使わず、指定JPEG品質で1回保存する。"""
    loaded = _load_image(input_path)
    if isinstance(loaded, CompressionResult):
        return loaded

    _, original_bytes, image = loaded
    width, height = image.size

    if not 1 <= quality <= 100:
        return _failed(input_path, original_bytes, "JPEG画質の設定値が不正です。")

    try:
        data = _encode_jpeg(image, quality)
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_bytes(data)
        output_size = len(data)
        if output_size > original_bytes:
            return CompressionResult(
                CompressionStatus.WARNING, input_path, str(output_file), original_bytes,
                output_size, quality,
                f"{label}（JPEG品質 {quality}）で保存しましたが、元画像より容量が増加しました。",
                width, height
            )
        return CompressionResult(
            CompressionStatus.SUCCESS, input_path, str(output_file), original_bytes,
            output_size, quality, f"{label}（JPEG品質 {quality}）で保存しました。", width, height
        )
    except PermissionError:
        return _failed(input_path, original_bytes, "保存先への書き込み権限がありません。")
    except OSError as exc:
        return _failed(input_path, original_bytes, f"保存処理でエラーが発生しました: {exc}")
    except Exception as exc:
        return _failed(input_path, original_bytes, f"予期しない保存エラーが発生しました: {exc}")

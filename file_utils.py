import os
from pathlib import Path

def ensure_output_directory(directory: str) -> Path:
    if not directory.strip():
        raise ValueError("保存先フォルダが指定されていません。")
    output_dir = Path(directory)
    output_dir.mkdir(parents=True, exist_ok=True)
    if not output_dir.is_dir():
        raise NotADirectoryError(f"保存先がフォルダではありません: {output_dir}")
    test_path = output_dir / ".write_test.tmp"
    try:
        test_path.write_bytes(b"test")
    finally:
        if test_path.exists():
            test_path.unlink()
    return output_dir

def sanitize_suffix(suffix: str) -> str:
    invalid = '<>:"/\\|?*'
    cleaned = "".join("_" if c in invalid else c for c in suffix.strip())
    return cleaned or "_compressed"

def create_output_path(input_path: str, output_directory: str, suffix="_compressed") -> str:
    input_file = Path(input_path)
    output_dir = ensure_output_directory(output_directory)
    safe_suffix = sanitize_suffix(suffix)
    candidate = output_dir / f"{input_file.stem}{safe_suffix}.jpg"
    counter = 2
    while candidate.exists() or candidate.resolve() == input_file.resolve():
        candidate = output_dir / f"{input_file.stem}{safe_suffix}_{counter}.jpg"
        counter += 1
    return str(candidate)

def human_readable_size(size_bytes):
    if size_bytes is None:
        return "-"
    size = float(size_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.2f} {unit}"
        size /= 1024

def open_folder(path: str):
    if not path:
        raise ValueError("フォルダが指定されていません。")
    os.startfile(path)

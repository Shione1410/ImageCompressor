from dataclasses import dataclass
from enum import Enum


class CompressionStatus(str, Enum):
    SUCCESS = "success"
    WARNING = "warning"
    FAILED = "failed"


@dataclass(slots=True)
class CompressionResult:
    status: CompressionStatus
    input_path: str
    output_path: str | None
    original_bytes: int
    output_bytes: int | None
    quality: int | None
    message: str
    width: int | None = None
    height: int | None = None

    @property
    def reduction_rate(self) -> float | None:
        """旧仕様互換。削減できた場合に正の値となる。"""
        if self.output_bytes is None or self.original_bytes <= 0:
            return None
        return (1 - self.output_bytes / self.original_bytes) * 100

    @property
    def size_change_rate(self) -> float | None:
        """容量変化率。削減は負、増加は正で表す。"""
        if self.output_bytes is None or self.original_bytes <= 0:
            return None
        return (self.output_bytes / self.original_bytes - 1) * 100


@dataclass(slots=True)
class LogEntry:
    timestamp: str
    file_name: str
    result_text: str
    status: CompressionStatus
    input_format: str
    output_format: str
    mode_text: str
    quality: int | None
    original_bytes: int
    output_bytes: int | None
    size_change_rate: float | None
    image_size: str
    print_setting: str
    ppi_text: str
    message: str
    input_path: str
    output_path: str | None

    def to_csv_row(self) -> list[str]:
        return [
            self.timestamp,
            self.file_name,
            self.result_text,
            self.input_format,
            self.output_format,
            self.mode_text,
            "" if self.quality is None else str(self.quality),
            str(self.original_bytes),
            "" if self.output_bytes is None else str(self.output_bytes),
            "" if self.size_change_rate is None else f"{self.size_change_rate:.2f}",
            self.image_size,
            self.print_setting,
            self.ppi_text,
            self.message,
            self.input_path,
            self.output_path or "",
        ]

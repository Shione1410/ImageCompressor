from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal, Qt
from PySide6.QtGui import QColor, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QFileDialog,
    QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMainWindow, QMessageBox, QPushButton, QProgressBar, QSpinBox,
    QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget
)

from compressor import compress_image, compress_image_at_quality
from file_utils import create_output_path, human_readable_size, open_folder
from models import CompressionStatus, LogEntry
from print_utils import PRINT_JPEG_QUALITY, evaluate_print

PATH_ROLE = Qt.UserRole

NORMAL_QUALITY = {
    "標準": 80,
    "高画質": 90,
    "最低画質（容量優先）": 60,
}

LOG_HEADERS = [
    "ファイル名", "元容量", "変換後容量", "容量変化率",
    "結果", "時刻", "入力形式", "出力形式", "設定",
    "JPEG品質", "画像サイズ", "印刷設定", "ppi", "メッセージ"
]

CSV_HEADERS = [
    "日時", "ファイル名", "結果", "入力形式", "出力形式", "設定",
    "JPEG品質", "元容量(byte)", "変換後容量(byte)", "容量変化率(%)",
    "画像サイズ", "印刷設定", "ppi", "メッセージ", "入力パス", "出力パス"
]


class DropTableWidget(QTableWidget):
    files_dropped = Signal(list)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            paths = [url.toLocalFile() for url in event.mimeData().urls()]
            if any(Path(path).suffix.lower() in {".jpg", ".jpeg", ".png", ".heic", ".heif"} for path in paths):
                event.acceptProposedAction()
                return
        event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent):
        if not event.mimeData().hasUrls():
            event.ignore()
            return

        files = []
        for url in event.mimeData().urls():
            path = Path(url.toLocalFile())
            if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg", ".png", ".heic", ".heif"}:
                files.append(str(path))

        if files:
            self.files_dropped.emit(files)
            event.acceptProposedAction()
        else:
            event.ignore()


class CompressionWorker(QObject):
    progress = Signal(int, int)
    result_ready = Signal(object, object)
    completed = Signal(bool)
    failed = Signal(str)

    def __init__(self, files, output_directory, suffix, same_folder, settings):
        super().__init__()
        self.files = files
        self.output_directory = output_directory
        self.suffix = suffix
        self.same_folder = same_folder
        self.settings = settings
        self.cancel_requested = False

    def request_cancel(self):
        self.cancel_requested = True

    def _mode_text(self) -> str:
        mode = self.settings["mode"]
        if mode == "normal":
            return f"通常：{self.settings['normal_preset']}"
        if mode == "numeric":
            return f"数値指定：{self.settings['target_kb']} KB"
        if mode == "print":
            return f"印刷：{self.settings['paper_size']} / {self.settings['print_quality']}"
        return mode

    def run(self):
        try:
            total = len(self.files)
            cancelled = False

            for index, input_path in enumerate(self.files, 1):
                if self.cancel_requested:
                    cancelled = True
                    break

                output_dir = str(Path(input_path).parent) if self.same_folder else self.output_directory
                output_path = create_output_path(input_path, output_dir, self.suffix)

                mode = self.settings["mode"]
                print_text = "-"
                print_setting = "-"
                ppi_text = "-"

                if mode == "normal":
                    preset = self.settings["normal_preset"]
                    quality = NORMAL_QUALITY[preset]
                    result = compress_image_at_quality(
                        input_path, output_path, quality, f"通常設定：{preset}"
                    )

                elif mode == "numeric":
                    result = compress_image(
                        input_path,
                        output_path,
                        self.settings["target_kb"] * 1024,
                    )

                elif mode == "print":
                    print_quality = self.settings["print_quality"]
                    quality = PRINT_JPEG_QUALITY[print_quality]
                    result = compress_image_at_quality(
                        input_path, output_path, quality, f"印刷設定：{print_quality}"
                    )
                    print_setting = f"{self.settings['paper_size']} / {print_quality}"
                    if result.width and result.height:
                        suitable, ppi, required = evaluate_print(
                            result.width,
                            result.height,
                            self.settings["paper_size"],
                            print_quality,
                        )
                        mark = "適合" if suitable else "不足"
                        ppi_text = f"{ppi:.0f} ppi"
                        print_text = f"{mark}：{ppi:.0f} ppi（目安 {required} ppi）"
                else:
                    raise ValueError(f"未対応の圧縮モードです: {mode}")

                status_text = {
                    CompressionStatus.SUCCESS: "成功",
                    CompressionStatus.WARNING: "警告",
                    CompressionStatus.FAILED: "失敗",
                }[result.status]

                input_format = Path(result.input_path).suffix.replace(".", "").upper() or "-"
                image_size = (
                    f"{result.width}×{result.height}"
                    if result.width and result.height else "-"
                )

                log_entry = LogEntry(
                    timestamp=datetime.now().strftime("%Y/%m/%d %H:%M:%S"),
                    file_name=Path(result.input_path).name,
                    result_text=status_text,
                    status=result.status,
                    input_format=input_format,
                    output_format="JPEG" if result.output_path else "-",
                    mode_text=self._mode_text(),
                    quality=result.quality,
                    original_bytes=result.original_bytes,
                    output_bytes=result.output_bytes,
                    size_change_rate=result.size_change_rate,
                    image_size=image_size,
                    print_setting=print_setting,
                    ppi_text=ppi_text,
                    message=result.message,
                    input_path=result.input_path,
                    output_path=result.output_path,
                )

                self.result_ready.emit(result, (print_text, log_entry))
                self.progress.emit(index, total)

            self.completed.emit(cancelled)
        except Exception as exc:
            self.failed.emit(str(exc))


class MainWindow(QMainWindow):
    COL_FILE, COL_ORIGINAL, COL_OUTPUT, COL_CHANGE, COL_STATUS, COL_PRINT, COL_MESSAGE = range(7)

    LOG_FILE, LOG_ORIGINAL, LOG_AFTER, LOG_CHANGE, LOG_RESULT, LOG_TIME, \
        LOG_INPUT, LOG_OUTPUT, LOG_MODE, LOG_QUALITY, LOG_DIMENSIONS, LOG_PRINT, \
        LOG_PPI, LOG_MESSAGE = range(14)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("画像容量調整ツール Ver.1.3.8")
        self.resize(1380, 800)
        self.thread = None
        self.worker = None
        self.row_by_path = {}
        self.log_entries: list[LogEntry] = []
        self.current_run_entries: list[LogEntry] = []
        self.current_run_started_at: str | None = None
        self._build_ui()
        self._connect()
        self._update_mode_ui()
        self._update_summary()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)

        title = QLabel("画像容量調整ツール Ver.1.3.8")
        title.setStyleSheet("font-size:22px;font-weight:bold;")
        root_layout.addWidget(title)

        desc = QLabel("JPEG・PNG・HEIC画像を用途に応じた設定でJPEGへ変換し、処理結果を比較できます。")
        desc.setWordWrap(True)
        root_layout.addWidget(desc)

        self.splitter = QSplitter(Qt.Horizontal)
        root_layout.addWidget(self.splitter, 1)

        # ===== 左側：画像選択・設定・実行 =====
        left = QWidget()
        left_layout = QVBoxLayout(left)

        buttons = QHBoxLayout()
        self.add_button = QPushButton("画像を追加")
        self.remove_button = QPushButton("選択を削除")
        self.clear_button = QPushButton("すべて削除")
        for button in (self.add_button, self.remove_button, self.clear_button):
            button.setMinimumWidth(100)
            buttons.addWidget(button)
        buttons.addStretch()
        left_layout.addLayout(buttons)

        drop_hint = QLabel("画像ファイルをこの一覧へドラッグ＆ドロップできます")
        drop_hint.setStyleSheet("color:#666;")
        left_layout.addWidget(drop_hint)

        self.table = DropTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["ファイル名", "元容量", "圧縮後", "容量変化率", "状態", "印刷判定", "内容"]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(self.COL_FILE, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(self.COL_MESSAGE, QHeaderView.Stretch)
        self.table.setMinimumHeight(360)
        left_layout.addWidget(self.table, 1)

        settings_group = QGroupBox("圧縮設定")
        settings_group.setObjectName("settingsGroup")
        settings_layout = QVBoxLayout(settings_group)

        mode_row = QHBoxLayout()
        self.normal_check = QCheckBox("通常設定")
        self.detail_check = QCheckBox("詳細設定")
        self.normal_check.setChecked(True)
        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)
        self.mode_group.addButton(self.normal_check)
        self.mode_group.addButton(self.detail_check)
        mode_row.addWidget(self.normal_check)
        mode_row.addWidget(self.detail_check)
        mode_row.addStretch()
        settings_layout.addLayout(mode_row)

        self.normal_box = QGroupBox("通常設定")
        self.normal_box.setObjectName("normalBox")
        normal_form = QFormLayout(self.normal_box)
        self.normal_combo = QComboBox()
        self.normal_combo.addItems(["最低画質（容量優先）", "標準", "高画質"])
        self.normal_combo.setCurrentIndex(0)
        normal_form.addRow("圧縮モード", self.normal_combo)
        settings_layout.addWidget(self.normal_box)

        self.detail_box = QGroupBox("詳細設定")
        self.detail_box.setObjectName("detailBox")
        detail_layout = QVBoxLayout(self.detail_box)

        detail_mode_row = QHBoxLayout()
        self.numeric_check = QCheckBox("数値指定")
        self.print_check = QCheckBox("印刷設定")
        self.numeric_check.setChecked(True)
        self.detail_mode_group = QButtonGroup(self)
        self.detail_mode_group.setExclusive(True)
        self.detail_mode_group.addButton(self.numeric_check)
        self.detail_mode_group.addButton(self.print_check)
        detail_mode_row.addWidget(self.numeric_check)
        detail_mode_row.addWidget(self.print_check)
        detail_mode_row.addStretch()
        detail_layout.addLayout(detail_mode_row)

        self.numeric_box = QGroupBox("数値指定")
        self.numeric_box.setObjectName("numericBox")
        numeric_form = QFormLayout(self.numeric_box)
        self.target_spin = QSpinBox()
        self.target_spin.setRange(1, 1_000_000)
        self.target_spin.setValue(700)
        self.target_spin.setSuffix(" KB")
        numeric_form.addRow("目標容量", self.target_spin)
        detail_layout.addWidget(self.numeric_box)

        self.print_box = QGroupBox("印刷設定")
        self.print_box.setObjectName("printBox")
        print_form = QFormLayout(self.print_box)
        self.paper_combo = QComboBox()
        self.paper_combo.addItems(["使用しない", "L判", "はがき", "A4", "A3"])
        self.paper_combo.setCurrentText("A4")
        print_form.addRow("印刷サイズ", self.paper_combo)

        self.print_quality_combo = QComboBox()
        self.print_quality_combo.addItems(["最低画質（容量優先）", "標準", "高画質"])
        self.print_quality_combo.setCurrentIndex(0)
        print_form.addRow("印刷品質", self.print_quality_combo)

        self.print_help = QLabel(
            "実効ppiを、下限150 / 標準240 / 高画質300 ppiを目安に判定します。"
        )
        self.print_help.setWordWrap(True)
        print_form.addRow("ppi判定", self.print_help)
        detail_layout.addWidget(self.print_box)

        settings_layout.addWidget(self.detail_box)
        left_layout.addWidget(settings_group)

        file_form = QFormLayout()
        self.suffix_edit = QLineEdit("_compressed")
        file_form.addRow("ファイル名の接尾辞", self.suffix_edit)

        outrow = QHBoxLayout()
        self.output_edit = QLineEdit()
        self.output_button = QPushButton("参照")
        self.output_button.setObjectName("compactButton")
        outrow.addWidget(self.output_edit)
        outrow.addWidget(self.output_button)
        file_form.addRow("保存先", outrow)

        self.same_folder = QCheckBox("元画像と同じフォルダへ保存する")
        file_form.addRow("", self.same_folder)
        left_layout.addLayout(file_form)

        actions = QHBoxLayout()
        self.start_button = QPushButton("圧縮を開始")
        self.start_button.setObjectName("primaryButton")
        self.cancel_button = QPushButton("中止")
        self.cancel_button.setEnabled(False)
        self.open_button = QPushButton("保存先を開く")
        actions.addWidget(self.start_button)
        actions.addWidget(self.cancel_button)
        actions.addStretch()
        actions.addWidget(self.open_button)
        left_layout.addLayout(actions)

        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        left_layout.addWidget(self.progress)

        self.summary = QLabel()
        left_layout.addWidget(self.summary)

        # ===== 右側：処理ログ =====
        right = QWidget()
        right_layout = QVBoxLayout(right)

        log_header = QHBoxLayout()
        log_title = QLabel("処理ログ")
        log_title.setStyleSheet("font-size:16px;font-weight:bold;")
        self.export_csv_button = QPushButton("CSV出力")
        self.export_csv_button.setObjectName("compactButton")
        self.clear_log_button = QPushButton("ログをクリア")
        self.clear_log_button.setObjectName("compactDangerButton")
        log_header.addWidget(log_title)
        log_header.addStretch()
        log_header.addWidget(self.export_csv_button)
        log_header.addWidget(self.clear_log_button)
        right_layout.addLayout(log_header)

        log_help = QLabel("最新の実行を上に表示します。中央の境界をドラッグしてログ表示幅を調整できます。")
        log_help.setWordWrap(True)
        right_layout.addWidget(log_help)

        self.log_table = QTableWidget(0, len(LOG_HEADERS))
        self.log_table.setHorizontalHeaderLabels(LOG_HEADERS)
        self.log_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.log_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.log_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.log_table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.log_table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)

        # 狭い状態では「時刻・ファイル名・結果」が中心に見える。
        widths = [180, 95, 95, 105, 70, 75, 75, 75, 150, 80, 110, 130, 90, 330]
        for col, width in enumerate(widths):
            self.log_table.setColumnWidth(col, width)
        self.log_table.horizontalHeader().setStretchLastSection(False)
        right_layout.addWidget(self.log_table, 1)

        self.splitter.addWidget(left)
        self.splitter.addWidget(right)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(8)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 2)
        self.splitter.setSizes([850, 530])
        self.splitter.setStyleSheet("""
            QSplitter::handle {
                background: #d5d9df;
            }
            QSplitter::handle:hover {
                background: #aeb6c2;
            }
        """)

        self.setStyleSheet(self.styleSheet() + """
            QGroupBox#settingsGroup {
                border: 1px solid #cfd6df;
                border-radius: 12px;
                margin-top: 12px;
                padding: 12px;
                background: #fbfcfe;
                font-weight: 600;
            }
            QGroupBox#settingsGroup::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
                color: #46566b;
            }
            QGroupBox#normalBox {
                border: 1px solid #b9d7f4;
                border-radius: 10px;
                margin-top: 10px;
                padding: 10px;
                background: #edf7ff;
                font-weight: 600;
            }
            QGroupBox#normalBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
                color: #3d6f9d;
            }
            QGroupBox#detailBox {
                border: 1px solid #d8c7ef;
                border-radius: 10px;
                margin-top: 10px;
                padding: 10px;
                background: #f7f1ff;
                font-weight: 600;
            }
            QGroupBox#detailBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
                color: #71559a;
            }
            QGroupBox#numericBox, QGroupBox#printBox {
                border: 1px solid #ded7e8;
                border-radius: 8px;
                margin-top: 8px;
                padding: 8px;
                background: #ffffff;
                font-weight: 500;
            }

            QPushButton {
                min-height: 34px;
                padding: 4px 13px;
                border-radius: 11px;
                border: 1px solid #d9dfe6;
                background-color: #ffffff;
                color: #27313c;
                font-size: 11pt;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #f6f8fa;
                border-color: #cbd3dc;
            }
            QPushButton:pressed {
                background-color: #edf1f4;
            }
            QPushButton:disabled {
                background-color: #f3f4f5;
                color: #aaaaaa;
                border-color: #e3e3e3;
            }
            QPushButton#primaryButton {
                min-height: 38px;
                padding: 5px 18px;
                background-color: #e7f1ff;
                color: #245b8f;
                border: 1px solid #bed7f2;
                font-size: 12pt;
                font-weight: 700;
            }
            QPushButton#primaryButton:hover {
                background-color: #dcecff;
                border-color: #a7c9ec;
            }
            QPushButton#primaryButton:pressed {
                background-color: #cfe3f8;
            }
            QPushButton#secondaryButton {
                background-color: #ffffff;
                color: #2d3a46;
                border: 1px solid #d8dee6;
                font-size: 11pt;
            }
            QPushButton#dangerButton {
                background-color: #fff7f7;
                color: #ad4b4b;
                border: 1px solid #efd1d1;
                font-size: 11pt;
            }
            QPushButton#compactButton {
                min-height: 30px;
                padding: 3px 10px;
                border-radius: 10px;
                background-color: #ffffff;
                color: #33414d;
                border: 1px solid #d8dee6;
                font-size: 10pt;
                font-weight: 600;
            }
            QPushButton#compactButton:hover {
                background-color: #f7f9fb;
            }
            QPushButton#compactDangerButton {
                min-height: 30px;
                padding: 3px 10px;
                border-radius: 10px;
                background-color: #fff7f7;
                color: #ad4b4b;
                border: 1px solid #efd1d1;
                font-size: 10pt;
                font-weight: 600;
            }
            QPushButton#compactDangerButton:hover {
                background-color: #ffeded;
            }
        """)

    def _connect(self):
        self.add_button.clicked.connect(self._add_files)
        self.table.files_dropped.connect(self._add_paths)
        self.remove_button.clicked.connect(self._remove_rows)
        self.clear_button.clicked.connect(self._clear)
        self.output_button.clicked.connect(self._select_output)
        self.same_folder.toggled.connect(self._toggle_output)
        self.start_button.clicked.connect(self._start)
        self.cancel_button.clicked.connect(self._cancel)
        self.open_button.clicked.connect(self._open_folder)
        self.export_csv_button.clicked.connect(self._export_csv)
        self.clear_log_button.clicked.connect(self._clear_log)
        self.normal_check.toggled.connect(self._update_mode_ui)
        self.detail_check.toggled.connect(self._update_mode_ui)
        self.numeric_check.toggled.connect(self._update_mode_ui)
        self.print_check.toggled.connect(self._update_mode_ui)

    def _update_mode_ui(self):
        normal_enabled = self.normal_check.isChecked()
        detail_enabled = self.detail_check.isChecked()
        numeric_enabled = detail_enabled and self.numeric_check.isChecked()
        print_enabled = detail_enabled and self.print_check.isChecked()

        self.normal_box.setVisible(normal_enabled)
        self.detail_box.setVisible(detail_enabled)
        self.numeric_box.setVisible(numeric_enabled)
        self.print_box.setVisible(print_enabled)

        self.normal_check.setText("✓ 通常設定" if normal_enabled else "通常設定")
        self.detail_check.setText("✓ 詳細設定" if detail_enabled else "詳細設定")

    def _add_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "画像を選択", "", "画像ファイル (*.jpg *.jpeg *.png *.heic *.heif)"
        )
        self._add_paths(files)

    def _add_paths(self, files):
        supported = {".jpg", ".jpeg", ".png", ".heic", ".heif"}

        for path in files:
            path = str(Path(path))
            if Path(path).suffix.lower() not in supported:
                continue
            if path in self.row_by_path:
                continue

            row = self.table.rowCount()
            self.table.insertRow(row)
            item = QTableWidgetItem(Path(path).name)
            item.setToolTip(path)
            item.setData(PATH_ROLE, path)

            try:
                size = Path(path).stat().st_size
            except OSError:
                size = 0

            self.table.setItem(row, self.COL_FILE, item)
            self.table.setItem(
                row, self.COL_ORIGINAL, QTableWidgetItem(human_readable_size(size))
            )
            for col, value in [
                (self.COL_OUTPUT, "-"), (self.COL_CHANGE, "-"),
                (self.COL_STATUS, "待機中"), (self.COL_PRINT, "-"), (self.COL_MESSAGE, "")
            ]:
                self.table.setItem(row, col, QTableWidgetItem(value))

        self._reindex()
        self._update_summary()

    def _remove_rows(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        for row in rows:
            self.table.removeRow(row)
        self._reindex()
        self._update_summary()

    def _clear(self):
        """画像一覧のみクリア。比較用ログは残す。"""
        self.table.setRowCount(0)
        self.row_by_path.clear()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self._update_summary()

    def _select_output(self):
        folder = QFileDialog.getExistingDirectory(self, "保存先を選択")
        if folder:
            self.output_edit.setText(folder)

    def _toggle_output(self, checked):
        self.output_edit.setEnabled(not checked)
        self.output_button.setEnabled(not checked)

    def _paths(self):
        return [self.table.item(r, self.COL_FILE).data(PATH_ROLE) for r in range(self.table.rowCount())]

    def _settings(self):
        if self.normal_check.isChecked():
            return {"mode": "normal", "normal_preset": self.normal_combo.currentText()}
        if self.numeric_check.isChecked():
            return {"mode": "numeric", "target_kb": self.target_spin.value()}
        return {
            "mode": "print",
            "paper_size": self.paper_combo.currentText(),
            "print_quality": self.print_quality_combo.currentText(),
        }

    def _validate(self):
        if self.table.rowCount() == 0:
            return "画像を選択してください。"
        if not self.same_folder.isChecked() and not self.output_edit.text().strip():
            return "保存先を指定してください。"
        if self.detail_check.isChecked() and self.print_check.isChecked():
            if self.paper_combo.currentText() == "使用しない":
                return "印刷設定を使用する場合は印刷サイズを選択してください。"
        return None

    def _start(self):
        validation = self._validate()
        if validation:
            QMessageBox.warning(self, "確認", validation)
            return

        self.current_run_entries = []
        self.current_run_started_at = datetime.now().strftime("%Y/%m/%d %H:%M:%S")

        for row in range(self.table.rowCount()):
            for col in range(self.table.columnCount()):
                item = self.table.item(row, col)
                if item is not None:
                    item.setBackground(QColor("white"))
            for col, value in [
                (self.COL_OUTPUT, "-"), (self.COL_CHANGE, "-"),
                (self.COL_STATUS, "待機中"), (self.COL_PRINT, "-"), (self.COL_MESSAGE, "")
            ]:
                self.table.setItem(row, col, QTableWidgetItem(value))

        files = self._paths()
        self.progress.setRange(0, len(files))
        self.progress.setValue(0)
        self.thread = QThread(self)
        self.worker = CompressionWorker(
            files,
            self.output_edit.text().strip(),
            self.suffix_edit.text(),
            self.same_folder.isChecked(),
            self._settings(),
        )
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(lambda current, total: self.progress.setValue(current))
        self.worker.result_ready.connect(self._apply_result)
        self.worker.completed.connect(self._finished)
        self.worker.failed.connect(self._failed)
        self.worker.completed.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self.thread.finished.connect(self._cleanup)
        self._set_running(True)
        self.thread.start()

    def _apply_result(self, result, payload):
        print_text, log_entry = payload
        row = self.row_by_path.get(result.input_path)
        if row is not None:
            self.table.setItem(row, self.COL_OUTPUT, QTableWidgetItem(human_readable_size(result.output_bytes)))
            change = result.size_change_rate
            self.table.setItem(
                row, self.COL_CHANGE,
                QTableWidgetItem("-" if change is None else f"{change:+.1f}%")
            )

            status = {
                CompressionStatus.SUCCESS: "成功",
                CompressionStatus.WARNING: "警告",
                CompressionStatus.FAILED: "失敗",
            }[result.status]

            status_item = QTableWidgetItem(status)
            print_item = QTableWidgetItem(print_text)
            message_item = QTableWidgetItem(result.message)

            background = self._status_color(result.status)
            for col in range(self.table.columnCount()):
                item = self.table.item(row, col)
                if item is not None:
                    item.setBackground(background)

            for item in (status_item, print_item, message_item):
                item.setBackground(background)

            self.table.setItem(row, self.COL_STATUS, status_item)
            self.table.setItem(row, self.COL_PRINT, print_item)
            self.table.setItem(row, self.COL_MESSAGE, message_item)

        self.current_run_entries.append(log_entry)
        self._update_summary()

    def _insert_log_row(self, row: int, entry: LogEntry):
        self.log_table.insertRow(row)

        change = "-" if entry.size_change_rate is None else f"{entry.size_change_rate:+.1f}%"
        values = [
            entry.file_name,
            human_readable_size(entry.original_bytes),
            human_readable_size(entry.output_bytes),
            change,
            entry.result_text,
            entry.timestamp.split(" ")[1],
            entry.input_format,
            entry.output_format,
            entry.mode_text,
            "-" if entry.quality is None else str(entry.quality),
            entry.image_size,
            entry.print_setting,
            entry.ppi_text,
            entry.message,
        ]

        background = self._status_color(entry.status)
        for col, value in enumerate(values):
            item = QTableWidgetItem(value)
            item.setBackground(background)
            if col == self.LOG_FILE:
                item.setToolTip(entry.input_path)
            if col == self.LOG_MESSAGE:
                item.setToolTip(entry.message)
            self.log_table.setItem(row, col, item)

    def _insert_run_block_at_top(self, entries: list[LogEntry], cancelled: bool):
        if not entries:
            return

        # 最新実行を最上部へ。区切り行の直下に今回のファイル結果を並べる。
        marker_row = 0
        self.log_table.insertRow(marker_row)

        started = self.current_run_started_at or entries[0].timestamp
        setting = entries[0].mode_text
        result_counts = {"成功": 0, "警告": 0, "失敗": 0}
        for entry in entries:
            result_counts[entry.result_text] = result_counts.get(entry.result_text, 0) + 1

        marker_text = (
            f"▼ {started}　{setting}　{len(entries)}件"
            f"　成功 {result_counts.get('成功', 0)} / 警告 {result_counts.get('警告', 0)}"
            f" / 失敗 {result_counts.get('失敗', 0)}"
        )
        if cancelled:
            marker_text += "　[中止]"

        marker_item = QTableWidgetItem(marker_text)
        marker_item.setBackground(QColor(225, 232, 242))
        marker_item.setForeground(QColor(40, 60, 90))
        font = marker_item.font()
        font.setBold(True)
        marker_item.setFont(font)

        self.log_table.setSpan(marker_row, 0, 1, self.log_table.columnCount())
        self.log_table.setItem(marker_row, 0, marker_item)
        self.log_table.setRowHeight(marker_row, 26)

        for offset, entry in enumerate(entries, start=1):
            self._insert_log_row(offset, entry)

        # CSVもUIと同じく最新実行が先頭になるよう保持。
        self.log_entries = list(entries) + self.log_entries
        self.log_table.scrollToTop()

    @staticmethod
    def _status_color(status):
        if status == CompressionStatus.SUCCESS:
            return QColor(220, 245, 225)
        if status == CompressionStatus.WARNING:
            return QColor(255, 244, 204)
        return QColor(255, 220, 220)

    def _export_csv(self):
        if not self.log_entries:
            QMessageBox.information(self, "CSV出力", "出力できるログがありません。")
            return

        default_name = f"compression_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "処理ログをCSV保存",
            default_name,
            "CSVファイル (*.csv)"
        )
        if not path:
            return

        if not path.lower().endswith(".csv"):
            path += ".csv"

        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as file:
                writer = csv.writer(file)
                writer.writerow(CSV_HEADERS)
                for entry in self.log_entries:
                    writer.writerow(entry.to_csv_row())
            QMessageBox.information(self, "CSV出力", f"ログを保存しました。\n{path}")
        except OSError as exc:
            QMessageBox.warning(self, "CSV出力エラー", f"CSVを保存できませんでした。\n{exc}")

    def _clear_log(self):
        if not self.log_entries and self.log_table.rowCount() == 0:
            QMessageBox.information(self, "ログをクリア", "クリアするログがありません。")
            return

        answer = QMessageBox.question(
            self,
            "ログをクリア",
            "処理ログをすべてクリアしますか？\n画像一覧は残ります。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        self.log_entries.clear()
        self.current_run_entries = []
        self.current_run_started_at = None
        self.log_table.clearSpans()
        self.log_table.setRowCount(0)

    def _finished(self, cancelled):
        self._insert_run_block_at_top(self.current_run_entries, cancelled)
        self.current_run_entries = []
        self.current_run_started_at = None
        self._set_running(False)
        self._update_summary()
        QMessageBox.information(
            self, "処理終了", "処理を中止しました。" if cancelled else "画像の処理が完了しました。"
        )

    def _failed(self, message):
        self._set_running(False)
        QMessageBox.critical(self, "処理エラー", message)

    def _cleanup(self):
        if self.worker:
            self.worker.deleteLater()
        if self.thread:
            self.thread.deleteLater()
        self.worker = None
        self.thread = None

    def _cancel(self):
        if self.worker:
            self.worker.request_cancel()
            self.cancel_button.setEnabled(False)

    def _set_running(self, running):
        for widget in (
            self.add_button, self.remove_button, self.clear_button, self.start_button,
            self.suffix_edit, self.same_folder, self.normal_check, self.detail_check,
            self.normal_combo, self.numeric_check, self.print_check, self.target_spin,
            self.paper_combo, self.print_quality_combo,
        ):
            widget.setEnabled(not running)
        self.cancel_button.setEnabled(running)
        self.output_edit.setEnabled(not running and not self.same_folder.isChecked())
        self.output_button.setEnabled(not running and not self.same_folder.isChecked())
        self.export_csv_button.setEnabled(not running)
        self.clear_log_button.setEnabled(not running)
        if not running:
            self._update_mode_ui()

    def _update_summary(self):
        counts = {"成功": 0, "警告": 0, "失敗": 0, "待機中": 0}
        for row in range(self.table.rowCount()):
            item = self.table.item(row, self.COL_STATUS)
            key = item.text() if item else "待機中"
            counts[key] = counts.get(key, 0) + 1
        self.summary.setText(
            f"合計 {self.table.rowCount()}件　成功 {counts.get('成功', 0)}件　"
            f"警告 {counts.get('警告', 0)}件　失敗 {counts.get('失敗', 0)}件　"
            f"待機 {counts.get('待機中', 0)}件"
        )

    def _open_folder(self):
        try:
            if self.same_folder.isChecked():
                if self.table.rowCount() == 0:
                    raise ValueError("画像が選択されていません。")
                folder = str(Path(self.table.item(0, self.COL_FILE).data(PATH_ROLE)).parent)
            else:
                folder = self.output_edit.text().strip()
            open_folder(folder)
        except Exception as exc:
            QMessageBox.warning(self, "保存先を開けません", str(exc))

    def _reindex(self):
        self.row_by_path = {}
        for row in range(self.table.rowCount()):
            item = self.table.item(row, self.COL_FILE)
            self.row_by_path[str(item.data(PATH_ROLE))] = row

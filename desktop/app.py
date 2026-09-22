# -*- coding: utf-8 -*-
"""PySide6 桌面 UI。

支持两种输出格式：
    - SHP：每个文件独立输出，用户选择输出文件夹
    - GPKG：所有文件写入一个 GeoPackage，用户选择输出文件

输入支持两种模式（点"浏览"后可选）：
    - 选择文件夹：处理该文件夹下（可含子文件夹）的全部 MapGIS 文件
    - 选择文件：只处理显式选中的若干文件
"""

import logging
import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QSettings, Qt, QThread, Signal, Slot
from PySide6.QtGui import QColor, QCursor, QFont, QTextCursor
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox,
    QPlainTextEdit, QProgressBar, QPushButton, QSizePolicy,
    QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from desktop.worker import ConvertWorker
from core.convert import convert_folder


# ======================================================================
# 日志 → Qt 信号
# ======================================================================
class LogEmitter(QObject):
    message = Signal(str, int)


class QtLogHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.emitter = LogEmitter()

    def emit(self, record):
        try:
            msg = self.format(record)
            self.emitter.message.emit(msg, record.levelno)
        except Exception:
            self.handleError(record)


# ======================================================================
# 主窗口
# ======================================================================
class ConverterWindow(QMainWindow):

    SETTINGS_ORG = "mapgis2gpkg"
    SETTINGS_APP = "converter"

    def __init__(self):
        super().__init__()
        self.setWindowTitle("mapgis2gpkg")
        self.resize(1000, 800)
        self.setMinimumSize(840, 660)

        self._worker: ConvertWorker | None = None
        self._log_handler: QtLogHandler | None = None
        self._settings = QSettings(self.SETTINGS_ORG, self.SETTINGS_APP)
        self._input_files = []          # 显式选择的文件列表；空表示文件夹模式
        self._output_dir = None         # 转换完成后用于「打开文件夹」

        self._build_ui()
        self._install_log_handler()
        self._restore_settings()

    # ------------------------------------------------------------------
    # UI 构建
    # ------------------------------------------------------------------
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(12)

        title = QLabel("mapgis2gpkg")
        title.setFont(QFont("Microsoft YaHei", 20, QFont.Bold))
        root.addWidget(title)

        subtitle = QLabel("批量将 .wt / .wl / .wp 转换为 GPKG 或 SHP")
        subtitle.setStyleSheet("color: #888; font-size: 12px;")
        root.addWidget(subtitle)

        root.addSpacing(6)

        # 输入路径：单一"浏览"按钮，点击弹菜单选择文件或文件夹
        _, self._input_edit = self._add_path_row(
            root, "输入文件/文件夹", self._pick_input,
        )
        # 输出路径（标签会随格式切换）
        self._output_label, self._output_edit = self._add_path_row(
            root, "输出", self._pick_output,
        )

        self._hint = QLabel("")
        self._hint.setStyleSheet("color: #999; font-size: 11px;")
        self._hint.setWordWrap(True)
        root.addWidget(self._hint)

        root.addSpacing(6)

        # ---- 选项行 ----
        opts = QHBoxLayout()
        opts.setSpacing(16)

        opts.addWidget(QLabel("输出格式"))
        self._format_combo = QComboBox()
        self._format_combo.addItems([
            "GPKG (合并为一个文件)",
            "SHP (每个文件独立)",
        ])
        self._format_combo.setMinimumWidth(200)
        self._format_combo.currentIndexChanged.connect(
            self._on_format_changed
        )
        opts.addWidget(self._format_combo)

        opts.addWidget(QLabel("坐标系"))
        self._crs_combo = QComboBox()
        self._crs_combo.addItems([
            "EPSG:4326 (WGS 84)",
            "EPSG:4490 (CGCS2000)",
            "保持原坐标系 (北京54)",
        ])
        self._crs_combo.setMinimumWidth(200)
        opts.addWidget(self._crs_combo)

        opts.addWidget(QLabel("编码"))
        self._enc_combo = QComboBox()
        self._enc_combo.addItems(["gb18030", "gbk", "utf-8"])
        self._enc_combo.setMinimumWidth(110)
        opts.addWidget(self._enc_combo)

        self._recursive_cb = QCheckBox("包含子文件夹")
        opts.addWidget(self._recursive_cb)

        opts.addStretch()
        root.addLayout(opts)

        root.addSpacing(6)

        # 开始按钮
        self._start_btn = QPushButton("开始转换")
        self._start_btn.setMinimumHeight(48)
        self._start_btn.setFont(QFont("Microsoft YaHei", 14, QFont.Bold))
        self._start_btn.setStyleSheet("""
            QPushButton {
                background-color: #2D7FF9;
                color: white;
                border: none;
                border-radius: 8px;
            }
            QPushButton:hover  { background-color: #1A6FEA; }
            QPushButton:pressed { background-color: #1558C9; }
            QPushButton:disabled { background-color: #B0C4DE; }
        """)
        self._start_btn.clicked.connect(self._start)
        root.addWidget(self._start_btn)

        # 进度条
        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setMinimumHeight(8)
        self._progress.setTextVisible(False)
        self._progress.setStyleSheet("""
            QProgressBar {
                border: none;
                border-radius: 4px;
                background-color: #E8E8E8;
            }
            QProgressBar::chunk {
                background-color: #2D7FF9;
                border-radius: 4px;
            }
        """)
        root.addWidget(self._progress)

        # 状态行
        status_row = QHBoxLayout()
        self._status = QLabel("就绪")
        self._status.setStyleSheet("color: #888; font-size: 12px;")
        status_row.addWidget(self._status)
        status_row.addStretch()

        self._open_btn = QPushButton("打开输出位置")
        self._open_btn.setEnabled(False)
        self._open_btn.setStyleSheet("""
            QPushButton {
                padding: 4px 14px;
                border-radius: 6px;
                border: 1px solid #C0C0C0;
                background-color: #F8F8F8;
            }
            QPushButton:hover { background-color: #EEEEEE; }
            QPushButton:disabled { color: #AAAAAA; }
        """)
        self._open_btn.clicked.connect(self._open_output_folder)
        status_row.addWidget(self._open_btn)
        root.addLayout(status_row)

        # ---- 上下分栏 ----
        splitter = QSplitter(Qt.Vertical)

        # 结果表
        table_wrap = QWidget()
        table_layout = QVBoxLayout(table_wrap)
        table_layout.setContentsMargins(0, 0, 0, 0)
        table_layout.setSpacing(4)

        table_label = QLabel("转换结果")
        table_label.setFont(QFont("Microsoft YaHei", 11, QFont.Bold))
        table_layout.addWidget(table_label)

        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(
            ["文件名", "图层名", "状态", "要素数", "耗时(s)"]
        )
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setAlternatingRowColors(True)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self._table.setStyleSheet("""
            QTableWidget {
                background-color: #FAFAFA;
                border: 1px solid #E0E0E0;
                border-radius: 6px;
                gridline-color: #EEEEEE;
            }
            QHeaderView::section {
                background-color: #F0F0F0;
                border: none;
                padding: 6px 8px;
                font-weight: bold;
            }
        """)
        table_layout.addWidget(self._table)

        splitter.addWidget(table_wrap)

        # 日志
        log_wrap = QWidget()
        log_layout = QVBoxLayout(log_wrap)
        log_layout.setContentsMargins(0, 0, 0, 0)
        log_layout.setSpacing(4)

        log_label = QLabel("日志")
        log_label.setFont(QFont("Microsoft YaHei", 11, QFont.Bold))
        log_layout.addWidget(log_label)

        self._log_view = QPlainTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setFont(QFont("Consolas", 10))
        self._log_view.setStyleSheet("""
            QPlainTextEdit {
                background-color: #FAFAFA;
                border: 1px solid #E0E0E0;
                border-radius: 6px;
                padding: 8px;
                color: #333;
            }
        """)
        self._log_view.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Expanding,
        )
        log_layout.addWidget(self._log_view)

        splitter.addWidget(log_wrap)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)

        root.addWidget(splitter, stretch=1)

        # 初始化：先更新标签（依赖当前格式）
        self._on_format_changed()

    def _add_path_row(self, parent_layout, label_text, callback=None,
                      buttons=None):
        """buttons 优先；若为 None，则用 callback 生成单个按钮。"""
        row = QHBoxLayout()
        row.setSpacing(8)

        lbl = QLabel(label_text)
        lbl.setMinimumWidth(110)      # 让"输入文件/文件夹"能完整显示
        row.addWidget(lbl)

        edit = QLineEdit()
        edit.setPlaceholderText("请选择...")
        edit.setMinimumHeight(34)
        row.addWidget(edit, stretch=1)

        if buttons is None:
            buttons = [("浏览", callback)]

        for text, cb in buttons:
            btn = QPushButton(text)
            btn.setMinimumHeight(34)
            btn.setMinimumWidth(72)
            btn.clicked.connect(cb)
            row.addWidget(btn)

        parent_layout.addLayout(row)
        return lbl, edit

    # ------------------------------------------------------------------
    # 日志重定向
    # ------------------------------------------------------------------
    def _install_log_handler(self):
        self._log_handler = QtLogHandler()
        self._log_handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S",
        ))
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.INFO)
        root_logger.addHandler(self._log_handler)
        self._log_handler.emitter.message.connect(self._append_log)

    @Slot(str, int)
    def _append_log(self, text: str, level: int):
        self._log_view.appendPlainText(text)
        self._log_view.moveCursor(QTextCursor.End)

    # ------------------------------------------------------------------
    # 设置持久化
    # ------------------------------------------------------------------
    def _restore_settings(self):
        s = self._settings
        self._input_edit.setText(s.value("last_input", "", type=str))
        self._output_edit.setText(s.value("last_output", "", type=str))
        fmt = s.value("last_format", 0, type=int)     # 0 = GPKG（新默认）
        self._format_combo.setCurrentIndex(fmt)
        crs = s.value("last_crs", "EPSG:4326 (WGS 84)", type=str)
        idx = self._crs_combo.findText(crs)
        if idx >= 0:
            self._crs_combo.setCurrentIndex(idx)
        enc = s.value("last_enc", "gb18030", type=str)
        idx = self._enc_combo.findText(enc)
        if idx >= 0:
            self._enc_combo.setCurrentIndex(idx)
        self._recursive_cb.setChecked(
            s.value("last_recursive", False, type=bool)
        )
        self._on_format_changed()

    def _save_settings(self):
        s = self._settings
        s.setValue("last_input", self._input_edit.text())
        s.setValue("last_output", self._output_edit.text())
        s.setValue("last_format", self._format_combo.currentIndex())
        s.setValue("last_crs", self._crs_combo.currentText())
        s.setValue("last_enc", self._enc_combo.currentText())
        s.setValue("last_recursive", self._recursive_cb.isChecked())

    # ------------------------------------------------------------------
    # 格式切换
    # ------------------------------------------------------------------
    def _is_gpkg(self) -> bool:
        # index 0 = GPKG（新顺序）
        return self._format_combo.currentIndex() == 0

    def _on_format_changed(self):
        """格式切换时更新标签、提示文字、输出路径。"""
        if self._is_gpkg():
            self._output_label.setText("输出文件")
            self._output_edit.setPlaceholderText("请选择 .gpkg 文件...")
        else:
            self._output_label.setText("输出文件夹")
            self._output_edit.setPlaceholderText("请选择文件夹...")

        base = self._current_input_base()
        if base:
            self._auto_fill_output(base)

        self._update_hint()

    def _current_input_base(self):
        """返回当前输入对应的"基准路径"：
            - 文件模式 → 第一个文件的父目录
            - 文件夹模式 → 文件夹路径
        无有效输入时返回 None。
        """
        if self._input_files:
            return str(Path(self._input_files[0]).parent)
        src = self._input_edit.text().strip()
        if src and Path(src).is_dir():
            return src
        return None

    def _auto_fill_output(self, base: str):
        """根据基准路径 + 当前格式推导输出路径。"""
        p = Path(base)
        if self._is_gpkg():
            self._output_edit.setText(str(p.parent / f"{p.name}.gpkg"))
        else:
            self._output_edit.setText(str(p.parent / f"{p.name}convert"))

    def _update_hint(self):
        if self._is_gpkg():
            self._hint.setText(
                "GPKG 模式：所有文件写入同一个 GeoPackage，"
                "每个输入文件作为一个图层，图层名与原文件名一致。"
            )
        else:
            self._hint.setText(
                "SHP 模式：每个输入文件生成独立的 Shapefile。"
                "选文件夹时处理其下全部 MapGIS 文件；选文件时只处理选中项。"
            )

    # ------------------------------------------------------------------
    # 输入选择：单一"浏览"按钮 → 弹菜单
    # ------------------------------------------------------------------
    def _pick_input(self):
        """点"浏览"时弹菜单：选择文件 / 选择文件夹。"""
        menu = QMenu(self)
        act_files = menu.addAction("选择文件（可多选）")
        act_dir = menu.addAction("选择文件夹")

        btn = self.sender()
        if isinstance(btn, QPushButton):
            pos = btn.mapToGlobal(btn.rect().bottomLeft())
        else:
            pos = QCursor.pos()

        chosen = menu.exec(pos)
        if chosen == act_files:
            self._pick_input_files()
        elif chosen == act_dir:
            self._pick_input_dir()

    def _pick_input_dir(self):
        """选文件夹。"""
        path = QFileDialog.getExistingDirectory(
            self, "选择包含 MapGIS 文件的文件夹",
        )
        if not path:
            return
        self._input_files = []
        self._input_edit.setText(path)
        self._auto_fill_output(path)

    def _pick_input_files(self):
        """选文件（支持多选）。"""
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择 MapGIS 文件", "",
            "MapGIS 文件 (*.wt *.wl *.wp);;所有文件 (*)",
        )
        if not files:
            return
        self._input_files = list(files)
        if len(files) == 1:
            self._input_edit.setText(files[0])
        else:
            self._input_edit.setText(f"已选 {len(files)} 个文件")
        base = str(Path(files[0]).parent)
        self._auto_fill_output(base)

    def _pick_output(self):
        if self._is_gpkg():
            default = self._output_edit.text().strip()
            if not default:
                base = self._current_input_base()
                if base:
                    p = Path(base)
                    default = str(p.parent / f"{p.name}.gpkg")
            path, _ = QFileDialog.getSaveFileName(
                self, "选择输出 GeoPackage 文件",
                default, "GeoPackage (*.gpkg)",
            )
            if path:
                if not path.lower().endswith('.gpkg'):
                    path += '.gpkg'
                self._output_edit.setText(path)
        else:
            path = QFileDialog.getExistingDirectory(self, "选择输出文件夹")
            if path:
                self._output_edit.setText(path)

    # ------------------------------------------------------------------
    # 转换流程
    # ------------------------------------------------------------------
    def _start(self):
        # ---- 判断输入类型 ----
        if self._input_files:
            src_dir = str(Path(self._input_files[0]).parent)
            src_for_output = src_dir
            files_arg = list(self._input_files)
            folder_arg = None
        else:
            src = self._input_edit.text().strip()
            if not src or not Path(src).is_dir():
                QMessageBox.warning(self, "提示",
                                    "请先选择有效的文件夹或文件。")
                return
            src_for_output = src
            files_arg = None
            folder_arg = src

        out = self._output_edit.text().strip()
        output_format = 'gpkg' if self._is_gpkg() else 'shp'

        # GPKG 模式下如果输出为空，自动推导
        if output_format == 'gpkg' and not out:
            p = Path(src_for_output)
            out = str(p.parent / f"{p.name}.gpkg")

        self._table.setRowCount(0)

        self._start_btn.setEnabled(False)
        self._start_btn.setText("转换中...")
        self._open_btn.setEnabled(False)
        self._progress.setValue(0)
        self._status.setText("准备中...")
        self._status.setStyleSheet("color: #888; font-size: 12px;")

        self._save_settings()

        crs = self._resolve_crs()
        self._worker = ConvertWorker(
            input_dir=folder_arg,
            files=files_arg,
            output=out,
            output_format=output_format,
            encoding=self._enc_combo.currentText(),
            recursive=self._recursive_cb.isChecked(),
            target_crs=crs,
        )
        self._worker.progress.connect(self._on_progress)
        self._worker.file_done.connect(self._on_file_done)
        self._worker.finished_ok.connect(self._on_done)
        self._worker.failed.connect(self._on_error)
        self._worker.start()

    def _resolve_crs(self):
        text = self._crs_combo.currentText()
        if text.startswith("EPSG:"):
            return "EPSG:" + text.split(":")[1].split()[0]
        return None

    @Slot(int, int)
    def _on_progress(self, done: int, total: int):
        pct = int(done / total * 100) if total else 0
        self._progress.setValue(pct)
        self._status.setText(f"进行中  {done}/{total}")

    @Slot(dict)
    def _on_file_done(self, res: dict):
        row = self._table.rowCount()
        self._table.insertRow(row)

        self._table.setItem(
            row, 0, QTableWidgetItem(Path(res['source']).name)
        )

        layer = res.get('layer') or (
            Path(res['source']).stem if res['success'] else '-'
        )
        self._table.setItem(row, 1, QTableWidgetItem(layer))

        status_item = QTableWidgetItem(
            "✓ 成功" if res['success'] else "✗ 失败"
        )
        status_item.setForeground(
            QColor("#22AA55") if res['success'] else QColor("#CC3344")
        )
        self._table.setItem(row, 2, status_item)

        self._table.setItem(
            row, 3,
            QTableWidgetItem(
                str(res['features']) if res['success'] else "-"
            ),
        )

        self._table.setItem(
            row, 4, QTableWidgetItem(f"{res['elapsed']:.2f}")
        )

        self._table.scrollToBottom()

    @Slot(dict)
    def _on_done(self, stats: dict):
        self._start_btn.setEnabled(True)
        self._start_btn.setText("开始转换")
        self._progress.setValue(100)
        self._status.setText(
            f"完成  成功 {stats['success']} / 失败 {stats['failed']} "
            f"/ 总计 {stats['total']}"
        )
        self._status.setStyleSheet("color: #22AA55; font-size: 12px;")

        self._output_dir = stats['output_dir']
        if stats['success'] > 0:
            self._open_btn.setEnabled(True)
            self._open_folder(self._output_dir)

    @Slot(str)
    def _on_error(self, message: str):
        self._start_btn.setEnabled(True)
        self._start_btn.setText("开始转换")
        self._status.setText(f"失败：{message}")
        self._status.setStyleSheet("color: #CC3344; font-size: 12px;")
        QMessageBox.critical(self, "错误", message)

    # ------------------------------------------------------------------
    # 打开文件夹
    # ------------------------------------------------------------------
    def _open_output_folder(self):
        if self._output_dir:
            self._open_folder(self._output_dir)

    @staticmethod
    def _open_folder(path: str):
        try:
            if sys.platform == 'win32':
                os.startfile(path)
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', path])
            else:
                subprocess.Popen(['xdg-open', path])
        except Exception:
            logging.exception("打开文件夹失败")

    # ------------------------------------------------------------------
    def closeEvent(self, event):
        self._save_settings()
        if self._log_handler is not None:
            logging.getLogger().removeHandler(self._log_handler)
            self._log_handler = None
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            if not self._worker.wait(5000):
                self._worker.terminate()
                self._worker.wait(1000)
        event.accept()


# ======================================================================
# 入口
# ======================================================================
def run_gui():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = ConverterWindow()
    window.show()
    sys.exit(app.exec())
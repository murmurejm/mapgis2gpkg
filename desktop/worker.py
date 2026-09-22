# -*- coding: utf-8 -*-
"""后台转换线程。"""

import logging

from PySide6.QtCore import QThread, Signal

from core.convert import convert_folder


class ConvertWorker(QThread):
    progress = Signal(int, int)
    file_done = Signal(dict)
    finished_ok = Signal(dict)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, input_dir=None, files=None,
                 output='', output_format='shp',
                 encoding='gb18030', recursive=False,
                 target_crs='EPSG:4326', parent=None):
        super().__init__(parent)
        self._input_dir = input_dir
        self._files = files
        self._output = output
        self._output_format = output_format
        self._encoding = encoding
        self._recursive = recursive
        self._target_crs = target_crs

    def cancel(self):
        self.requestInterruption()

    def run(self):
        try:
            stats = convert_folder(
                folder=self._input_dir,
                files=self._files,
                output_format=self._output_format,
                output=self._output,
                target_crs=self._target_crs,
                encoding=self._encoding,
                recursive=self._recursive,
                progress_callback=self._on_progress,
                file_done_callback=self._on_file_done,
            )
            if self.isInterruptionRequested():
                self.cancelled.emit()
                return
            self.finished_ok.emit(stats)
        except InterruptedError:
            self.cancelled.emit()
        except Exception as e:
            logging.exception("转换失败")
            self.failed.emit(str(e))

    def _on_progress(self, done, total):
        if self.isInterruptionRequested():
            raise InterruptedError("用户取消")
        self.progress.emit(done, total)

    def _on_file_done(self, res):
        if self.isInterruptionRequested():
            raise InterruptedError("用户取消")
        self.file_done.emit(res)
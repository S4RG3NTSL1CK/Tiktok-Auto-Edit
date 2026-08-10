import threading
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from ..core.pipeline import PipelineCancelled, PipelineSettings, run_pipeline
from ..core.updater import UpdateInfo, check_for_update, download_installer


class PipelineWorker(QThread):
    progress = Signal(int, str)
    finished_ok = Signal(list)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, video_path: str, settings: PipelineSettings, parent=None):
        super().__init__(parent)
        self.video_path = video_path
        self.settings = settings
        self._cancel_event = threading.Event()

    def cancel(self):
        self._cancel_event.set()

    def run(self):
        try:
            results = run_pipeline(
                self.video_path,
                self.settings,
                progress_cb=lambda pct, msg: self.progress.emit(pct, msg),
                cancel_event=self._cancel_event,
            )
            self.finished_ok.emit(results)
        except PipelineCancelled:
            self.cancelled.emit()
        except Exception as exc:
            self.failed.emit(str(exc))


class UpdateCheckWorker(QThread):
    found = Signal(object)  # UpdateInfo
    none_found = Signal()

    def __init__(self, current_version: str, parent=None):
        super().__init__(parent)
        self.current_version = current_version

    def run(self):
        info = check_for_update(self.current_version)
        if info:
            self.found.emit(info)
        else:
            self.none_found.emit()


class UpdateDownloadWorker(QThread):
    finished_ok = Signal(str)
    failed = Signal(str)

    def __init__(self, info: UpdateInfo, dest_dir: Path, parent=None):
        super().__init__(parent)
        self.info = info
        self.dest_dir = dest_dir

    def run(self):
        try:
            path = download_installer(self.info, self.dest_dir)
            self.finished_ok.emit(str(path))
        except Exception as exc:
            self.failed.emit(str(exc))

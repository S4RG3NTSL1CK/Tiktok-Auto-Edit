import threading

from PySide6.QtCore import QThread, Signal

from ..core.pipeline import PipelineCancelled, PipelineSettings, run_pipeline


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

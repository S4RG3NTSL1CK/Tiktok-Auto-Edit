import secrets
import threading
import webbrowser
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from ..core.copyright_check import check_copyright
from ..core.pipeline import PipelineCancelled, PipelineSettings, run_pipeline
from ..core.tiktok_client import (
    build_authorize_url, code_challenge_from_verifier, exchange_code_for_token,
    generate_code_verifier, get_display_name, upload_video_to_inbox, wait_for_oauth_callback,
)
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


class CopyrightCheckWorker(QThread):
    finished_ok = Signal(object)  # CopyrightMatch or None
    failed = Signal(str)

    def __init__(self, clip_path: str, api_token: str, parent=None):
        super().__init__(parent)
        self.clip_path = clip_path
        self.api_token = api_token

    def run(self):
        try:
            match = check_copyright(self.clip_path, self.api_token)
            self.finished_ok.emit(match)
        except Exception as exc:
            self.failed.emit(str(exc))


class TikTokLoginWorker(QThread):
    finished_ok = Signal(object, str)  # TikTokTokens, display_name
    failed = Signal(str)

    def __init__(self, client_key: str, client_secret: str, parent=None):
        super().__init__(parent)
        self.client_key = client_key
        self.client_secret = client_secret

    def run(self):
        try:
            verifier = generate_code_verifier()
            challenge = code_challenge_from_verifier(verifier)
            state = secrets.token_urlsafe(16)
            url = build_authorize_url(self.client_key, state, challenge)

            webbrowser.open(url)
            result = wait_for_oauth_callback()
            if result["state"] != state:
                raise RuntimeError("State mismatch on TikTok login callback — possible CSRF, aborting.")

            tokens = exchange_code_for_token(self.client_key, self.client_secret, result["code"], verifier)
            display_name = get_display_name(tokens.access_token)
            self.finished_ok.emit(tokens, display_name)
        except Exception as exc:
            self.failed.emit(str(exc))


class TikTokUploadWorker(QThread):
    finished_ok = Signal(str)  # publish_id
    failed = Signal(str)

    def __init__(self, access_token: str, clip_path: str, parent=None):
        super().__init__(parent)
        self.access_token = access_token
        self.clip_path = clip_path

    def run(self):
        try:
            publish_id = upload_video_to_inbox(self.access_token, self.clip_path)
            self.finished_ok.emit(publish_id)
        except Exception as exc:
            self.failed.emit(str(exc))

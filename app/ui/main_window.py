import sys
import tempfile
import time
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QRectF
from PySide6.QtGui import QDesktopServices, QPainter, QPen, QBrush, QColor, QLinearGradient, QPixmap
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel,
    QPushButton, QSpinBox, QDoubleSpinBox, QComboBox, QCheckBox, QLineEdit,
    QSlider, QProgressBar, QPlainTextEdit, QListWidget, QListWidgetItem,
    QFileDialog, QMessageBox, QGroupBox, QSplitter, QScrollArea,
)

from .. import config
from ..core.ffmpeg_utils import probe_video, FFmpegError
from ..core.music_provider import resolve_local_tracks
from ..core.pipeline import PipelineSettings
from ..core.tiktok_client import TikTokError, refresh_access_token
from ..core.updater import launch_installer_and_exit, versions_equal
from ..version import __version__
from .music_browser_dialog import MusicBrowserDialog
from .settings_dialog import SettingsDialog
from .theme import INDIGO, VIOLET, asset_path, mark_accent
from .tiktok_dialog import TikTokAccountDialog
from .workers import (
    CopyrightCheckWorker, PipelineWorker, TikTokUploadWorker, UpdateCheckWorker, UpdateDownloadWorker,
)


class DropArea(QLabel):
    fileDropped = Signal(str)

    def __init__(self):
        super().__init__("Drag & drop an .mp4 file here, or click Browse below")
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumHeight(110)
        self.setAcceptDrops(True)
        self.setStyleSheet(
            "QLabel { color: #b8b8c8; padding: 12px; background: transparent; border: none; }"
        )

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            if path.lower().endswith(".mp4"):
                self.fileDropped.emit(path)
            else:
                QMessageBox.warning(self, "Unsupported file", "Please drop an .mp4 file.")

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        rect = QRectF(2, 2, self.width() - 4, self.height() - 4)
        gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
        gradient.setColorAt(0, QColor(INDIGO))
        gradient.setColorAt(1, QColor(VIOLET))

        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#16161f"))
        painter.drawRoundedRect(rect, 14, 14)

        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QBrush(gradient), 2))
        painter.drawRoundedRect(rect, 14, 14)

        bracket_len = 22
        bracket_margin = 16
        pen = QPen(QBrush(gradient), 3)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        w, h = self.width(), self.height()
        painter.drawLine(bracket_margin, bracket_margin, bracket_margin + bracket_len, bracket_margin)
        painter.drawLine(bracket_margin, bracket_margin, bracket_margin, bracket_margin + bracket_len)
        painter.drawLine(w - bracket_margin, h - bracket_margin, w - bracket_margin - bracket_len, h - bracket_margin)
        painter.drawLine(w - bracket_margin, h - bracket_margin, w - bracket_margin, h - bracket_margin - bracket_len)

        painter.end()
        super().paintEvent(event)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Tiktok Auto Edit v{__version__}")
        self.resize(780, 820)

        self.cfg = config.load_config()
        self.video_path = None
        self.video_info = None
        self.worker = None
        self.selected_track = None
        self.selected_track_path = None
        self.local_music_path = None
        self.update_check_worker = None
        self.update_download_worker = None
        self._pending_update_version = None
        self.copyright_check_worker = None
        self.tiktok_upload_worker = None

        # Full settings content can naturally want more vertical space than
        # many screens have (drop zone + two settings groups + progress/log/
        # results). A scroll area lets it degrade to scrolling instead of
        # Qt force-compressing every row into illegible slivers to fit.
        root = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setWidget(root)
        self.setCentralWidget(scroll)
        layout = QVBoxLayout(root)

        top_bar = QHBoxLayout()
        top_bar.setSpacing(10)
        logo_label = QLabel()
        logo_pixmap = QPixmap(str(asset_path("icon.png")))
        if not logo_pixmap.isNull():
            logo_label.setPixmap(
                logo_pixmap.scaled(36, 36, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
        top_bar.addWidget(logo_label)
        title = QLabel(
            f'<span style="font-size:17pt; font-weight:700;">Tiktok</span> '
            f'<span style="font-size:17pt; font-weight:700; color:{VIOLET};">Auto Edit</span>'
        )
        top_bar.addWidget(title)
        top_bar.addStretch()
        tiktok_account_btn = QPushButton("TikTok Account")
        tiktok_account_btn.clicked.connect(self._open_tiktok_account)
        top_bar.addWidget(tiktok_account_btn)
        settings_btn = QPushButton("Settings")
        settings_btn.clicked.connect(self._open_settings)
        top_bar.addWidget(settings_btn)
        layout.addLayout(top_bar)

        self.drop_area = DropArea()
        self.drop_area.fileDropped.connect(self._set_video)
        layout.addWidget(self.drop_area)

        browse_row = QHBoxLayout()
        self.file_label = QLabel("No file selected")
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_video)
        browse_row.addWidget(self.file_label, stretch=1)
        browse_row.addWidget(browse_btn)
        layout.addLayout(browse_row)

        settings_box = QGroupBox("Clip settings")
        form = QFormLayout(settings_box)

        self.num_clips_spin = QSpinBox()
        self.num_clips_spin.setRange(1, 30)
        self.num_clips_spin.setValue(self.cfg["num_clips"])
        form.addRow("Number of clips:", self.num_clips_spin)

        len_row = QHBoxLayout()
        self.min_len_spin = QDoubleSpinBox()
        self.min_len_spin.setRange(5, 180)
        self.min_len_spin.setValue(self.cfg["min_len"])
        self.min_len_spin.setSuffix(" s")
        self.max_len_spin = QDoubleSpinBox()
        self.max_len_spin.setRange(5, 180)
        self.max_len_spin.setValue(self.cfg["max_len"])
        self.max_len_spin.setSuffix(" s")
        len_row.addWidget(QLabel("min"))
        len_row.addWidget(self.min_len_spin)
        len_row.addWidget(QLabel("max"))
        len_row.addWidget(self.max_len_spin)
        form.addRow("Clip length range:", len_row)

        self.aspect_combo = QComboBox()
        self.aspect_combo.addItems(["9:16", "1:1", "original"])
        self.aspect_combo.setCurrentText(self.cfg["aspect"])
        form.addRow("Aspect ratio:", self.aspect_combo)

        self.resolution_combo = QComboBox()
        self.resolution_combo.addItem("1080p", "1080p")
        self.resolution_combo.addItem("4K", "4k")
        self.resolution_combo.addItem("Source (native)", "source")
        res_idx = self.resolution_combo.findData(self.cfg.get("resolution_tier", "1080p"))
        self.resolution_combo.setCurrentIndex(res_idx if res_idx >= 0 else 0)
        self.resolution_combo.setToolTip(
            "Source: passes your video's native resolution straight through, uncropped scale-wise "
            "— fastest, and the only option that's always genuinely lossless regardless of what "
            "your footage actually is. 1080p/4K: exports at that fixed size no matter the source; "
            "if your source doesn't actually have that much detail after cropping, this upscales "
            "rather than adding real detail — the app warns you in the log when that happens."
        )
        form.addRow("Resolution:", self.resolution_combo)

        self.fps_combo = QComboBox()
        self.fps_combo.addItem("Source (native)", "source")
        self.fps_combo.addItem("30 fps", "30")
        self.fps_combo.addItem("60 fps", "60")
        fps_idx = self.fps_combo.findData(self.cfg.get("fps_tier", "source"))
        self.fps_combo.setCurrentIndex(fps_idx if fps_idx >= 0 else 0)
        self.fps_combo.setToolTip(
            "Source: passes your video's native frame rate straight through — fastest, and always "
            "genuinely that smooth. 30/60: conforms to that rate regardless of source; if your "
            "source is actually slower, frames get duplicated to fill the timeline rather than "
            "being genuinely smoother motion — the app warns you in the log when that happens."
        )
        form.addRow("Frame rate:", self.fps_combo)

        self.highlight_reel_checkbox = QCheckBox("Also stitch all clips into one highlight reel")
        self.highlight_reel_checkbox.setChecked(self.cfg.get("create_highlight_reel", False))
        self.highlight_reel_checkbox.setToolTip(
            "Concatenates every generated clip into a single highlight_reel.mp4, in chronological "
            "order, with a short crossfade at each join instead of a hard cut. The individual clip "
            "files are still produced as normal."
        )
        form.addRow(self.highlight_reel_checkbox)

        self.transcript_checkbox = QCheckBox("Use speech transcription to favor hook moments (questions, lists, etc.)")
        self.transcript_checkbox.setChecked(self.cfg.get("transcript_enabled", False))
        self.transcript_checkbox.setToolTip(
            "Transcribes the video locally (no cloud call) and biases clip selection toward "
            "strong spoken openers — questions, numbered lists, direct address. First use "
            "downloads a small speech-recognition model (~140MB, one-time) and adds some "
            "render time up front to transcribe the full video."
        )
        form.addRow(self.transcript_checkbox)

        self.output_dir_edit = QLineEdit(self.cfg["output_dir"])
        out_browse_btn = QPushButton("Browse...")
        out_browse_btn.clicked.connect(self._browse_output_dir)
        out_row = QHBoxLayout()
        out_row.addWidget(self.output_dir_edit)
        out_row.addWidget(out_browse_btn)
        form.addRow("Output folder:", out_row)

        layout.addWidget(settings_box)

        music_box = QGroupBox("Music")
        music_form = QFormLayout(music_box)

        self.music_checkbox = QCheckBox("Add royalty-free background music")
        self.music_checkbox.setChecked(self.cfg["music_enabled"])
        music_form.addRow(self.music_checkbox)

        self.music_provider_combo = QComboBox()
        self.music_provider_combo.addItems(["freesound", "jamendo"])
        self.music_provider_combo.setCurrentText(self.cfg.get("music_provider", "freesound"))
        music_form.addRow("Music provider:", self.music_provider_combo)

        self.tags_edit = QLineEdit(self.cfg.get("music_tags", ""))
        self.tags_edit.setPlaceholderText("e.g. lofi chill, cinematic epic, upbeat pop — blank rotates presets")
        music_form.addRow("Genre / mood tags:", self.tags_edit)

        self.instrumental_checkbox = QCheckBox("Instrumental only (avoids clashing with talking)")
        self.instrumental_checkbox.setChecked(self.cfg.get("music_instrumental_only", True))
        music_form.addRow(self.instrumental_checkbox)

        self.energy_combo = QComboBox()
        energy_labels = [("auto", "Auto (match each clip's own energy)"), ("any", "Any"),
                          ("verylow", "Very Low"), ("low", "Low"), ("medium", "Medium"),
                          ("high", "High"), ("veryhigh", "Very High")]
        for value, label in energy_labels:
            self.energy_combo.addItem(label, value)
        current_energy = self.cfg.get("music_energy", "auto")
        idx = self.energy_combo.findData(current_energy)
        self.energy_combo.setCurrentIndex(idx if idx >= 0 else 0)
        music_form.addRow("Energy / tempo:", self.energy_combo)

        self.beat_sync_checkbox = QCheckBox("Beat-sync clip cuts to music (recommended)")
        self.beat_sync_checkbox.setChecked(self.cfg.get("beat_sync_enabled", True))
        music_form.addRow(self.beat_sync_checkbox)

        browse_row = QHBoxLayout()
        browse_music_btn = QPushButton("Browse && Listen...")
        browse_music_btn.clicked.connect(self._open_music_browser)
        self.clear_track_btn = QPushButton("Clear")
        self.clear_track_btn.setEnabled(False)
        self.clear_track_btn.clicked.connect(self._clear_selected_track)
        browse_row.addWidget(browse_music_btn)
        browse_row.addWidget(self.clear_track_btn)
        music_form.addRow(browse_row)

        self.selected_track_label = QLabel("No specific track selected — auto-picks per clip from tags above.")
        self.selected_track_label.setWordWrap(True)
        music_form.addRow(self.selected_track_label)

        local_row = QHBoxLayout()
        use_local_file_btn = QPushButton("Use Local File...")
        use_local_file_btn.clicked.connect(self._use_local_file)
        use_local_folder_btn = QPushButton("Use Local Folder...")
        use_local_folder_btn.clicked.connect(self._use_local_folder)
        self.clear_local_btn = QPushButton("Clear")
        self.clear_local_btn.setEnabled(False)
        self.clear_local_btn.clicked.connect(self._clear_local_music)
        local_row.addWidget(use_local_file_btn)
        local_row.addWidget(use_local_folder_btn)
        local_row.addWidget(self.clear_local_btn)
        music_form.addRow(local_row)

        self.local_music_label = QLabel("No local music selected — you're responsible for the license of your own files.")
        self.local_music_label.setWordWrap(True)
        music_form.addRow(self.local_music_label)

        self.music_vol_slider = QSlider(Qt.Horizontal)
        self.music_vol_slider.setRange(0, 100)
        self.music_vol_slider.setValue(int(self.cfg["music_volume"] * 100))
        music_form.addRow("Music volume:", self.music_vol_slider)

        self.orig_vol_slider = QSlider(Qt.Horizontal)
        self.orig_vol_slider.setRange(0, 100)
        self.orig_vol_slider.setValue(int(self.cfg["orig_volume"] * 100))
        music_form.addRow("Original audio volume:", self.orig_vol_slider)

        layout.addWidget(music_box)

        action_row = QHBoxLayout()
        self.generate_btn = QPushButton("Generate Clips")
        mark_accent(self.generate_btn)
        self.generate_btn.clicked.connect(self._start_generation)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel_generation)
        action_row.addWidget(self.generate_btn)
        action_row.addWidget(self.cancel_btn)
        layout.addLayout(action_row)

        self.progress_bar = QProgressBar()
        self.status_label = QLabel("")
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.status_label)

        splitter = QSplitter(Qt.Vertical)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.results_list = QListWidget()
        splitter.addWidget(self.log_view)
        splitter.addWidget(self.results_list)
        layout.addWidget(splitter, stretch=1)

        results_action_row = QHBoxLayout()
        self.copyright_check_btn = QPushButton("Check Copyright")
        self.copyright_check_btn.setEnabled(False)
        self.copyright_check_btn.setToolTip(
            "Checks the selected clip's audio against AudD's commercial-music database. "
            "This is a best-effort proxy, not a guarantee of what TikTok's own detection will do."
        )
        self.copyright_check_btn.clicked.connect(self._check_copyright_selected)
        results_action_row.addWidget(self.copyright_check_btn)

        self.tiktok_upload_btn = QPushButton("Upload to TikTok (draft)")
        self.tiktok_upload_btn.setEnabled(False)
        self.tiktok_upload_btn.setToolTip(
            "Uploads the selected clip to your connected TikTok account's inbox as a draft "
            "for you to review and publish yourself."
        )
        self.tiktok_upload_btn.clicked.connect(self._upload_selected_to_tiktok)
        results_action_row.addWidget(self.tiktok_upload_btn)

        results_action_row.addStretch()
        layout.addLayout(results_action_row)

        self.results_list.itemDoubleClicked.connect(self._open_result_item)
        self.results_list.currentItemChanged.connect(self._on_result_selection_changed)

        self._notify_if_just_updated()
        self._check_for_update_in_background()

    def _notify_if_just_updated(self):
        pending_version = config.consume_pending_update()
        if not pending_version:
            return
        if versions_equal(pending_version, __version__):
            QMessageBox.information(
                self, "Update installed",
                f"✓ Updated to {pending_version} successfully.",
            )
        else:
            # The marker was written before install, but this running binary
            # is still an older version — the silent install didn't actually
            # land (e.g. it was still copying files when the app got
            # relaunched). Say so honestly instead of a false "success".
            QMessageBox.warning(
                self, "Update did not complete",
                f"An update to {pending_version} was started, but this is still v{__version__} — "
                "the install didn't finish. Wait a few seconds for any installer window to close, "
                "then try updating again.",
            )

    def _check_for_update_in_background(self):
        self.update_check_worker = UpdateCheckWorker(__version__, parent=self)
        self.update_check_worker.found.connect(self._on_update_found)
        self.update_check_worker.start()

    def _on_update_found(self, info):
        if self.worker is not None and self.worker.isRunning():
            # Don't interrupt an in-progress render with a force-close
            # installer; the check just runs again next launch.
            return
        reply = QMessageBox.question(
            self, "Update available",
            f"Tiktok Auto Edit {info.version} is available (you have v{__version__}).\n\n"
            f"{info.notes}\n\nDownload and install now? The app will close during install.",
        )
        if reply != QMessageBox.Yes:
            return
        self._pending_update_version = info.version
        self.status_label.setText(f"Downloading update {info.version}...")
        dest_dir = Path(tempfile.gettempdir()) / "tiktok_auto_edit_updates"
        self.update_download_worker = UpdateDownloadWorker(info, dest_dir, parent=self)
        self.update_download_worker.finished_ok.connect(self._on_update_downloaded)
        self.update_download_worker.failed.connect(
            lambda msg: QMessageBox.warning(self, "Update failed", f"Could not download update: {msg}")
        )
        self.update_download_worker.start()

    def _on_update_downloaded(self, installer_path: str):
        if sys.platform != "win32":
            QMessageBox.information(
                self, "Update downloaded",
                f"Downloaded to {installer_path}, but silent auto-install is only supported on "
                "the Windows build. Run it manually to install.",
            )
            return
        QMessageBox.information(
            self, "Installing update",
            f"Installing {self._pending_update_version} now. The app will close and reopen "
            "automatically — please don't launch it manually until it does.",
        )
        try:
            config.mark_pending_update(self._pending_update_version)
            launch_installer_and_exit(Path(installer_path))
        except RuntimeError as exc:
            QMessageBox.warning(self, "Update failed", str(exc))
            return
        self.close()

    def closeEvent(self, event):
        if self.worker is not None and self.worker.isRunning():
            reply = QMessageBox.question(
                self, "Generation in progress",
                "Clips are still being generated. Cancel generation and close?",
            )
            if reply != QMessageBox.Yes:
                event.ignore()
                return
            self.worker.cancel()
            self.worker.wait(15000)

        for worker in (
            self.update_check_worker, self.update_download_worker,
            self.copyright_check_worker, self.tiktok_upload_worker,
        ):
            if worker is not None and worker.isRunning():
                worker.wait(5000)
        super().closeEvent(event)

    def _open_settings(self):
        dlg = SettingsDialog(self)
        if dlg.exec():
            self.cfg = config.load_config()
            self.output_dir_edit.setText(self.cfg["output_dir"])

    def _open_tiktok_account(self):
        dlg = TikTokAccountDialog(self)
        dlg.exec()
        self._on_result_selection_changed(self.results_list.currentItem(), None)

    def _browse_video(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select video", "", "MP4 videos (*.mp4)")
        if path:
            self._set_video(path)

    def _set_video(self, path: str):
        self.video_path = path
        self.file_label.setText(path)
        try:
            info = probe_video(path)
            self.video_info = info
            self.drop_area.setText(
                f"{Path(path).name}  —  {info.width}x{info.height}  —  "
                f"{info.fps:.0f}fps  —  {info.duration:.1f}s"
            )
            res_source_idx = self.resolution_combo.findData("source")
            self.resolution_combo.setItemText(
                res_source_idx, f"Source (native — {info.width}x{info.height})"
            )
            fps_source_idx = self.fps_combo.findData("source")
            self.fps_combo.setItemText(fps_source_idx, f"Source (native — {info.fps:.0f}fps)")
        except FFmpegError as exc:
            QMessageBox.warning(self, "Could not read video", str(exc))
            self.video_path = None
            self.video_info = None

    def _browse_output_dir(self):
        path = QFileDialog.getExistingDirectory(self, "Choose output folder", self.output_dir_edit.text())
        if path:
            self.output_dir_edit.setText(path)

    def _log(self, msg: str):
        self.log_view.appendPlainText(msg)

    def _open_music_browser(self):
        cfg = config.load_config()
        dlg = MusicBrowserDialog(
            self,
            provider=self.music_provider_combo.currentText(),
            freesound_api_key=cfg.get("freesound_api_key", ""),
            jamendo_api_key=cfg.get("jamendo_api_key", ""),
            initial_tags=self.tags_edit.text().strip(),
            initial_instrumental=self.instrumental_checkbox.isChecked(),
            initial_energy=self.energy_combo.currentData(),
        )
        if dlg.exec() and dlg.selected_track:
            self.selected_track = dlg.selected_track
            self.selected_track_path = dlg.selected_track_path
            self.selected_track_label.setText(
                f"Selected: \"{self.selected_track.name}\" by {self.selected_track.artist} "
                f"({self.selected_track.license}) — used on every generated clip."
            )
            self.clear_track_btn.setEnabled(True)
            self.music_checkbox.setChecked(True)
            self._clear_local_music()

    def _clear_selected_track(self):
        self.selected_track = None
        self.selected_track_path = None
        self.selected_track_label.setText("No specific track selected — auto-picks per clip from tags above.")
        self.clear_track_btn.setEnabled(False)

    def _use_local_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select a local music file", "",
            "Audio files (*.mp3 *.wav *.m4a *.flac *.ogg *.aac)",
        )
        if not path:
            return
        self._set_local_music(path, f"Local file: {Path(path).name} — used on every generated clip.")

    def _use_local_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Select a folder of local music files")
        if not path:
            return
        tracks = resolve_local_tracks(path)
        if not tracks:
            QMessageBox.warning(self, "No audio files found", f"No supported audio files found in:\n{path}")
            return
        self._set_local_music(path, f"Local folder: {Path(path).name} ({len(tracks)} tracks) — one picked per clip.")

    def _set_local_music(self, path: str, label_text: str):
        self.local_music_path = path
        self.local_music_label.setText(label_text)
        self.clear_local_btn.setEnabled(True)
        self.music_checkbox.setChecked(True)
        self._clear_selected_track()

    def _clear_local_music(self):
        self.local_music_path = None
        self.local_music_label.setText("No local music selected — you're responsible for the license of your own files.")
        self.clear_local_btn.setEnabled(False)

    def _collect_settings(self) -> PipelineSettings:
        cfg = config.load_config()
        if self.local_music_path:
            music_source = "local"
        elif self.selected_track_path:
            music_source = "manual"
        else:
            music_source = "auto"
        return PipelineSettings(
            num_clips=self.num_clips_spin.value(),
            min_len=self.min_len_spin.value(),
            max_len=max(self.max_len_spin.value(), self.min_len_spin.value()),
            aspect=self.aspect_combo.currentText(),
            music_enabled=self.music_checkbox.isChecked(),
            music_tags=self.tags_edit.text().strip(),
            music_instrumental_only=self.instrumental_checkbox.isChecked(),
            music_energy=self.energy_combo.currentData(),
            music_volume=self.music_vol_slider.value() / 100,
            orig_volume=self.orig_vol_slider.value() / 100,
            output_dir=self.output_dir_edit.text().strip(),
            music_provider=self.music_provider_combo.currentText(),
            freesound_api_key=cfg.get("freesound_api_key", ""),
            jamendo_api_key=cfg.get("jamendo_api_key", ""),
            music_source=music_source,
            manual_track_path=self.selected_track_path or "",
            manual_track_attribution=self.selected_track.attribution_line() if self.selected_track else "",
            local_music_path=self.local_music_path or "",
            beat_sync_enabled=self.beat_sync_checkbox.isChecked(),
            resolution_tier=self.resolution_combo.currentData(),
            fps_tier=self.fps_combo.currentData(),
            create_highlight_reel=self.highlight_reel_checkbox.isChecked(),
            transcript_enabled=self.transcript_checkbox.isChecked(),
        )

    def _start_generation(self):
        if not self.video_path:
            QMessageBox.warning(self, "No video", "Select or drop an .mp4 file first.")
            return
        settings = self._collect_settings()
        provider_key = settings.freesound_api_key if settings.music_provider == "freesound" else settings.jamendo_api_key
        if settings.music_enabled and settings.music_source == "auto" and not provider_key:
            QMessageBox.warning(
                self, "Missing API key",
                f"Music is enabled with provider '{settings.music_provider}' but no API key is "
                "set for it. Add one in Settings, switch provider, or disable music.",
            )
            return
        if not settings.output_dir:
            QMessageBox.warning(self, "No output folder", "Choose an output folder first.")
            return

        persisted = config.load_config()
        persisted.update({
            "num_clips": settings.num_clips,
            "min_len": settings.min_len,
            "max_len": settings.max_len,
            "aspect": settings.aspect,
            "resolution_tier": settings.resolution_tier,
            "fps_tier": settings.fps_tier,
            "create_highlight_reel": settings.create_highlight_reel,
            "transcript_enabled": settings.transcript_enabled,
            "music_enabled": settings.music_enabled,
            "music_provider": settings.music_provider,
            "music_tags": settings.music_tags,
            "music_instrumental_only": settings.music_instrumental_only,
            "music_energy": settings.music_energy,
            "music_volume": settings.music_volume,
            "orig_volume": settings.orig_volume,
            "beat_sync_enabled": settings.beat_sync_enabled,
            "output_dir": settings.output_dir,
        })
        config.save_config(persisted)

        self.results_list.clear()
        self.log_view.clear()
        self.progress_bar.setValue(0)
        self.generate_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)

        self.worker = PipelineWorker(self.video_path, settings)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished_ok.connect(self._on_finished)
        self.worker.failed.connect(self._on_failed)
        self.worker.cancelled.connect(self._on_cancelled)
        self.worker.start()

    def _cancel_generation(self):
        if self.worker:
            self.worker.cancel()
            self.status_label.setText("Cancelling...")

    def _on_progress(self, pct: int, msg: str):
        self.progress_bar.setValue(pct)
        self.status_label.setText(msg)
        self._log(f"[{pct}%] {msg}")

    def _on_finished(self, results: list):
        self.generate_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self._log(f"Done. {len(results)} clip(s) written to {self.output_dir_edit.text()}")
        for r in results:
            item = QListWidgetItem(
                f"{Path(r.path).name}   ({r.start:.1f}s - {r.end:.1f}s)"
                + (f"   ♪ {r.track_attribution}" if r.track_attribution else "")
            )
            item.setData(Qt.UserRole, r.path)
            self.results_list.addItem(item)

    def _on_failed(self, message: str):
        self.generate_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self._log(f"ERROR: {message}")
        QMessageBox.critical(self, "Generation failed", message)

    def _on_cancelled(self):
        self.generate_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.status_label.setText("Cancelled")
        self._log("Cancelled by user.")

    def _open_result_item(self, item: QListWidgetItem):
        path = item.data(Qt.UserRole)
        if path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).parent)))

    def _on_result_selection_changed(self, current, _previous):
        self.copyright_check_btn.setEnabled(current is not None)
        cfg = config.load_config()
        self.tiktok_upload_btn.setEnabled(current is not None and bool(cfg.get("tiktok_open_id", "")))

    def _check_copyright_selected(self):
        item = self.results_list.currentItem()
        if not item:
            return
        clip_path = item.data(Qt.UserRole)
        cfg = config.load_config()
        api_token = cfg.get("audd_api_token", "")
        if not api_token:
            QMessageBox.warning(
                self, "Missing API key",
                "No AudD API token configured. Add one in Settings first.",
            )
            return

        self.copyright_check_btn.setEnabled(False)
        self.copyright_check_btn.setText("Checking...")
        self.copyright_check_worker = CopyrightCheckWorker(clip_path, api_token, parent=self)
        self.copyright_check_worker.finished_ok.connect(self._on_copyright_check_done)
        self.copyright_check_worker.failed.connect(self._on_copyright_check_failed)
        self.copyright_check_worker.start()

    def _on_copyright_check_done(self, match):
        self.copyright_check_btn.setEnabled(True)
        self.copyright_check_btn.setText("Check Copyright")
        if match is None:
            QMessageBox.information(
                self, "Copyright check",
                "No commercial match found in AudD's database. This is a good sign, but not a "
                "guarantee — TikTok's own detection system is separate and not publicly checkable.",
            )
        else:
            QMessageBox.warning(
                self, "Possible copyright match",
                f"This clip's audio matches a known commercial track:\n\n{match.summary()}\n\n"
                "This could get muted or claimed on TikTok. This is a best-effort check against "
                "AudD's database, not TikTok's own system, so treat it as a warning sign to "
                "investigate rather than a certainty.",
            )

    def _on_copyright_check_failed(self, message: str):
        self.copyright_check_btn.setEnabled(True)
        self.copyright_check_btn.setText("Check Copyright")
        QMessageBox.warning(self, "Copyright check failed", message)

    def _get_valid_tiktok_access_token(self):
        cfg = config.load_config()
        access_token = cfg.get("tiktok_access_token", "")
        if not access_token:
            return None
        if time.time() < cfg.get("tiktok_token_expires_at", 0):
            return access_token
        try:
            tokens = refresh_access_token(
                cfg.get("tiktok_client_key", ""), cfg.get("tiktok_client_secret", ""),
                cfg.get("tiktok_refresh_token", ""),
            )
        except TikTokError as exc:
            QMessageBox.warning(
                self, "TikTok session expired",
                f"Could not refresh your TikTok login: {exc}\n\nReconnect via TikTok Account.",
            )
            return None
        cfg["tiktok_access_token"] = tokens.access_token
        cfg["tiktok_refresh_token"] = tokens.refresh_token
        cfg["tiktok_token_expires_at"] = tokens.expires_at
        config.save_config(cfg)
        return tokens.access_token

    def _upload_selected_to_tiktok(self):
        item = self.results_list.currentItem()
        if not item:
            return
        clip_path = item.data(Qt.UserRole)
        access_token = self._get_valid_tiktok_access_token()
        if not access_token:
            QMessageBox.warning(
                self, "Not connected",
                "Connect your TikTok account first via the TikTok Account button.",
            )
            return

        self.tiktok_upload_btn.setEnabled(False)
        self.tiktok_upload_btn.setText("Uploading...")
        self.tiktok_upload_worker = TikTokUploadWorker(access_token, clip_path, parent=self)
        self.tiktok_upload_worker.finished_ok.connect(self._on_tiktok_upload_done)
        self.tiktok_upload_worker.failed.connect(self._on_tiktok_upload_failed)
        self.tiktok_upload_worker.start()

    def _on_tiktok_upload_done(self, publish_id: str):
        self.tiktok_upload_btn.setEnabled(True)
        self.tiktok_upload_btn.setText("Upload to TikTok (draft)")
        QMessageBox.information(
            self, "Uploaded to TikTok",
            "Sent to your TikTok inbox as a draft. Open the TikTok app to review, edit, and "
            f"publish it yourself.\n\nPublish ID: {publish_id}",
        )

    def _on_tiktok_upload_failed(self, message: str):
        self.tiktok_upload_btn.setEnabled(True)
        self.tiktok_upload_btn.setText("Upload to TikTok (draft)")
        QMessageBox.warning(self, "TikTok upload failed", message)

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel,
    QPushButton, QSpinBox, QDoubleSpinBox, QComboBox, QCheckBox, QLineEdit,
    QSlider, QProgressBar, QPlainTextEdit, QListWidget, QListWidgetItem,
    QFileDialog, QMessageBox, QGroupBox, QSplitter,
)

from .. import config
from ..core.ffmpeg_utils import probe_video, FFmpegError
from ..core.pipeline import PipelineSettings
from .music_browser_dialog import MusicBrowserDialog
from .settings_dialog import SettingsDialog
from .workers import PipelineWorker


class DropArea(QLabel):
    fileDropped = Signal(str)

    def __init__(self):
        super().__init__("Drag & drop an .mp4 file here, or click Browse below")
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumHeight(90)
        self.setAcceptDrops(True)
        self.setStyleSheet(
            "QLabel { border: 2px dashed #888; border-radius: 8px; padding: 12px; color: #666; }"
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


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Tiktok Auto Edit")
        self.resize(760, 720)

        self.cfg = config.load_config()
        self.video_path = None
        self.worker = None
        self.selected_track = None
        self.selected_track_path = None

        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)

        top_bar = QHBoxLayout()
        title = QLabel("<h2>Tiktok Auto Edit</h2>")
        top_bar.addWidget(title)
        top_bar.addStretch()
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
        energy_labels = [("any", "Any"), ("verylow", "Very Low"), ("low", "Low"),
                          ("medium", "Medium"), ("high", "High"), ("veryhigh", "Very High")]
        for value, label in energy_labels:
            self.energy_combo.addItem(label, value)
        current_energy = self.cfg.get("music_energy", "any")
        idx = self.energy_combo.findData(current_energy)
        self.energy_combo.setCurrentIndex(idx if idx >= 0 else 0)
        music_form.addRow("Energy / tempo:", self.energy_combo)

        browse_row = QHBoxLayout()
        browse_music_btn = QPushButton("Browse & Listen...")
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

        self.results_list.itemDoubleClicked.connect(self._open_result_item)

    def _open_settings(self):
        dlg = SettingsDialog(self)
        if dlg.exec():
            self.cfg = config.load_config()
            self.output_dir_edit.setText(self.cfg["output_dir"])

    def _browse_video(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select video", "", "MP4 videos (*.mp4)")
        if path:
            self._set_video(path)

    def _set_video(self, path: str):
        self.video_path = path
        self.file_label.setText(path)
        try:
            info = probe_video(path)
            self.drop_area.setText(
                f"{Path(path).name}  —  {info.width}x{info.height}  —  {info.duration:.1f}s"
            )
        except FFmpegError as exc:
            QMessageBox.warning(self, "Could not read video", str(exc))
            self.video_path = None

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

    def _clear_selected_track(self):
        self.selected_track = None
        self.selected_track_path = None
        self.selected_track_label.setText("No specific track selected — auto-picks per clip from tags above.")
        self.clear_track_btn.setEnabled(False)

    def _collect_settings(self) -> PipelineSettings:
        cfg = config.load_config()
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
            manual_track_path=self.selected_track_path or "",
            manual_track_attribution=self.selected_track.attribution_line() if self.selected_track else "",
            jamendo_api_key=cfg.get("jamendo_api_key", ""),
        )

    def _start_generation(self):
        if not self.video_path:
            QMessageBox.warning(self, "No video", "Select or drop an .mp4 file first.")
            return
        settings = self._collect_settings()
        provider_key = settings.freesound_api_key if settings.music_provider == "freesound" else settings.jamendo_api_key
        if settings.music_enabled and not settings.manual_track_path and not provider_key:
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
            "music_enabled": settings.music_enabled,
            "music_provider": settings.music_provider,
            "music_tags": settings.music_tags,
            "music_instrumental_only": settings.music_instrumental_only,
            "music_energy": settings.music_energy,
            "music_volume": settings.music_volume,
            "orig_volume": settings.orig_volume,
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

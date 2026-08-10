from PySide6.QtCore import Qt, QUrl, QThread, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QLineEdit,
    QComboBox, QCheckBox, QPushButton, QListWidget, QListWidgetItem, QMessageBox,
)

from ..core.music_provider import MusicSpec, default_cache_dir, get_client
from .theme import mark_accent, style_dialog


class SearchWorker(QThread):
    finished_ok = Signal(list)
    failed = Signal(str)

    def __init__(self, client, spec: MusicSpec, parent=None):
        super().__init__(parent)
        self.client = client
        self.spec = spec

    def run(self):
        try:
            tracks = self.client.search(self.spec, min_duration=10, max_duration=600, page_size=30)
            self.finished_ok.emit(tracks)
        except Exception as exc:
            self.failed.emit(str(exc))


class DownloadWorker(QThread):
    finished_ok = Signal(str)
    failed = Signal(str)

    def __init__(self, client, track, parent=None):
        super().__init__(parent)
        self.client = client
        self.track = track

    def run(self):
        try:
            path = self.client.download_preview(self.track, default_cache_dir())
            self.finished_ok.emit(str(path))
        except Exception as exc:
            self.failed.emit(str(exc))


class MusicBrowserDialog(QDialog):
    def __init__(
        self, parent, provider: str, freesound_api_key: str, jamendo_api_key: str,
        initial_tags: str = "", initial_instrumental: bool = True, initial_energy: str = "any",
    ):
        super().__init__(parent)
        self.setWindowTitle("Browse Music")
        style_dialog(self)
        self.setMinimumSize(560, 480)

        self.freesound_api_key = freesound_api_key
        self.jamendo_api_key = jamendo_api_key
        self.search_worker = None
        self.download_worker = None
        self.selected_track = None
        self.selected_track_path = None

        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_output)
        self.player.playbackStateChanged.connect(self._on_playback_state_changed)
        self.player.errorOccurred.connect(self._on_player_error)

        layout = QVBoxLayout(self)

        form = QFormLayout()
        self.provider_combo = QComboBox()
        self.provider_combo.addItems(["freesound", "jamendo"])
        self.provider_combo.setCurrentText(provider)
        form.addRow("Provider:", self.provider_combo)

        self.tags_edit = QLineEdit(initial_tags)
        self.tags_edit.setPlaceholderText("e.g. lofi chill, cinematic epic, upbeat pop")
        self.tags_edit.returnPressed.connect(self._start_search)
        form.addRow("Genre / mood tags:", self.tags_edit)

        self.instrumental_checkbox = QCheckBox("Instrumental only")
        self.instrumental_checkbox.setChecked(initial_instrumental)
        form.addRow(self.instrumental_checkbox)

        self.energy_combo = QComboBox()
        for value, label in [("any", "Any"), ("verylow", "Very Low"), ("low", "Low"),
                              ("medium", "Medium"), ("high", "High"), ("veryhigh", "Very High")]:
            self.energy_combo.addItem(label, value)
        idx = self.energy_combo.findData(initial_energy)
        self.energy_combo.setCurrentIndex(idx if idx >= 0 else 0)
        form.addRow("Energy / tempo:", self.energy_combo)

        layout.addLayout(form)

        search_row = QHBoxLayout()
        self.search_btn = QPushButton("Search")
        self.search_btn.clicked.connect(self._start_search)
        search_row.addWidget(self.search_btn)
        search_row.addStretch()
        layout.addLayout(search_row)

        self.results_list = QListWidget()
        self.results_list.currentItemChanged.connect(self._on_selection_changed)
        self.results_list.itemDoubleClicked.connect(lambda _: self._toggle_play())
        layout.addWidget(self.results_list, stretch=1)

        playback_row = QHBoxLayout()
        self.play_btn = QPushButton("▶ Play preview")
        self.play_btn.setEnabled(False)
        self.play_btn.clicked.connect(self._toggle_play)
        playback_row.addWidget(self.play_btn)
        self.status_label = QLabel("")
        playback_row.addWidget(self.status_label, stretch=1)
        layout.addLayout(playback_row)

        button_row = QHBoxLayout()
        self.use_btn = QPushButton("Use this track")
        mark_accent(self.use_btn)
        self.use_btn.setEnabled(False)
        self.use_btn.clicked.connect(self._use_selected_track)
        close_btn = QPushButton("Cancel")
        close_btn.clicked.connect(self.reject)
        button_row.addStretch()
        button_row.addWidget(close_btn)
        button_row.addWidget(self.use_btn)
        layout.addLayout(button_row)

        self._start_search()

    def _current_client(self):
        provider = self.provider_combo.currentText()
        key = self.freesound_api_key if provider == "freesound" else self.jamendo_api_key
        if not key:
            QMessageBox.warning(
                self, "Missing API key",
                f"No API key configured for '{provider}'. Add one in Settings first.",
            )
            return None
        return get_client(provider, self.freesound_api_key, self.jamendo_api_key)

    def _start_search(self):
        client = self._current_client()
        if not client:
            return
        spec = MusicSpec(
            tags=self.tags_edit.text().strip(),
            instrumental_only=self.instrumental_checkbox.isChecked(),
            energy=self.energy_combo.currentData(),
        )
        self.player.stop()
        self.results_list.clear()
        self.play_btn.setEnabled(False)
        self.use_btn.setEnabled(False)
        self.status_label.setText("Searching...")
        self.search_btn.setEnabled(False)

        self.search_worker = SearchWorker(client, spec, parent=self)
        self.search_worker.finished_ok.connect(self._on_search_done)
        self.search_worker.failed.connect(self._on_search_failed)
        self.search_worker.start()

    def _on_search_done(self, tracks: list):
        self.search_btn.setEnabled(True)
        if not tracks:
            self.status_label.setText("No tracks found. Try different tags.")
            return
        self.status_label.setText(f"{len(tracks)} track(s) found.")
        for track in tracks:
            minutes, seconds = divmod(int(track.duration), 60)
            genre_part = f" [{track.genre}]" if track.genre else ""
            label = f"{track.name}{genre_part} — {track.artist} — {track.license} — {minutes}:{seconds:02d}"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, track)
            self.results_list.addItem(item)

    def _on_search_failed(self, message: str):
        self.search_btn.setEnabled(True)
        self.status_label.setText(f"Search failed: {message}")

    def _on_selection_changed(self, current, _previous):
        self.player.stop()
        self.play_btn.setText("▶ Play preview")
        self.play_btn.setEnabled(current is not None)
        self.use_btn.setEnabled(current is not None)

    def _toggle_play(self):
        item = self.results_list.currentItem()
        if not item:
            return
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.stop()
            return
        track = item.data(Qt.UserRole)
        self.player.setSource(QUrl(track.preview_url))
        self.player.play()
        self.status_label.setText(f"Playing: {track.name}")

    def _on_playback_state_changed(self, state):
        self.play_btn.setText("⏸ Stop preview" if state == QMediaPlayer.PlayingState else "▶ Play preview")

    def _on_player_error(self, _error, error_string: str):
        if error_string:
            self.status_label.setText(f"Playback error: {error_string}")

    def _use_selected_track(self):
        item = self.results_list.currentItem()
        if not item:
            return
        track = item.data(Qt.UserRole)
        client = self._current_client()
        if not client:
            return

        self.player.stop()
        self.use_btn.setEnabled(False)
        self.status_label.setText(f"Downloading '{track.name}'...")

        self.download_worker = DownloadWorker(client, track, parent=self)
        self.download_worker.finished_ok.connect(lambda path: self._on_download_done(track, path))
        self.download_worker.failed.connect(self._on_download_failed)
        self.download_worker.start()

    def _on_download_done(self, track, path: str):
        self.selected_track = track
        self.selected_track_path = path
        self.accept()

    def _on_download_failed(self, message: str):
        self.use_btn.setEnabled(True)
        self.status_label.setText(f"Download failed: {message}")

    def done(self, result):
        # QDialog's accept()/reject()/closeEvent all funnel through here. A
        # QThread destroyed while still running aborts the whole process, so
        # block briefly until any in-flight search/download finishes.
        self.player.stop()
        for worker in (self.search_worker, self.download_worker):
            if worker is not None and worker.isRunning():
                worker.wait(5000)
        super().done(result)

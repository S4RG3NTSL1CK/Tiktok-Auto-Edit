from PySide6.QtWidgets import (
    QDialog, QFormLayout, QLineEdit, QDialogButtonBox, QLabel, QVBoxLayout, QFileDialog, QHBoxLayout, QPushButton
)

from .. import config
from ..core.tiktok_client import REDIRECT_URI
from .theme import mark_accent, style_dialog


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        style_dialog(self)
        self.setMinimumWidth(420)
        self._cfg = config.load_config()

        layout = QVBoxLayout(self)

        info = QLabel(
            'Get a free Freesound API key at '
            '<a href="https://freesound.org/apiv2/apply/">freesound.org/apiv2/apply</a> '
            "(select \"Client Credentials\" or the default token flow; you only need "
            "the API key, not OAuth). Get a free Jamendo client_id at "
            '<a href="https://devportal.jamendo.com">devportal.jamendo.com</a> '
            "(create an application, copy its Client ID). You only need a key for "
            "whichever provider you plan to use. Get a free AudD API token (300 free "
            'checks) at <a href="https://dashboard.audd.io/">dashboard.audd.io</a> '
            "for the copyright check button."
        )
        info.setOpenExternalLinks(True)
        info.setWordWrap(True)
        layout.addWidget(info)

        form = QFormLayout()
        self.api_key_edit = QLineEdit(self._cfg.get("freesound_api_key", ""))
        self.api_key_edit.setPlaceholderText("Freesound API key")
        form.addRow("Freesound API key:", self.api_key_edit)

        self.jamendo_key_edit = QLineEdit(self._cfg.get("jamendo_api_key", ""))
        self.jamendo_key_edit.setPlaceholderText("Jamendo client_id")
        form.addRow("Jamendo API key:", self.jamendo_key_edit)

        self.audd_key_edit = QLineEdit(self._cfg.get("audd_api_token", ""))
        self.audd_key_edit.setPlaceholderText("AudD API token")
        form.addRow("AudD API token:", self.audd_key_edit)

        tiktok_info = QLabel(
            'Register an app at <a href="https://developers.tiktok.com/apps">'
            "developers.tiktok.com/apps</a>, add the <b>Login Kit</b> and "
            "<b>Content Posting API</b> products, and set the redirect URI to "
            f"exactly:<br><b>{REDIRECT_URI}</b><br>Then paste the Client Key and "
            "Client Secret below. Uploads land as a draft in your TikTok inbox for "
            "you to review — an unaudited app can't post publicly on its own."
        )
        tiktok_info.setOpenExternalLinks(True)
        tiktok_info.setWordWrap(True)
        layout.addWidget(tiktok_info)

        self.tiktok_key_edit = QLineEdit(self._cfg.get("tiktok_client_key", ""))
        self.tiktok_key_edit.setPlaceholderText("TikTok Client Key")
        form.addRow("TikTok Client Key:", self.tiktok_key_edit)

        self.tiktok_secret_edit = QLineEdit(self._cfg.get("tiktok_client_secret", ""))
        self.tiktok_secret_edit.setPlaceholderText("TikTok Client Secret")
        form.addRow("TikTok Client Secret:", self.tiktok_secret_edit)

        output_row = QHBoxLayout()
        self.output_dir_edit = QLineEdit(self._cfg.get("output_dir", ""))
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_output_dir)
        output_row.addWidget(self.output_dir_edit)
        output_row.addWidget(browse_btn)
        form.addRow("Default output folder:", output_row)

        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        mark_accent(buttons.button(QDialogButtonBox.Save))
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _browse_output_dir(self):
        path = QFileDialog.getExistingDirectory(self, "Choose output folder", self.output_dir_edit.text())
        if path:
            self.output_dir_edit.setText(path)

    def _save(self):
        self._cfg["freesound_api_key"] = self.api_key_edit.text().strip()
        self._cfg["jamendo_api_key"] = self.jamendo_key_edit.text().strip()
        self._cfg["audd_api_token"] = self.audd_key_edit.text().strip()
        self._cfg["tiktok_client_key"] = self.tiktok_key_edit.text().strip()
        self._cfg["tiktok_client_secret"] = self.tiktok_secret_edit.text().strip()
        self._cfg["output_dir"] = self.output_dir_edit.text().strip()
        config.save_config(self._cfg)
        self.accept()

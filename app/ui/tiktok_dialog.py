from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QMessageBox

from .. import config
from ..core.tiktok_client import REDIRECT_URI
from .theme import mark_accent, style_dialog
from .workers import TikTokLoginWorker


class TikTokAccountDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("TikTok Account")
        style_dialog(self)
        self.setMinimumWidth(440)
        self.login_worker = None

        layout = QVBoxLayout(self)

        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        info = QLabel(
            "Register a TikTok developer app at "
            '<a href="https://developers.tiktok.com/apps">developers.tiktok.com/apps</a>, '
            "add the Login Kit and Content Posting API products, and set the redirect URI "
            f"to exactly:<br><b>{REDIRECT_URI}</b><br>"
            "Then paste the Client Key and Client Secret in Settings before connecting. "
            "Uploads land as a draft in your TikTok inbox — an unaudited app can't post "
            "publicly on its own, you finish and publish it yourself in the TikTok app."
        )
        info.setOpenExternalLinks(True)
        info.setWordWrap(True)
        layout.addWidget(info)

        btn_row = QHBoxLayout()
        self.connect_btn = QPushButton("Connect TikTok Account")
        mark_accent(self.connect_btn)
        self.connect_btn.clicked.connect(self._connect)
        self.disconnect_btn = QPushButton("Disconnect")
        self.disconnect_btn.clicked.connect(self._disconnect)
        btn_row.addWidget(self.connect_btn)
        btn_row.addWidget(self.disconnect_btn)
        layout.addLayout(btn_row)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)

        self._refresh_status()

    def _refresh_status(self):
        cfg = config.load_config()
        open_id = cfg.get("tiktok_open_id", "")
        if open_id:
            display = cfg.get("tiktok_display_name", "") or open_id
            self.status_label.setText(f"✓ Connected as {display}")
            self.disconnect_btn.setEnabled(True)
        else:
            self.status_label.setText("Not connected.")
            self.disconnect_btn.setEnabled(False)

    def _connect(self):
        cfg = config.load_config()
        client_key = cfg.get("tiktok_client_key", "")
        client_secret = cfg.get("tiktok_client_secret", "")
        if not client_key or not client_secret:
            QMessageBox.warning(
                self, "Missing credentials",
                "Add your TikTok Client Key and Client Secret in Settings first.",
            )
            return
        self.connect_btn.setEnabled(False)
        self.status_label.setText("Opening TikTok login in your browser — complete it there...")
        self.login_worker = TikTokLoginWorker(client_key, client_secret, parent=self)
        self.login_worker.finished_ok.connect(self._on_login_done)
        self.login_worker.failed.connect(self._on_login_failed)
        self.login_worker.start()

    def _on_login_done(self, tokens, display_name: str):
        cfg = config.load_config()
        cfg["tiktok_access_token"] = tokens.access_token
        cfg["tiktok_refresh_token"] = tokens.refresh_token
        cfg["tiktok_open_id"] = tokens.open_id
        cfg["tiktok_token_expires_at"] = tokens.expires_at
        cfg["tiktok_display_name"] = display_name
        config.save_config(cfg)
        self.connect_btn.setEnabled(True)
        self._refresh_status()

    def _on_login_failed(self, message: str):
        self.connect_btn.setEnabled(True)
        self.status_label.setText("Not connected.")
        QMessageBox.warning(self, "TikTok login failed", message)

    def _disconnect(self):
        cfg = config.load_config()
        for key in ("tiktok_access_token", "tiktok_refresh_token", "tiktok_open_id", "tiktok_display_name"):
            cfg[key] = ""
        cfg["tiktok_token_expires_at"] = 0
        config.save_config(cfg)
        self._refresh_status()

    def closeEvent(self, event):
        if self.login_worker is not None and self.login_worker.isRunning():
            QMessageBox.information(
                self, "Login in progress",
                "TikTok login is still waiting for you to finish in your browser (or it will "
                "time out on its own shortly). Please wait for that before closing this window.",
            )
            event.ignore()
            return
        super().closeEvent(event)

import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from app.ui.main_window import MainWindow
from app.ui.theme import apply_theme, asset_path


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Tiktok Auto Edit")
    apply_theme(app)
    icon_path = asset_path("icon.png")
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

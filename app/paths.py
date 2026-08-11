import sys
from pathlib import Path


def base_dir() -> Path:
    # PyInstaller sets sys._MEIPASS to the bundle's data directory when
    # frozen; __file__-based paths aren't reliable there.
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent


def asset_path(*parts) -> Path:
    return base_dir() / "app" / "assets" / Path(*parts)

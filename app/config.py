import json
from pathlib import Path

from platformdirs import user_config_dir, user_documents_dir

APP_NAME = "TiktokAutoEdit"

DEFAULTS = {
    "freesound_api_key": "",
    "jamendo_api_key": "",
    "music_provider": "freesound",
    "output_dir": str(Path(user_documents_dir()) / "TiktokAutoEdit" / "clips"),
    "num_clips": 5,
    "min_len": 15,
    "max_len": 45,
    "aspect": "9:16",
    "music_enabled": True,
    "music_mood": "",
    "music_volume": 0.25,
    "orig_volume": 1.0,
}


def _config_path() -> Path:
    d = Path(user_config_dir(APP_NAME))
    d.mkdir(parents=True, exist_ok=True)
    return d / "config.json"


def load_config() -> dict:
    path = _config_path()
    if not path.exists():
        return dict(DEFAULTS)
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return dict(DEFAULTS)
    merged = dict(DEFAULTS)
    merged.update(data)
    return merged


def save_config(config: dict) -> None:
    path = _config_path()
    merged = dict(DEFAULTS)
    merged.update(config)
    path.write_text(json.dumps(merged, indent=2))


def music_cache_dir() -> Path:
    d = Path(user_config_dir(APP_NAME)) / "music_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d

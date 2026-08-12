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
    "music_tags": "",
    "music_instrumental_only": True,
    "music_energy": "auto",
    "music_volume": 0.25,
    "orig_volume": 1.0,
    "beat_sync_enabled": True,
    "resolution_tier": "1080p",
    "fps_tier": "source",
    "edit_template": "",
    "color_grade": "none",
    "transition_style": "fade",
    "create_highlight_reel": False,
    "transcript_enabled": False,
    "audd_api_token": "",
    "tiktok_client_key": "",
    "tiktok_client_secret": "",
    "tiktok_access_token": "",
    "tiktok_refresh_token": "",
    "tiktok_open_id": "",
    "tiktok_token_expires_at": 0,
    "tiktok_display_name": "",
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


def whisper_model_cache_dir() -> Path:
    d = Path(user_config_dir(APP_NAME)) / "whisper_model_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _update_marker_path() -> Path:
    return Path(user_config_dir(APP_NAME)) / "update_pending.json"


def mark_pending_update(new_version: str) -> None:
    """Called right before launching the silent installer, so the relaunched
    app can confirm the update actually landed instead of just going quiet."""
    _update_marker_path().write_text(json.dumps({"version": new_version}))


def consume_pending_update() -> str:
    """Returns the pending version and clears the marker, or None if there
    wasn't one. Call once at startup."""
    path = _update_marker_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        return data.get("version")
    except (json.JSONDecodeError, OSError):
        return None
    finally:
        path.unlink(missing_ok=True)

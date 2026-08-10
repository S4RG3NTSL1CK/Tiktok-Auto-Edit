import tempfile
from dataclasses import dataclass
from pathlib import Path

import requests

from . import ffmpeg_utils

AUDD_URL = "https://api.audd.io/"


class CopyrightCheckError(RuntimeError):
    pass


@dataclass
class CopyrightMatch:
    title: str
    artist: str
    album: str
    release_date: str
    song_link: str

    def summary(self) -> str:
        parts = [f'"{self.title}" by {self.artist}']
        if self.album:
            parts.append(f"(album: {self.album})")
        if self.release_date:
            parts.append(f"— released {self.release_date}")
        return " ".join(parts)


def _extract_check_audio(clip_path: str, out_path: str) -> None:
    ffmpeg_utils.run_ffmpeg([
        "-i", clip_path,
        "-vn", "-c:a", "libmp3lame", "-b:a", "96k", "-ac", "1",
        out_path,
    ])


def check_copyright(clip_path: str, api_token: str) -> CopyrightMatch:
    """Checks a clip's full audio against AudD's commercial-music fingerprint
    database. Returns a CopyrightMatch if a known commercial track is
    detected, or None if no match. This is a best-effort proxy signal, not a
    guarantee of what TikTok's own (non-public) detection system will do."""
    if not api_token:
        raise CopyrightCheckError("No AudD API token configured. Add one in Settings.")

    with tempfile.TemporaryDirectory(prefix="tiktok_auto_edit_copyright_") as tmp_dir:
        audio_path = str(Path(tmp_dir) / "check.mp3")
        try:
            _extract_check_audio(clip_path, audio_path)
        except ffmpeg_utils.FFmpegError as exc:
            raise CopyrightCheckError(f"Could not extract audio from clip: {exc}") from exc

        with open(audio_path, "rb") as f:
            resp = requests.post(
                AUDD_URL,
                data={"api_token": api_token, "return": "apple_music,spotify"},
                files={"file": f},
                timeout=30,
            )

    if resp.status_code != 200:
        raise CopyrightCheckError(f"AudD request failed: HTTP {resp.status_code}")

    payload = resp.json()
    if payload.get("status") != "success":
        error = payload.get("error", {})
        raise CopyrightCheckError(f"AudD error: {error.get('error_message', 'unknown error')}")

    result = payload.get("result")
    if not result:
        return None

    return CopyrightMatch(
        title=result.get("title", ""),
        artist=result.get("artist", ""),
        album=result.get("album", ""),
        release_date=result.get("release_date", ""),
        song_link=result.get("song_link", ""),
    )

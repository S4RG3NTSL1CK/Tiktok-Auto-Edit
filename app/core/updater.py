import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import requests

GITHUB_REPO = "S4RG3NTSL1CK/Tiktok-Auto-Edit"
RELEASES_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"


@dataclass
class UpdateInfo:
    version: str
    download_url: str
    notes: str


def _parse_version(v: str) -> tuple:
    v = v.strip().lstrip("vV")
    parts = []
    for p in v.split("."):
        digits = "".join(ch for ch in p if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def is_newer(remote_version: str, current_version: str) -> bool:
    return _parse_version(remote_version) > _parse_version(current_version)


def versions_equal(a: str, b: str) -> bool:
    return _parse_version(a) == _parse_version(b)


def check_for_update(current_version: str, timeout: float = 10) -> UpdateInfo:
    """Returns an UpdateInfo if a newer release with a .exe asset exists, else None.
    Never raises: any network/parse failure is treated as "no update available"."""
    try:
        resp = requests.get(RELEASES_API, timeout=timeout)
        if resp.status_code != 200:
            return None
        data = resp.json()
        tag = data.get("tag_name", "")
        if not tag or not is_newer(tag, current_version):
            return None
        asset = next(
            (a for a in data.get("assets", []) if a.get("name", "").lower().endswith(".exe")),
            None,
        )
        if not asset:
            return None
        return UpdateInfo(version=tag, download_url=asset["browser_download_url"], notes=data.get("body") or "")
    except (requests.RequestException, ValueError, KeyError):
        return None


def download_installer(info: UpdateInfo, dest_dir: Path) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    out_path = dest_dir / f"TiktokAutoEdit-Update-{info.version}.exe"
    resp = requests.get(info.download_url, timeout=120, stream=True)
    resp.raise_for_status()
    with open(out_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=1 << 16):
            f.write(chunk)
    return out_path


def launch_installer_and_exit(installer_path: Path) -> None:
    """Launches the downloaded installer in silent mode, detached from this
    process. Caller must quit the application immediately after this returns
    so the installer isn't blocked by files the running app still holds open."""
    if sys.platform != "win32":
        raise RuntimeError("Silent auto-update is only supported on Windows.")
    subprocess.Popen(
        [str(installer_path), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS"],
        close_fds=True,
    )

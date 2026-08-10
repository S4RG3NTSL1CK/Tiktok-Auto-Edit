import random
from dataclasses import dataclass
from pathlib import Path

import requests

FREESOUND_SEARCH_URL = "https://freesound.org/apiv2/search/text/"
JAMENDO_SEARCH_URL = "https://api.jamendo.com/v3.0/tracks/"

MOOD_QUERIES = [
    "upbeat energetic background",
    "chill lofi background",
    "epic cinematic background",
    "corporate motivational background",
    "happy pop background",
    "dramatic trailer background",
]

PROVIDERS = ["freesound", "jamendo"]


class MusicProviderError(RuntimeError):
    pass


@dataclass
class Track:
    id: str
    name: str
    artist: str
    license: str
    duration: float
    preview_url: str
    source: str
    page_url: str

    @property
    def key(self) -> str:
        return f"{self.source}:{self.id}"

    def attribution_line(self) -> str:
        return f'"{self.name}" by {self.artist} — {self.license} — {self.page_url} (via {self.source})'


class FreesoundClient:
    source = "Freesound"

    def __init__(self, api_key: str):
        if not api_key:
            raise MusicProviderError("No Freesound API key configured. Add one in Settings.")
        self.api_key = api_key

    def search(self, query: str, min_duration: float, max_duration: float, page_size: int = 20) -> list:
        filter_str = (
            f'duration:[{max(min_duration - 2, 1):.0f} TO {max_duration + 180:.0f}] '
            f'(license:"Creative Commons 0" OR license:"Attribution")'
        )
        params = {
            "query": query,
            "token": self.api_key,
            "filter": filter_str,
            "fields": "id,name,username,license,duration,previews",
            "sort": "rating_desc",
            "page_size": page_size,
        }
        resp = requests.get(FREESOUND_SEARCH_URL, params=params, timeout=15)
        if resp.status_code == 401:
            raise MusicProviderError("Freesound rejected the API key (401 Unauthorized).")
        if resp.status_code != 200:
            raise MusicProviderError(f"Freesound search failed: HTTP {resp.status_code}")

        results = resp.json().get("results", [])
        tracks = []
        for r in results:
            previews = r.get("previews", {})
            preview_url = previews.get("preview-hq-mp3") or previews.get("preview-lq-mp3")
            if not preview_url:
                continue
            tracks.append(Track(
                id=str(r["id"]),
                name=r["name"],
                artist=r["username"],
                license=_freesound_license(r["license"]),
                duration=r["duration"],
                preview_url=preview_url,
                source=self.source,
                page_url=f"https://freesound.org/people/{r['username']}/sounds/{r['id']}/",
            ))
        return tracks

    def download_preview(self, track: Track, cache_dir: Path) -> Path:
        return _download(track, track.preview_url, cache_dir)


class JamendoClient:
    source = "Jamendo"

    def __init__(self, api_key: str):
        if not api_key:
            raise MusicProviderError("No Jamendo API key configured. Add one in Settings.")
        self.api_key = api_key

    def search(self, query: str, min_duration: float, max_duration: float, page_size: int = 20) -> list:
        params = {
            "client_id": self.api_key,
            "format": "json",
            "search": query,
            "durationbetween": f"{max(int(min_duration - 2), 5)}_{int(max_duration + 180)}",
            "ccnc": "false",
            "ccnd": "false",
            "audioformat": "mp32",
            "order": "popularity_total_desc",
            "limit": page_size,
        }
        resp = requests.get(JAMENDO_SEARCH_URL, params=params, timeout=15)
        if resp.status_code != 200:
            raise MusicProviderError(f"Jamendo search failed: HTTP {resp.status_code}")

        payload = resp.json()
        api_status = payload.get("headers", {}).get("status")
        if api_status != "success":
            error_message = payload.get("headers", {}).get("error_message", "unknown error")
            raise MusicProviderError(f"Jamendo API error: {error_message}")

        results = payload.get("results", [])
        tracks = []
        for r in results:
            license_ccurl = r.get("license_ccurl") or ""
            audio_url = r.get("audio") or ""
            if not license_ccurl or not audio_url:
                continue
            tracks.append(Track(
                id=str(r["id"]),
                name=r["name"],
                artist=r.get("artist_name", "Unknown artist"),
                license=_jamendo_license(license_ccurl),
                duration=float(r.get("duration") or 0),
                preview_url=audio_url,
                source=self.source,
                page_url=r.get("shareurl") or f"https://www.jamendo.com/track/{r['id']}",
            ))
        return tracks

    def download_preview(self, track: Track, cache_dir: Path) -> Path:
        return _download(track, track.preview_url, cache_dir)


def _download(track: Track, url: str, cache_dir: Path) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    out_path = cache_dir / f"{track.source.lower()}_{track.id}.mp3"
    if out_path.exists():
        return out_path
    resp = requests.get(url, timeout=30)
    if resp.status_code != 200:
        raise MusicProviderError(f"Failed to download track {track.key}: HTTP {resp.status_code}")
    out_path.write_bytes(resp.content)
    return out_path


def _freesound_license(url: str) -> str:
    if "zero" in url:
        return "CC0"
    if "by/" in url:
        return "CC-BY"
    return url


def _jamendo_license(ccurl: str) -> str:
    if "publicdomain" in ccurl or "zero" in ccurl:
        return "CC0"
    marker = "/licenses/"
    if marker in ccurl:
        code = ccurl.split(marker, 1)[1].split("/", 1)[0]
        return "CC-" + code.upper()
    return ccurl


def get_client(provider: str, freesound_api_key: str, jamendo_api_key: str):
    if provider == "jamendo":
        return JamendoClient(jamendo_api_key)
    return FreesoundClient(freesound_api_key)


def pick_track(tracks: list, exclude_keys: set) -> Track:
    pool = [t for t in tracks if t.key not in exclude_keys] or tracks
    top = pool[: max(len(pool) // 2, 1)]
    return random.choice(top)


def get_music_for_clip(
    client,
    duration: float,
    cache_dir: Path,
    used_keys: set,
    mood: str = "",
) -> tuple:
    query = mood.strip() or random.choice(MOOD_QUERIES)
    tracks = client.search(query, min_duration=duration, max_duration=max(duration * 4, 60))
    if not tracks:
        tracks = client.search(random.choice(MOOD_QUERIES), min_duration=5, max_duration=600)
    if not tracks:
        raise MusicProviderError(f"No usable tracks found on {client.source} for query '{query}'.")

    track = pick_track(tracks, used_keys)
    used_keys.add(track.key)
    local_path = client.download_preview(track, cache_dir)
    return local_path, track

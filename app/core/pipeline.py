import tempfile
import shutil
from dataclasses import dataclass
from pathlib import Path

from . import ffmpeg_utils
from .audio_energy import compute_energy_curve
from .highlight_selector import select_highlights
from .music_provider import (
    MusicProviderError, MusicSpec, default_cache_dir, get_client, get_music_for_clip,
    pick_local_track, resolve_local_tracks,
)
from .scene_detect import detect_scene_cuts


class PipelineCancelled(Exception):
    pass


@dataclass
class PipelineSettings:
    num_clips: int = 5
    min_len: float = 15
    max_len: float = 45
    aspect: str = "9:16"
    music_enabled: bool = True
    music_tags: str = ""
    music_instrumental_only: bool = True
    music_energy: str = "any"
    music_volume: float = 0.25
    orig_volume: float = 1.0
    output_dir: str = ""
    music_provider: str = "freesound"
    freesound_api_key: str = ""
    jamendo_api_key: str = ""
    music_source: str = "auto"  # "auto" | "manual" | "local"
    manual_track_path: str = ""
    manual_track_attribution: str = ""
    local_music_path: str = ""


@dataclass
class ClipResult:
    path: str
    start: float
    end: float
    track_attribution: str = ""


def _check_cancel(cancel_event):
    if cancel_event is not None and cancel_event.is_set():
        raise PipelineCancelled()


def run_pipeline(video_path: str, settings: PipelineSettings, progress_cb=None, cancel_event=None) -> list:
    def report(pct, msg):
        if progress_cb:
            progress_cb(pct, msg)

    local_tracks = []
    if settings.music_enabled and settings.music_source == "manual":
        if not settings.manual_track_path or not Path(settings.manual_track_path).exists():
            raise RuntimeError(
                "The selected music track is no longer on disk. Re-pick it in the Music Browser."
            )
    elif settings.music_enabled and settings.music_source == "local":
        local_tracks = resolve_local_tracks(settings.local_music_path)
        if not local_tracks:
            raise RuntimeError(
                f"No usable audio files found at '{settings.local_music_path}'. "
                "Pick a local music file or folder in the Music panel."
            )

    report(2, "Probing video...")
    info = ffmpeg_utils.probe_video(video_path)
    _check_cancel(cancel_event)

    tmp_dir = Path(tempfile.mkdtemp(prefix="tiktok_auto_edit_"))
    output_dir = Path(settings.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        report(8, "Extracting audio track...")
        wav_path = tmp_dir / "audio.wav"
        ffmpeg_utils.extract_audio_wav(video_path, str(wav_path))
        _check_cancel(cancel_event)

        report(20, "Analyzing audio energy...")
        times, values = compute_energy_curve(str(wav_path))
        _check_cancel(cancel_event)

        report(32, "Detecting scene changes...")
        scene_cuts = detect_scene_cuts(video_path)
        _check_cancel(cancel_event)

        report(45, "Selecting highlight moments...")
        windows = select_highlights(
            duration=info.duration,
            energy_times=times,
            energy_values=values,
            scene_cuts=scene_cuts,
            min_len=settings.min_len,
            max_len=settings.max_len,
            num_clips=settings.num_clips,
        )
        _check_cancel(cancel_event)

        music_client = None
        if settings.music_enabled and settings.music_source == "auto":
            music_client = get_client(
                settings.music_provider, settings.freesound_api_key, settings.jamendo_api_key,
            )

        cache_dir = default_cache_dir()
        used_track_keys = set()
        used_local_paths = set()
        music_spec = MusicSpec(
            tags=settings.music_tags,
            instrumental_only=settings.music_instrumental_only,
            energy=settings.music_energy,
        )
        results = []
        attributions = []

        total = len(windows)
        for i, window in enumerate(windows):
            _check_cancel(cancel_event)
            base_pct = 50 + int((i / max(total, 1)) * 45)
            report(base_pct, f"Rendering clip {i + 1}/{total}...")

            music_path = None
            attribution_line = ""
            is_local_music = False
            if settings.music_enabled and settings.music_source == "manual":
                music_path = settings.manual_track_path
                attribution_line = settings.manual_track_attribution
            elif settings.music_enabled and settings.music_source == "local":
                track_path = pick_local_track(local_tracks, used_local_paths)
                used_local_paths.add(str(track_path))
                music_path = track_path
                attribution_line = f"Local file: {track_path.name}"
                is_local_music = True
            elif music_client:
                try:
                    music_path, track = get_music_for_clip(
                        music_client, window.duration, cache_dir, used_track_keys, music_spec,
                    )
                    attribution_line = track.attribution_line()
                except MusicProviderError as exc:
                    attribution_line = f"(music skipped for this clip: {exc})"

            out_path = output_dir / f"clip_{i + 1:02d}.mp4"
            ffmpeg_utils.export_clip(
                video_path=video_path,
                output_path=str(out_path),
                start=window.start,
                duration=window.duration,
                width=info.width,
                height=info.height,
                aspect=settings.aspect,
                music_path=str(music_path) if music_path else None,
                music_volume=settings.music_volume,
                orig_volume=settings.orig_volume,
            )

            results.append(ClipResult(
                path=str(out_path),
                start=window.start,
                end=window.end,
                track_attribution=attribution_line,
            ))
            if attribution_line and not is_local_music and not attribution_line.startswith("(music skipped"):
                attributions.append(f"{out_path.name}: {attribution_line}")

        if attributions:
            attributions_path = output_dir / "ATTRIBUTIONS.txt"
            attributions_path.write_text(
                "Keep this file with your clips if any track below requires attribution "
                "(any non-CC0 license).\n\n" + "\n".join(attributions) + "\n"
            )

        report(100, "Done.")
        return results
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

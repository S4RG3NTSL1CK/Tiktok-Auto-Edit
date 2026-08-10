import tempfile
import shutil
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import beat_align, ffmpeg_utils
from .audio_energy import compute_energy_curve, energy_in_range
from .highlight_selector import select_highlights, select_snippet_window
from .motion_energy import compute_motion_curve
from .music_provider import (
    MusicProviderError, MusicSpec, default_cache_dir, get_client, get_music_for_clip,
    pick_local_track, resolve_local_tracks,
)
from .scene_detect import detect_scene_cuts

# How much visual motion counts vs audio energy when scoring moments for
# clip/highlight selection. Audio still leads (a loud exclamation usually IS
# the moment), but this stops a visually dynamic, audio-quiet moment (a
# trick, a fast pan) from being invisible to the scorer just because it's
# quiet. Music-track energy matching stays audio-only on purpose — the
# music should match the clip's actual sound, not its visual busyness.
MOTION_BLEND_WEIGHT = 0.4


class PipelineCancelled(Exception):
    pass


def _bucket_energy(value: float) -> str:
    if value < 0.2:
        return "verylow"
    if value < 0.4:
        return "low"
    if value < 0.6:
        return "medium"
    if value < 0.8:
        return "high"
    return "veryhigh"


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
    beat_sync_enabled: bool = True
    four_k_60fps: bool = False
    create_highlight_reel: bool = False


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

    if settings.four_k_60fps and ffmpeg_utils.is_upscale(info.width, info.height, settings.aspect, True):
        report(3, (
            f"Note: source is {info.width}x{info.height} — after cropping to {settings.aspect}, "
            "4K output will be upscaled, not genuinely higher detail."
        ))

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

        report(28, "Analyzing visual motion...")
        motion_times, motion_values = compute_motion_curve(video_path)
        _check_cancel(cancel_event)

        # Blend audio energy + visual motion onto the audio time grid for
        # scoring — see MOTION_BLEND_WEIGHT above for why.
        motion_resampled = np.interp(times, motion_times, motion_values)
        combined_values = (1 - MOTION_BLEND_WEIGHT) * values + MOTION_BLEND_WEIGHT * motion_resampled

        report(32, "Detecting scene changes...")
        scene_cuts = detect_scene_cuts(video_path)
        _check_cancel(cancel_event)

        report(45, "Selecting highlight moments...")
        windows = select_highlights(
            duration=info.duration,
            energy_times=times,
            energy_values=combined_values,
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
        beat_cache = {}
        results = []
        attributions = []

        def get_beat_grid(music_file_path: str):
            if music_file_path not in beat_cache:
                beat_wav = tmp_dir / f"beatsrc_{len(beat_cache)}.wav"
                try:
                    ffmpeg_utils.extract_audio_wav(music_file_path, str(beat_wav))
                    beat_cache[music_file_path] = beat_align.detect_beats(str(beat_wav))
                except ffmpeg_utils.FFmpegError:
                    beat_cache[music_file_path] = (None, None)
            return beat_cache[music_file_path]

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
                energy = settings.music_energy
                if energy == "auto":
                    mean_energy, _ = energy_in_range(times, values, window.start, window.end)
                    energy = _bucket_energy(mean_energy)
                clip_spec = MusicSpec(
                    tags=settings.music_tags,
                    instrumental_only=settings.music_instrumental_only,
                    energy=energy,
                )
                try:
                    music_path, track = get_music_for_clip(
                        music_client, window.duration, cache_dir, used_track_keys, clip_spec,
                    )
                    attribution_line = track.attribution_line()
                except MusicProviderError as exc:
                    attribution_line = f"(music skipped for this clip: {exc})"

            clip_start, clip_duration = window.start, window.duration
            if settings.beat_sync_enabled and music_path:
                bpm, beat_times = get_beat_grid(str(music_path))
                if beat_times is not None:
                    new_start, new_duration = beat_align.align_window_to_beats(
                        window.start, window.duration, beat_times, settings.min_len, settings.max_len,
                    )
                    new_start = max(0.0, min(new_start, info.duration))
                    new_duration = min(new_duration, info.duration - new_start)
                    if new_duration >= min(settings.min_len, 5.0):
                        clip_start, clip_duration = new_start, new_duration

            out_path = output_dir / f"clip_{i + 1:02d}.mp4"
            ffmpeg_utils.export_clip(
                video_path=video_path,
                output_path=str(out_path),
                start=clip_start,
                duration=clip_duration,
                width=info.width,
                height=info.height,
                aspect=settings.aspect,
                music_path=str(music_path) if music_path else None,
                music_volume=settings.music_volume,
                orig_volume=settings.orig_volume,
                four_k_60fps=settings.four_k_60fps,
            )

            results.append(ClipResult(
                path=str(out_path),
                start=clip_start,
                end=clip_start + clip_duration,
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

        if settings.create_highlight_reel and results:
            report(97, "Pulling highlights for the reel...")
            # Target the reel at the SAME length range as one normal clip,
            # not the sum of every clip — pull a short highlight out of each
            # clip instead of concatenating them whole.
            target_reel_duration = (settings.min_len + settings.max_len) / 2
            per_snippet_duration = max(target_reel_duration / len(results), 1.5)

            snippet_clips = []
            for i, r in enumerate(results):
                snippet_start, snippet_end = select_snippet_window(
                    times, combined_values, r.start, r.end, per_snippet_duration,
                )
                snippet_duration = snippet_end - snippet_start
                rel_start = snippet_start - r.start
                snippet_path = tmp_dir / f"reel_snippet_{i}.mp4"
                ffmpeg_utils.trim_clip(r.path, str(snippet_path), rel_start, snippet_duration)
                snippet_clips.append((str(snippet_path), snippet_duration))

            report(98, "Stitching highlight reel...")
            reel_path = output_dir / "highlight_reel.mp4"
            ffmpeg_utils.stitch_clips_with_crossfade(snippet_clips, str(reel_path))
            reel_duration = sum(d for _, d in snippet_clips) - max(len(snippet_clips) - 1, 0) * 0.4
            results.append(ClipResult(
                path=str(reel_path),
                start=0.0,
                end=reel_duration,
                track_attribution=(
                    f"Highlight reel — best {per_snippet_duration:.1f}s moment from each of "
                    f"{len(snippet_clips)} clips, stitched with crossfades"
                ),
            ))

        report(100, "Done.")
        return results
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

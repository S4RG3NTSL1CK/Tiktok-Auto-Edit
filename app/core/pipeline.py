import tempfile
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import soundfile as sf

from . import beat_align, ffmpeg_utils
from .audio_energy import compute_energy_curve, energy_in_range
from .highlight_selector import select_highlights, select_snippet_window
from .hook_scoring import compute_hook_curve
from .motion_energy import compute_motion_curve
from .smart_crop import find_horizontal_focus_track
from .transcription import TranscriptionError, transcribe_audio
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

# Used instead of the audio/motion-only split above when transcript-based
# hook scoring is enabled and succeeds — a hook line (a question, a strong
# opener) is a real signal a viewer would keep watching for, distinct from
# both loudness and visual motion, so it earns its own share of the score
# rather than just nudging the other two.
AUDIO_WEIGHT_WITH_HOOK = 0.45
MOTION_WEIGHT_WITH_HOOK = 0.30
HOOK_WEIGHT_WITH_HOOK = 0.25


class PipelineCancelled(Exception):
    pass


def _nearest(value: float, candidates) -> float:
    if candidates is None or len(candidates) == 0:
        return value
    return float(candidates[np.argmin(np.abs(candidates - value))])


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
    # 0-based clip index -> explicit track path, only for music_source ==
    # "local" with a folder. A clip index absent from this dict falls back
    # to the existing round-robin pick_local_track behavior.
    local_track_assignments: dict = field(default_factory=dict)
    local_reel_track: str = ""
    beat_sync_enabled: bool = True
    resolution_tier: str = "1080p"  # "source" | "1080p" | "4k"
    fps_tier: str = "source"        # "source" | "30" | "60"
    create_highlight_reel: bool = False
    transcript_enabled: bool = False
    color_grade: str = "none"        # "none" | "cinematic" | "vibrant" | "warm" | "punchy"
    transition_style: str = "fade"   # reel crossfade style, see ffmpeg_utils.VALID_TRANSITION_STYLES


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

    if ffmpeg_utils.is_upscale(info.width, info.height, settings.aspect, settings.resolution_tier):
        report(3, (
            f"Note: source is {info.width}x{info.height} — after cropping to {settings.aspect}, "
            f"{settings.resolution_tier} output will be upscaled, not genuinely higher detail."
        ))
    if ffmpeg_utils.is_fps_upscale(info.fps, settings.fps_tier):
        report(3, (
            f"Note: source is {info.fps:.1f}fps — {settings.fps_tier}fps output will be "
            "frame-duplicated to fill the timeline, not genuinely smoother motion."
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
        motion_resampled = np.interp(times, motion_times, motion_values)

        hook_resampled = None
        if settings.transcript_enabled:
            report(30, "Transcribing speech for hook detection...")
            try:
                segments = transcribe_audio(str(wav_path))
                hook_times, hook_values = compute_hook_curve(segments, info.duration)
                hook_resampled = np.interp(times, hook_times, hook_values)
            except TranscriptionError as exc:
                report(30, f"Transcription skipped ({exc}) — continuing without hook scoring.")
        _check_cancel(cancel_event)

        # Blend audio energy + visual motion (+ speech hook score, if
        # enabled and it succeeded) onto the audio time grid for scoring.
        if hook_resampled is not None:
            combined_values = (
                AUDIO_WEIGHT_WITH_HOOK * values
                + MOTION_WEIGHT_WITH_HOOK * motion_resampled
                + HOOK_WEIGHT_WITH_HOOK * hook_resampled
            )
        else:
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
            # Audio-only (not the blended motion curve) — a natural pause
            # is a quiet SOUND, not a visually-still frame, so the fallback
            # boundary snap should key off what's actually being said/heard.
            quiet_times=times,
            quiet_values=values,
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
        music_analysis_cache = {}
        results = []
        attributions = []

        def get_music_analysis(music_file_path: str):
            """Returns (bpm, beat_times, downbeat_times, energy_times,
            energy_values, track_duration) for a music file, cached by
            path — one audio extraction serves both beat-sync and picking
            the track's own best-matching segment (its own energy curve),
            instead of always starting every track from its beginning."""
            if music_file_path not in music_analysis_cache:
                analysis_wav = tmp_dir / f"musicsrc_{len(music_analysis_cache)}.wav"
                try:
                    ffmpeg_utils.extract_audio_wav(music_file_path, str(analysis_wav))
                    bpm, beat_times, downbeat_times = beat_align.detect_beats(str(analysis_wav))
                    energy_times, energy_values = compute_energy_curve(str(analysis_wav))
                    track_duration = float(sf.info(str(analysis_wav)).duration)
                    music_analysis_cache[music_file_path] = (
                        bpm, beat_times, downbeat_times, energy_times, energy_values, track_duration,
                    )
                except ffmpeg_utils.FFmpegError:
                    music_analysis_cache[music_file_path] = (None, None, None, None, None, 0.0)
            return music_analysis_cache[music_file_path]

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
                assigned = settings.local_track_assignments.get(i)
                track_path = Path(assigned) if assigned else pick_local_track(local_tracks, used_local_paths)
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
            music_start_offset = 0.0
            if music_path:
                bpm, beat_times, downbeat_times, m_times, m_values, track_duration = get_music_analysis(
                    str(music_path)
                )

                # Pick the track's own best-matching (highest-energy)
                # segment for this clip instead of always starting the
                # song from its beginning — reuses the same "best
                # sub-window" search already used to pick video highlights.
                if m_times is not None and track_duration > 0:
                    off_start, _off_end = select_snippet_window(
                        m_times, m_values, 0.0, track_duration, window.duration,
                    )
                    music_start_offset = off_start

                if settings.beat_sync_enabled and beat_times is not None:
                    # Shift the beat grid to be relative to the chosen
                    # segment's start, since that's what will actually play
                    # under the clip — not the track's own beginning.
                    shifted_beats = beat_times[beat_times >= music_start_offset] - music_start_offset
                    shifted_downbeats = None
                    if downbeat_times is not None:
                        shifted_downbeats = (
                            downbeat_times[downbeat_times >= music_start_offset] - music_start_offset
                        )
                    if len(shifted_beats) >= 2:
                        new_start, new_duration = beat_align.align_window_to_beats(
                            window.start, window.duration, shifted_beats, settings.min_len, settings.max_len,
                            downbeat_times=shifted_downbeats,
                        )
                        new_start = max(0.0, min(new_start, info.duration))
                        new_duration = min(new_duration, info.duration - new_start)
                        if new_duration >= min(settings.min_len, 5.0):
                            clip_start, clip_duration = new_start, new_duration

                # Safety clamp: beat-sync may have changed clip_duration
                # after the segment was picked — make sure the trimmed
                # segment still has enough track left from the chosen
                # offset to cover the final duration.
                if track_duration > 0:
                    music_start_offset = min(music_start_offset, max(track_duration - clip_duration, 0.0))

            # Face-aware crop focus: where to center the vertical/square crop
            # horizontally instead of always centering on the full frame.
            # Time-varying (not a single static offset) so the crop pans to
            # follow the subject on longer/high-motion clips instead of
            # drifting off them partway through. No-op for aspect="original"
            # (no horizontal crop happens then), so skip the sampling work.
            focus_x = 0.5
            if settings.aspect != "original":
                focus_x = find_horizontal_focus_track(video_path, clip_start, clip_start + clip_duration)

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
                resolution_tier=settings.resolution_tier,
                fps_tier=settings.fps_tier,
                focus_x=focus_x,
                color_grade=settings.color_grade,
                music_start_offset=music_start_offset,
            )

            results.append(ClipResult(
                path=str(out_path),
                start=clip_start,
                end=clip_start + clip_duration,
                track_attribution=attribution_line,
            ))
            if attribution_line and not is_local_music and not attribution_line.startswith("(music skipped"):
                attributions.append(f"{out_path.name}: {attribution_line}")

        if settings.create_highlight_reel and results:
            report(97, "Pulling highlights for the reel...")
            # Target the reel at the SAME length range as one normal clip,
            # not the sum of every clip — pull a short highlight out of each
            # clip instead of concatenating them whole.
            target_reel_duration = (settings.min_len + settings.max_len) / 2
            per_snippet_duration = max(target_reel_duration / len(results), 1.5)

            # Music is picked (and its beat grid detected) BEFORE snippets
            # are built, so snippet durations can be tuned to land the
            # crossfade cuts on the beat — previously snippets were chosen
            # purely by content energy with zero relationship to the music
            # laid under the reel.
            reel_music_path = None
            reel_attribution = ""
            if settings.music_enabled and settings.music_source == "manual":
                reel_music_path = settings.manual_track_path
                reel_attribution = settings.manual_track_attribution
            elif settings.music_enabled and settings.music_source == "local" and local_tracks:
                track_path = (
                    Path(settings.local_reel_track) if settings.local_reel_track
                    else pick_local_track(local_tracks, set())
                )
                reel_music_path = track_path
                reel_attribution = f"Local file: {track_path.name}"
            elif settings.music_enabled and settings.music_source == "auto" and music_client:
                try:
                    reel_music_path, track = get_music_for_clip(
                        music_client, target_reel_duration, cache_dir, set(), MusicSpec(
                            tags=settings.music_tags,
                            instrumental_only=settings.music_instrumental_only,
                            # "auto" means per-clip energy-matching, which
                            # doesn't cleanly apply to one track spanning
                            # several different highlights' energy levels.
                            energy=settings.music_energy if settings.music_energy != "auto" else "any",
                        ),
                    )
                    reel_attribution = track.attribution_line()
                except MusicProviderError as exc:
                    reel_attribution = f"(music skipped for reel: {exc})"

            reel_beat_times, reel_downbeat_times = None, None
            reel_music_start_offset = 0.0
            reel_track_duration = 0.0
            if reel_music_path:
                _, reel_beat_times, reel_downbeat_times, r_times, r_values, reel_track_duration = (
                    get_music_analysis(str(reel_music_path))
                )
                # Best-matching (highest-energy) segment of the track for
                # the whole reel, instead of always starting at its
                # beginning.
                if r_times is not None and reel_track_duration > 0:
                    off_start, _off_end = select_snippet_window(
                        r_times, r_values, 0.0, reel_track_duration, target_reel_duration,
                    )
                    reel_music_start_offset = off_start
                if not settings.beat_sync_enabled:
                    reel_beat_times, reel_downbeat_times = None, None

            # Downbeats read as more intentional cut points than any beat;
            # use them when available, otherwise any detected beat. Shifted
            # to be relative to the chosen segment's start, since that's
            # what will actually play under the reel.
            cut_targets = (
                reel_downbeat_times if reel_downbeat_times is not None and len(reel_downbeat_times) > 0
                else reel_beat_times
            )
            if cut_targets is not None and len(cut_targets) > 0:
                cut_targets = cut_targets[cut_targets >= reel_music_start_offset] - reel_music_start_offset

            xfade_dur = 0.4  # matches stitch_clips_with_crossfade's default
            snippet_clips = []
            cumulative_end = 0.0
            for i, r in enumerate(results):
                planned_duration = per_snippet_duration
                if cut_targets is not None and len(cut_targets) > 0:
                    prior_xfade = xfade_dur if i > 0 else 0.0
                    target_cumulative = cumulative_end + per_snippet_duration - prior_xfade
                    aligned_cumulative = _nearest(target_cumulative, cut_targets)
                    candidate_duration = aligned_cumulative - cumulative_end + prior_xfade
                    # Keep within a sane range of the natural target so a
                    # sparse beat grid can't produce a degenerate snippet.
                    lo, hi = per_snippet_duration * 0.5, per_snippet_duration * 1.6
                    if lo <= candidate_duration <= hi:
                        planned_duration = candidate_duration

                snippet_start, snippet_end = select_snippet_window(
                    times, combined_values, r.start, r.end, planned_duration,
                )
                snippet_duration = snippet_end - snippet_start
                cumulative_end += snippet_duration - (xfade_dur if i > 0 else 0.0)

                # Extracted straight from the ORIGINAL source, not the
                # already-rendered clip: each clip's own music is already
                # mixed into its file, so trimming from that would carry a
                # different track into each segment of the reel. One track
                # gets mixed once over the whole assembled reel below
                # instead, so it doesn't change at every cut.
                snippet_focus_x = 0.5
                if settings.aspect != "original":
                    snippet_focus_x = find_horizontal_focus_track(video_path, snippet_start, snippet_end)
                snippet_path = tmp_dir / f"reel_snippet_{i}.mp4"
                ffmpeg_utils.export_clip(
                    video_path=video_path,
                    output_path=str(snippet_path),
                    start=snippet_start,
                    duration=snippet_duration,
                    width=info.width,
                    height=info.height,
                    aspect=settings.aspect,
                    music_path=None,
                    resolution_tier=settings.resolution_tier,
                    fps_tier=settings.fps_tier,
                    focus_x=snippet_focus_x,
                    color_grade=settings.color_grade,
                )
                snippet_clips.append((str(snippet_path), snippet_duration))

            report(98, "Stitching highlight reel...")
            reel_video_path = tmp_dir / "reel_no_music.mp4"
            ffmpeg_utils.stitch_clips_with_crossfade(
                snippet_clips, str(reel_video_path), transition_duration=xfade_dur,
                transition_style=settings.transition_style,
            )
            reel_duration = sum(d for _, d in snippet_clips) - max(len(snippet_clips) - 1, 0) * xfade_dur

            # Safety clamp: the snippet durations actually built may differ
            # slightly from target_reel_duration — make sure the chosen
            # segment still has enough track left from its offset to cover
            # the final reel length.
            if reel_track_duration > 0:
                reel_music_start_offset = min(
                    reel_music_start_offset, max(reel_track_duration - reel_duration, 0.0)
                )

            report(99, "Mixing reel music...")
            reel_path = output_dir / "highlight_reel.mp4"
            if reel_music_path:
                ffmpeg_utils.mix_music_over_video(
                    str(reel_video_path), str(reel_music_path), str(reel_path),
                    duration=reel_duration,
                    music_volume=settings.music_volume, orig_volume=settings.orig_volume,
                    music_start_offset=reel_music_start_offset,
                )
                is_local_reel_track = settings.music_source == "local"
                if reel_attribution and not is_local_reel_track and not reel_attribution.startswith("(music skipped"):
                    attributions.append(f"{reel_path.name}: {reel_attribution}")
            else:
                shutil.copy(str(reel_video_path), str(reel_path))

            results.append(ClipResult(
                path=str(reel_path),
                start=0.0,
                end=reel_duration,
                track_attribution=(
                    f"Highlight reel — best {per_snippet_duration:.1f}s moment from each of "
                    f"{len(snippet_clips)} clips, stitched with crossfades"
                    + (f", one track throughout: {reel_attribution}" if reel_music_path else "")
                    + (", cuts synced to the beat" if cut_targets is not None and len(cut_targets) > 0 else "")
                ),
            ))

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

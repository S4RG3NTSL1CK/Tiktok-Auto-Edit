import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import cv2
import imageio_ffmpeg

# ffmpeg.exe is a console app; spawning it from the windowed (console=False)
# PyInstaller build still briefly flashes a console window per invocation
# unless this flag is set — run_ffmpeg is called once per clip, per reel
# snippet, per beat-detection extraction, so without it a batch run flashes
# a window over and over throughout generation. No-op / doesn't exist on
# non-Windows platforms.
_SUBPROCESS_FLAGS = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


class FFmpegError(RuntimeError):
    pass


# preset "fast" + crf 18 (vs the old "veryfast"/20): meaningfully better
# quality-per-bitrate from libx264 at a modest, worthwhile render-time cost
# for clips this short.
VIDEO_CODEC_ARGS = ["-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p"]
AUDIO_CODEC_ARGS = ["-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2"]


def ffmpeg_exe() -> str:
    return imageio_ffmpeg.get_ffmpeg_exe()


def run_ffmpeg(args: list) -> None:
    cmd = [ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error"] + args
    result = subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        creationflags=_SUBPROCESS_FLAGS,
    )
    if result.returncode != 0:
        raise FFmpegError(result.stderr.strip() or "ffmpeg failed with no stderr output")


@dataclass
class VideoInfo:
    width: int
    height: int
    fps: float
    duration: float


def probe_video(path: str) -> VideoInfo:
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise FFmpegError(f"Could not open video file: {path}")
    try:
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = frame_count / fps if fps > 0 else 0.0
    finally:
        cap.release()
    if width <= 0 or height <= 0 or duration <= 0:
        raise FFmpegError(f"Could not read valid video metadata from: {path}")
    return VideoInfo(width=width, height=height, fps=fps, duration=duration)


def extract_audio_wav(video_path: str, out_wav_path: str, sample_rate: int = 22050) -> None:
    run_ffmpeg([
        "-i", video_path,
        "-vn", "-ac", "1", "-ar", str(sample_rate),
        "-f", "wav", out_wav_path,
    ])


def crop_dimensions_for_aspect(width: int, height: int, aspect: str):
    """Returns (crop_w, crop_h) — the frame size after cropping to `aspect`,
    before any scaling. `aspect == "original"` returns the source size
    unchanged (no crop applied)."""
    if aspect == "original":
        return width, height
    target_ratio = 9 / 16 if aspect == "9:16" else 1.0
    current_ratio = width / height
    if current_ratio > target_ratio:
        new_w = int(round(height * target_ratio))
        new_w -= new_w % 2
        return new_w, height
    else:
        new_h = int(round(width / target_ratio))
        new_h -= new_h % 2
        return width, new_h


def _dynamic_crop_x_expr(track: list, width: int, crop_w: int) -> str:
    """Builds an ffmpeg filter expression for the crop filter's `x`, given
    `track` = [(t, focus_x), ...] (t in seconds, relative to the clip's own
    start — matches ffmpeg's `t` after input-side -ss rebases PTS to ~0).
    Piecewise-linear interpolation between samples; holds the last value
    beyond the final sample. A single-sample track collapses to a constant.
    """
    points = [
        (t, int(max(0, min(fx * width - crop_w / 2, width - crop_w))))
        for t, fx in track
    ]
    if len(points) == 1:
        return str(points[0][1])

    expr = str(points[-1][1])
    for i in range(len(points) - 2, -1, -1):
        t0, x0 = points[i]
        t1, x1 = points[i + 1]
        if t1 <= t0:
            continue
        lerp = f"({x0}+({x1}-{x0})*(t-{t0:.3f})/{(t1 - t0):.3f})"
        expr = f"if(lt(t,{t1:.3f}),{lerp},{expr})"
    return expr


def crop_filter_for_aspect(width: int, height: int, aspect: str, focus_x=0.5):
    """`focus_x` is either a plain 0..1 fraction of width (static center),
    or a time-varying track [(t, focus_x), ...] from
    smart_crop.find_horizontal_focus_track — a single static offset holds
    up poorly on longer/high-motion clips where the subject moves around
    during the clip, so the crop x position pans smoothly to follow it
    instead of staying fixed. Clamped so the crop window never runs off
    either edge. Defaults to plain center."""
    if aspect == "original":
        return None
    crop_w, crop_h = crop_dimensions_for_aspect(width, height, aspect)
    y = (height - crop_h) // 2

    if isinstance(focus_x, (list, tuple)):
        # crop is joined with other filters via top-level commas in
        # export_clip (crop=...,scale=...,setsar=1) — the if(...) expression
        # has its own internal commas that must be escaped, or ffmpeg reads
        # them as filter-chain separators and corrupts the whole chain.
        x = _dynamic_crop_x_expr(focus_x, width, crop_w).replace(",", "\\,")
    else:
        ideal_x = focus_x * width - crop_w / 2
        x = int(max(0, min(ideal_x, width - crop_w)))
    return f"crop={crop_w}:{crop_h}:{x}:{y}"


def scale_target_for_aspect(aspect: str, width: int, height: int, four_k: bool = False) -> str:
    # Lanczos explicitly: sharper than ffmpeg's default scaling algorithm,
    # especially noticeable on the downscales most clips actually do.
    flags = ":flags=lanczos"
    if aspect == "9:16":
        return ("scale=2160:3840" if four_k else "scale=1080:1920") + flags
    if aspect == "1:1":
        return ("scale=2160:2160" if four_k else "scale=1080:1080") + flags
    # original: preserve source aspect ratio, just cap the long edge
    if not four_k:
        return "scale=trunc(iw/2)*2:trunc(ih/2)*2" + flags
    return ("scale=3840:-2" if width >= height else "scale=-2:3840") + flags


def is_upscale(width: int, height: int, aspect: str, four_k: bool) -> bool:
    """True if a four_k export would be stretching source pixels rather than
    reflecting genuine source detail — i.e. the cropped source is smaller
    than the 4K target in its shorter dimension."""
    if not four_k:
        return False
    crop_w, crop_h = crop_dimensions_for_aspect(width, height, aspect)
    return min(crop_w, crop_h) < 2160


def export_clip(
    video_path: str,
    output_path: str,
    start: float,
    duration: float,
    width: int,
    height: int,
    aspect: str,
    music_path: str = None,
    music_volume: float = 0.25,
    orig_volume: float = 1.0,
    four_k_60fps: bool = False,
    focus_x=0.5,
) -> None:
    crop = crop_filter_for_aspect(width, height, aspect, focus_x)
    scale = scale_target_for_aspect(aspect, width, height, four_k_60fps)
    filters = [f for f in (crop, scale, "setsar=1") if f]
    if four_k_60fps:
        filters.append("fps=60")
    video_chain = f"[0:v]{','.join(filters)}[v]"

    args = ["-ss", f"{start:.3f}", "-t", f"{duration:.3f}", "-i", video_path]

    if music_path:
        args += ["-i", music_path]
        fade_start = max(duration - 1.0, 0.0)
        filter_complex = (
            f"{video_chain};"
            f"[0:a]volume={orig_volume}[oa];"
            f"[1:a]atrim=0:{duration:.3f},asetpts=PTS-STARTPTS,"
            f"afade=t=out:st={fade_start:.3f}:d=1,volume={music_volume}[ma];"
            f"[oa][ma]amix=inputs=2:duration=first:dropout_transition=1,"
            f"loudnorm=I=-14:TP=-1.5:LRA=11[a]"
        )
        args += [
            "-filter_complex", filter_complex,
            "-map", "[v]", "-map", "[a]",
        ]
    else:
        args += [
            "-filter_complex", video_chain,
            "-map", "[v]", "-map", "0:a?",
        ]

    args += VIDEO_CODEC_ARGS + AUDIO_CODEC_ARGS + ["-movflags", "+faststart", output_path]
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(args)


def mix_music_over_video(
    video_path: str,
    music_path: str,
    output_path: str,
    duration: float,
    music_volume: float = 0.25,
    orig_volume: float = 1.0,
) -> None:
    """Mixes ONE music track over an already-assembled video's full
    duration (used for the highlight reel, so the whole thing plays one
    continuous track instead of switching songs at every snippet cut).
    Video stream is copied through untouched — only audio is touched, so
    this doesn't re-encode/re-crop video that's already in its final form.
    Assumes `music_path` is at least `duration` seconds; callers search for
    a track with that minimum (e.g. get_music_for_clip)."""
    fade_start = max(duration - 1.5, 0.0)
    filter_complex = (
        f"[0:a]volume={orig_volume}[oa];"
        f"[1:a]atrim=0:{duration:.3f},asetpts=PTS-STARTPTS,"
        f"afade=t=out:st={fade_start:.3f}:d=1.5,volume={music_volume}[ma];"
        f"[oa][ma]amix=inputs=2:duration=first:dropout_transition=1,"
        f"loudnorm=I=-14:TP=-1.5:LRA=11[a]"
    )
    args = [
        "-i", video_path, "-i", music_path,
        "-filter_complex", filter_complex,
        "-map", "0:v", "-map", "[a]",
        "-c:v", "copy",
    ] + AUDIO_CODEC_ARGS + ["-movflags", "+faststart", output_path]
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(args)


def stitch_clips_with_crossfade(clips: list, output_path: str, transition_duration: float = 0.4) -> None:
    """Concatenates already-rendered clips (same resolution/fps/audio format,
    as produced by export_clip) into one video, crossfading video and audio
    at each join instead of hard-cutting. `clips` is a list of
    (path: str, duration: float)."""
    if not clips:
        raise ValueError("No clips to stitch")

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    if len(clips) == 1:
        run_ffmpeg(["-i", clips[0][0], "-c", "copy", "-movflags", "+faststart", output_path])
        return

    xfade_dur = min(transition_duration, max(min(d for _, d in clips) / 2, 0.1))

    args = []
    for path, _ in clips:
        args += ["-i", path]

    filter_parts = []
    v_label, a_label = "0:v", "0:a"
    cumulative = clips[0][1]
    for i in range(1, len(clips)):
        offset = cumulative - xfade_dur
        next_v, next_a = f"v{i}", f"a{i}"
        filter_parts.append(
            f"[{v_label}][{i}:v]xfade=transition=fade:duration={xfade_dur:.3f}:offset={offset:.3f}[{next_v}]"
        )
        filter_parts.append(f"[{a_label}][{i}:a]acrossfade=d={xfade_dur:.3f}[{next_a}]")
        v_label, a_label = next_v, next_a
        cumulative += clips[i][1] - xfade_dur

    args += [
        "-filter_complex", ";".join(filter_parts),
        "-map", f"[{v_label}]", "-map", f"[{a_label}]",
    ] + VIDEO_CODEC_ARGS + AUDIO_CODEC_ARGS + ["-movflags", "+faststart", output_path]
    run_ffmpeg(args)

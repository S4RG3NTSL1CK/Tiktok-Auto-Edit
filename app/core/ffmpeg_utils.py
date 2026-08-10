import subprocess
from dataclasses import dataclass
from pathlib import Path

import cv2
import imageio_ffmpeg


class FFmpegError(RuntimeError):
    pass


def ffmpeg_exe() -> str:
    return imageio_ffmpeg.get_ffmpeg_exe()


def run_ffmpeg(args: list) -> None:
    cmd = [ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error"] + args
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
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


def crop_filter_for_aspect(width: int, height: int, aspect: str):
    if aspect == "original":
        return None
    target_ratio = 9 / 16 if aspect == "9:16" else 1.0
    current_ratio = width / height
    if current_ratio > target_ratio:
        new_w = int(round(height * target_ratio))
        new_w -= new_w % 2
        x = (width - new_w) // 2
        return f"crop={new_w}:{height}:{x}:0"
    else:
        new_h = int(round(width / target_ratio))
        new_h -= new_h % 2
        y = (height - new_h) // 2
        return f"crop={width}:{new_h}:0:{y}"


def scale_target_for_aspect(aspect: str) -> str:
    if aspect == "9:16":
        return "scale=1080:1920"
    if aspect == "1:1":
        return "scale=1080:1080"
    return "scale=trunc(iw/2)*2:trunc(ih/2)*2"


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
) -> None:
    crop = crop_filter_for_aspect(width, height, aspect)
    scale = scale_target_for_aspect(aspect)
    video_chain = f"[0:v]{crop},{scale},setsar=1[v]" if crop else f"[0:v]{scale},setsar=1[v]"

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

    args += [
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        output_path,
    ]
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(args)

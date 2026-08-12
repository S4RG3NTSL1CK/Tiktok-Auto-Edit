import cv2
import numpy as np

from ..paths import asset_path

_MODEL_PATH = str(asset_path("face_detection_yunet.onnx"))
_detector = None


def _get_detector():
    global _detector
    if _detector is None:
        _detector = cv2.FaceDetectorYN.create(_MODEL_PATH, "", (320, 320), 0.7, 0.3, 5000)
    return _detector


def _detect_face_center_x(frame) -> float:
    """Horizontal center (0..1 fraction of width) of the most confident face
    in `frame`, or None if no face is found."""
    detector = _get_detector()
    h, w = frame.shape[:2]
    detector.setInputSize((w, h))
    _, faces = detector.detect(frame)
    if faces is None or len(faces) == 0:
        return None
    best = max(faces, key=lambda f: f[14])
    face_center_x = best[0] + best[2] / 2.0
    return float(np.clip(face_center_x / w, 0.0, 1.0))


def _motion_center_x(gray_frames: list) -> float:
    """Fallback saliency when no face is found: horizontal center of visual
    motion across a sequence of already-downscaled grayscale frames."""
    if len(gray_frames) < 2:
        return 0.5
    total_diff = np.zeros_like(gray_frames[0], dtype=np.float32)
    for i in range(1, len(gray_frames)):
        total_diff += np.abs(gray_frames[i].astype(np.float32) - gray_frames[i - 1].astype(np.float32))
    col_sums = total_diff.sum(axis=0)
    if col_sums.sum() <= 0:
        return 0.5
    col_indices = np.arange(len(col_sums))
    weighted_center = float(np.sum(col_indices * col_sums) / np.sum(col_sums))
    return weighted_center / len(col_sums)


def find_horizontal_focus_track(video_path: str, start: float, end: float, sample_interval: float = 2.5) -> list:
    """Returns [(t_relative_to_start, focus_x), ...] tracking where the
    subject/action is horizontally, sampled roughly every `sample_interval`
    seconds across [start, end] — NOT a single static value for the whole
    clip. A fixed offset falls apart on longer or high-motion clips (a
    60s boss fight where the subject moves all over the frame): confirmed
    by reviewing real output where a single-offset crop clearly drifted off
    the action partway through a long clip. `t_relative_to_start` is
    0-based (0 at `start`) to match ffmpeg's `t` inside a filter graph
    after input-side `-ss` trimming, which rebases PTS to ~0.

    Per sample: detected face position (YuNet) first, else a short local
    motion estimate (two nearby frames, not the whole clip), else the
    previous sample's value for continuity, else 0.5 center as the final
    fallback. Light exponential smoothing is applied across the resulting
    sequence so the crop pans rather than snaps between samples.
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return [(0.0, 0.5)]
    try:
        duration = max(end - start, 0.1)
        num_samples = max(int(duration / sample_interval), 1) + 1
        sample_rel_times = np.linspace(0, duration, num_samples)

        track = []
        prev_fx = None
        for t_rel in sample_rel_times:
            t_abs = start + t_rel
            cap.set(cv2.CAP_PROP_POS_MSEC, t_abs * 1000)
            ok, frame = cap.read()
            if not ok:
                fx = prev_fx if prev_fx is not None else 0.5
                track.append((float(t_rel), fx))
                continue

            fx = _detect_face_center_x(frame)
            if fx is None:
                cap.set(cv2.CAP_PROP_POS_MSEC, max(t_abs - 0.2, start) * 1000)
                ok2, frame2 = cap.read()
                if ok2:
                    small1 = cv2.resize(frame, (160, 90), interpolation=cv2.INTER_AREA)
                    small2 = cv2.resize(frame2, (160, 90), interpolation=cv2.INTER_AREA)
                    gray1 = cv2.cvtColor(small1, cv2.COLOR_BGR2GRAY)
                    gray2 = cv2.cvtColor(small2, cv2.COLOR_BGR2GRAY)
                    motion_fx = _motion_center_x([gray2, gray1])
                    fx = motion_fx if motion_fx != 0.5 else None
            if fx is None:
                fx = prev_fx if prev_fx is not None else 0.5

            track.append((float(t_rel), fx))
            prev_fx = fx

        if not track:
            return [(0.0, 0.5)]

        alpha = 0.35
        smoothed_xs = [track[0][1]]
        for _, fx in track[1:]:
            smoothed_xs.append(alpha * fx + (1 - alpha) * smoothed_xs[-1])
        return [(t, fx) for (t, _), fx in zip(track, smoothed_xs)]
    finally:
        cap.release()

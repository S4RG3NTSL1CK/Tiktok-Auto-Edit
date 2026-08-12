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


# Hard ceiling on how far the crop is ever allowed to move from dead
# center (as a fraction of frame width), applied as the very last step
# no matter which code path produced the value. Exists because damping
# alone still lets a sustained, confident off-center signal pull the
# result fairly far from center over time, and the no-face motion
# fallback previously had no centering bias applied to it at all —
# confirmed as the actual cause of clips still coming out uncentered
# after the smoothing/damping fix. This clamp makes a dramatically
# off-center result impossible regardless of what any signal says.
MAX_CENTER_DEVIATION = 0.12


def _clamp_to_center(fx: float) -> float:
    return float(np.clip(fx, 0.5 - MAX_CENTER_DEVIATION, 0.5 + MAX_CENTER_DEVIATION))


def find_horizontal_focus_track(video_path: str, start: float, end: float, sample_interval: float = 2.5) -> list:
    """Returns [(t_relative_to_start, focus_x), ...] tracking where the
    subject is horizontally, sampled roughly every `sample_interval`
    seconds across [start, end]. `t_relative_to_start` is 0-based (0 at
    `start`) to match ffmpeg's `t` inside a filter graph after input-side
    `-ss` trimming, which rebases PTS to ~0.

    Strongly biased to stay centered — only a real, confident face
    detection can move the crop off-center; per-sample motion/frame-diff
    was removed as a per-sample signal after confirming it caused visible
    unwanted sway on real footage (action-game VFX/particles/screen shake
    all register as "motion" with no relation to where the actual subject
    is, so chasing it per-sample looked like drifting/swaying rather than
    tracking). A sample with no face decays back toward center rather than
    holding an old off-center position indefinitely. The whole sequence is
    then heavily smoothed and damped toward center, and every value —
    including the no-face-anywhere fallback below — is hard-clamped to
    MAX_CENTER_DEVIATION of center as a final guarantee.

    If NO face is found anywhere in the whole clip (pure b-roll, no
    people), falls back to a single static motion-weighted estimate for
    the entire clip instead of time-varying — faceless content doesn't
    have a "subject" to chase, so a stable single crop is more appropriate
    than time-varying noise. That estimate gets the same centering clamp
    as everything else, since raw motion saliency has no reason to be
    anywhere near center on its own.
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return [(0.0, 0.5)]
    try:
        duration = max(end - start, 0.1)
        num_samples = max(int(duration / sample_interval), 1) + 1
        sample_rel_times = np.linspace(0, duration, num_samples)

        raw_track = []
        gray_frames = []
        prev_fx = 0.5
        any_face_found = False
        for t_rel in sample_rel_times:
            t_abs = start + t_rel
            cap.set(cv2.CAP_PROP_POS_MSEC, t_abs * 1000)
            ok, frame = cap.read()
            if not ok:
                raw_track.append((float(t_rel), prev_fx))
                continue

            face_fx = _detect_face_center_x(frame)
            small = cv2.resize(frame, (160, 90), interpolation=cv2.INTER_AREA)
            gray_frames.append(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY))

            if face_fx is not None:
                any_face_found = True
                fx = face_fx
            else:
                # No face this sample: drift back toward center instead of
                # chasing motion/visual noise.
                fx = prev_fx + (0.5 - prev_fx) * 0.3

            raw_track.append((float(t_rel), fx))
            prev_fx = fx

        if not raw_track:
            return [(0.0, 0.5)]

        if not any_face_found:
            return [(0.0, _clamp_to_center(_motion_center_x(gray_frames)))]

        # Heavy smoothing + damping toward center: a strong bias toward
        # staying centered that only drifts for a sustained, confident
        # reason, not single-sample noise. Seeded at 0.5 (not the raw
        # first sample) so even an early off-center face detection gets
        # pulled through the same smoothing as everything else, rather
        # than anchoring the whole sequence's starting point.
        alpha = 0.12
        damping = 0.5
        smoothed = [0.5]
        for _, fx in raw_track:
            smoothed.append(alpha * fx + (1 - alpha) * smoothed[-1])
        smoothed = smoothed[1:]
        damped = [_clamp_to_center(0.5 + (v - 0.5) * damping) for v in smoothed]

        return [(t, fx) for (t, _), fx in zip(raw_track, damped)]
    finally:
        cap.release()

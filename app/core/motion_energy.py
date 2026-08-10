import cv2
import numpy as np


def compute_motion_curve(video_path: str, window_sec: float = 0.5, sample_fps: float = 4.0):
    """Visual motion energy over time: mean frame-to-frame pixel difference
    of downscaled, grayscale sampled frames, bucketed into `window_sec`
    windows and peak-normalized to 0..1 — same shape/contract as
    audio_energy.compute_energy_curve so the two can be combined directly.

    Catches a real gap in audio-only highlight scoring: a visually dynamic
    moment with quiet audio (a trick, a fast pan, motion without a loud
    sound) would otherwise score low and get skipped.

    Samples via VideoCapture.grab() (cheap, no decode) for skipped frames
    and only retrieve()s + processes every Nth frame, so this stays fast
    even on a long source video.
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return np.array([0.0]), np.array([0.0])

    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = frame_count / fps if fps > 0 else 0.0
        if duration <= 0:
            return np.array([0.0]), np.array([0.0])

        sample_interval = max(int(round(fps / sample_fps)), 1)

        prev_gray = None
        sample_times = []
        sample_diffs = []
        frame_idx = 0
        while True:
            if not cap.grab():
                break
            if frame_idx % sample_interval == 0:
                ok, frame = cap.retrieve()
                if not ok:
                    break
                small = cv2.resize(frame, (160, 90), interpolation=cv2.INTER_AREA)
                gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY).astype(np.float32)
                if prev_gray is not None:
                    sample_times.append(frame_idx / fps)
                    sample_diffs.append(float(np.mean(np.abs(gray - prev_gray))))
                prev_gray = gray
            frame_idx += 1
    finally:
        cap.release()

    if not sample_diffs:
        return np.array([0.0]), np.array([0.0])

    sample_times = np.array(sample_times)
    sample_diffs = np.array(sample_diffs)

    num_windows = max(int(duration / window_sec), 1)
    bin_times = np.arange(num_windows) * window_sec
    bin_values = np.zeros(num_windows)
    for i in range(num_windows):
        mask = (sample_times >= i * window_sec) & (sample_times < (i + 1) * window_sec)
        if mask.any():
            bin_values[i] = sample_diffs[mask].mean()

    peak = bin_values.max()
    if peak > 0:
        bin_values = bin_values / peak

    return bin_times, bin_values

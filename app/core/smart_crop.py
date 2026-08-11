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


def find_horizontal_focus(video_path: str, start: float, end: float, sample_count: int = 8) -> float:
    """Returns a 0..1 fraction of frame width for where the subject/action
    is horizontally within [start, end] — used to offset a vertical/square
    crop instead of always centering it.

    Priority: detected face position (YuNet DNN, MIT-licensed bundled
    model) if at least one sample has a face, else a motion-weighted
    saliency fallback (extends the frame-diff approach from
    motion_energy.py to track horizontal concentration, not just
    magnitude), else 0.5 (plain center) as the safe default.
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return 0.5
    try:
        duration = max(end - start, 0.1)
        sample_times = np.linspace(start, end, sample_count, endpoint=False) + duration / (2 * sample_count)

        face_centers = []
        gray_frames = []
        for t in sample_times:
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
            ok, frame = cap.read()
            if not ok:
                continue
            face_x = _detect_face_center_x(frame)
            if face_x is not None:
                face_centers.append(face_x)
            small = cv2.resize(frame, (160, 90), interpolation=cv2.INTER_AREA)
            gray_frames.append(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY))

        if face_centers:
            return float(np.median(face_centers))
        if gray_frames:
            return _motion_center_x(gray_frames)
        return 0.5
    finally:
        cap.release()

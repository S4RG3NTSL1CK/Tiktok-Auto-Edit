import numpy as np
import soundfile as sf
from scipy.signal import stft

MIN_BPM = 60.0
MAX_BPM = 180.0


def _onset_envelope(samples: np.ndarray, sr: int, hop_length: int = 512, n_fft: int = 2048):
    _, t, Zxx = stft(samples, fs=sr, nperseg=n_fft, noverlap=n_fft - hop_length, boundary=None)
    mag = np.abs(Zxx)
    flux = np.diff(mag, axis=1)
    flux = np.maximum(flux, 0).sum(axis=0)
    flux = np.concatenate([[0.0], flux])
    peak = flux.max()
    if peak > 0:
        flux = flux / peak
    return t, flux


def _estimate_tempo(times: np.ndarray, envelope: np.ndarray) -> float:
    if len(times) < 2:
        return 120.0
    hop_time = times[1] - times[0]
    centered = envelope - envelope.mean()
    ac = np.correlate(centered, centered, mode="full")
    ac = ac[len(ac) // 2:]

    min_lag = max(int((60.0 / MAX_BPM) / hop_time), 1)
    max_lag = min(int((60.0 / MIN_BPM) / hop_time), len(ac) - 1)
    if max_lag <= min_lag:
        return 120.0

    segment = ac[min_lag:max_lag + 1]
    best_lag = min_lag + int(np.argmax(segment))
    period_sec = best_lag * hop_time
    if period_sec <= 0:
        return 120.0
    return 60.0 / period_sec


def _generate_beat_grid(times: np.ndarray, envelope: np.ndarray, bpm: float, duration: float) -> np.ndarray:
    if len(times) < 2 or duration <= 0:
        return np.array([])

    period = 60.0 / bpm
    hop_time = times[1] - times[0]

    search_end = min(period * 2, times[-1])
    mask = times <= search_end
    first_beat = times[mask][np.argmax(envelope[mask])] if mask.any() else 0.0

    t = first_beat
    while t - period >= 0:
        t -= period

    grid = []
    while t <= duration:
        if t >= 0:
            grid.append(t)
        t += period
    if not grid:
        return np.array([])

    refine_window = period / 6.0
    refine_frames = max(int(refine_window / hop_time), 1)
    refined = []
    for b in grid:
        idx = int(np.searchsorted(times, b))
        lo = max(idx - refine_frames, 0)
        hi = min(idx + refine_frames, len(envelope))
        if hi > lo:
            local_idx = lo + int(np.argmax(envelope[lo:hi]))
            refined.append(times[local_idx])
        else:
            refined.append(b)
    return np.array(sorted(set(refined)))


def detect_beats(wav_path: str):
    """Returns (bpm, beat_times) for an already-transcoded WAV file, or
    (None, None) if detection isn't possible (e.g. silent/too-short audio).
    Never raises — callers should treat a None result as "beat sync
    unavailable for this track" and fall back to unaligned timing."""
    try:
        data, sr = sf.read(wav_path, always_2d=False)
        if data.ndim > 1:
            data = data.mean(axis=1)
        duration = len(data) / sr
        if duration < 3:
            return None, None

        times, envelope = _onset_envelope(data, sr)
        if envelope.max() <= 0:
            return None, None

        bpm = _estimate_tempo(times, envelope)
        beat_times = _generate_beat_grid(times, envelope, bpm, duration)
        if len(beat_times) < 2:
            return None, None
        return bpm, beat_times
    except Exception:
        return None, None


def align_window_to_beats(start: float, duration: float, beat_times: np.ndarray, min_len: float, max_len: float):
    """Snaps a clip's start to the nearest beat, and its end to the nearest
    beat that keeps the resulting length within [min_len, max_len]. Falls
    back to the original duration (from the snapped start) if no beat in
    range qualifies."""
    if beat_times is None or len(beat_times) == 0:
        return start, duration

    new_start = float(beat_times[np.argmin(np.abs(beat_times - start))])
    end = start + duration

    candidates = beat_times[beat_times > new_start]
    lengths = candidates - new_start
    in_range = candidates[(lengths >= min_len) & (lengths <= max_len)]
    if len(in_range) == 0:
        return new_start, duration

    new_end = float(in_range[np.argmin(np.abs(in_range - end))])
    return new_start, new_end - new_start

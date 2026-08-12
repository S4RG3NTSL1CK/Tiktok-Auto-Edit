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

    # Octave-error correction: a periodic signal's autocorrelation is also
    # elevated at exact multiples of the true period (2x, 3x, ...), and
    # that harmonic can end up taller than the fundamental itself — e.g. a
    # strong recurring downbeat reinforces the 2x lag, especially near the
    # search range's boundary. Confirmed this actually happens (not just
    # theoretical) on a synthetic click track: it locked onto exactly 2x
    # the true period. If halving the detected lag is still in range and
    # nearly as strong, prefer the shorter lag — it's far more common for
    # a detector to lock onto a tempo multiple than a sub-multiple of the
    # true beat.
    while True:
        half_lag = best_lag // 2
        if half_lag < min_lag:
            break
        if ac[half_lag] >= ac[best_lag] * 0.7:
            best_lag = half_lag
        else:
            break

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


def _detect_downbeats(times: np.ndarray, envelope: np.ndarray, beat_times: np.ndarray, beats_per_bar: int = 4) -> np.ndarray:
    """Classifies `beat_times` into downbeats — the strong, first beat of
    each bar — by finding which phase (of `beats_per_bar`) has the highest
    average onset-envelope strength. Downbeats are conventionally the most
    emphasized beats in a bar (kick drum, chord change, etc.), so the phase
    with the loudest average onset wins. Falls back to treating every beat
    as a downbeat if there aren't enough beats to find a meaningful phase.
    """
    if len(beat_times) < beats_per_bar * 2:
        return beat_times

    beat_strengths = []
    for b in beat_times:
        idx = min(int(np.searchsorted(times, b)), len(envelope) - 1)
        beat_strengths.append(envelope[idx])
    beat_strengths = np.array(beat_strengths)

    best_phase, best_avg = 0, -1.0
    for phase in range(beats_per_bar):
        phase_strengths = beat_strengths[phase::beats_per_bar]
        if len(phase_strengths) == 0:
            continue
        avg = float(phase_strengths.mean())
        if avg > best_avg:
            best_avg, best_phase = avg, phase

    return beat_times[best_phase::beats_per_bar]


def detect_beats(wav_path: str):
    """Returns (bpm, beat_times, downbeat_times) for an already-transcoded
    WAV file, or (None, None, None) if detection isn't possible (e.g.
    silent/too-short audio). Never raises — callers should treat a None
    result as "beat sync unavailable for this track" and fall back to
    unaligned timing."""
    try:
        data, sr = sf.read(wav_path, always_2d=False)
        if data.ndim > 1:
            data = data.mean(axis=1)
        duration = len(data) / sr
        if duration < 3:
            return None, None, None

        times, envelope = _onset_envelope(data, sr)
        if envelope.max() <= 0:
            return None, None, None

        bpm = _estimate_tempo(times, envelope)
        beat_times = _generate_beat_grid(times, envelope, bpm, duration)
        if len(beat_times) < 2:
            return None, None, None
        downbeat_times = _detect_downbeats(times, envelope, beat_times)
        return bpm, beat_times, downbeat_times
    except Exception:
        return None, None, None


def align_window_to_beats(
    start: float, duration: float, beat_times: np.ndarray, min_len: float, max_len: float,
    downbeat_times: np.ndarray = None,
):
    """Snaps a clip's start to the nearest beat, and its end to the nearest
    beat that keeps the resulting length within [min_len, max_len]. Falls
    back to the original duration (from the snapped start) if no beat in
    range qualifies.

    When `downbeat_times` is given, prefers snapping the start to a nearby
    downbeat (the strong, first beat of a bar) instead of any arbitrary
    beat — starting exactly "on the one" reads as far more musically
    intentional than landing on an arbitrary beat. Only applied when a
    downbeat is within about 60% of a bar's length of the original start,
    so it doesn't drag the start far from the actual highlight moment just
    to land on one.
    """
    if beat_times is None or len(beat_times) == 0:
        return start, duration

    new_start = None
    if downbeat_times is not None and len(downbeat_times) > 0:
        nearest_downbeat = float(downbeat_times[np.argmin(np.abs(downbeat_times - start))])
        if len(downbeat_times) > 1:
            avg_bar = float(np.mean(np.diff(downbeat_times)))
        elif len(beat_times) > 1:
            avg_bar = 4 * float(np.mean(np.diff(beat_times)))
        else:
            avg_bar = 2.0
        if abs(nearest_downbeat - start) <= avg_bar * 0.6:
            new_start = nearest_downbeat

    if new_start is None:
        new_start = float(beat_times[np.argmin(np.abs(beat_times - start))])

    end = start + duration

    candidates = beat_times[beat_times > new_start]
    lengths = candidates - new_start
    in_range = candidates[(lengths >= min_len) & (lengths <= max_len)]
    if len(in_range) == 0:
        return new_start, duration

    new_end = float(in_range[np.argmin(np.abs(in_range - end))])
    return new_start, new_end - new_start

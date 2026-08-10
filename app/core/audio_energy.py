import numpy as np
import soundfile as sf


def compute_energy_curve(wav_path: str, window_sec: float = 0.5):
    data, sample_rate = sf.read(wav_path, always_2d=False)
    if data.ndim > 1:
        data = data.mean(axis=1)
    data = data.astype(np.float64)

    window_size = max(int(window_sec * sample_rate), 1)
    num_windows = max(len(data) // window_size, 1)
    trimmed = data[: num_windows * window_size]
    frames = trimmed.reshape(num_windows, window_size)

    rms = np.sqrt(np.mean(frames ** 2, axis=1))
    peak = rms.max()
    if peak > 0:
        rms = rms / peak

    times = (np.arange(num_windows) * window_size) / sample_rate
    return times, rms


def energy_in_range(times: np.ndarray, values: np.ndarray, start: float, end: float):
    mask = (times >= start) & (times < end)
    windowed = values[mask]
    if len(windowed) == 0:
        return 0.0, 0.0
    return float(windowed.mean()), float(windowed.std())

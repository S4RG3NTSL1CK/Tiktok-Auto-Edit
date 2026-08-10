from dataclasses import dataclass

import numpy as np

from .audio_energy import energy_in_range


@dataclass
class HighlightWindow:
    start: float
    end: float
    score: float

    @property
    def duration(self) -> float:
        return self.end - self.start


def _cut_density(scene_cuts: list, start: float, end: float) -> float:
    length = end - start
    if length <= 0:
        return 0.0
    count = sum(1 for c in scene_cuts if start <= c < end)
    return count / length


def _snap(t: float, scene_cuts: list, tolerance: float = 1.5) -> float:
    if not scene_cuts:
        return t
    nearest = min(scene_cuts, key=lambda c: abs(c - t))
    return nearest if abs(nearest - t) <= tolerance else t


def select_highlights(
    duration: float,
    energy_times: np.ndarray,
    energy_values: np.ndarray,
    scene_cuts: list,
    min_len: float,
    max_len: float,
    num_clips: int,
    step: float = 2.0,
    min_gap: float = 3.0,
) -> list:
    if duration <= min_len:
        return [HighlightWindow(0.0, duration, 1.0)]

    lengths = sorted(set(
        max(min_len, min(max_len, x))
        for x in (min_len, (min_len + max_len) / 2, max_len)
    ))

    raw = []
    for length in lengths:
        start = 0.0
        while start + length <= duration:
            end = start + length
            mean_e, std_e = energy_in_range(energy_times, energy_values, start, end)
            density = _cut_density(scene_cuts, start, end)
            raw.append([start, end, mean_e, std_e, density])
            start += step

    if not raw:
        return [HighlightWindow(0.0, min(max_len, duration), 1.0)]

    means = np.array([r[2] for r in raw])
    stds = np.array([r[3] for r in raw])
    densities = np.array([r[4] for r in raw])

    def norm(arr):
        lo, hi = arr.min(), arr.max()
        return (arr - lo) / (hi - lo) if hi > lo else np.zeros_like(arr)

    scores = 0.55 * norm(means) + 0.25 * norm(stds) + 0.20 * norm(densities)

    candidates = [
        HighlightWindow(r[0], r[1], float(s))
        for r, s in zip(raw, scores)
    ]
    candidates.sort(key=lambda w: w.score, reverse=True)

    selected = []
    for c in candidates:
        if len(selected) >= num_clips:
            break
        overlaps = any(
            c.start < s.end + min_gap and s.start < c.end + min_gap
            for s in selected
        )
        if overlaps:
            continue
        snapped_start = max(0.0, _snap(c.start, scene_cuts))
        snapped_end = min(duration, _snap(c.end, scene_cuts))
        if snapped_end - snapped_start < min_len * 0.8:
            snapped_start, snapped_end = c.start, c.end
        selected.append(HighlightWindow(snapped_start, snapped_end, c.score))

    selected.sort(key=lambda w: w.start)
    return selected

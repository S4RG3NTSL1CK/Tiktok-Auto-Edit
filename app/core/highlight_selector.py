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


def _local_quiet_point(t: float, times: np.ndarray, values: np.ndarray, tolerance: float) -> float:
    """Nudges `t` to the quietest instant within `tolerance` seconds of it —
    a local audio-energy minimum, i.e. a natural pause/breath. Used as a
    softer fallback than scene-cut snapping so a clip boundary lands between
    words/sounds instead of hard-cutting mid-word."""
    if times is None or values is None or len(times) == 0:
        return t
    mask = (times >= t - tolerance) & (times <= t + tolerance)
    if not mask.any():
        return t
    local_times = times[mask]
    local_values = values[mask]
    idx = int(np.argmin(local_values))
    return float(local_times[idx])


def _snap(
    t: float,
    scene_cuts: list,
    quiet_times: np.ndarray = None,
    quiet_values: np.ndarray = None,
    scene_tolerance: float = 1.5,
    quiet_tolerance: float = 0.6,
) -> float:
    # Prefer a real scene cut (a hard visual edit point) when one's close
    # by; otherwise fall back to the nearest natural quiet point so cuts
    # still avoid landing mid-word/mid-sound even with no scene change.
    if scene_cuts:
        nearest = min(scene_cuts, key=lambda c: abs(c - t))
        if abs(nearest - t) <= scene_tolerance:
            return nearest
    return _local_quiet_point(t, quiet_times, quiet_values, quiet_tolerance)


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
    quiet_times: np.ndarray = None,
    quiet_values: np.ndarray = None,
) -> list:
    if duration <= min_len:
        return [HighlightWindow(0.0, duration, 1.0)]

    if quiet_times is None:
        quiet_times, quiet_values = energy_times, energy_values

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
        snapped_start = max(0.0, _snap(c.start, scene_cuts, quiet_times, quiet_values))
        snapped_end = min(duration, _snap(c.end, scene_cuts, quiet_times, quiet_values))
        if snapped_end - snapped_start < min_len * 0.8:
            snapped_start, snapped_end = c.start, c.end
        selected.append(HighlightWindow(snapped_start, snapped_end, c.score))

    selected.sort(key=lambda w: w.start)
    return selected


def select_snippet_window(
    energy_times: np.ndarray,
    energy_values: np.ndarray,
    start: float,
    end: float,
    duration: float,
    step: float = 1.0,
) -> tuple:
    """Finds the highest-energy sub-window of `duration` seconds within
    [start, end], for pulling a short highlight out of an already-selected
    clip. Returns (snippet_start, snippet_end). If the clip is already
    shorter than `duration`, returns the clip's own bounds unchanged."""
    span = end - start
    if span <= duration:
        return start, end

    best_start, best_score = start, -1.0
    t = start
    while t + duration <= end:
        mean_e, _ = energy_in_range(energy_times, energy_values, t, t + duration)
        if mean_e > best_score:
            best_score = mean_e
            best_start = t
        t += step

    # Light polish only — nudge the edges to nearby quiet points without
    # meaningfully moving off the energy-maximizing window we just found.
    snippet_end = best_start + duration
    polished_start = _local_quiet_point(best_start, energy_times, energy_values, tolerance=0.4)
    polished_end = _local_quiet_point(snippet_end, energy_times, energy_values, tolerance=0.4)
    if polished_end - polished_start < duration * 0.9:
        return best_start, snippet_end
    return polished_start, polished_end

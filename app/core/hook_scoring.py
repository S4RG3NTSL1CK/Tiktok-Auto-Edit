import re

import numpy as np

_QUESTION_STARTERS = re.compile(
    r"^\s*(what|why|how|who|when|where|did|do|does|are|is|can|will|would|have|has)\b",
    re.IGNORECASE,
)
_LIST_CUES = re.compile(
    r"\b(first|second|third|next|finally|here('?s| are| is)|ways? to|tips?|reasons?|steps?|"
    r"mistakes?|secrets?)\b",
    re.IGNORECASE,
)
_IMPERATIVE_OPENERS = re.compile(
    r"^\s*(stop|try|imagine|watch|listen|never|always|don'?t|remember|picture|think)\b",
    re.IGNORECASE,
)
_SECOND_PERSON = re.compile(r"\b(you|your|you're|yours)\b", re.IGNORECASE)
_HAS_DIGIT = re.compile(r"\d")

# No cloud/LLM call here on purpose — stays consistent with the rest of the
# app's fully-local, offline scoring (audio energy, motion, scene cuts).
# This is a cheap, explainable heuristic, not a semantic judgment of what's
# actually "good" — a strong proxy signal, not a guarantee, same framing as
# the copyright-check feature.


def score_segment_text(text: str) -> float:
    """0..1 heuristic hook score for one piece of transcript text — how much
    it reads like an attention-grabbing opener/hook rather than routine
    narration."""
    if not text or not text.strip():
        return 0.0

    score = 0.0
    if "?" in text:
        score += 0.3
    if "!" in text:
        score += 0.15
    if _QUESTION_STARTERS.search(text):
        score += 0.2
    if _HAS_DIGIT.search(text):
        score += 0.25
    if _LIST_CUES.search(text):
        score += 0.15
    if _SECOND_PERSON.search(text):
        score += 0.15
    if _IMPERATIVE_OPENERS.search(text):
        score += 0.15

    return min(score, 1.0)


def compute_hook_curve(segments: list, duration: float, window_sec: float = 0.5):
    """Converts segment-level hook scores into the same continuous
    (times, values) time-grid contract as audio_energy.compute_energy_curve
    and motion_energy.compute_motion_curve, so it can be blended or queried
    the same way. Peak-normalized to 0..1; a bonus is applied to the very
    first spoken segment since the literal opening line disproportionately
    determines scroll-past-or-not in short-form content."""
    num_windows = max(int(duration / window_sec), 1)
    bin_times = np.arange(num_windows) * window_sec
    bin_values = np.zeros(num_windows)

    if not segments:
        return bin_times, bin_values

    for i, seg in enumerate(segments):
        score = score_segment_text(seg.text)
        if i == 0:
            score = min(score + 0.2, 1.0)
        start_bin = max(int(seg.start / window_sec), 0)
        end_bin = min(int(seg.end / window_sec) + 1, num_windows)
        if start_bin >= num_windows:
            continue
        bin_values[start_bin:end_bin] = np.maximum(bin_values[start_bin:end_bin], score)

    peak = bin_values.max()
    if peak > 0:
        bin_values = bin_values / peak

    return bin_times, bin_values

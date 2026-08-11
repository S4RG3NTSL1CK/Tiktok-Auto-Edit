from dataclasses import dataclass

from faster_whisper import WhisperModel

from ..config import whisper_model_cache_dir

# "base.en" — good speed/accuracy tradeoff for hook detection, which only
# needs roughly-right text (questions, numbers, emphasis words), not a
# word-perfect transcript. int8 quantization on CPU: ~16x realtime measured
# locally. Model downloads once (~140MB) to whisper_model_cache_dir() on
# first use, not bundled in the installer.
MODEL_SIZE = "base.en"

_model = None


class TranscriptionError(RuntimeError):
    pass


@dataclass
class Segment:
    start: float
    end: float
    text: str


def _get_model() -> WhisperModel:
    global _model
    if _model is None:
        try:
            _model = WhisperModel(
                MODEL_SIZE, device="cpu", compute_type="int8",
                download_root=str(whisper_model_cache_dir()),
            )
        except Exception as exc:
            raise TranscriptionError(
                f"Could not load the speech-recognition model (first use downloads "
                f"~140MB — check your internet connection): {exc}"
            ) from exc
    return _model


def transcribe_audio(wav_path: str) -> list:
    """Transcribes `wav_path` (the same mono WAV already extracted for audio-
    energy analysis) into a list of Segment(start, end, text) — one per
    detected sentence/phrase, timestamped against the original video.

    Raises TranscriptionError on any failure (model load, decode, etc.) —
    this is an optional feature, so callers should catch this and fall back
    to running without transcript-based scoring rather than failing the
    whole pipeline run over it."""
    model = _get_model()
    try:
        segments, _info = model.transcribe(wav_path, beam_size=5, vad_filter=True)
        return [
            Segment(start=s.start, end=s.end, text=s.text.strip())
            for s in segments
            if s.text.strip()
        ]
    except Exception as exc:
        raise TranscriptionError(f"Transcription failed: {exc}") from exc

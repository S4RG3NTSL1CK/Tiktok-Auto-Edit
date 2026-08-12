from dataclasses import dataclass


@dataclass
class EditTemplate:
    key: str
    label: str
    description: str
    num_clips: int
    min_len: float
    max_len: float
    beat_sync_enabled: bool
    music_instrumental_only: bool
    music_energy: str
    music_volume: float
    orig_volume: float
    create_highlight_reel: bool
    transcript_enabled: bool


# Each template is a coherent pacing/structure preset — clip length, cut
# count, how hard cuts snap to the beat, how loud music sits under the
# original audio, and whether hook-detection/highlight-reel are worth the
# extra render time for that style of content. Deliberately does NOT
# touch aspect ratio, resolution/fps, or which music/tags/provider to
# use — those are separate choices the user makes on their own, a
# template only governs the editing style itself.
TEMPLATES = [
    EditTemplate(
        key="fast_highlights",
        label="Fast-Paced Highlights",
        description=(
            "Short, punchy clips with hard beat-synced cuts and a highlight reel. "
            "A solid general-purpose default for most content."
        ),
        num_clips=6, min_len=8, max_len=15,
        beat_sync_enabled=True, music_instrumental_only=True, music_energy="high",
        music_volume=0.25, orig_volume=1.0,
        create_highlight_reel=True, transcript_enabled=True,
    ),
    EditTemplate(
        key="cinematic",
        label="Cinematic Story",
        description=(
            "Longer, fewer clips that let dialogue and pacing breathe. Music stays "
            "subtle underneath and cuts aren't forced onto the beat."
        ),
        num_clips=3, min_len=30, max_len=60,
        beat_sync_enabled=False, music_instrumental_only=True, music_energy="verylow",
        music_volume=0.12, orig_volume=1.0,
        create_highlight_reel=False, transcript_enabled=False,
    ),
    EditTemplate(
        key="music_video",
        label="Music Video / Beat Drop",
        description=(
            "Very short, rapid cuts tightly synced to strong beats, built around a "
            "highlight reel. Works best with high-energy music with vocals."
        ),
        num_clips=5, min_len=6, max_len=12,
        beat_sync_enabled=True, music_instrumental_only=False, music_energy="veryhigh",
        music_volume=0.3, orig_volume=0.9,
        create_highlight_reel=True, transcript_enabled=False,
    ),
    EditTemplate(
        key="podcast",
        label="Podcast / Talking Head",
        description=(
            "Clips built around strong spoken hooks with room for a full thought. "
            "Background music stays quiet and out of the way of speech."
        ),
        num_clips=5, min_len=20, max_len=45,
        beat_sync_enabled=False, music_instrumental_only=True, music_energy="verylow",
        music_volume=0.10, orig_volume=1.0,
        create_highlight_reel=False, transcript_enabled=True,
    ),
    EditTemplate(
        key="gaming",
        label="Gaming / Action Highlights",
        description=(
            "Medium-length clips built for fast on-screen action, beat-synced cuts, "
            "and a highlight reel of the best moments."
        ),
        num_clips=6, min_len=10, max_len=20,
        beat_sync_enabled=True, music_instrumental_only=True, music_energy="high",
        music_volume=0.22, orig_volume=1.0,
        create_highlight_reel=True, transcript_enabled=False,
    ),
]


def get_template(key: str):
    return next((t for t in TEMPLATES if t.key == key), None)

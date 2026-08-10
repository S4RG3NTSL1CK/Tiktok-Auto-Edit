# Tiktok Auto Edit

Desktop app: drop in an `.mp4`, get back a batch of high-energy short-form
vertical clips with royalty-free background music mixed in.

## How it picks clips

Fully local, offline heuristic — no cloud video AI:
- Extracts the audio track and computes an RMS energy curve.
- Runs scene-cut detection (PySceneDetect) on the video.
- Scores candidate windows by average energy, energy variance ("peakiness"),
  and scene-cut density, then greedily picks the top non-overlapping windows,
  snapped to nearby scene cuts for clean edit points.

## Music

Background music is pulled live from [Freesound](https://freesound.org) at
generation time, filtered to CC0 and CC-BY (Attribution) licensed tracks only.
Pixabay's public API does not expose a music endpoint (image/video only), so
it isn't used here.

- Get a free API key: https://freesound.org/apiv2/apply/ (you only need the
  API key itself, not the OAuth flow).
- Paste it into the app's **Settings** dialog.
- CC-BY tracks require attribution — the app writes an `ATTRIBUTIONS.txt`
  into your output folder listing every track that needs it. Keep it with
  the clips if you use them.
- Freesound leans toward sound-effects/loops more than polished full songs;
  quality varies by track.

## Setup

```bash
cd /home/mcserver/Projects/Tiktok-Auto-Edit
./setup.sh
```

Don't run `pip install -r requirements.txt` directly — `scenedetect` pulls in
non-headless `opencv-python`, which conflicts on-disk with
`opencv-python-headless` (both packages install into the same `cv2/`
directory and silently break each other, crashing PySide6 with a Qt platform
plugin error at launch). `setup.sh` installs them in the right order with the
right flags to avoid that.

No system FFmpeg install is required — `imageio-ffmpeg` bundles a static
FFmpeg binary automatically on install.

## Run

```bash
source .venv/bin/activate
python main.py
```

## Usage

1. Drag & drop (or Browse) an `.mp4` file.
2. Set number of clips, clip length range, aspect ratio (9:16 / 1:1 /
   original), and an output folder.
3. Optionally set a music mood keyword, or leave it blank to rotate through
   moods automatically.
4. Click **Generate Clips**. Output lands in the chosen folder as
   `clip_01.mp4`, `clip_02.mp4`, etc.

## Notes

- `opencv-python-headless` is used deliberately instead of `opencv-python` —
  the non-headless build bundles its own Qt platform plugins, which conflict
  with PySide6's and can crash the app on launch with a Qt platform plugin
  error.
- Freesound API keys and your default output folder are stored locally in
  your OS config directory (via `platformdirs`), not in this repo.

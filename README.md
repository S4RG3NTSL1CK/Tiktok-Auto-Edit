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

Two royalty-free music providers, picked per run from the Music panel.
Pixabay's public API does not expose a music endpoint (image/video only), so
it isn't used here.

- **Freesound** — get a free API key: https://freesound.org/apiv2/apply/
  (you only need the API key itself, not the OAuth flow). Leans toward
  sound-effects/loops more than polished full songs; quality varies by track.
- **Jamendo** — get a free `client_id`: https://devportal.jamendo.com
  (create an application, copy its **Client ID**, not the secret — it's a
  short ~8-character string). Actual songs with real genre/mood/tempo
  metadata, generally the better choice for "real music."

Paste whichever key(s) you use into the app's **Settings** dialog. Both
providers are filtered to CC0, CC-BY, and CC-BY-SA licensed tracks only — no
NonCommercial or NoDerivatives restrictions. Any non-CC0 track requires
attribution — the app writes an `ATTRIBUTIONS.txt` into your output folder
listing every track that needs it. Keep it with the clips if you use them.

**Two ways to pick music:**
- **Auto (default):** set genre/mood tags (e.g. "lofi chill", "epic
  cinematic"), instrumental-only (on by default, avoids clashing with
  talking), and energy/tempo. Each generated clip gets an independently
  picked matching track.
- **Manual:** click **Browse & Listen...** in the Music panel to search
  either provider, preview tracks in-app before committing, and pick one
  specific track. That exact track is then used on every clip in the batch
  instead of auto-picking per clip. Click **Clear** to go back to auto mode.

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
3. Set up music (see above) — either genre/mood tags for auto-picking, or
   **Browse & Listen...** to pick one specific track.
4. Click **Generate Clips**. Output lands in the chosen folder as
   `clip_01.mp4`, `clip_02.mp4`, etc.

## Notes

- `opencv-python-headless` is used deliberately instead of `opencv-python` —
  the non-headless build bundles its own Qt platform plugins, which conflict
  with PySide6's and can crash the app on launch with a Qt platform plugin
  error.
- API keys and your default output folder are stored locally in your OS
  config directory (via `platformdirs`), not in this repo.
- In-app music preview playback uses PySide6's bundled Qt Multimedia +
  FFmpeg backend, so it works without any system media libraries installed.

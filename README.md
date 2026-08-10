# Tiktok Auto Edit

Desktop app: drop in an `.mp4`, get back a batch of high-energy short-form
vertical clips with royalty-free background music mixed in.

## Windows install

Download the latest installer from the
[Releases page](https://github.com/S4RG3NTSL1CK/Tiktok-Auto-Edit/releases/latest),
run it, and launch **Tiktok Auto Edit** from the Start Menu. No Python or
FFmpeg install needed — everything's bundled.

The installer is unsigned (no paid code-signing cert), so Windows SmartScreen
will show an "Unknown Publisher" warning on first run — click **More info →
Run anyway**.

**Auto-update:** on launch, the app checks GitHub for a newer release. If one
exists, it asks before downloading and installing — accepting closes the app,
installs silently, and you relaunch it. No manual reinstall needed after the
first install.

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

**Three ways to pick music** (mutually exclusive — picking one clears the others):
- **Auto (default):** set genre/mood tags (e.g. "lofi chill", "epic
  cinematic"), instrumental-only (on by default, avoids clashing with
  talking), and energy/tempo. Each generated clip gets an independently
  picked matching track.
- **Manual:** click **Browse & Listen...** in the Music panel to search
  either provider, preview tracks in-app before committing, and pick one
  specific track. That exact track is then used on every clip in the batch.
- **Local:** click **Use Local File...** to apply one music file you already
  have on disk to every clip, or **Use Local Folder...** to point at a folder
  of tracks — each clip gets a different one picked from it, no repeats until
  the folder's exhausted. No API key, no network call, works offline.
  Supports `.mp3 .wav .m4a .flac .ogg .aac`. Local tracks are never written to
  `ATTRIBUTIONS.txt` — the app makes no claim about their license, that's on
  you to know since they're your own files.

Click **Clear** next to whichever mode you used to go back to Auto.

## Running from source (Linux/Mac, or Windows dev setup)

The Windows install above is the normal path for actually using the app. Run
from source only for development.

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

## Releasing a new Windows build

CI can't run on this machine (Linux) — the actual .exe is built by a
`windows-latest` GitHub Actions runner, triggered by pushing a version tag:

```bash
git tag v1.1.0
git push origin v1.1.0
```

The workflow (`.github/workflows/release.yml`) installs dependencies, runs
PyInstaller (`build.spec`) to produce a onedir build, wraps it with Inno
Setup (`installer.iss`) into a proper installer, and publishes it as a
GitHub Release asset. That release is what the in-app updater checks
against — so a bad tag push ships straight to every installed copy that
accepts the prompt. Only tag a version once it's actually been tested.

## Notes

- `opencv-python-headless` is used deliberately instead of `opencv-python` —
  the non-headless build bundles its own Qt platform plugins, which conflict
  with PySide6's and can crash the app on launch with a Qt platform plugin
  error.
- API keys and your default output folder are stored locally in your OS
  config directory (via `platformdirs`), not in this repo.
- In-app music preview playback uses PySide6's bundled Qt Multimedia +
  FFmpeg backend, so it works without any system media libraries installed.

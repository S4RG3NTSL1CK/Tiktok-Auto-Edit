# Tiktok Auto Edit

Desktop app: drop in an `.mp4`, get back a batch of high-energy short-form
vertical clips with royalty-free background music mixed in. Dark UI with an
indigo-to-violet gradient identity (`app/ui/theme.py`) matching the app icon.

## Windows install

Download the latest installer from the
[Releases page](https://github.com/S4RG3NTSL1CK/Tiktok-Auto-Edit/releases/latest),
run it, and launch **Tiktok Auto Edit** from the Start Menu. No Python or
FFmpeg install needed — everything's bundled.

The installer is unsigned (no paid code-signing cert), so Windows SmartScreen
will show an "Unknown Publisher" warning on first run — click **More info →
Run anyway**.

**Auto-update:** on launch, the app checks GitHub for a newer release. If one
exists, it asks before downloading; once downloaded it tells you it's about
to install and close — **wait for it to reopen on its own rather than
launching it manually**, especially now that the bundle includes
numpy/scipy/opencv and can take a little while to copy. If you do launch it
manually mid-install and get a stale version, it'll now say so honestly
("update did not complete") instead of falsely claiming success — just try
updating again.

## How it picks clips

Fully local, offline heuristic — no cloud video AI:
- Extracts the audio track and computes an RMS energy curve.
- Computes a **visual motion curve** too (frame-to-frame pixel difference on
  downscaled grayscale samples via OpenCV, no extra dependency) — catches
  moments that are visually dynamic but audio-quiet (a trick, a fast pan),
  which pure audio-energy scoring would otherwise miss entirely.
- Runs scene-cut detection (PySceneDetect) on the video.
- Blends audio energy (60%) and motion (40%) into one score, plus energy
  variance ("peakiness") and scene-cut density, then greedily picks the top
  non-overlapping windows. Music-track energy matching stays audio-only on
  purpose — the music should match what the clip actually sounds like, not
  how visually busy it is.
- **Clean cut points:** boundaries snap to a nearby scene cut first (a real
  visual edit point); if none is close by, they fall back to the nearest
  local audio-energy minimum instead — a natural pause/breath — so a clip
  is far less likely to start or end mid-word or mid-sound.

**Encoding quality**: `crf=18` / `preset=fast` (up from `20`/`veryfast`) and
explicit Lanczos scaling — meaningfully better quality-per-bitrate at a
modest, worthwhile render-time increase for clips this short.

## Speech transcription / hook detection

Optional checkbox in Clip settings: **Use speech transcription to favor
hook moments**, off by default. When on, the app transcribes the video's
speech locally (via [faster-whisper](https://github.com/SYSTRAN/faster-whisper),
CPU-only, no cloud call — audio never leaves your machine) and scores each
spoken line with a simple heuristic: questions, exclamations, numbers/lists
("3 tips", "top 5"), direct address ("you"/"your"), imperative openers
("never", "stop", "imagine"), with an extra bonus on the very first spoken
line. That score gets blended into the same scoring pass as audio energy
and visual motion (45% audio / 30% motion / 25% hook, versus 60/40 with it
off), so a clip is more likely to be built around a strong verbal hook
instead of just a loud or visually busy moment.

**What this actually is and isn't:** it's a heuristic on the *words used*,
not a judgment of whether a line is actually interesting — same honest
framing as the copyright check. A monotone question still scores as a
hook; a genuinely compelling line without a question mark or a number
might not. It's a proxy signal, not a content-quality model, and there's
no cloud LLM involved (deliberately, to keep the app fully local).

First use downloads a small (~140MB) speech-recognition model, cached in
your OS config directory alongside the app's other cached data — this
happens once, not per run. Transcribing adds render time up front,
roughly proportional to video length (measured at faster than realtime on
CPU with the default model). If the download or transcription fails for
any reason (no internet on first use, etc.), the app logs it and falls
back to scoring without the hook signal rather than failing the run.

## Smart crop

When cropping down to 9:16 or 1:1, the app no longer just center-crops
blindly. It samples across the clip's time range roughly every 2.5s (not
once for the whole clip) and runs face detection (YuNet, a small
MIT-licensed local DNN model — bundled in the app, no network call) at
each sample — if a face is found, the crop centers on it; otherwise it
falls back to a motion-weighted saliency estimate for that moment, or the
previous sample's position if neither finds anything, smoothed so the pan
doesn't jump between samples. The crop then **pans smoothly over time** to
follow the subject instead of using one fixed offset for the whole clip —
important on longer or high-motion clips, where a subject moving around
during a 30-60s clip would otherwise drift out of a crop window computed
once at the start. This only affects the horizontal offset; vertical
framing is unaffected (a 9:16 crop from a landscape source keeps the full
source height). Aspect mode "original" skips this entirely since no
horizontal crop happens in that mode.

## Highlight reel

Optional checkbox: **Also stitch all clips into one highlight reel**, off by
default. When on, every generated clip still gets its own file as normal
(`clip_01.mp4`, etc.) — this adds one more file, `highlight_reel.mp4`.

The reel is **not** all your clips concatenated end to end — that would run
several minutes long. Instead it pulls the single highest-energy moment out
of *each* clip (reusing the same audio-energy analysis used to pick the
clips in the first place) and stitches just those short highlights
together, with a crossfade (video and audio) at each join instead of a hard
cut. The total reel length targets the same range as one normal clip (the
midpoint of your min/max clip length setting, split evenly across however
many clips you generated) — so with the default 15–45s range, the reel
itself lands around 30s regardless of how many clips fed into it, not
N times longer.

The reel always plays **one continuous track the whole way through**,
regardless of music mode — even if Auto music picked a different track per
clip, the reel doesn't inherit any of those. Snippets are pulled fresh
from the original source with no music mixed in yet, stitched together,
and then exactly one track (searched to fit the reel's full length) is
mixed once over the assembled result. In Auto mode that's a fresh pick
sized for the reel; in Manual/Local mode it's the same track/file you
already chose.

## Video/music alignment

Two things happen automatically to make the video and its music feel like
they belong together, not just overlaid:

- **Beat-sync (on by default):** once a track is chosen for a clip, the app
  detects its beat grid (spectral-flux onset detection + autocorrelation
  tempo estimate + phase-locked beat grid — hand-rolled on `numpy`/`scipy`,
  deliberately not `librosa`, to avoid dragging `numba`/`llvmlite` into the
  Windows build) and snaps that clip's start **and** end to the nearest
  beats, within your min/max length range. Cuts land on the beat instead of
  at an arbitrary sample. Toggle: **Beat-sync clip cuts to music**.
- **Energy-matched auto music (default energy setting):** in Auto music
  mode, each clip's own audio energy (already computed for clip selection)
  is bucketed into very-low → very-high and used to bias that specific
  clip's music search — a calm segment pulls calmer tracks, a high-energy
  segment pulls higher-tempo ones, independently per clip. Set the Energy
  dropdown to a fixed value instead of **Auto** to override this and force
  the same energy level on every clip.

Beat-sync applies no matter which music source you're using (Auto/Manual/
Local). Energy-matching only applies in Auto mode — Manual and Local already
lock in one specific track ahead of time, so there's nothing to match.

## 4K / 60 FPS export

Optional checkbox in Clip settings, off by default. Two things worth knowing
before you turn it on:

- **Upscaling isn't extra detail.** If your source video isn't already
  near 4K, this stretches the same pixels into a bigger frame — it doesn't
  invent new detail. Cropping landscape footage down to vertical 9:16 keeps
  only the center slice, so even a genuinely 4K landscape source usually
  ends up upscaled once cropped vertical. The app checks this per-run and
  logs a note when it's about to happen — check the log, not just the
  checkbox.
- **60fps is standard frame-rate conversion, not motion interpolation.**
  Frames are resampled onto a 60fps timeline; the app does not generate new
  in-between frames via motion estimation (`minterpolate` in ffmpeg terms).
  That keeps renders fast and avoids interpolation artifacts (warping around
  fast motion, the "soap opera effect"), at the cost of not producing truly
  fluid new motion from a lower-fps source.
- **Expect roughly 8x the encode work** (4x pixels × 2x frame rate) versus
  the 1080p30 default, and files several times larger.

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

## Copyright check

**Check Copyright** button under the results list, enabled once a clip is
selected. Extracts that clip's full mixed audio and checks it against
[AudD](https://audd.io)'s commercial-music fingerprint database (160M+
tracks) — reports a match with title/artist/album if found.

**What this actually is and isn't:** there is no public API — from TikTok or
anyone — that tells you what TikTok's own (internal, non-public) mute/
copyright-detection system will do with a specific clip. This is a
best-effort proxy signal against a large but different database. A clean
result is a good sign, not a guarantee; a match is a real warning sign
worth investigating, not a certainty of what TikTok specifically will flag.
Needs a free AudD API token (300 free checks, then ~$2–5/1000) in Settings.

## TikTok upload

**TikTok Account** button (top bar) to connect your account, then **Upload
to TikTok (draft)** under the results list once a clip is selected.

- Register your own app at
  [developers.tiktok.com/apps](https://developers.tiktok.com/apps), add the
  **Login Kit** and **Content Posting API** products, and set the redirect
  URI to exactly `http://127.0.0.1:58642/callback` (shown in the app too —
  TikTok's desktop OAuth flow supports a localhost redirect, unlike most of
  their other flows). Paste the Client Key and Client Secret into Settings.
- Login opens your browser to TikTok, then hands control back to the app
  automatically via a local callback — no copy-pasting a code.
- **Uploads land as a draft in your TikTok inbox, not a public post.** This
  app is unaudited (TikTok's full app-review process is a separate,
  business-verification-heavy track, out of scope for personal use) — draft
  mode sidesteps that entirely rather than pretending to control visibility
  it can't. Open TikTok yourself to review, edit, and actually publish.
- Tokens are stored locally in your OS config directory alongside your other
  API keys, refreshed automatically when they expire.

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
5. Optionally select a clip and click **Check Copyright** before posting it
   anywhere, or **Upload to TikTok (draft)** to send it to your TikTok inbox
   (connect your account first via the **TikTok Account** button).

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

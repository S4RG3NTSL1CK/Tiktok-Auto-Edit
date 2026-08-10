#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip

# opencv-python-headless must land before scenedetect, and scenedetect must
# install with --no-deps — otherwise pip pulls in non-headless opencv-python
# too, and the two packages conflict on-disk (they share the cv2/ package
# directory), which crashes PySide6 with a Qt platform plugin error.
pip install PySide6 opencv-python-headless numpy scipy soundfile requests imageio-ffmpeg platformdirs click tqdm
pip install --no-deps scenedetect

echo "Setup complete. Run the app with: source .venv/bin/activate && python main.py"

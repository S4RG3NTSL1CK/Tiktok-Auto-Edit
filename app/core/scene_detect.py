def detect_scene_cuts(video_path: str) -> list:
    try:
        from scenedetect import detect, ContentDetector
        scenes = detect(video_path, ContentDetector(threshold=27.0))
        return [scene[0].get_seconds() for scene in scenes if scene[0].get_seconds() > 0]
    except Exception:
        return []

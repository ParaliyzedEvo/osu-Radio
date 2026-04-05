import os
import sys
import json
import hashlib
import subprocess
import tempfile
from pathlib import Path
from PySide6.QtCore import QThread, Signal
from osuRadio.config import BASE_PATH, get_lazer_reader_path, get_silent_subprocess_kwargs
from osuRadio.db import save_cache

def compute_file_hash(path: str) -> str:
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""

def run_lazer_reader(lazer_dir: str) -> list:
    reader_path = get_lazer_reader_path()
    frozen = getattr(sys, "frozen", False)

    if frozen:
        cmd = [str(reader_path), lazer_dir]
    else:
        cmd = ["node", str(reader_path), lazer_dir]

    print(f"[LazerReader] Running: {' '.join(cmd)}")

    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            **get_silent_subprocess_kwargs()
        )
        if result.returncode != 0:
            print(f"[LazerReader] Error output: {result.stderr}")
            return []
    except FileNotFoundError as e:
        print(f"[LazerReader] Could not find reader: {e}")
        return []

    # Read the output JSON file
    cache_dir = Path(tempfile.gettempdir()) / "OsuRadioCache"
    output_path = cache_dir / "lazer-audio-paths.json"
    if not output_path.exists():
        print("[LazerReader] Output file not found after run")
        return []

    try:
        with open(output_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[LazerReader] Failed to parse output JSON: {e}")
        return []


def convert_lazer_to_songs(raw: list) -> list:
    seen = {}
    for entry in raw:
        if not entry.get("fileExists"):
            continue
        key = (
            entry.get("title", "").strip(),
            entry.get("artist", "").strip(),
            entry.get("mapper", "").strip(),
        )
        if key not in seen:
            seen[key] = entry

    songs = []
    for entry in seen.values():
        audio_path = entry.get("audioPath", "")
        audio_hash = entry.get("audioHash", "")
        songs.append({
            "title": entry.get("title", "Unknown"),
            "artist": entry.get("artist", "Unknown"),
            "mapper": entry.get("mapper", "Unknown"),
            "audio": entry.get("audioFilename", "audio"),
            "audio_path": audio_path,   # full path to hash file
            "audio_hash": audio_hash,
            "background": entry.get("backgroundPath") or "",
            "length": 0,                # lazer JSON doesn't include length
            "osu_file": "",
            "folder": audio_path,       # folder = hash path for lazer songs
            "source": "lazer",
        })
    return songs


class LazerScanner(QThread):
    done = Signal(list)
    progress_update = Signal(str)

    def __init__(self, lazer_dir: str):
        super().__init__()
        self.lazer_dir = lazer_dir

    def run(self):
        self.progress_update.emit("Reading osu!lazer library...")
        raw = run_lazer_reader(self.lazer_dir)
        if not raw:
            self.progress_update.emit("⚠️ No lazer data found or reader failed.")
            self.done.emit([])
            return

        self.progress_update.emit(f"🔄 Processing {len(raw)} lazer beatmaps...")
        songs = convert_lazer_to_songs(raw)
        self.progress_update.emit(f"Saving {len(songs)} lazer songs to cache...")
        save_cache(self.lazer_dir, songs, source="lazer")
        self.progress_update.emit(f"✅ Lazer import complete! ({len(songs)} songs)")
        self.done.emit(songs)
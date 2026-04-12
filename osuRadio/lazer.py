import sys
import json
import hashlib
import subprocess
import tempfile
from pathlib import Path
from PySide6.QtCore import QThread, Signal
from osuRadio.config import get_lazer_reader_path, get_silent_subprocess_kwargs
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
        songs.append({
            "title": entry.get("title", "Unknown"),
            "artist": entry.get("artist", "Unknown"),
            "mapper": entry.get("mapper", "Unknown"),
            "audio": entry.get("audioFilename", "audio.mp3"),  # just the filename
            "audio_path": entry.get("audioPath", ""),    # full path to hash file
            "audio_hash": entry.get("audioHash", ""),
            "background": entry.get("backgroundPath") or "",
            "background_hash": entry.get("backgroundHash") or "",
            "length": 0,
            "osu_file": "",
            "folder": entry.get("audioPath", ""),        # full hash file path, used as existence check
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
        self.progress_update.emit("[osu!Lazer] 📖 Reading osu!Lazer library...")
        raw = run_lazer_reader(self.lazer_dir)
        if not raw:
            self.progress_update.emit("[osu!Lazer] ⚠️ No lazer data found or reader failed.")
            self.done.emit([])
            return

        total = len(raw)
        self.progress_update.emit(f"[osu!Lazer] 🔍 Scanning osu!Lazer... (found {total} beatmaps)")

        seen = {}
        for i, entry in enumerate(raw):
            if self.isInterruptionRequested():
                print("[LazerScanner] Interruption requested, stopping.")
                return

            if not entry.get("fileExists"):
                continue

            key = (
                entry.get("title", "").strip(),
                entry.get("artist", "").strip(),
                entry.get("mapper", "").strip(),
            )
            if key not in seen:
                seen[key] = entry

            if i % 10 == 0:
                artist = entry.get("artist", "Unknown")
                title = entry.get("title", "Unknown")
                self.progress_update.emit(
                    f"[osu!Lazer] 🎵 Processing: {artist} - {title} ({i + 1}/{total})"
                )

        songs = []
        for entry in seen.values():
            songs.append({
                "title":           entry.get("title", "Unknown"),
                "artist":          entry.get("artist", "Unknown"),
                "mapper":          entry.get("mapper", "Unknown"),
                "audio":           entry.get("audioFilename", "audio.mp3"),
                "audio_path":      entry.get("audioPath", ""),
                "audio_hash":      entry.get("audioHash", ""),
                "background":      entry.get("backgroundPath") or "",
                "background_hash": entry.get("backgroundHash") or "",
                "length":          0,
                "osu_file":        "",
                "folder":          entry.get("audioPath", ""),
                "source":          "lazer",
            })

        self.progress_update.emit(f"[osu!Lazer] 💾 Saving {len(songs)} lazer songs to cache...")
        save_cache(self.lazer_dir, songs, source="lazer")
        self.progress_update.emit(f"[osu!Lazer] ✅ Lazer import complete! ({len(songs)} songs)")
        self.done.emit(songs)
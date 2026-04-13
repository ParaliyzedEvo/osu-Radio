import sys
import json
import hashlib
import subprocess
import tempfile
import time
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


def run_lazer_reader(lazer_dir: str, progress_cb=None) -> list:
    """
    Run the lazer reader subprocess.
    progress_cb: optional callable(str) called periodically while waiting,
                 so the caller can emit signals and keep Qt's event loop aware.
    """
    reader_path = get_lazer_reader_path()
    frozen = getattr(sys, "frozen", False)

    if frozen:
        cmd = [str(reader_path), lazer_dir]
    else:
        cmd = ["node", str(reader_path), lazer_dir]

    print(f"[LazerReader] Running: {' '.join(cmd)}")

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            **get_silent_subprocess_kwargs()
        )
    except FileNotFoundError as e:
        print(f"[LazerReader] Could not find reader: {e}")
        return []

    dots = 0
    while proc.poll() is None:
        time.sleep(0.1)
        dots += 1
        if progress_cb and dots % 10 == 0:
            n = (dots // 10) % 4
            progress_cb(f"[osu!Lazer] 📖 Reading osu!Lazer library{'.' * (n + 1)}")

    if proc.returncode != 0:
        stderr = proc.stderr.read()
        print(f"[LazerReader] Error output: {stderr}")
        return []

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
            "title":            entry.get("title",          "Unknown"),
            "artist":           entry.get("artist",         "Unknown"),
            "mapper":           entry.get("mapper",         "Unknown"),
            "audio":            entry.get("audioFilename",  "audio.mp3"),
            "audio_path":       entry.get("audioPath",      ""),
            "audio_hash":       entry.get("audioHash",      ""),
            "background":       entry.get("backgroundPath") or "",
            "background_hash":  entry.get("backgroundHash") or "",
            "length":           0,
            "osu_file":         "",
            "folder":           entry.get("audioPath",      ""),
            "source":           "lazer",
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

        raw = run_lazer_reader(
            self.lazer_dir,
            progress_cb=lambda msg: self.progress_update.emit(msg)
        )

        if not raw:
            self.progress_update.emit("[osu!Lazer] ⚠️ No lazer data found or reader failed.")
            self.done.emit([])
            return

        if self.isInterruptionRequested():
            return

        total = len(raw)
        self.progress_update.emit(f"[osu!Lazer] 🔍 Scanning osu!Lazer... (found {total} beatmaps)")

        seen = {}
        processed = 0
        for entry in raw:
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

            processed += 1
            if processed % 10 == 0:
                artist = entry.get("artist", "Unknown")
                title  = entry.get("title",  "Unknown")
                self.progress_update.emit(
                    f"[osu!Lazer] 🎵 Processing: {artist} - {title} ({processed}/{total})"
                )

        if self.isInterruptionRequested():
            return

        songs = []
        for entry in seen.values():
            songs.append({
                "title":            entry.get("title",          "Unknown"),
                "artist":           entry.get("artist",         "Unknown"),
                "mapper":           entry.get("mapper",         "Unknown"),
                "audio":            entry.get("audioFilename",  "audio.mp3"),
                "audio_path":       entry.get("audioPath",      ""),
                "audio_hash":       entry.get("audioHash",      ""),
                "background":       entry.get("backgroundPath") or "",
                "background_hash":  entry.get("backgroundHash") or "",
                "length":           0,
                "osu_file":         "",
                "folder":           entry.get("audioPath",      ""),
                "source":           "lazer",
            })

        self.progress_update.emit(f"[osu!Lazer] 💾 Saving {len(songs)} lazer songs to cache...")
        save_cache(self.lazer_dir, songs, source="lazer")
        self.progress_update.emit(f"[osu!Lazer] ✅ Lazer import complete! ({len(songs)} songs)")
        self.done.emit(songs)
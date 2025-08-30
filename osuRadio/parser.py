import re
from pathlib import Path
from mutagen.mp3 import MP3
from .config import *

def read_osu_lines(path: str) -> list:
    for enc in ("utf-8", "utf-8-sig", "cp1251", "latin-1"):
        try:
            with open(path, encoding=enc) as f:
                return f.read().splitlines()
        except UnicodeDecodeError:
            continue
    with open(path, encoding="utf-8", errors="ignore") as f:
        return f.read().splitlines()

class OsuParser:
    @staticmethod
    def parse(path: str) -> dict:
        data = {
            "audio": "", "title": "", "artist": "", "mapper": "",
            "background": "", "length": 0,
            "osu_file": path, "folder": str(Path(path).parent)
        }
        for line in read_osu_lines(path):
            line = line.strip()
            if m := re.match(r'audiofilename\s*:\s*(.+)', line, re.IGNORECASE):
                data["audio"] = m.group(1).strip()
            elif line.lower().startswith("title:"):
                data["title"] = line.split(":", 1)[1].strip()
            elif line.lower().startswith("artist:"):
                data["artist"] = line.split(":", 1)[1].strip()
            elif line.lower().startswith("creator:"):
                data["mapper"] = line.split(":", 1)[1].strip()
            elif line.startswith("0,0") and not data["background"]:
                if bg := re.search(r'0,0,"([^"]+)"', line):
                    data["background"] = bg.group(1)
        try:
            mp3_path = Path(data["folder"]) / data["audio"]
            mp3 = MP3(str(mp3_path))
            data["length"] = int(mp3.info.length * 1000)
        except Exception:
            pass
        return data
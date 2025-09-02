import sys
import os
import platform
from pathlib import Path

# Paths
IS_WINDOWS = os.name == "nt"
BASE_PATH = Path(getattr(sys, "frozen", False) and sys.executable or __file__).resolve().parent
DATABASE_FILE = BASE_PATH / "songs.db"
SETTINGS_FILE = BASE_PATH / "settings.json"
CUSTOM_SONGS_PATH = BASE_PATH / "custom_songs"
CUSTOM_SONGS_PATH.mkdir(exist_ok=True)
EXPORT_STATE_FILE = BASE_PATH / "export_selected.json"

if IS_WINDOWS:
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    user32 = ctypes.windll.user32
else:
    user32 = None

WM_HOTKEY, MOD_NOREPEAT = 0x0312, 0x4000
VK_MEDIA_PLAY_PAUSE, VK_MEDIA_NEXT_TRACK, VK_MEDIA_PREV_TRACK = 0xB3, 0xB0, 0xB1

if getattr(sys, "frozen", False):
    ASSETS_PATH = Path(sys._MEIPASS)
    BASE_PATH = Path(sys.executable).parent  # For writing settings, DB
else:
    BASE_PATH = Path(__file__).parent
    ASSETS_PATH = BASE_PATH

if sys.platform == "darwin":
    ICON_FILE = "Osu!RadioIcon.icns"
elif sys.platform.startswith("linux"):
    ICON_FILE = "Osu!RadioIcon.png"
elif sys.platform.startswith("win"):
    ICON_FILE = "Osu!RadioIcon.ico"
else:
    ICON_FILE = "Osu!RadioIcon.png"  # fallback
    
ICON_PATH = ASSETS_PATH / ICON_FILE
IMG_PATH = ASSETS_PATH / "img"

# FFmpeg bin setup
def get_ffmpeg_bin_path():
    base = Path(__file__).resolve().parent / "ffmpeg_bin"
    system = platform.system().lower()
    if system == "windows":
        return base / "windows" / "bin" / "ffmpeg.exe"
    elif system == "darwin":
        return base / "macos" / "ffmpeg"
    elif system == "linux":
        return base / "linux" / "bin" / "ffmpeg"
    else:
        raise RuntimeError(f"Unsupported platform: {system}")
    
def get_yt_dlp_path():
    base = Path(__file__).resolve().parent / "ffmpeg_bin"
    system = platform.system().lower()
    if system == "windows":
        return base / "windows" / "bin" / "yt-dlp.exe"
    elif system == "darwin":
        return base / "macos" / "yt-dlp"
    elif system == "linux":
        return base / "linux" / "bin" / "yt-dlp"
    else:
        raise RuntimeError(f"Unsupported platform: {system}")
import sys
import os
import platform
from pathlib import Path

# Paths & Environment
IS_WINDOWS = os.name == "nt"

# Base path for read/write (settings, db, songs, etc.)
if getattr(sys, "frozen", False):
    BASE_PATH = Path(sys.executable).parent
else:
    BASE_PATH = Path(__file__).resolve().parent

# PyInstaller unpack folder (read-only resources)
if getattr(sys, "frozen", False):
    ASSETS_PATH = Path(sys._MEIPASS)
else:
    ASSETS_PATH = BASE_PATH

def resource_path(*parts) -> Path:
    """
    Return an absolute path to a resource, working for both
    development and PyInstaller-frozen mode.
    """
    return ASSETS_PATH.joinpath(*parts)

# Files & folders
DATABASE_FILE      = BASE_PATH / "songs.db"
SETTINGS_FILE      = BASE_PATH / "settings.json"
CUSTOM_SONGS_PATH  = BASE_PATH / "custom_songs"
EXPORT_STATE_FILE  = BASE_PATH / "export_selected.json"
CUSTOM_SONGS_PATH.mkdir(exist_ok=True)

# DPI awareness (Windows only)
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

# Icon setup
if sys.platform == "darwin":
    ICON_FILE = "Osu!RadioIcon.icns"
elif sys.platform.startswith("linux"):
    ICON_FILE = "Osu!RadioIcon.png"
elif sys.platform.startswith("win"):
    ICON_FILE = "Osu!RadioIcon.ico"
else:
    ICON_FILE = "Osu!RadioIcon.png"  # fallback

ICON_PATH = resource_path(ICON_FILE)
IMG_PATH  = resource_path("img")

# External Binaries
def get_ffmpeg_bin_path():
    system = platform.system().lower()
    if system == "windows":
        return resource_path("ffmpeg_bin", "windows", "bin", "ffmpeg.exe")
    elif system == "darwin":
        return resource_path("ffmpeg_bin", "macos", "ffmpeg")
    elif system == "linux":
        return resource_path("ffmpeg_bin", "linux", "bin", "ffmpeg")
    else:
        raise RuntimeError(f"Unsupported platform: {system}")

def get_yt_dlp_path():
    system = platform.system().lower()
    if system == "windows":
        return resource_path("ffmpeg_bin", "windows", "bin", "yt-dlp.exe")
    elif system == "darwin":
        return resource_path("ffmpeg_bin", "macos", "yt-dlp")
    elif system == "linux":
        return resource_path("ffmpeg_bin", "linux", "bin", "yt-dlp")
    else:
        raise RuntimeError(f"Unsupported platform: {system}")
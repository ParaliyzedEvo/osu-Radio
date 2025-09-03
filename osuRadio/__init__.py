__version__ = "1.9.0b3"
__author__ = "Paraliyzed_evo"

from osuRadio.audio import PitchAdjustedPlayer, get_audio_duration
from osuRadio.db import load_cache, save_cache, get_audio_path
from osuRadio.settings import SettingsDialog
from osuRadio.ui import MarqueeLabel, BackgroundWidget
from osuRadio.update import check_for_update, download_and_install_update
from osuRadio.media_keys import update_media_key_listener
from osuRadio.msg import show_modal
from osuRadio.scanner import LibraryScanner
from osuRadio.config import (BASE_PATH, DATABASE_FILE, SETTINGS_FILE,
                            CUSTOM_SONGS_PATH, EXPORT_STATE_FILE, ICON_PATH,
                            IMG_PATH, get_yt_dlp_path, IS_WINDOWS)

__all__ = ["PitchAdjustedPlayer", "get_audio_duration", "load_cache", "save_cache", "get_audio_path", "SettingsDialog",
           "MarqueeLabel", "BackgroundWidget", "check_for_update", "download_and_install_update", "update_media_key_listener",
           "show_modal", "LibraryScanner", "BASE_PATH", "DATABASE_FILE", "SETTINGS_FILE", "IS_WINDOWS",
            "CUSTOM_SONGS_PATH", "EXPORT_STATE_FILE", "ICON_PATH", "IMG_PATH", "get_yt_dlp_path","__version__"]
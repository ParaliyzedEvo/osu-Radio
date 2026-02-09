__version__ = "1.9.2b2"
__author__ = "Paraliyzed_evo"

# Audio
from osuRadio.audio import PitchAdjustedPlayer, get_audio_duration, PlayerMixin

# Database
from osuRadio.db import load_cache, save_cache, get_audio_path, remove_missing_songs, validate_cache, update_folder_mtime

# Settings & UI
from osuRadio.settings import SettingsDialog, SettingsMixin
from osuRadio.ui import MarqueeLabel, BackgroundWidget, UiMixin

# System
from osuRadio.update import check_for_update, download_and_install_update, UpdateMixin
from osuRadio.media_keys import update_media_key_listener
from osuRadio.msg import show_modal

# Features
from osuRadio.custom_songs import CustomSongsMixin
from osuRadio.scanner import LibraryScanner, LibraryMixin
from osuRadio.context_menu import ContextMenuMixin

# Config
from osuRadio.config import (
    BASE_PATH, DATABASE_FILE, SETTINGS_FILE, CUSTOM_SONGS_PATH,
    EXPORT_STATE_FILE, ICON_PATH, IMG_PATH, get_yt_dlp_path, IS_WINDOWS
)

__all__ = [
    # Audio
    "PitchAdjustedPlayer", "get_audio_duration", "PlayerMixin",

    # Database
    "load_cache", "save_cache", "get_audio_path", "remove_missing_songs", "validate_cache", "update_folder_mtime",

    # Settings & UI
    "SettingsDialog", "SettingsMixin", "MarqueeLabel", "BackgroundWidget", "UiMixin",

    # System
    "check_for_update", "download_and_install_update", "UpdateMixin", "update_media_key_listener", "show_modal",

    # Features
    "CustomSongsMixin", "LibraryScanner", "LibraryMixin", "ContextMenuMixin",

    # Config
    "BASE_PATH", "DATABASE_FILE", "SETTINGS_FILE", "CUSTOM_SONGS_PATH",
    "EXPORT_STATE_FILE", "ICON_PATH", "IMG_PATH", "get_yt_dlp_path", "IS_WINDOWS",
]

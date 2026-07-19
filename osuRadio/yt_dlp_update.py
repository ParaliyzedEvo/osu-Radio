# yt_dlp_update.py
import os
import json
import platform
import shutil
import requests
from PySide6.QtCore import QThread, Signal

from osuRadio.config import get_yt_dlp_path, SETTINGS_FILE, IS_WINDOWS

YT_DLP_API_URL = "https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest"

YT_DLP_DOWNLOAD_URLS = {
    "windows": "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe",
    "darwin":  "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp_macos",
    "linux":   "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp_linux",
}


def get_installed_yt_dlp_version() -> str:
    if not SETTINGS_FILE.exists():
        return ""
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f).get("yt_dlp_version", "")
    except Exception:
        return ""


def _set_installed_yt_dlp_version(tag: str):
    # Read-modify-write against the existing file so we don't clobber settings the main window has already saved (or is about to save).
    settings = {}
    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                settings = json.load(f)
        except Exception as e:
            print(f"[yt-dlp update] Failed to read settings.json: {e}")

    settings["yt_dlp_version"] = tag

    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
    except Exception as e:
        print(f"[yt-dlp update] Failed to write settings.json: {e}")


def check_latest_yt_dlp_tag():
    """Returns the latest GitHub release tag_name, or None on failure."""
    try:
        resp = requests.get(YT_DLP_API_URL, timeout=5)
        resp.raise_for_status()
        return resp.json().get("tag_name")
    except Exception as e:
        print(f"[yt-dlp update] Failed to check for updates: {e}")
        return None


def download_yt_dlp(latest_tag: str) -> bool:
    system = platform.system().lower()
    url = YT_DLP_DOWNLOAD_URLS.get(system)
    if not url:
        print(f"[yt-dlp update] Unsupported platform: {system}")
        return False

    dest = get_yt_dlp_path()
    tmp_dest = dest.with_name(dest.name + ".tmp")

    try:
        with requests.get(url, stream=True, timeout=30, allow_redirects=True) as r:
            r.raise_for_status()
            with open(tmp_dest, "wb") as f:
                shutil.copyfileobj(r.raw, f)

        tmp_dest.replace(dest)

        if not IS_WINDOWS:
            os.chmod(dest, 0o755)

        _set_installed_yt_dlp_version(latest_tag)
        print(f"[yt-dlp update] Updated yt-dlp to {latest_tag}")
        return True

    except Exception as e:
        print(f"[yt-dlp update] Download failed: {e}")
        if tmp_dest.exists():
            try:
                tmp_dest.unlink()
            except Exception:
                pass
        return False


def check_and_update_yt_dlp():
    # Checks GitHub for the latest yt-dlp release and downloads it only if we don't already have a matching local version.
    latest_tag = check_latest_yt_dlp_tag()
    if not latest_tag:
        return

    installed = get_installed_yt_dlp_version()
    binary_exists = get_yt_dlp_path().exists()

    if binary_exists and installed == latest_tag:
        print(f"[yt-dlp update] Already up to date ({installed})")
        return

    print(f"[yt-dlp update] {'Installing' if not binary_exists else 'Updating'} yt-dlp -> {latest_tag}")
    download_yt_dlp(latest_tag)


class YtDlpUpdateThread(QThread):
    # Runs the check/download off the UI thread so startup doesn't block on a network call.
    finished_update = Signal(str)

    def run(self):
        check_and_update_yt_dlp()
        self.finished_update.emit(get_installed_yt_dlp_version())
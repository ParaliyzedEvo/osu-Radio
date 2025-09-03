import sys
import os
import json
import requests
import zipfile
import tarfile
import tempfile
import shutil
import subprocess
import tempfile
from dateutil import parser as date_parser
from packaging import version
from PySide6.QtCore import (
    Qt
)
from PySide6.QtGui import (
    QIcon
)
from PySide6.QtWidgets import (
    QApplication, QMessageBox, QProgressDialog
)
from osuRadio.config import ICON_PATH, BASE_PATH
from osuRadio.msg import show_modal

def check_for_update(current_version, skipped_versions=None, manual_check=False, include_prerelease=False):
    url = "https://api.github.com/repos/Paraliyzedevo/osu-Radio/releases"
    try:
        releases = requests.get(url, timeout=5).json()
        valid = []
        current_parsed = version.parse(current_version.lstrip("v"))

        for r in releases:
            tag = r.get("tag_name", "").lstrip("v")
            created = r.get("created_at")
            is_prerelease = r.get("prerelease", False)

            if not tag:
                continue
            if not manual_check and skipped_versions and tag in skipped_versions:
                continue
            if is_prerelease and not include_prerelease:
                continue
            if '+' in tag and not include_prerelease:
                continue

            try:
                parsed_tag = version.parse(tag)
                created_at = date_parser.parse(created)
                valid.append((parsed_tag, is_prerelease, '+' in tag, created_at, r))
            except Exception:
                continue

        if not valid:
            return None, None

        # Sort by: newest date, stable > pre, no local > local, then version (tie-breaker)
        valid.sort(key=lambda v: (v[3], not v[1], not v[2], v[0]), reverse=True)
        latest_ver, _, _, _, latest_data = valid[0]

        if current_parsed < latest_ver:
            return str(latest_ver), latest_data.get("assets", [])
    except Exception as e:
        print(f"[check_for_update] Failed: {e}")
    return None, None

def download_and_install_update(assets, latest_version, skipped_versions, settings_path, main_window=None):
    platform = sys.platform
    url = None

    for asset in assets:
        name = asset["name"].lower()
        if platform.startswith("win") and name.endswith(".zip"):
            url = asset["browser_download_url"]
        elif platform == "darwin" and (name.endswith(".dmg") or name.endswith(".pkg")):
            url = asset["browser_download_url"]
        elif platform.startswith("linux") and name.endswith(".tar.gz"):
            url = asset["browser_download_url"]
        if url:
            break

    if not url:
        QMessageBox.information(None, "Update", "No suitable update found.")
        return

    msg = QMessageBox()
    msg.setWindowTitle("Update Available")
    msg.setText(f"Version {latest_version} is available. Do you want to update?")
    msg.setWindowIcon(QIcon(str(ICON_PATH)))
    update_btn = msg.addButton("Update Now", QMessageBox.AcceptRole)
    remind_btn = msg.addButton("Remind Me Later", QMessageBox.RejectRole)
    skip_btn = msg.addButton("Skip This Version", QMessageBox.DestructiveRole)
    show_modal(msg)

    if msg.clickedButton() == skip_btn:
        if latest_version not in skipped_versions:
            skipped_versions.append(latest_version)
        # Save immediately
        try:
            with open(settings_path, "r+") as f:
                settings = json.load(f)
                existing = settings.get("skipped_versions", [])
                if latest_version not in existing:
                    existing.append(latest_version)
                    settings["skipped_versions"] = existing
                    f.seek(0)
                    json.dump(settings, f, indent=2)
                    f.truncate()
        except Exception as e:
            print("Failed to save skipped version:", e)
        return

    if msg.clickedButton() != update_btn:
        if main_window:
            main_window.skip_downgrade_for_now = True
        return

    # Proceed with update
    temp_dir = tempfile.mkdtemp()
    file_path = os.path.join(temp_dir, os.path.basename(url))
    with requests.get(url, stream=True) as r:
        with open(file_path, "wb") as f:
            total = int(r.headers.get('content-length', 0))
            progress = QProgressDialog("Downloading update...", "Cancel", 0, total)
            progress.setWindowModality(Qt.ApplicationModal)
            progress.setWindowTitle("osu!Radio Updater")
            progress.setWindowIcon(QIcon(str(ICON_PATH)))
            progress.setMinimumWidth(400)
            progress.show()

            downloaded = 0
            for chunk in r.iter_content(chunk_size=8192):
                if not chunk:
                    continue
                f.write(chunk)
                downloaded += len(chunk)
                progress.setValue(downloaded)
                QApplication.processEvents()
                if progress.wasCanceled():
                    QMessageBox.information(None, "Update Cancelled", "The update was cancelled.")
                    return
            progress.close()

    extract_dir = tempfile.mkdtemp()
    if file_path.endswith(".zip"):
        with zipfile.ZipFile(file_path, "r") as zip_ref:
            zip_ref.extractall(extract_dir)
    elif file_path.endswith(".tar.gz"):
        with tarfile.open(file_path, "r:gz") as tar_ref:
            tar_ref.extractall(extract_dir)
    else:
        QMessageBox.information(
            None,
            "Manual Install Required",
            f"The downloaded file ({os.path.basename(file_path)}) is a macOS installer.\n\n"
            "1. Double-click the .dmg or .pkg file to open it.\n"
            "2. Follow the on-screen instructions to complete the update.\n\n"
            f"3. Close program (if you haven't done so) and replace all files with the new files downloaded on {file_path}"
            f"File saved to: {file_path}"
        )
        return

    # Look inside nested structure (like dist/osu!Radio/)
    subdir = None
    for root, dirs, files in os.walk(extract_dir):
        for file in files:
            if file.lower() == "osu!radio.exe":
                subdir = root
                break
        if subdir:
            break

    if not subdir:
        QMessageBox.warning(None, "Update Failed", "Could not find osu!Radio.exe in the extracted files.")
        return

    msg = QMessageBox()
    msg.setIcon(QMessageBox.Information)
    msg.setWindowTitle("Restarting")
    msg.setText("osu!Radio will now restart with the update applied.")
    msg.setStandardButtons(QMessageBox.Ok)
    show_modal(msg)
    ret = msg.result()

    if ret == QMessageBox.Ok:
        if getattr(sys, 'frozen', False):
            if sys.platform.startswith("win"):
                updater = os.path.join(sys._MEIPASS, "updater.exe")
            elif sys.platform.startswith("linux"):
               updater = os.path.join(sys._MEIPASS, "updater") 
        else:
            if sys.platform.startswith("win"):
                updater = os.path.join(BASE_PATH, "updater.exe")
            elif sys.platform.startswith("linux"):
               updater = os.path.join(BASE_PATH, "updater")
               
        if sys.platform.startswith("linux"):
            os.chmod(updater, 0o755)
            
        if sys.platform.startswith("win"):
            exe = "osu!Radio.exe"
        elif sys.platform.startswith("linux"):
            exe = "osu!Radio"

        temp_updater = tempfile.NamedTemporaryFile(delete=False, suffix=".exe").name
        shutil.copy2(updater, temp_updater)

        subprocess.Popen([
            temp_updater,
            subdir, str(BASE_PATH), exe, str(os.getpid())
        ])
        shutil.rmtree(temp_dir, ignore_errors=True)
        sys.exit(0)
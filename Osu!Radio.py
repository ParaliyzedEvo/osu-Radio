__version__ = "1.7.0b3"

import sys
import os
import re
import json
import random
import sqlite3
import requests
import zipfile
import tarfile
import tempfile
import shutil
import subprocess
import tempfile
import ffmpeg
import platform
import atexit
import wave
from datetime import datetime
from dateutil import parser as date_parser
from packaging import version
from pathlib import Path
from mutagen.mp3 import MP3
from time import monotonic
from PySide6.QtCore import (
    Qt, QUrl, QTimer, QThread, QMetaObject,
    QPropertyAnimation, QEasingCurve, Property,
    QSequentialAnimationGroup, QPauseAnimation, Signal,
    QEvent, QIODevice, QBuffer, QByteArray, QObject, QFile
)
from PySide6.QtGui import (
    QIcon, QPixmap, QPainter, QColor,
    QKeySequence, QShortcut, QCursor,
    QGuiApplication
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, QFileDialog,
    QHBoxLayout, QVBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLineEdit, QSlider, QStyle, QStackedLayout,
    QDialog, QDialogButtonBox, QCheckBox, QComboBox,
    QGraphicsOpacityEffect, QGraphicsColorizeEffect,
    QMenu, QGridLayout, QSplitter, QToolTip, QSizePolicy,
    QMessageBox, QProgressDialog
)
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput, QVideoSink, QAudioSink, QAudioFormat, QMediaDevices, QAudio

# Paths
IS_WINDOWS = os.name == "nt"
BASE_PATH = Path(getattr(sys, "frozen", False) and sys.executable or __file__).resolve().parent
DATABASE_FILE = BASE_PATH / "songs.db"
SETTINGS_FILE = BASE_PATH / "settings.json"

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

# === FFmpeg bin setup ===
def get_ffmpeg_bin_path():
    base_dir = Path(__file__).resolve().parent / "ffmpeg_bin"
    system = platform.system().lower()
    if system == "windows":
        return base_dir / "windows" / "bin" / "ffmpeg.exe"
    elif system == "darwin":
        return base_dir / "macos" / "ffmpeg"
    elif system == "linux":
        return base_dir / "linux" / "bin" / "ffmpeg"
    else:
        raise RuntimeError(f"Unsupported platform: {system}")

ffmpeg_path = str(get_ffmpeg_bin_path())

# Monkey-patch ffmpeg-python to use custom ffmpeg binary
ffmpeg._run.FFmpeg = lambda *args, **kwargs: subprocess.Popen(
    [ffmpeg_path, *args[1:]],
    **kwargs
)

try:
    out = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, check=True)
    print("[Debug] ffmpeg found:", out.stdout.splitlines()[0])
except Exception as e:
    print("[Error] ffmpeg NOT found in PATH!", e)

# Utility functions
def get_audio_path(song: dict) -> Path:
    return Path(song["folder"]) / song["audio"]
    
def init_db():
    with sqlite3.connect(DATABASE_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS songs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                artist TEXT,
                mapper TEXT,
                audio TEXT,
                background TEXT,
                length INTEGER,
                osu_file TEXT,
                folder TEXT,
                UNIQUE(title, artist, mapper)
            )""")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT
            )""")
        conn.commit()
        
def load_cache(folder: str) -> list | None:
    if not DATABASE_FILE.exists():
        return None
    try:
        with sqlite3.connect(DATABASE_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM metadata WHERE key = 'folder_mtime'")
            mtime = cursor.fetchone()
            if mtime and mtime[0] == str(os.path.getmtime(folder)):
                cursor.execute("SELECT title, artist, mapper, audio, background, length, osu_file, folder FROM songs")
                return [
                    dict(zip(["title", "artist", "mapper", "audio", "background", "length", "osu_file", "folder"], row))
                    for row in cursor.fetchall()
                ]
    except Exception as e:
        print(f"[load_cache] Error: {e}")
    return None
    
def save_cache(folder: str, maps: list):
    init_db()
    try:
        with sqlite3.connect(DATABASE_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("BEGIN TRANSACTION")
            for s in maps:
                cursor.execute("""
                    INSERT OR REPLACE INTO songs
                    (title, artist, mapper, audio, background, length, osu_file, folder)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)""", (
                        s.get("title"), s.get("artist"), s.get("mapper"),
                        s.get("audio"), s.get("background"), s.get("length", 0),
                        s.get("osu_file"), s.get("folder")
                    ))
            cursor.execute("INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
                           ('folder_mtime', str(os.path.getmtime(folder))))
            conn.commit()
    except Exception as e:
        print(f"[save_cache] Error: {e}")
        
def read_osu_lines(path: str) -> list:
    for enc in ("utf-8", "utf-8-sig", "cp1251", "latin-1"):
        try:
            with open(path, encoding=enc) as f:
                return f.read().splitlines()
        except UnicodeDecodeError:
            continue
    with open(path, encoding="utf-8", errors="ignore") as f:
        return f.read().splitlines()
        
def get_audio_duration(file_path):
    try:
        probe = ffmpeg.probe(str(file_path))
        duration = float(probe['format']['duration'])
        return duration
    except Exception as e:
        print(f"Error getting duration: {e}")
        return None


def process_audio(input_file, speed=1.0, adjust_pitch=False, cache_dir=None):
    input_path = Path(input_file)
    if cache_dir is None:
        cache_dir = Path(tempfile.gettempdir()) / "OsuRadioCache"
    cache_dir.mkdir(exist_ok=True)

    base_name = input_path.stem
    suffix = f"{speed:.2f}x_pitch" if adjust_pitch else f"{speed:.2f}x"
    output_file = cache_dir / f"{base_name}_{suffix}.wav"

    if output_file.exists():
        return output_file, get_audio_duration(output_file)

    print(f"[FFmpeg] Processing '{input_file}' → '{output_file}' with speed={speed}, pitch_adjust={adjust_pitch}")

    stream = ffmpeg.input(str(input_file))

    if speed == 1.0:
        stream.output(str(output_file), format='wav', acodec="pcm_s16le", ac=2, ar=44100).run(overwrite_output=True)
    else:
        if adjust_pitch:
            remaining = speed
            while remaining < 0.5 or remaining > 2.0:
                factor = 0.5 if remaining < 0.5 else 2.0
                stream = stream.filter('atempo', factor)
                remaining /= factor
            stream = stream.filter('atempo', remaining)
        else:
            stream = stream.filter('rubberband', tempo=speed)

        stream.output(str(output_file), acodec="pcm_s16le", ac=2, ar=44100).run(overwrite_output=True)

    return output_file, get_audio_duration(output_file)
        
class PitchAdjustedPlayer:
    def __init__(self, audio_output: QAudioOutput, parent=None):
        self.player = QMediaPlayer(parent)
        self.player.setAudioOutput(audio_output)
        self._last_path = None
        self.audio_output = audio_output
        self.current_temp = None
        self.last_temp = None
        self.playback_rate = 1.0
        self.preserve_pitch = True  # default toggle state (set externally)
        
    def _get_wav_duration_ms(self, path):
        try:
            if path.endswith(".wav"):
                with wave.open(path, 'rb') as wf:
                    frames = wf.getnframes()
                    rate = wf.getframerate()
                    return int((frames / rate) * 1000)
            else:
                duration = get_audio_duration(path)
                return int(duration * 1000) if duration else 0
        except Exception as e:
            print(f"[Duration Error] Could not get duration for {path}: {e}")
            return 0

    def play(self, input_path: str, speed: float = 1.0, preserve_pitch: bool = True, start_ms: int = 0):
        # Smart resume check: skip reprocessing if already loaded
        if (
            self.player.mediaStatus() == QMediaPlayer.LoadedMedia
            and self._last_path == input_path
            and self.playback_rate == speed
            and self.preserve_pitch == preserve_pitch
        ):
            print(f"[Resume] Resuming existing playback at {self.player.position()} ms")
            if start_ms > 0:
                self.player.setPosition(start_ms)
            self.player.play()
            return

        self._last_path = input_path
        self.preserve_pitch = preserve_pitch
        self.playback_rate = speed

        print(f"[Debug] Speed={speed}, PitchAdjust={not preserve_pitch}, Seek={start_ms}")

        if preserve_pitch:
            processed_file, _ = process_audio(input_path, speed=speed, adjust_pitch=True)
            file_url = QUrl.fromLocalFile(str(processed_file))
            self.player.setSource(file_url)
            self.current_temp = Path(processed_file)
        else:
            file_url = QUrl.fromLocalFile(str(input_path))
            self.player.setSource(file_url)
            self.player.setPlaybackRate(speed)
            self.current_temp = None

        self.last_duration = self._get_wav_duration_ms(file_url.toLocalFile())

        if start_ms > 0:
            self.player.setPosition(start_ms)

        self.player.play()
        print(f"[QMediaPlayer] 🎵 Now playing: {file_url.toString()}")

        # Delete the last file if safe
        if self.last_temp and self.last_temp.exists() and self.last_temp != self.current_temp:
            try:
                os.remove(self.last_temp)
                print(f"[Cleanup] Deleted old cache: {self.last_temp}")
            except Exception as e:
                print(f"[Cleanup Error] Could not delete {self.last_temp}: {e}")

        self.last_temp = self.current_temp

    def stop(self):
        self.player.stop()
        if self.current_temp and os.path.exists(self.current_temp):
            # Avoid deleting if it's still the current one in use
            if self.current_temp != self.last_temp:
                try:
                    os.remove(self.current_temp)
                    print(f"[Stop] Deleted current temp: {self.current_temp}")
                except Exception as e:
                    print(f"[Stop] Failed to delete {self.current_temp}: {e}")
                    
        self.current_temp = None
        
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
    msg.exec()

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

    ret = QMessageBox.information(
        None,
        "Restarting",
        "osu!Radio will now restart with the update applied.",
        QMessageBox.Ok
    )

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

class LibraryScanner(QThread):
    done = Signal(list)
    progress_update = Signal(str)

    def __init__(self, folder):
        super().__init__()
        self.folder = folder

    def run(self):
        uniq = {}
        print(f"[LibraryScanner] Starting scan for folder: {self.folder}")
        for root, _, files in os.walk(self.folder):
            if self.isInterruptionRequested():
                print("[LibraryScanner] Interruption requested, stopping scan (outer loop).")
                return
            for fn in files:
                if self.isInterruptionRequested():
                    print("[LibraryScanner] Interruption requested, stopping scan (inner loop).")
                    return
                if fn.lower().endswith(".osu"):
                    full_path = os.path.join(root, fn)
                    try:
                        s = OsuParser.parse(full_path)
                        title = s.get("title", f"Unknown Title - {fn}")
                        artist = s.get("artist", "Unknown Artist")
                        mapper = s.get("mapper", "Unknown Mapper")
                        key = (title, artist, mapper)
                        if key not in uniq:
                            uniq[key] = s
                            msg = f"🎵 Found beatmap: {s['artist']} - {s['title']}"
                            self.progress_update.emit(msg)
                    except Exception as e:
                        print(f"[LibraryScanner] Error parsing {full_path}: {e}")

        if self.isInterruptionRequested():
            print("[LibraryScanner] Interruption requested before saving cache.")
            return

        library = list(uniq.values())
        print(f"[LibraryScanner] Scan complete. Found {len(library)} unique beatmaps.")
        save_cache(self.folder, library)

        if self.isInterruptionRequested():
            print("[LibraryScanner] Interruption requested before emitting 'done' signal.")
            return

        self.done.emit(library)
        print("[LibraryScanner] 'done' signal emitted.")

class MarqueeLabel(QLabel):
    def __init__(self, *args):
        super().__init__(*args)
        self._offset = 0
        self._anim = QSequentialAnimationGroup(self)

    def setText(self, txt):
        super().setText(txt)
        fm = self.fontMetrics()
        text_w = fm.horizontalAdvance(txt)
        avail = self.width()
        self._anim.stop()
        self._offset = 0

        if text_w > avail:
            span = text_w - avail + 20
            a1 = QPropertyAnimation(self, b"offset", self)
            a1.setStartValue(0)
            a1.setEndValue(span)
            a1.setDuration(span * 20)
            a1.setEasingCurve(QEasingCurve.Linear)

            p1 = QPauseAnimation(1000, self)

            a2 = QPropertyAnimation(self, b"offset", self)
            a2.setStartValue(span)
            a2.setEndValue(0)
            a2.setDuration(span * 20)
            a2.setEasingCurve(QEasingCurve.Linear)

            p2 = QPauseAnimation(1000, self)

            self._anim.clear()
            self._anim.addAnimation(a1)
            self._anim.addAnimation(p1)
            self._anim.addAnimation(a2)
            self._anim.addAnimation(p2)
            self._anim.setLoopCount(-1)
            self._anim.start()
        else:
            self.update()

    def paintEvent(self, ev):
        painter = QPainter(self)
        painter.setClipRect(self.rect())
        painter.drawText(-self._offset, self.height() - 5, self.text())

    def offset(self): return self._offset
    def setOffset(self, v): self._offset = v; self.update()
    offset = Property(int, offset, setOffset)

class BackgroundWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._raw_frame = None
        self._pixmap = QPixmap()
        self._last_size = self.size()
        self.effect = QGraphicsColorizeEffect(self)
        self.effect.setStrength(1.0)
        self.setGraphicsEffect(self.effect)

        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.timeout.connect(self._rescale_pixmap)

    def setFrame(self, frame):
        self._raw_frame = frame
        self._last_size = self.size()
        img = frame.toImage()
        self._pixmap = QPixmap.fromImage(img).scaled(
            self.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
        )
        self.update()

    def resizeEvent(self, event):
        if self._raw_frame and self.size() != self._last_size:
            self._resize_timer.start(69)
        super().resizeEvent(event)

    def _rescale_pixmap(self):
        if self._raw_frame:
            self._last_size = self.size()
            img = self._raw_frame.toImage()
            self._pixmap = QPixmap.fromImage(img).scaled(
                self.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
            )
            self.update()

    def paintEvent(self, ev):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)

        painter.drawPixmap(0, 0, self._pixmap)

        # If the QGraphicsColorizeEffect is not active, apply hue manually
        if not self.effect.isEnabled():
            hue_color = self.effect.color()
            overlay = QColor.fromHsv(hue_color.hue(), 255, 255)
            overlay.setAlphaF(self.effect.strength())
            painter.setCompositionMode(QPainter.CompositionMode_Multiply)
            painter.fillRect(self.rect(), overlay)

        painter.end()

class SettingsDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setFixedSize(400, 350)
        self.main = parent

        layout = QVBoxLayout(self)

        # Songs folder selection
        self.folder_edit = QLineEdit(parent.osu_folder)
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self.browse_folder)

        folder_layout = QHBoxLayout()
        folder_layout.addWidget(QLabel("Songs Folder:"))
        folder_layout.addWidget(self.folder_edit)
        folder_layout.addWidget(browse_btn)
        layout.addLayout(folder_layout)

        # Toggles
        self.light_mode_checkbox = QCheckBox("Light Mode")
        self.video_checkbox = QCheckBox("Enable Background Video")
        self.autoplay_checkbox = QCheckBox("Autoplay on Startup")
        self.media_key_checkbox = QCheckBox("Enable Media Key Support")
        self.pitch_checkbox = QCheckBox("Preserve Original Pitch")
        self.prerelease_checkbox = QCheckBox("Include Pre-release Updates")

        self.light_mode_checkbox.setChecked(parent.light_mode)
        self.video_checkbox.setChecked(parent.video_enabled)
        self.autoplay_checkbox.setChecked(parent.autoplay)
        self.media_key_checkbox.setChecked(parent.media_keys_enabled)
        self.pitch_checkbox.setChecked(parent.preserve_pitch)
        self.prerelease_checkbox.setChecked(parent.allow_prerelease)

        for checkbox in (
            self.light_mode_checkbox, self.video_checkbox, self.autoplay_checkbox,
            self.media_key_checkbox, self.pitch_checkbox, self.prerelease_checkbox
        ):
            layout.addWidget(checkbox)

        # Opacity slider
        self.opacity_slider = QSlider(Qt.Horizontal)
        self.opacity_slider.setRange(10, 100)
        self.opacity_slider.setValue(int(parent.ui_opacity * 100))
        self.opacity_slider.valueChanged.connect(
            lambda v: parent.ui_effect.setOpacity(v / 100)
        )

        opacity_layout = QHBoxLayout()
        opacity_layout.addWidget(QLabel("UI Opacity:"))
        opacity_layout.addWidget(self.opacity_slider)
        layout.addLayout(opacity_layout)

        # Hue slider
        self.hue_slider = QSlider(Qt.Horizontal)
        self.hue_slider.setRange(0, 360)
        self.hue_slider.setValue(parent.hue)
        self.hue_slider.valueChanged.connect(
            lambda v: parent.bg_widget.effect.setColor(QColor.fromHsv(v, 255, 255))
        )

        hue_layout = QHBoxLayout()
        hue_layout.addWidget(QLabel("Hue:"))
        hue_layout.addWidget(self.hue_slider)
        layout.addLayout(hue_layout)

        # Resolution dropdown
        self.res_combo = QComboBox()
        self.resolutions = {
            "1920×1080": (1920, 1080),
            "1280×720": (1280, 720),
            "854×480": (854, 480),
            "640×360": (640, 360),
            "480×270": (480, 270),
        }
        self.res_combo.addItems(self.resolutions)
        current_res = f"{parent.width()}×{parent.height()}"
        if current_res in self.resolutions:
            self.res_combo.setCurrentText(current_res)

        res_layout = QHBoxLayout()
        res_layout.addWidget(QLabel("Resolution:"))
        res_layout.addWidget(self.res_combo)
        layout.addLayout(res_layout)

        # Update button
        update_btn = QPushButton("Check for Updates")
        update_btn.clicked.connect(lambda: parent.check_updates(manual=True))
        layout.addWidget(update_btn)

        # Buttons
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.apply)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        # Preview state backup
        self._original_opacity = parent.ui_opacity
        self._original_hue = parent.hue

    def browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select osu! Songs Folder")
        if folder:
            self.folder_edit.setText(folder)

    def apply(self):
        folder = self.folder_edit.text()
        light = self.light_mode_checkbox.isChecked()
        opacity = self.opacity_slider.value() / 100
        hue = self.hue_slider.value()
        res = self.res_combo.currentText()
        w, h = self.resolutions.get(res, (854, 480))
        video_on = self.video_checkbox.isChecked()
        autoplay = self.autoplay_checkbox.isChecked()
        media_keys = self.media_key_checkbox.isChecked()
        preserve_pitch = self.pitch_checkbox.isChecked()
        allow_prerelease = self.prerelease_checkbox.isChecked()

        was_prerelease = self.main.allow_prerelease
        self.main.apply_settings(
            folder, light, opacity, w, h, hue,
            video_on, autoplay, media_keys, preserve_pitch, allow_prerelease
        )

        if was_prerelease != allow_prerelease:
            self.main.skip_downgrade_for_now = False
            self.main.check_updates(manual=True)

        self.accept()

    def reject(self):
        self.main.ui_effect.setOpacity(self._original_opacity)
        self.main.bg_widget.effect.setColor(QColor.fromHsv(self._original_hue, 255, 255))
        self.main.ui_opacity = self._original_opacity
        self.main.hue = self._original_hue
        super().reject()
        
class MainWindow(QMainWindow):
    def __init__(self):  
        super().__init__()
        
        self.library = []
        self.queue   = []
        self.current_index = 0
        self.media_key_listener = None
            
        self.setWindowIcon(QIcon(str(ICON_PATH)))
        
        self.setWindowTitle(f"osu!Radio v{__version__}")
        self.aspect_ratio = 16 / 9
        self.loop_mode = 0
        geom = QGuiApplication.primaryScreen().availableGeometry()
        min_w, min_h = 480, int(480 / self.aspect_ratio)
        max_w, max_h = min(1920, geom.width()), min(1080, geom.height())
        self.setMinimumSize(min_w, min_h)
        self.setMaximumSize(max_w, max_h)

        # Load settings
        first_setup = not SETTINGS_FILE.exists()
        settings = self.load_user_settings()

        # Apply defaults if missing
        self.osu_folder          = settings.get("osu_folder")
        if not self.osu_folder:
            self.osu_folder = QFileDialog.getExistingDirectory(self, "Select osu! Songs Folder")
            first_time_setup = True  # Force scan after folder selection
            if not self.osu_folder:
                sys.exit()
        if not self.osu_folder:
            sys.exit()

        self.light_mode         = settings.get("light_mode", False)
        self.ui_opacity         = settings.get("ui_opacity", 0.75)
        self.hue                = settings.get("hue", 240)
        self.loop_mode          = settings.get("loop_mode", 0)
        self.video_enabled      = settings.get("video_enabled", True)
        self.autoplay           = settings.get("autoplay", False)
        self.media_keys_enabled = settings.get("media_keys_enabled", True)
        self.vol                = settings.get("volume", 30)
        self.preserve_pitch     = settings.get("preserve_pitch", True)
        self.allow_prerelease   = settings.get("allow_prerelease", False)
        self.was_prerelease     = settings.get("was_prerelease", False)
        self.skipped_versions   = settings.get("skipped_versions", [])
        res                     = settings.get("resolution", "854×480")
        rw, rh = (854, 480)
        if res and "×" in res:
            try:
                rw, rh = map(int, res.split("×"))
            except:
                pass
        w = max(min_w, min(rw, max_w))
        h = max(min_h, min(rh, max_h))
        self.setFixedSize(w, h)

        if not self.osu_folder or not os.path.isdir(self.osu_folder):
            self.osu_folder = QFileDialog.getExistingDirectory(self, "Select osu! Songs Folder")
            if not self.osu_folder:
                sys.exit()
        
        self.save_user_settings()
        
        self.downgrade_prompted = False
        self.skip_downgrade_for_now = False
        
        if (
            settings.get("was_prerelease", False)
            and not self.allow_prerelease
            and self.is_prerelease_version(__version__)
            and not self.downgrade_prompted
        ):
            self.downgrade_prompted = True
            choice = QMessageBox.question(
                self,
                "Return to Stable?",
                "You're currently on a pre-release build, but pre-release updates have been disabled.\n\n"
                "Would you like to return to the latest stable version?",
                QMessageBox.Yes | QMessageBox.No
            )
            if choice == QMessageBox.Yes:
                latest_version, assets = check_for_update(
                    current_version=__version__,
                    skipped_versions=self.skipped_versions,
                    manual_check=True,
                    include_prerelease=False
                )
                if latest_version:
                    download_and_install_update(assets, latest_version, self.skipped_versions, str(SETTINGS_FILE), self)
                else:
                    QMessageBox.information(self, "No Stable Update Found", "You're already on the most recent stable release.")
            else:
                self.skip_downgrade_for_now = True

        # Audio player
        def get_embedded_ffmpeg_path():
            base = os.path.abspath(os.path.join(os.path.dirname(__file__), "ffmpeg_bin"))
            system = platform.system()

            if system == "Windows":
                return os.path.join(base, "ffmpeg", "windows", "bin", "ffmpeg.exe")
            elif system == "Darwin":  # macOS
                return os.path.join(base, "ffmpeg", "macos", "ffmpeg")
            elif system == "Linux":
                return os.path.join(base, "ffmpeg", "linux", "bin", "ffmpeg")
            else:
                raise RuntimeError(f"Unsupported platform: {system}")
        self.setup_media_players()
        
        #ffmpeg_path = get_embedded_ffmpeg_path()
        #ffmpeg._ffmpeg_path = ffmpeg_path
        #ffmpeg._probe = os.path.join(os.path.dirname(ffmpeg_path), "ffprobe" + (".exe" if platform.system() == "Windows" else ""))
        #if platform.system() != "Windows":
        #    os.chmod(ffmpeg_path, 0o755)

        # Central + stacking
        central = QWidget(self)
        self.setCentralWidget(central)
        grid = QGridLayout(central)
        self.ui_effect = QGraphicsOpacityEffect(self.centralWidget())
        self.centralWidget().setGraphicsEffect(self.ui_effect)
        grid.setContentsMargins(0, 0, 0, 0)

        # Background video widget
        self.bg_widget = BackgroundWidget(central)
        self.bg_widget.main = self
        self.bg_widget.setAttribute(Qt.WA_TransparentForMouseEvents)
        grid.addWidget(self.bg_widget, 0, 0)

        # UI overlay
        left = QWidget(central)
        ll = QVBoxLayout(left)
        self.ui_effect = QGraphicsOpacityEffect(left)
        left.setGraphicsEffect(self.ui_effect)

        tl = QHBoxLayout()
        self.queue_lbl = QLabel(f"Queue: {len(self.queue)} songs")
        tl.addWidget(self.queue_lbl, 1)

        self.search = QLineEdit(); self.search.setPlaceholderText("Search…")
        self.search.textChanged.connect(self.filter_list)
        tl.addWidget(self.search, 2)

        btn_set = QPushButton()
        btn_set.setIcon(self.style().standardIcon(QStyle.SP_FileDialogDetailedView))
        btn_set.clicked.connect(self.open_settings)
        tl.addWidget(btn_set)

        # Reload Maps button
        btn_reload = QPushButton("Reload Maps")
        btn_reload.setToolTip("Rescan osu! songs folder and update cache")
        btn_reload.clicked.connect(self.reload_songs)
        tl.addWidget(btn_reload)

        ll.addLayout(tl)

        self.song_list = QListWidget()
        self.song_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.song_list.customContextMenuRequested.connect(self.onSongContextMenu)
        self.song_list.itemDoubleClicked.connect(
            lambda itm: self.play_song_at_index(self.song_list.row(itm))
        )
        ll.addWidget(self.song_list)
        self.populate_list(self.queue)
        grid.addWidget(left, 0, 0)
        
        # bg = song.get('background', '')
        # p  = os.path.join(folder, bg)
        # Need this for later :P

        # Create bottom control layout
        bot = QHBoxLayout()

        # Volume slider + overlay
        vol = QSlider(Qt.Horizontal)
        vol.setRange(0, 100)
        vol.setValue(self.vol)
        self.volume_label = QLabel(f"{self.vol}%")
        self.volume_label.setVisible(True)
        vol.valueChanged.connect(self.set_volume)

        vol_widget = QWidget()
        vol_widget.setMinimumHeight(30)
        vol_widget.setMaximumHeight(30)
        vol_layout = QVBoxLayout(vol_widget)
        vol_layout.setContentsMargins(0, 0, 0, 0)
        vol_layout.setSpacing(0)
        vol_layout.addWidget(vol)

        self.volume_label.setParent(vol_widget)
        self.volume_label.move(vol_widget.width() - self.volume_label.width() - 7, -4)
        self.volume_label.raise_()
        self.volume_label.show()

        vol_widget.resizeEvent = lambda event: self.volume_label.move(
            vol_widget.width() - self.volume_label.width() - 7, -4
        )
        bot.addWidget(vol_widget, 1)

        # Seek slider + overlay
        class SeekSlider(QSlider):
            # Custom QSlider that supports click-to-seek behavior.
            seekRequested = Signal(int)

            def mousePressEvent(self, event):
                if event.button() == Qt.LeftButton:
                    x = event.position().x() if hasattr(event, "position") else event.x()
                    ratio = x / self.width()
                    new_val = int(ratio * self.maximum())
                    self.setValue(new_val)
                    self.seekRequested.emit(new_val)
                super().mousePressEvent(event)

        self.slider = SeekSlider(Qt.Horizontal)
        self.slider.seekRequested.connect(self.seek)
        self.connect_slider_signals()
        self.slider.setMouseTracking(True)
        self.slider.installEventFilter(self)
        self.slider.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.playback_timer = QTimer(self)
        self.playback_timer.setInterval(1000)
        self.playback_timer.timeout.connect(self._tick_seekbar)
        self._playback_start_time = None

        # Drag tracking logic
        self.slider.sliderPressed.connect(lambda: setattr(self, "_user_dragging", True))
        self.slider.sliderReleased.connect(lambda: (
            setattr(self, "_user_dragging", False),
            self.seek(self.slider.value())
        ))

        self.slider.valueChanged.connect(lambda v: (
            self.elapsed_label.setText(self.format_time(v))
            if getattr(self, "_user_dragging", False) else None
        ))

        self.elapsed_label = QLabel("0:00")
        self.total_label = QLabel("0:00")

        seek_widget = QWidget()
        seek_widget.setMinimumHeight(30)
        seek_widget.setMaximumHeight(30)
        seek_layout = QVBoxLayout(seek_widget)
        seek_layout.setContentsMargins(0, 0, 0, 0)
        seek_layout.setSpacing(0)
        seek_layout.addWidget(self.slider)

        self.elapsed_label.setParent(seek_widget)
        self.total_label.setParent(seek_widget)
        self.elapsed_label.show()
        self.total_label.show()

        def position_seek_labels():
            self.elapsed_label.adjustSize()
            self.total_label.adjustSize()
            self.elapsed_label.move(5, (seek_widget.height() - self.elapsed_label.height()) // 2 - 11)
            self.total_label.move(
                seek_widget.width() - self.total_label.width() - 5,
                (seek_widget.height() - self.total_label.height()) // 2 - 11
            )
            self.elapsed_label.raise_()
            self.total_label.raise_()

        seek_widget.resizeEvent = lambda event: position_seek_labels()
        QTimer.singleShot(0, lambda: position_seek_labels())

        bot.addWidget(seek_widget, 2)
        
        # Playback speed dropdown
        self.speed_combo = QComboBox()
        self.speed_combo.setEditable(True)
        self.speed_combo.addItems(["0.5x", "0.75x", "1x", "1.25x", "1.5x", "2x"])
        self.speed_combo.setCurrentText("1x")
        self.speed_combo.setToolTip("Playback Speed")
        self.speed_combo.setFixedWidth(69)
        # Dropbox
        self.speed_combo.activated.connect(
            lambda index: self.change_speed(self.speed_combo.itemText(index))
        )
        # When user presses Enter in the line edit
        self.speed_combo.lineEdit().returnPressed.connect(
            lambda: self.change_speed(self.speed_combo.currentText())
        )
        # When user clicks away from the input box
        self.speed_combo.lineEdit().focusOutEvent = self._wrap_focus_out(
            self.speed_combo.lineEdit().focusOutEvent
        )
        bot.addWidget(self.speed_combo)
        
        # Playback and info label
        self.loop_btn = QPushButton()
        self.loop_btn.setToolTip("Loop: Off")
        self.update_loop_icon()
        self.loop_btn.clicked.connect(self.toggle_loop_mode)
        bot.addWidget(self.loop_btn)

        b_shuf = QPushButton("🔀")
        b_shuf.setFixedHeight(24)
        b_shuf.setFixedWidth(34)
        b_shuf.setStyleSheet("font-size: 15px;")
        b_shuf.clicked.connect(self.shuffle)
        bot.addWidget(b_shuf)

        # Skip Backward
        btn_prev = QPushButton()
        btn_prev.setIcon(self.style().standardIcon(QStyle.SP_MediaSkipBackward))
        btn_prev.clicked.connect(self.prev_song)
        bot.addWidget(btn_prev)

        # Toggle Play/Pause
        self.btn_play_pause = QPushButton()
        self.play_icon = self.style().standardIcon(QStyle.SP_MediaPlay)
        self.pause_icon = self.style().standardIcon(QStyle.SP_MediaPause)
        self.update_play_pause_icon()
        self.btn_play_pause.clicked.connect(self.toggle_play)
        bot.addWidget(self.btn_play_pause)

        # Skip Forward
        btn_next = QPushButton()
        btn_next.setIcon(self.style().standardIcon(QStyle.SP_MediaSkipForward))
        btn_next.clicked.connect(self.next_song)
        bot.addWidget(btn_next)

        self.now_lbl = MarqueeLabel("—")
        self.now_lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.now_lbl.setToolTip(self.now_lbl.text())
        min_w = self.now_lbl.fontMetrics().averageCharWidth() * 15
        self.now_lbl.setMinimumWidth(min_w)
        bot.addWidget(self.now_lbl, 1)

        # Add to layout
        ll.addLayout(bot)

        # video background setup & loop
        if self.autoplay:
            QTimer.singleShot(300, lambda: self.play_song_at_index(0))
        video_file = Path(__file__).parent / "Background Video" / "Triangles.mov"
        if video_file.exists():
            self.video_sink = QVideoSink(self)
            self.video_sink.videoFrameChanged.connect(self.bg_widget.setFrame)
            self.bg_player = QMediaPlayer(self)
            self.bg_player.setVideoOutput(self.video_sink)
            self.bg_player.setSource(QUrl.fromLocalFile(str(video_file)))
            self.bg_player.mediaStatusChanged.connect(self.loop_video)
            self.bg_player.play()

        # shortcuts
        QShortcut(QKeySequence("Ctrl+Right"), self, self.next_song)
        QShortcut(QKeySequence("Ctrl+Left"),  self, self.prev_song)
        QShortcut(QKeySequence("Ctrl+Up"),    self, self.play_song)
        QShortcut(QKeySequence("Ctrl+Down"),  self, self.pause_song)
        # Media‐key support:
        QShortcut(QKeySequence(Qt.Key_MediaNext),     self, self.next_song)
        QShortcut(QKeySequence(Qt.Key_MediaPrevious), self, self.prev_song)
        QShortcut(QKeySequence(Qt.Key_MediaPlay),     self, self.play_song)
        QShortcut(QKeySequence(Qt.Key_MediaPause),    self, self.pause_song)
        
        # register global media-key hotkeys
        # arguments: hWnd (0 for all windows), id, fsModifiers, vk
        if user32 and self.media_keys_enabled:
            user32.RegisterHotKey(0, 1, MOD_NOREPEAT, VK_MEDIA_PLAY_PAUSE)
            user32.RegisterHotKey(0, 2, MOD_NOREPEAT, VK_MEDIA_NEXT_TRACK)
            user32.RegisterHotKey(0, 3, MOD_NOREPEAT, VK_MEDIA_PREV_TRACK)
        else:
            print("Global hotkeys not available on this platform.")
            
        # Load from cache if available
        cached = load_cache(self.osu_folder)
        if cached:
            print(f"[startup] ✅ Loaded {len(cached)} maps from cache.")
            self.library = cached
            self.queue = list(cached)
            self.populate_list(self.queue)
            self.queue_lbl.setText(f"Queue: {len(self.queue)} songs")
        elif first_setup:
            print("[startup] 🛠 First setup, scanning without prompt.")
            self.reload_songs()
        else:
            print("[startup] ⚠️ No cache found — will prompt for rescan.")
            prompt = QMessageBox.question(
                self, "Cache Missing",
                "No song cache was found.\nWould you like to scan your osu! songs folder?",
                QMessageBox.Yes | QMessageBox.No
            )
            if prompt == QMessageBox.Yes:
                json_path = BASE_PATH / "library_cache.json"
                if json_path.exists():
                    try:
                        print("[startup] Found legacy JSON cache. Importing to SQLite...")
                        with open(json_path, "r", encoding="utf-8") as f:
                            data = json.load(f)
                            maps = data.get("maps", []) if isinstance(data, dict) else []
                        if isinstance(maps, list):
                            save_cache(self.osu_folder, maps)
                            for s in maps:
                                self.progress_label.setText(f"🎵 Found beatmap: {s['artist']} - {s['title']}")
                                QApplication.processEvents()
                            json_path.unlink()
                            cached = load_cache(self.osu_folder)
                            if cached:
                                self.library = cached
                                self.queue = list(cached)
                                self.populate_list(self.queue)
                                self.queue_lbl.setText(f"Queue: {len(self.queue)} songs")
                                return
                    except Exception as e:
                        print(f"[startup] Failed to import from legacy JSON: {e}")
                print("[startup] Starting full scan...")
                self.reload_songs()
            else:
                sys.exit()
            
        self.apply_settings(
            self.osu_folder, self.light_mode, self.ui_opacity,
            w, h, self.hue, self.video_enabled, self.autoplay,
            self.media_keys_enabled, self.preserve_pitch, self.allow_prerelease
        )
        
        QTimer.singleShot(1000, lambda: self.check_updates())
        
    def _tick_seekbar(self):
        if self._playback_start_time is None:
            return
        elapsed_ms = int((monotonic() - self._playback_start_time) * 1000)
        if not getattr(self, "_user_dragging", False):
            self.slider.setValue(elapsed_ms)
            self.elapsed_label.setText(self.format_time(elapsed_ms))
        if elapsed_ms >= self.current_duration:
            self.playback_timer.stop()
            self.next_song()
        
    def _wrap_focus_out(self, old_handler):
        def new_handler(event):
            self.change_speed(self.speed_combo.currentText())
            if old_handler:
                old_handler(event)
        return new_handler
        
    def change_speed(self, text):
        try:
            rate = float(text.replace("x", "").strip())
            if rate <= 0:
                raise ValueError("Speed must be positive.")

            if abs(rate - self.pitch_player.playback_rate) < 0.01:
                return  # No change, skip

            self.playback_rate = rate

            if not self.preserve_pitch:
                self.pitch_player.player.setPlaybackRate(rate)
                print(f"[Playback Speed] Set to {rate}x")

            default_speeds = ["0.5x", "0.75x", "1x", "1.25x", "1.5x", "2x"]
            self.speed_combo.blockSignals(True)
            self.speed_combo.clear()
            self.speed_combo.addItems(default_speeds)
            self.speed_combo.setEditText(f"{rate}x")
            self.speed_combo.blockSignals(False)

        except ValueError:
            QMessageBox.warning(self, "Invalid Speed", "Enter a number above 0 (e.g., 1.25).")
            self.speed_combo.setEditText("1x")
            self.pitch_player.player.setPlaybackRate(1.0)
            
        if getattr(self, "is_playing", False):
            self.seek(self.slider.value())
            
        if self.is_playing:
            self.seek(self.slider.value())
        
    def _update_volume_label(self, v):
        self.volume_label.setText(f"{v}%")
        
    def set_volume(self, v):
        self.audio_out.setVolume(v / 100)
        self._update_volume_label(v)
        self.vol = v
        self.save_user_settings()
        
    def check_updates(self, manual=False):
        current_version = __version__
        skipped_versions = self.skipped_versions

        # Skip automatic checks only if user already declined downgrade
        if not manual and self.skip_downgrade_for_now:
            print("[check_updates] Skipping auto update check due to earlier 'No' response.")
            return

        # Pre-release downgrade offer
        if manual and not self.allow_prerelease and self.is_prerelease_version(current_version):
            choice = QMessageBox.question(
                self,
                "Stable Release Available?",
                "You're currently on a pre-release build. Would you like to return to the latest stable version?",
                QMessageBox.Yes | QMessageBox.No
            )
            if choice == QMessageBox.Yes:
                latest_version, assets = check_for_update(
                    current_version=current_version,
                    skipped_versions=skipped_versions,
                    manual_check=True,
                    include_prerelease=False
                )
                if latest_version:
                    download_and_install_update(assets, latest_version, self.skipped_versions, str(SETTINGS_FILE), self)
                else:
                    QMessageBox.information(self, "No Stable Update Found", "You're already on the most recent release.")
            else:
                self.skip_downgrade_for_now = True
            return

        # Normal update check
        latest_version, assets = check_for_update(
            current_version=current_version,
            skipped_versions=skipped_versions,
            manual_check=manual,
            include_prerelease=self.allow_prerelease
        )

        if latest_version:
            download_and_install_update(assets, latest_version, self.skipped_versions, str(SETTINGS_FILE), self)
        elif manual:
            QMessageBox.information(self, "osu!Radio", "You're already on the latest version.")
            
    def is_prerelease_version(self, ver):
        parsed = version.parse(ver)
        return parsed.is_prerelease or '+' in ver

    def setup_media_players(self):
        output_device = QMediaDevices.defaultAudioOutput()

        audio_format = QAudioFormat()
        audio_format.setSampleRate(44100)
        audio_format.setChannelCount(2)
        audio_format.setSampleFormat(QAudioFormat.Int16)

        if not output_device.isFormatSupported(audio_format):
            print("❌ 44100Hz Int16 not supported — falling back to preferred format.")
            audio_format = output_device.preferredFormat()
        else:
            print("✅ Using 44100Hz Int16")

        print("[Audio Format] Using format:")
        print(f"  Sample Rate: {audio_format.sampleRate()}")
        print(f"  Channels:    {audio_format.channelCount()}")
        print(f"  Sample Type: {audio_format.sampleFormat()}")

        # Create QAudioSink and set volume here (not in __init__)
        self.audio_out = QAudioOutput(output_device, self)
        self.audio_out.setVolume(self.vol / 100)

        self.pitch_player = PitchAdjustedPlayer(self.audio_out, self)
        
    def connect_slider_signals(self):
        # Link slider drag behavior and update preview time.
        self.slider.sliderPressed.connect(lambda: setattr(self, "_user_dragging", True))
        self.slider.sliderReleased.connect(lambda: (
            setattr(self, "_user_dragging", False),
            self.seek(self.slider.value())
        ))

        self.slider.valueChanged.connect(lambda v: (
            self.elapsed_label.setText(self.format_time(v))
            if getattr(self, "_user_dragging", False) else None
        ))
        
    def update_position(self, pos):
        if not getattr(self, "_user_dragging", False):
            self.slider.setValue(pos)
            self.elapsed_label.setText(self.format_time(pos))

    def update_duration(self, duration):
        self.slider.setRange(0, duration)
        self.total_label.setText(self.format_time(duration))
        
    def slider_tooltip(self, event):
        if hasattr(self, "current_duration") and self.current_duration > 0:
            x = event.position().x() if hasattr(event, "position") else event.x()
            ratio = x / self.slider.width()
            pos = int(ratio * self.current_duration)
            mins, secs = divmod(pos // 1000, 60)
            QToolTip.showText(QCursor.pos(), f"{mins}:{secs:02d}")

    def format_time(self, ms):
        mins, secs = divmod(ms // 1000, 60)
        return f"{mins}:{secs:02d}"
        
    def eventFilter(self, source, event):
        if source == self.slider and event.type() == QEvent.MouseMove:
            self.slider_tooltip(event)
        return super().eventFilter(source, event)

    def _slider_jump_to_click(self):
        # Get position relative to the slider width
        mouse_pos = self.slider.mapFromGlobal(QCursor.pos()).x()
        ratio = mouse_pos / self.slider.width()
        new_pos = int(ratio * self.audio.duration())
        self.seek(new_pos)

    def _on_playback_state(self, state):
        if state == QMediaPlayer.EndOfMedia:
            self.next_song()

    def loop_video(self, status):
        if status == QMediaPlayer.EndOfMedia:
            self.bg_player.setPosition(0)
            self.bg_player.play()

    def apply_settings(self, folder, light, opacity, w, h, hue, video_on, autoplay, media_keys, preserve_pitch, allow_prerelease):
        if folder != self.osu_folder and os.path.isdir(folder):
            self.osu_folder = folder
            self.reload_songs()

        self._apply_ui_settings(light, opacity, w, h, hue)
        self._apply_video_setting(video_on)

        self.light_mode = light
        self.ui_opacity = opacity
        self.hue = hue
        self.video_enabled = video_on
        self.autoplay = autoplay
        if self.media_keys_enabled != media_keys:
            self.media_keys_enabled = media_keys
            self.update_media_key_listener()
        self.preserve_pitch = preserve_pitch
        self.allow_prerelease = allow_prerelease
        self.setFixedSize(w, h)
        self.save_user_settings()

    def _apply_ui_settings(self, light, opacity, w, h, hue):
        self.light_mode = light
        self.apply_theme(light)
        self.ui_opacity = opacity
        self.ui_effect.setOpacity(opacity)
        self.setFixedSize(w, h)
        self.hue = hue
        self.bg_widget.effect.setColor(QColor.fromHsv(hue, 255, 255))
        self.save_user_settings()

    def _apply_video_setting(self, enabled):
        self.video_enabled = enabled
        self.bg_widget.setVisible(True)

        if enabled:
            # Restore hue effect
            self.bg_widget.setGraphicsEffect(self.bg_widget.effect)
            self.bg_widget.effect.setEnabled(True)

            if not hasattr(self, "bg_player"):
                video_file = Path(__file__).parent / "Background Video" / "Triangles.mov"
                if video_file.exists():
                    self.video_sink = QVideoSink(self)
                    self.video_sink.videoFrameChanged.connect(self.bg_widget.setFrame)
                    self.bg_player = QMediaPlayer(self)
                    self.bg_player.setVideoOutput(self.video_sink)
                    self.bg_player.setSource(QUrl.fromLocalFile(str(video_file)))
                    self.bg_player.mediaStatusChanged.connect(self.loop_video)

            self.bg_player.play()

        else:
            # Remove video and disable QGraphicsColorizeEffect
            if hasattr(self, "bg_player"):
                self.bg_player.stop()
                self.bg_player.deleteLater()
                del self.bg_player
            if hasattr(self, "video_sink"):
                self.video_sink.deleteLater()
                del self.video_sink

            # Remove hue effect and trigger repaint with manual hue
            self.bg_widget.setGraphicsEffect(self.bg_widget.effect)
            self.bg_widget.effect.setEnabled(False)
            self.bg_widget.update()
                
    def update_media_key_listener(self):
        try:
            if self.media_key_listener:
                self.media_key_listener.stop()
                self.media_key_listener = None
        except Exception as e:
            print("Failed to stop media key listener:", e)

        if self.media_keys_enabled:
            try:
                from pynput import keyboard as kb

                def on_press(key):
                    if key == kb.Key.media_next:
                        QMetaObject.invokeMethod(self, "next_song", Qt.QueuedConnection)
                    elif key == kb.Key.media_previous:
                        QMetaObject.invokeMethod(self, "prev_song", Qt.QueuedConnection)
                    elif key == kb.Key.media_play_pause:
                        QMetaObject.invokeMethod(self, "toggle_play", Qt.QueuedConnection)

                self.media_key_listener = kb.Listener(on_press=on_press)
                self.media_key_listener.start()
            except Exception as e:
                print("Failed to start media key listener:", e)

    def apply_theme(self, light: bool):
        if light:
            style = """
                QWidget { background-color: rgba(255,255,255,200); color: black; }
                QPushButton { background-color: #e0e0e0; }
            """
        else:
            style = ""  # Use system default
        self.centralWidget().setStyleSheet(style)

    def populate_list(self, songs):
        # Update the visible song list.
        self.song_list.clear()
        for song in songs:
            item = QListWidgetItem(f"{song['artist']} - {song['title']}")
            item.setData(Qt.UserRole, song)
            self.song_list.addItem(item)

    def filter_list(self, text):
        t = text.lower().strip()
        if not t:
            self.populate_list(self.queue)
        else:
            filtered = [
                s for s in self.library
                if t in s["title"].lower() or t in s["artist"].lower() or t in s["mapper"].lower()
            ]
            self.populate_list(filtered)

    def toggle_loop_mode(self):
        self.loop_mode = (self.loop_mode + 1) % 3
        modes = ["Loop: Off", "Loop: All", "Loop: One"]
        self.loop_btn.setToolTip(modes[self.loop_mode])
        self.update_loop_icon()
        
    def update_play_pause_icon(self):
        if getattr(self, "is_playing", False):
            self.btn_play_pause.setIcon(self.pause_icon)
        else:
            self.btn_play_pause.setIcon(self.play_icon)

    def update_loop_icon(self):
        if self.loop_mode == 0:
            self.loop_btn.setIcon(self.style().standardIcon(QStyle.SP_BrowserStop))
            self.loop_btn.setText("")
        elif self.loop_mode == 1:
            self.loop_btn.setText("🔁")
            self.loop_btn.setIcon(QIcon())
            self.loop_btn.setStyleSheet("font-size: 15px;")
            self.loop_btn.setFixedHeight(24)
            self.loop_btn.setFixedWidth(34)
        elif self.loop_mode == 2:
            self.loop_btn.setText("🔂")
            self.loop_btn.setIcon(QIcon())
            self.loop_btn.setStyleSheet("font-size: 15px;")
            self.loop_btn.setFixedHeight(24)
            self.loop_btn.setFixedWidth(34)

    def play_song(self, song):
        audio_path = get_audio_path(song)
        self.audio.setSource(QUrl.fromLocalFile(str(audio_path)))
        self.audio.play()
        self.now_lbl.setText(f"{song['artist']} - {song['title']}")
       
    def toggle_play(self):
        # Play if paused/stopped, pause if playing, and update icon.
        state = self.audio.playbackState()
        if state == QMediaPlayer.PlayingState:
            self.audio.pause()
        else:
            self.audio.play()
        self.update_play_pause_icon()
   
    def pause_song(self):
        self.audio.pause()

    def play_song_at_index(self, index):
        self.current_index = index
        item = self.song_list.item(index)
        song = self.queue[index]

        if item:
            song = item.data(Qt.UserRole)

        self.current_duration = song.get("length", 0)
        self._playback_start_time = monotonic()
        self.slider.setRange(0, self.current_duration)
        self.total_label.setText(self.format_time(self.current_duration))
        self.playback_timer.start()
        path = get_audio_path(song)

        # Debug logging
        print(f"▶▶ play_song_at_index: idx={index}, file={path!r}")
        print("    folder exists? ", os.path.isdir(song["folder"]))
        print("    file exists?   ", os.path.isfile(path))

        if not path.exists():
            print("⚠️  Skipping playback — file not found:", path)
            QMessageBox.warning(self, "Missing File", f"The selected audio file does not exist:\n{path}")
            return

        # Set and play the media
        speed = float(self.speed_combo.currentText().replace("x", ""))
        self.pitch_player.play(str(path), speed=speed, preserve_pitch=self.preserve_pitch)
        self.current_duration = self.pitch_player.last_duration
        self.slider.setRange(0, self.current_duration)
        self.total_label.setText(self.format_time(self.current_duration))

        # Update UI
        self.now_lbl.setText(f"{song.get('title','')} — {song.get('artist','')}")
        self.song_list.setCurrentRow(index)
        self.is_playing = True
        self.update_play_pause_icon()

    def next_song(self):
        if self.loop_mode == 2:  # Loop single
            self.play_song_at_index(self.current_index)
        else:
            nxt = self.current_index + 1
            if nxt >= len(self.queue):
                if self.loop_mode == 1:  # Loop all
                    nxt = 0
                else:
                    return  # End of queue, do nothing
            self.play_song_at_index(nxt)

    def prev_song(self):
        idx = (self.current_index - 1) % len(self.queue)
        self.play_song_at_index(idx)

    def shuffle(self):
        random.shuffle(self.queue)
        self.populate_list(self.queue)
        self.queue_lbl.setText(f"Queue: {len(self.queue)} songs")
        self.song_list.setCurrentRow(self.current_index)

    def seek(self, pos):
        print(f"[Seek] Jump to position {pos} ms")

        song = self.queue[self.current_index]
        path = get_audio_path(song)
        speed = float(self.speed_combo.currentText().replace("x", ""))

        self._playback_start_time = monotonic() - (pos / 1000)
        print(f"[Seek Debug] path: {path}, speed: {speed}, preserve_pitch: {self.preserve_pitch}, start: {pos}")

        self.pitch_player.play(str(path), speed=speed, preserve_pitch=self.preserve_pitch, start_ms=pos)
        self.current_duration = self.pitch_player.last_duration
        self.slider.setRange(0, self.current_duration)
        self.total_label.setText(self.format_time(self.current_duration))
        self.current_duration = self.pitch_player.last_duration
        self.slider.setRange(0, self.current_duration)
        self.slider.setValue(pos)

        # Update seek label
        current_time = pos
        total_time = self.current_duration
        self.elapsed_label.setText(self.format_time(current_time))
        self.total_label.setText(self.format_time(total_time))

    def open_settings(self):
        SettingsDialog(self).exec()

    def reload_songs(self):
        self._progress_user_closed = False
        print(f"[reload_songs] Scanning folder: {self.osu_folder}")

        # Stop previous scan if running
        if hasattr(self, "_scanner") and self._scanner.isRunning():
            print("[reload_songs] Interrupting previous scanner...")
            self._scanner.requestInterruption()
            if not self._scanner.wait(5000):
                print("[reload_songs] Forcing scanner termination...")
                self._scanner.terminate()
                self._scanner.wait()

        # Optional: load from cache first
        cached = load_cache(self.osu_folder)
        if cached:
            print("[reload_songs] ✅ Loaded from cache.")
            self.library = cached
            self.queue = list(cached)
            self.populate_list(self.queue)
            self.queue_lbl.setText(f"Queue: {len(self.queue)} songs")

        # Progress dialog with message label
        self.progress = QProgressDialog("Importing beatmaps...", None, 0, 0, self)
        self.progress.setWindowModality(Qt.ApplicationModal)
        self.progress.setWindowTitle("osu!Radio")
        self.progress.setFixedSize(420, 69)
        self.progress.setCancelButton(None)
        self.progress.setMinimumDuration(0)

        # Add label below progress bar
        self.progress_label = QLabel("Starting scan…")
        self.progress.setLabel(self.progress_label)

        # Confirmation if closed
        def handle_close(ev):
            reply = QMessageBox.question(
                self,
                "Cancel Beatmap Scan?",
                "Are you sure you want to cancel scanning for beatmaps?\n\n"
                "To run it again, click Reload Maps in the top right.",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                self._progress_user_closed = True
                if hasattr(self, "_scanner") and self._scanner.isRunning():
                    self._scanner.requestInterruption()
                self.progress.cancel()
                ev.accept()
            else:
                ev.ignore()

        self.progress.closeEvent = handle_close
        self.progress.show()
        QApplication.processEvents()

        # Scanner thread
        self._scanner = LibraryScanner(self.osu_folder)
        self._scanner.progress_update.connect(self.progress_label.setText)
        self._scanner.done.connect(self._on_reload_complete)
        self._scanner.start()

    def load_user_settings(self):
        defaults = {
            "osu_folder": None,
            "light_mode": False,
            "ui_opacity": 0.75,
            "window_width": 854,
            "window_height": 480,
            "hue": 240,
            "loop_mode": 0,
            "video_enabled": True,
            "autoplay": False,
            "media_keys_enabled": True,
            "preserve_pitch": True,
            "allow_prerelease": False,
            "was_prerelease": False,
            "resolution": "854×480",
            "skipped_versions": [],
        }
        if SETTINGS_FILE.exists():
            try:
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    return {**defaults, **json.load(f)}
            except Exception as e:
                print("[load_user_settings] Failed to load settings:", e)
        return defaults

    def save_user_settings(self):
        settings = {
            "osu_folder": self.osu_folder,
            "light_mode": self.light_mode,
            "ui_opacity": self.ui_opacity,
            "window_width": self.width(),
            "window_height": self.height(),
            "hue": self.hue,
            "loop_mode": self.loop_mode,
            "video_enabled": self.video_enabled,
            "autoplay": self.autoplay,
            "media_keys_enabled": self.media_keys_enabled,
            "volume": int(self.audio_out.volume() * 100) if hasattr(self, "audio_out") else 30,
            "preserve_pitch": self.preserve_pitch,
            "allow_prerelease": self.allow_prerelease,
            "was_prerelease": self.is_prerelease_version(__version__),
            "resolution": f"{self.width()}×{self.height()}",
            "skipped_versions": self.skipped_versions,
        }
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(settings, f, indent=2)
        except Exception as e:
            print("[save_user_settings] Failed to save settings:", e)
        
    def _on_reload_complete(self, library):
        self.library = library
        self.queue = list(library)
        self.populate_list(self.queue)
        self.queue_lbl.setText(f"Queue: {len(self.queue)} songs")

        print(f"[reload_complete] ✅ Found {len(library)} total songs after rescan.")

        if hasattr(self, "progress") and self.progress:
            self.progress.closeEvent = lambda ev: ev.accept()  # disable cancel check
            self.progress.close()
            self.progress = None

        if not getattr(self, "_progress_user_closed", False):
            QMessageBox.information(self, "Import Complete", f"Imported {len(library)} beatmaps.")

    def onSongContextMenu(self, point):
        item = self.song_list.itemAt(point)
        if not item:
            return
        menu = QMenu(self)
        action = menu.addAction("Add to Next ▶")
        action.triggered.connect(lambda: self.addToNext(item))
        menu.exec(self.song_list.mapToGlobal(point))

    def addToNext(self, item):
        s = item.data(Qt.UserRole)
        pos = self.current_index + 1
        self.queue.insert(pos, s)
        QToolTip.showText(QCursor.pos(), "✅ Added to Next", self.song_list)
        self.populate_list(self.queue)
        self.song_list.setCurrentRow(self.current_index)
        self.queue_lbl.setText(f"Queue: {len(self.queue)} songs")

    def closeEvent(self, event):
        # 0) Stop the scanner thread (if it's still running)
        if hasattr(self, "_scanner") and self._scanner.isRunning():
            print("[closeEvent] Requesting scanner thread interruption...")
            self._scanner.requestInterruption()
            self._scanner.wait(3000)

        # 1) Unregister global hotkeys
        if user32 and self.media_keys_enabled:
            user32.UnregisterHotKey(0, 1)
            user32.UnregisterHotKey(0, 2)
            user32.UnregisterHotKey(0, 3)

        # 2) Stop video loop cleanly
        try:
            self.bg_player.stop()
        except:
            pass

        # 3) Stop pitch player and timer
        if hasattr(self, "pitch_player"):
            self.pitch_player.stop()
            self.playback_timer.stop()

        # 4) Save settings
        self.save_user_settings()

        # 5) Clean up temp cache folder
        cache_path = Path(tempfile.gettempdir()) / "OsuRadioCache"
        if cache_path.exists():
            try:
                shutil.rmtree(cache_path)
                print("[Exit Cleanup] Deleted temp cache folder.")
            except Exception as e:
                print(f"[Exit Cleanup] Failed to delete cache: {e}")

        # 6) Accept the event
        QTimer.singleShot(200, self.cleanup_cache)
        event.accept()
        
    def _on_audio_status(self, status):
        # QMediaPlayer.EndOfMedia fires once when a track finishes
        if status == QMediaPlayer.EndOfMedia:
            self.next_song()
            
    def cleanup_cache(self):
        cache_path = Path(tempfile.gettempdir()) / "OsuRadioCache"
        if cache_path.exists():
            try:
                shutil.rmtree(cache_path)
                print("[Exit Cleanup] Cache folder deleted.")
            except Exception as e:
                print(f"[Exit Cleanup] Cache delete failed: {e}")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    
    window.update_media_key_listener()

    sys.exit(app.exec())
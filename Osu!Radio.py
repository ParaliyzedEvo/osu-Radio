__version__ = "1.5.0"

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
from pathlib import Path
from mutagen.mp3 import MP3
from PySide6.QtCore import (
    Qt, QUrl, QTimer, QThread, QMetaObject,
    QPropertyAnimation, QEasingCurve, Property,
    QSequentialAnimationGroup, QPauseAnimation, Signal,
    QEvent
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
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput, QVideoSink

IS_WINDOWS = sys.platform.startswith("win")
BASE_PATH = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
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

if sys.platform == "darwin":
    ICON_FILE = "Osu!RadioIcon.icns"
elif sys.platform.startswith("linux"):
    ICON_FILE = "Osu!RadioIcon.png"
elif sys.platform.startswith("win"):
    ICON_FILE = "Osu!RadioIcon.ico"
else:
    icon = "Osu!RadioIcon.png"  # fallback
    
ICON_PATH = BASE_PATH / ICON_FILE

# Utility functions
def check_for_update(current_version, skipped_versions=None, manual_check=False):
    try:
        response = requests.get("https://api.github.com/repos/Paraliyzedevo/osu-Radio/releases/latest", timeout=5)
        data = response.json()
        latest_version = data["tag_name"]
        # Only skip version if it's not a manual check
        if not manual_check and skipped_versions and latest_version in skipped_versions:
            return None, None
        if latest_version != current_version:
            return latest_version, data["assets"]
    except Exception as e:
        print(f"Update check failed: {e}")
    return None, None

def download_and_install_update(assets, latest_version, skipped_versions, settings_path):
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
        return  # User chose "Remind me later"

    # Proceed with update
    temp_dir = tempfile.mkdtemp()
    file_path = os.path.join(temp_dir, os.path.basename(url))
    with requests.get(url, stream=True) as r:
        with open(file_path, "wb") as f:
            total = int(r.headers.get('content-length', 0))
            progress = QProgressDialog("Downloading update...", "Cancel", 0, total)
            progress.setWindowModality(Qt.ApplicationModal)
            progress.setWindowTitle("osu!Radio Updater")
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

        subprocess.Popen([
            updater,
            subdir, str(BASE_PATH), exe, str(os.getpid())
        ])
        shutil.rmtree(temp_dir, ignore_errors=True)
        sys.exit(0)

def init_db():
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    # Create songs table
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
        )
    """)
    # Create metadata table for folder modification time
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    conn.commit()
    conn.close()

def load_cache(folder):
    if not DATABASE_FILE.exists():
        return None
    init_db()
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT value FROM metadata WHERE key = 'folder_mtime'")
        row = cursor.fetchone()
        if row and row[0] == str(os.path.getmtime(folder)):
            cursor.execute("SELECT title, artist, mapper, audio, background, length, osu_file, folder FROM songs")
            maps = []
            for r in cursor.fetchall():
                maps.append({
                    "title": r[0], "artist": r[1], "mapper": r[2],
                    "audio": r[3], "background": r[4], "length": r[5],
                    "osu_file": r[6], "folder": r[7]
                })
            return maps
    except Exception as e:
        print(f"Error loading cache from SQLite: {e}")
    finally:
        conn.close()
    return None

def save_cache(folder, maps):
    init_db()
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    try:
        cursor.execute("BEGIN TRANSACTION")
        # Clear existing songs (optional, could also do INSERT OR REPLACE)
        # For simplicity, clear and re-insert if saving a full new list
        cursor.execute("DELETE FROM songs")

        for s_map in maps:
            cursor.execute("""
                INSERT OR IGNORE INTO songs (title, artist, mapper, audio, background, length, osu_file, folder)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (s_map.get("title"), s_map.get("artist"), s_map.get("mapper"),
                  s_map.get("audio"), s_map.get("background"), s_map.get("length", 0),
                  s_map.get("osu_file"), s_map.get("folder")))

        cursor.execute("INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
                       ('folder_mtime', str(os.path.getmtime(folder))))
        conn.commit()
    except Exception as e:
        print(f"Error saving cache to SQLite: {e}")
        conn.rollback()
    finally:
        conn.close()
        
def read_osu_lines(path):
    for enc in ("utf-8", "utf-8-sig", "cp1251", "latin-1"):
        try:
            with open(path, encoding=enc) as f:
                return f.read().splitlines()
        except UnicodeDecodeError:
            pass
    with open(path, encoding="utf-8", errors="ignore") as f:
        return f.read().splitlines()

class OsuParser:
    @staticmethod
    def parse(path):
        data = {"audio": "", "title": "", "artist": "", "mapper": "",
                "background": "", "length": 0, "osu_file": path,
                "folder": str(Path(path).parent)}
        for line in read_osu_lines(path):
            line = line.strip()
            if m := re.match(r'\s*audiofilename\s*:\s*(.+)', line, re.IGNORECASE):
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
            audio_path = Path(data["folder"]) / data["audio"]
            mp = MP3(str(audio_path))
            data["length"] = int(mp.info.length * 1000)
        except:
            pass
        return data

class LibraryScanner(QThread):
    done = Signal(list)

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
                        # Ensure essential keys exist for uniqueness, provide defaults if not
                        title = s.get("title", f"Unknown Title - {fn}")
                        artist = s.get("artist", "Unknown Artist")
                        mapper = s.get("mapper", "Unknown Mapper")
                        key = (title, artist, mapper)

                        if key not in uniq: # Add if truly new based on primary metadata
                            uniq[key] = s
                    except Exception as e:
                        print(f"[LibraryScanner] Error parsing {full_path}: {e}")
                        pass
                        
        if self.isInterruptionRequested():
            print("[LibraryScanner] Interruption requested before saving cache.")
            return
        library = list(uniq.values())
        print(f"[LibraryScanner] Scan complete. Found {len(library)} unique beatmaps.")
        
        # Check for interruption again before potentially lengthy save operation
        if self.isInterruptionRequested():
            print("[LibraryScanner] Interruption requested before saving cache.")
            return
        save_cache(self.folder, library)
        # And again before emitting signal
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
        avail  = self.width()
        self._anim.stop()
        self._offset = 0
        if text_w > avail:
            span = text_w - avail + 20
            a1 = QPropertyAnimation(self, b"offset", self)
            a1.setStartValue(0); a1.setEndValue(span); a1.setDuration(span * 20)
            a1.setEasingCurve(QEasingCurve.Linear)
            p1 = QPauseAnimation(1000, self)
            a2 = QPropertyAnimation(self, b"offset", self)
            a2.setStartValue(span); a2.setEndValue(0); a2.setDuration(span * 20)
            a2.setEasingCurve(QEasingCurve.Linear)
            p2 = QPauseAnimation(1000, self)
            self._anim.clear()
            for a in (a1, p1, a2, p2): self._anim.addAnimation(a)
            self._anim.setLoopCount(-1)
            self._anim.start()
        else:
            self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setClipRect(self.rect())
        p.drawText(-self._offset, self.height() - 5, self.text())
        p.end()

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

        # Debounce timer for resizing
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
        QPainter(self).drawPixmap(0, 0, self._pixmap)

class SettingsDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setFixedSize(400, 350)
        self.main = parent
        layout = QVBoxLayout(self)

        self.folderEdit = QLineEdit(parent.osu_folder)
        browseBtn = QPushButton("Browse…")
        browseBtn.clicked.connect(self.browse_folder)
        h1 = QHBoxLayout(); h1.addWidget(QLabel("Songs Folder:")); h1.addWidget(self.folderEdit); h1.addWidget(browseBtn)
        layout.addLayout(h1)

        self.lightCheck = QCheckBox("Light Mode"); self.lightCheck.setChecked(parent.light_mode)
        self.videoCheck = QCheckBox("Enable Background Video"); self.videoCheck.setChecked(parent.video_enabled)
        self.autoplayCheck = QCheckBox("Autoplay on Startup"); self.autoplayCheck.setChecked(parent.autoplay)
        self.mediaKeyCheck = QCheckBox("Enable Media Key Support"); self.mediaKeyCheck.setChecked(parent.media_keys_enabled)
        layout.addWidget(self.lightCheck); layout.addWidget(self.videoCheck); layout.addWidget(self.autoplayCheck); layout.addWidget(self.mediaKeyCheck)

        self.opacitySlider = QSlider(Qt.Horizontal)
        self.opacitySlider.setRange(10, 100)
        self.opacitySlider.setValue(int(parent.ui_opacity * 100))
        self.opacitySlider.valueChanged.connect(lambda v: parent.ui_effect.setOpacity(v / 100))
        h2 = QHBoxLayout(); h2.addWidget(QLabel("UI Opacity:")); h2.addWidget(self.opacitySlider)
        layout.addLayout(h2)

        self.hueSlider = QSlider(Qt.Horizontal)
        self.hueSlider.setRange(0, 360); self.hueSlider.setValue(parent.hue)
        self.hueSlider.valueChanged.connect(lambda v: parent.bg_widget.effect.setColor(QColor.fromHsv(v, 255, 255)))
        h3 = QHBoxLayout(); h3.addWidget(QLabel("Hue:")); h3.addWidget(self.hueSlider)
        layout.addLayout(h3)

        self.resCombo = QComboBox()
        self.resolutions = {"1920×1080": (1920, 1080), "1280×720": (1280, 720), "854×480": (854, 480), "640×360": (640, 360), "480×270": (480, 270)}
        self.resCombo.addItems(self.resolutions)
        current = f"{parent.width()}×{parent.height()}"
        if current in self.resolutions:
            self.resCombo.setCurrentText(current)
        h4 = QHBoxLayout(); h4.addWidget(QLabel("Resolution:")); h4.addWidget(self.resCombo)
        layout.addLayout(h4)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.apply)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        
        # Update button
        update_button = QPushButton("Check for Updates")
        update_button.clicked.connect(lambda: parent.check_updates(manual=True))
        layout.addWidget(update_button)
        
        # Save states for settings
        self._original_opacity = parent.ui_opacity
        self._original_hue = parent.hue

    def browse_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Select osu! Songs Folder")
        if d: self.folderEdit.setText(d)

    def apply(self):
        folder = self.folderEdit.text()
        light = self.lightCheck.isChecked()
        opacity = self.opacitySlider.value() / 100
        hue = self.hueSlider.value()
        res = self.resCombo.currentText()
        w, h = self.resolutions[res]
        video_on = self.videoCheck.isChecked()
        autoplay = self.autoplayCheck.isChecked()
        media_keys = self.mediaKeyCheck.isChecked()
        self.main.apply_settings(folder, light, opacity, w, h, hue, video_on, autoplay, media_keys)
        self.accept()
        
    def reject(self):
        # Restore original previewed values
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
        # Load from file
        settings = self.load_user_settings()

        # Apply defaults if missing
        self.osu_folder     = settings.get("osu_folder") or QFileDialog.getExistingDirectory(self, "Select osu! Songs Folder")
        if not self.osu_folder:
            sys.exit()

        self.light_mode         = settings.get("light_mode", False)
        self.ui_opacity         = settings.get("ui_opacity", 0.75)
        self.hue                = settings.get("hue", 240)
        self.loop_mode          = settings.get("loop_mode", 0)
        self.video_enabled      = settings.get("video_enabled", True)
        self.autoplay           = settings.get("autoplay", False)
        self.media_keys_enabled = settings.get("media_keys_enabled", True)
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

        # Audio player
        self.audio = QMediaPlayer(self)
        self.audio_out = QAudioOutput(self)
        self.audio.setAudioOutput(self.audio_out)
        self.audio.playbackStateChanged.connect(self.update_play_pause_icon)
        
        # ── DEBUG: log any QtMedia errors to console ──
        self.audio.errorOccurred.connect(
            lambda err, msg: print(f"🎶 QMediaPlayer error: {err}, message: {msg}")
        )

        # auto‐advance when track ends
        self.audio.mediaStatusChanged.connect(self._on_audio_status)

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

        # ── Volume slider + overlay ──
        vol = QSlider(Qt.Horizontal)
        vol.setRange(0, 100)
        vol.setValue(30)
        self.volume_label = QLabel("30%")
        vol.valueChanged.connect(lambda v: self.volume_label.setText(f"{v}%"))
        self.volume_label.setVisible(True)
        vol.valueChanged.connect(lambda v: self.audio_out.setVolume(v / 100))
        self.audio_out.setVolume(0.3)

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

        # ── Seek slider + overlay ──
        class SeekSlider(QSlider):
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
        self.slider.setMouseTracking(True)
        self.slider.installEventFilter(self)
        self.slider.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        # Drag tracking logic
        self.slider.sliderPressed.connect(lambda: setattr(self, "_user_dragging", True))
        self.slider.sliderReleased.connect(lambda: (
            setattr(self, "_user_dragging", False),
            self.audio.setPosition(self.slider.value())
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
            self.elapsed_label.move(5, -4)
            self.total_label.move(seek_widget.width() - self.total_label.width() - 5, -4)
            self.elapsed_label.raise_()
            self.total_label.raise_()

        seek_widget.resizeEvent = lambda event: position_seek_labels()
        QTimer.singleShot(0, lambda: position_seek_labels())

        bot.addWidget(seek_widget, 2)
        
        # ── Playback and info label ──
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

        # connect slider range updates
        self.audio.durationChanged.connect(self.update_duration)
        self.audio.positionChanged.connect(self.update_position)
        
        # register global media-key hotkeys
        # arguments: hWnd (0 for all windows), id, fsModifiers, vk
        if user32 and self.media_keys_enabled:
            user32.RegisterHotKey(0, 1, MOD_NOREPEAT, VK_MEDIA_PLAY_PAUSE)
            user32.RegisterHotKey(0, 2, MOD_NOREPEAT, VK_MEDIA_NEXT_TRACK)
            user32.RegisterHotKey(0, 3, MOD_NOREPEAT, VK_MEDIA_PREV_TRACK)
        else:
            print("Global hotkeys not available on this platform.")
            
        cached = load_cache(self.osu_folder)    
        # Ensure osu_folder is valid
        if not self.osu_folder or not os.path.isdir(self.osu_folder):
            self.osu_folder = QFileDialog.getExistingDirectory(self, "Select osu! Songs Folder")
            if not self.osu_folder:
                sys.exit()
            self.save_user_settings()

        # Try loading cache
        cached = load_cache(self.osu_folder)
        if cached:
            self.library = cached
            self.queue = list(cached)
            self.populate_list(self.queue)
            self.queue_lbl.setText(f"Queue: {len(self.queue)} songs")
        else:
            # No cache found: ask user to rebuild
            reply = QMessageBox.question(
                self, "Cache Missing",
                "No cache found. Would you like to scan your osu! songs folder and build the cache?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                json_path = BASE_PATH / "library_cache.json"
                if json_path.exists():
                    try:
                        print("[startup] Found legacy JSON cache. Importing to SQLite...")
                        with open(json_path, "r", encoding="utf-8") as f:
                            data = json.load(f)
                            maps = data.get("maps", []) if isinstance(data, dict) else []
                            print(f"[startup] ✅ Loaded JSON. Found {len(maps)} maps.")
                            print(f"[startup] ✅ JSON loaded. Type: {type(maps)}, Length: {len(maps) if isinstance(maps, list) else 'N/A'}")
                        if isinstance(maps, list):
                            print(f"[startup] ✅ Loaded {len(maps)} songs from library_cache.json")
                            save_cache(self.osu_folder, maps)
                            print("[startup] Listing all imported beatmaps from JSON:")
                            for s in maps:
                                print(f"  🎵 Imported beatmap: {s['artist']} - {s['title']}")
                            self.library = maps
                            self.queue = list(maps)
                            self.populate_list(self.queue)
                            self.queue_lbl.setText(f"Queue: {len(self.queue)} songs")
                            print(f"[startup] Imported {len(maps)} maps from legacy JSON.")
                            # 🔥 Delete old cache file
                            json_path.unlink()
                            print("[startup] Deleted library_cache.json.")
                            # Import was successful, now load from SQLite                           
                            cached = load_cache(self.osu_folder)
                            if cached:
                                self.library = cached
                                self.queue = list(cached)
                                self.populate_list(self.queue)
                                self.queue_lbl.setText(f"Queue: {len(self.queue)} songs")
                                print(f"[startup] ✅ Confirmed import into SQLite. {len(cached)} maps loaded.")
                                return
                            else:
                                print("[startup] ❌ Failed to load from SQLite after JSON import, doing full scan...")
                                self.reload_songs()
                    except Exception as e:
                        import traceback
                        print(f"[startup] Failed to import from JSON cache: {e}")
                        # If JSON fails or doesn't exist, fall back to full scan
                        self.reload_songs()
            else:
                sys.exit()
            
        self.apply_settings(
            self.osu_folder, self.light_mode, self.ui_opacity,
            w, h, self.hue, self.video_enabled, self.autoplay,
            self.media_keys_enabled
        )
        
        QTimer.singleShot(1000, lambda: self.check_updates())
        
    def check_updates(self, manual=False):
        current_version = __version__  # or however you define it
        skipped_versions = self.skipped_versions
        latest_version, assets = check_for_update(current_version, skipped_versions, manual_check=manual)
        if latest_version:
            download_and_install_update(assets, latest_version, self.skipped_versions, str(SETTINGS_FILE))
        if not latest_version:
            if manual:
                QMessageBox.information(self, "osu!Radio", "You're already on the latest version.")
            return

    def format_time(self, ms):
        mins, secs = divmod(ms // 1000, 60)
        return f"{mins}:{secs:02d}"
        
    def eventFilter(self, source, event):
        if source == self.slider and event.type() == QEvent.MouseMove:
            if self.audio.duration() > 0:
                x = event.position().x()
                ratio = x / self.slider.width()
                pos = int(ratio * self.audio.duration())
                mins, secs = divmod(pos // 1000, 60)
                QToolTip.showText(QCursor.pos(), f"{mins}:{secs:02d}")
        return super().eventFilter(source, event)

    def _slider_jump_to_click(self):
        # Get position relative to the slider width
        mouse_pos = self.slider.mapFromGlobal(QCursor.pos()).x()
        ratio = mouse_pos / self.slider.width()
        new_pos = int(ratio * self.audio.duration())
        self.audio.setPosition(new_pos)

    def _on_playback_state(self, state):
        if state == QMediaPlayer.EndOfMedia:
            self.next_song()

    def loop_video(self, status):
        if status == QMediaPlayer.EndOfMedia:
            self.bg_player.setPosition(0)
            self.bg_player.play()

    def apply_settings(self, folder, light, opacity, w, h, hue, video_on, autoplay, media_keys):
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
        if hasattr(self, "bg_player"):
            if enabled:
                self.bg_player.play()
            else:
                self.bg_player.pause()
                
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
            self.centralWidget().setStyleSheet("background-color: rgba(255,255,255,200); color:black;")
        else:
            self.centralWidget().setStyleSheet("")

    def populate_list(self, songs):
        self.song_list.clear()
        for song in songs:
            item = QListWidgetItem(f"{song['artist']} - {song['title']}")
            item.setData(Qt.UserRole, song)
            self.song_list.addItem(item)
        self.song_list.viewport().update()

    def filter_list(self, text):
        t = text.lower().strip()
        if not t:
            self.populate_list(self.queue)
        else:
            hits = [
                s for s in self.library
                if t in s['title'].lower()
                or t in s['artist'].lower()
                or t in s['mapper'].lower()
            ]
            self.populate_list(hits)
        self.song_list.viewport().update()

    def toggle_loop_mode(self):
        self.loop_mode = (self.loop_mode + 1) % 3
        modes = ["Loop: Off", "Loop: All", "Loop: One"]
        self.loop_btn.setToolTip(modes[self.loop_mode])
        self.update_loop_icon()
        
    def update_play_pause_icon(self):
        if self.audio.playbackState() == QMediaPlayer.PlayingState:
            self.btn_play_pause.setIcon(self.style().standardIcon(QStyle.SP_MediaPause))
        else:
            self.btn_play_pause.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))

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
        audio_path = Path(song["folder"]) / song["audio"]
        self.audio.setSource(QUrl.fromLocalFile(str(audio_path)))
        self.audio.play()
        self.now_lbl.setText(f"{song['artist']} - {song['title']}")

    def toggle_play(self):
        """Play if paused/stopped, pause if playing, and update icon."""
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
        folder = song["folder"]
        audio_file = os.path.join(song["folder"], song["audio"])
        if item:
            song = item.data(Qt.UserRole)
            if song:
                self.play_song(song)
        
        path = Path(song["folder"]) / song["audio"]

        # ─── DEBUG LOGGING ──────────────────────────────────
        print(f"▶▶ play_song_at_index: idx={index}, file={audio_file!r}")
        print("    folder exists? ", os.path.isdir(folder))
        print("    file exists?   ", os.path.isfile(path))
        # ────────────────────────────────────────────────────

        if not audio_file or not os.path.isfile(path):
            print("⚠️  Skipping playback because file missing")
            return

        # Set and play the media
        self.audio.setSource(QUrl.fromLocalFile(path))
        self.audio.play()

        # Update UI
        self.now_lbl.setText(f"{song.get('title','')} — {song.get('artist','')}")
        self.song_list.setCurrentRow(index)

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
        # if more than 3 s in, restart; else go to previous track
        if self.audio.position() < 3000:
            idx = (self.current_index - 1) % len(self.queue)
        else:
            idx = self.current_index
        self.play_song_at_index(idx)

    def shuffle(self):
        import random
        random.shuffle(self.queue)
        self.populate_list(self.queue)
        self.queue_lbl.setText(f"Queue: {len(self.queue)} songs")
        self.song_list.setCurrentRow(self.current_index)

    def seek(self, pos):
        self.audio.setPosition(pos)

    def update_position(self, p):
        if not getattr(self, "_user_dragging", False):
            self.slider.setValue(p)
            self.elapsed_label.setText(self.format_time(p))

    def update_duration(self, d):
        self.slider.setRange(0, d)
        mins, secs = divmod(d // 1000, 60)
        self.total_label.setText(self.format_time(d))

    def open_settings(self):
        SettingsDialog(self).exec()

    def reload_songs(self):
        """Populate immediately (sync if no cache), then always rescan in background."""
        print(f"[reload_songs] Scanning folder: {self.osu_folder}")  # 🔍 DEBUG
        
        # Stop and wait for any existing scanner thread
        if hasattr(self, "_scanner") and self._scanner.isRunning():
            print("[reload_songs] Previous scanner running. Requesting interruption...")
            self._scanner.requestInterruption()
            if not self._scanner.wait(5000):
                print("[reload_songs] Scanner thread did not terminate in time. Forcing termination.")
                self._scanner.terminate() # Force terminate if wait fails
                self._scanner.wait() # Wait for termination to complete
            print("[reload_songs] Previous scanner stopped.")

        cached = load_cache(self.osu_folder)
        if cached:
            print("[reload_songs] Loaded from cache.")
            self.library = cached
            self.queue = list(cached)
        else:
            print("[reload_songs] No valid cache found. Doing quick scan...")  # 🔍 DEBUG
            raw, uniq = [], {}
            for root, _, files in os.walk(self.osu_folder):
                for fn in files:
                    if fn.lower().endswith(".osu"):
                        full_path = os.path.join(root, fn)
                        try:
                            s = OsuParser.parse(full_path)
                            key = (
                                s.get("title", "<unknown>"),
                                s.get("artist", "<unknown>"),
                                s.get("mapper", "<unknown>")
                            )
                            if key not in uniq:
                                uniq[key] = s
                            print(f"  ✅ Found beatmap: {s['artist']} - {s['title']}")  # 🔍 DEBUG
                        except Exception as e:
                            print(f"  ⚠️ Error parsing {full_path}: {e}")  # 🔍 DEBUG
            self.library = list(uniq.values())
            self.queue = list(self.library)
            save_cache(self.osu_folder, self.library)

        print(f"[reload_songs] ✅ Reloaded {len(self.library)} songs from full folder scan")

        # Update UI immediately
        self.populate_list(self.queue)
        self.queue_lbl.setText(f"Queue: {len(self.queue)} songs")

        # Kick off a background thread to re-scan (and re-cache) later
        print("[reload_songs] Starting new background scanner thread...")
        self._scanner = LibraryScanner(self.osu_folder)
        self._scanner.done.connect(self._on_reload_complete)
        self._scanner.start()

    def load_user_settings(self):
        if SETTINGS_FILE.exists():
            try:
                with open(SETTINGS_FILE, "r") as f:
                    return json.load(f)
            except Exception as e:
                print("Failed to load settings:", e)
        return {}

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
            "resolution": f"{self.width()}×{self.height()}",
            "skipped_versions": self.skipped_versions,
        }
        try:
            with open(SETTINGS_FILE, "w") as f:
                json.dump(settings, f, indent=2)
        except Exception as e:
            print("Failed to save settings:", e)
        
    def _on_reload_complete(self, library):
        """Called when background thread finishes parsing."""
        self.library = library
        self.queue   = list(library)
        self.populate_list(self.queue)
        self.queue_lbl.setText(f"Queue: {len(self.queue)} songs")


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

    def closeEvent(self, ev):
        # 0) stop the scanner thread (if it's still running)
        if hasattr(self, "_scanner") and self._scanner.isRunning():
            print("[closeEvent] Scanner thread running. Requesting interruption...")
            self._scanner.requestInterruption()
            if not self._scanner.wait(5000):
                print("[closeEvent] Scanner thread did not terminate in time during close.")
        print("[closeEvent] Proceeding with close.")

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

        super().closeEvent(ev)
        
        self.save_user_settings()
        
    def _on_audio_status(self, status):
        # QMediaPlayer.EndOfMedia fires once when a track finishes
        if status == QMediaPlayer.EndOfMedia:
            self.next_song()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    
    window.update_media_key_listener()

    sys.exit(app.exec())
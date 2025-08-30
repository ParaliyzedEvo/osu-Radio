__version__ = "1.7.0"

import sys
import os
import json
import random
import sqlite3
import zipfile
import tempfile
import shutil
import subprocess
import tempfile
from packaging import version
from pathlib import Path
from time import monotonic
from PySide6.QtCore import (
    Qt, QUrl, QTimer, QThread, QMetaObject, Signal,
    QEvent, QSize
)
from PySide6.QtGui import (
    QIcon, QColor, QKeySequence, QShortcut, QCursor, QGuiApplication
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, QFileDialog,
    QHBoxLayout, QVBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLineEdit, QSlider, QStyle,
    QDialog, QDialogButtonBox, QCheckBox, QComboBox,
    QGraphicsOpacityEffect, QMenu, QGridLayout, QToolTip, QSizePolicy,
    QMessageBox, QProgressDialog, QScrollArea
)
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput, QVideoSink, QAudioFormat, QMediaDevices

from osuRadio.audio import PitchAdjustedPlayer, get_audio_duration
from osuRadio.db import load_cache, save_cache, get_audio_path
from osuRadio.parser import OsuParser
from osuRadio.settings import SettingsDialog
from osuRadio.ui import MarqueeLabel, BackgroundWidget
from osuRadio.update import check_for_update, download_and_install_update
from osuRadio.media_keys import update_media_key_listener
from osuRadio.msg import show_modal
from osuRadio.config import *

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
        
class MainWindow(QMainWindow):
    def __init__(self):  
        cache_path = Path(tempfile.gettempdir()) / "OsuRadioCache"
        if cache_path.exists():
            try:
                shutil.rmtree(cache_path)
                print("[Startup Cleanup] ✅ Deleted leftover temp cache.")
            except Exception as e:
                print(f"[Startup Cleanup] ❌ Failed to delete cache: {e}")
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
        self.resizable          = (res == "Custom Resolution")
        if res == "Custom Resolution":
            rw = settings.get("custom_width", 854)
            rh = settings.get("custom_height", 480)
            self.resizable = True
        else:
            try:
                rw, rh = map(int, res.split("×"))
            except:
                rw, rh = 854, 480
            self.resizable = False
        w = max(min_w, min(rw, max_w))
        h = max(min_h, min(rh, max_h))

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
            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Question)
            msg.setWindowTitle("Return to Stable?")
            msg.setText("You're currently on a pre-release build, but pre-release updates have been disabled.\n\n"
                        "Would you like to return to the latest stable version?")
            msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
            show_modal(msg)
            choice = msg.result()
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
        self.setup_media_players()
        self.is_playing = False

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

        btn_custom = QPushButton()
        btn_custom.setIcon(self.style().standardIcon(QStyle.SP_DirOpenIcon))
        btn_custom.setToolTip("Add Custom Songs")
        btn_custom.clicked.connect(self.add_custom_songs)
        tl.addWidget(btn_custom)

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
        self.playback_timer.setInterval(100)
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

        b_shuf = QPushButton()
        b_shuf.setIcon(QIcon(str(IMG_PATH / "shuffle.svg")))
        b_shuf.setIconSize(QSize(20, 20))
        b_shuf.setFixedHeight(24)
        b_shuf.setFixedWidth(34)
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
        osu_cache = load_cache(self.osu_folder)
        custom_cache = load_cache(BASE_PATH / "custom_songs")
        combined_cache = (osu_cache or []) + (custom_cache or [])
        if combined_cache:
            print(f"[startup] ✅ Loaded {len(combined_cache)} maps from cache.")
            self.library = combined_cache
            self.queue = list(combined_cache)
            self.populate_list(self.queue)
            self.queue_lbl.setText(f"Queue: {len(self.queue)} songs")
        elif first_setup:
            print("[startup] 🛠 First setup, scanning without prompt.")
            self.reload_songs()
        else:
            print("[startup] ⚠️ No cache found — will prompt for rescan.")
            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Question)
            msg.setWindowTitle("Cache Missing")
            msg.setText("No song cache was found.\nWould you like to scan your osu! songs folder?")
            msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
            show_modal(msg)
            prompt = msg.result()
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
            self.media_keys_enabled, self.preserve_pitch, self.allow_prerelease, 
            allow_resizing=self.resizable
        )
        
        QTimer.singleShot(1000, lambda: self.check_updates())
        QTimer.singleShot(0, self.apply_window_flags)
        QTimer.singleShot(0, self._set_dynamic_max_size)

    def add_custom_songs(self):
        msg = QMessageBox(self)
        msg.setWindowTitle("Custom Songs")
        msg.setText("Would you like to import or export custom songs?")
        import_btn = msg.addButton("Import", QMessageBox.AcceptRole)
        export_btn = msg.addButton("Export", QMessageBox.ActionRole)
        cancel_btn = msg.addButton(QMessageBox.Cancel)
        show_modal(msg)

        if msg.clickedButton() == import_btn:
            self.import_custom_songs_flow()
        elif msg.clickedButton() == export_btn:
            self.export_songs_dialog()

    def import_custom_audio(self, folder: Path):
        print(f"[Custom Audio] Importing from: {folder}")
        supported_exts = {".mp3", ".wav", ".ogg", ".flac", ".m4a", ".opus"}
        maps = []

        # Load existing songs from this folder
        existing = set()
        with sqlite3.connect(DATABASE_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT title, artist, audio FROM songs WHERE folder = ?", (str(folder),))
            existing = set((r[0], r[1], r[2]) for r in cursor.fetchall())

        for file in folder.glob("*"):
            if file.suffix.lower() in supported_exts:
                try:
                    title = file.stem
                    artist = "Custom"
                    audio = file.name

                    if (title, artist, audio) in existing:
                        print(f"[Custom Audio] Skipping duplicate: {title}")
                        continue

                    duration = get_audio_duration(file) or 0
                    maps.append({
                        "title": title,
                        "artist": artist,
                        "mapper": "User",
                        "audio": audio,
                        "background": "",
                        "length": int(duration * 1000),
                        "osu_file": "",
                        "folder": str(folder)
                    })
                    print(f"[Custom Audio] Found: {title} ({audio})")
                except Exception as e:
                    print(f"[Custom Audio] Failed to import {file}: {e}")

        if maps:
            save_cache(str(folder), maps)

            if maps:
                save_cache(str(folder), maps)
                try:
                    mtime = str(os.path.getmtime(self.osu_folder))
                    with sqlite3.connect(DATABASE_FILE) as conn:
                        cursor = conn.cursor()
                        cursor.execute(
                            "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
                            ("folder_mtime", mtime)
                        )
                        conn.commit()
                except Exception as e:
                    print(f"[Custom Audio] Failed to update folder_mtime: {e}")
                self.library.extend(maps)
                self.queue.extend(maps)
                self.populate_list(self.queue)
                self.queue_lbl.setText(f"Queue: {len(self.queue)} songs")
                QMessageBox.information(self, "Import Complete", f"Imported {len(maps)} custom songs.")
            else:
                QMessageBox.warning(self, "No Songs Found", "No supported audio files found.")
            
            if self.current_index >= len(self.queue):
                self.current_index = 0

    def import_custom_songs_flow(self):
        custom_folder = BASE_PATH / "custom_songs"
        custom_folder.mkdir(exist_ok=True)

        # Open file explorer
        if IS_WINDOWS:
            os.startfile(str(custom_folder))
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(custom_folder)])
        elif sys.platform.startswith("linux"):
            subprocess.Popen(["xdg-open", str(custom_folder)])

        # Ask to import now
        msg = QMessageBox(self)
        msg.setWindowTitle("Import Custom Songs")
        msg.setText("Do you want to import songs from the custom_songs folder now?")
        msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        show_modal(msg)

        if msg.result() == QMessageBox.Yes:
            self.import_custom_audio(custom_folder)

    def export_songs_dialog(self):        
        def filter_checkboxes(text):
            lower = text.lower()
            for cb in song_checks:
                song = cb.song_data
                visible = lower in song["title"].lower() or lower in song["artist"].lower()
                cb.setVisible(visible)
            update_select_all_state()

        def update_select_all_state():
            visible_checks = [cb for cb in song_checks if cb.isVisible()]
            checked = [cb for cb in visible_checks if cb.isChecked()]

            total = len(visible_checks)
            count_label.setText(f"{len(checked)} / {total} selected")

        previously_selected = set()
        try:
            if Path(EXPORT_STATE_FILE).exists():
                with open(EXPORT_STATE_FILE, "r", encoding="utf-8") as f:
                    previously_selected = set(json.load(f))
        except Exception as e:
            print(f"[Export] Failed to load previous selection: {e}")
            previously_selected = set()

        songs = []
        with sqlite3.connect(DATABASE_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT title, artist, audio, folder FROM songs")
            rows = cursor.fetchall()
            songs = [{"title": r[0], "artist": r[1], "audio": r[2], "folder": r[3]} for r in rows]

        if not songs:
            QMessageBox.information(self, "No Songs", "No songs found in the database.")
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("Export Songs")
        dialog.setMinimumSize(400, 500)

        layout = QVBoxLayout()

        search_bar = QLineEdit()
        search_bar.setPlaceholderText("Search songs…")
        layout.addWidget(search_bar)
        search_bar.textChanged.connect(filter_checkboxes)

        count_label = QLabel("0 / 0 selected")
        layout.addWidget(count_label)

        label = QLabel("Select songs to export:")
        layout.addWidget(label)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)

        song_checks = []
        for song in songs:
            checkbox = QCheckBox(f"{song['artist']} - {song['title']}")
            checkbox.song_data = song
            unique_key = f"{song['title']}|{song['artist']}|{song['audio']}"
            checkbox.song_key = unique_key
            if unique_key in previously_selected:
                checkbox.setChecked(True)
            checkbox.toggled.connect(update_select_all_state)
            scroll_layout.addWidget(checkbox)
            song_checks.append(checkbox)
        
        QTimer.singleShot(0, update_select_all_state)

        scroll_content.setLayout(scroll_layout)
        scroll.setWidget(scroll_content)
        layout.addWidget(scroll)

        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        layout.addWidget(button_box)

        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)

        dialog.setLayout(layout)

        if dialog.exec() != QDialog.Accepted:
            return

        selected_songs = [c.song_data for c in song_checks if c.isChecked()]
        if not selected_songs:
            QMessageBox.warning(self, "No Selection", "No songs selected for export.")
            return
        
        try:
            selected_keys = [c.song_key for c in song_checks if c.isChecked()]
            with open(EXPORT_STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(selected_keys, f, indent=2)
        except Exception as e:
            print(f"[Export] Failed to save export selection: {e}")

        path, _ = QFileDialog.getSaveFileName(self, "Export Songs As Zip", str(BASE_PATH / "custom_songs_export.zip"), "Zip Files (*.zip)")
        if not path:
            return

        try:
            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zipf:
                for song in selected_songs:
                    audio_path = Path(song["folder"]) / song["audio"]
                    if audio_path.exists():
                        arcname = f"{song['artist']} - {song['title']}{audio_path.suffix}"
                        zipf.write(audio_path, arcname=arcname)
                    else:
                        print(f"[Export] Missing: {audio_path}")
            QMessageBox.information(self, "Export Complete", f"Exported {len(selected_songs)} songs to:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "Export Failed", f"An error occurred while exporting:\n{e}")
        
    def apply_window_flags(self):
        if self.resizable:
            self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            self.setMinimumSize(480, int(480 / self.aspect_ratio))
            self._set_dynamic_max_size()
            self.setWindowFlags(
                Qt.Window |
                Qt.CustomizeWindowHint |
                Qt.WindowTitleHint |
                Qt.WindowMinMaxButtonsHint |
                Qt.WindowCloseButtonHint
            )
        else:
            self.setMinimumSize(self.width(), self.height())
            self.setMaximumSize(self.width(), self.height())
            self.setWindowFlags(
                Qt.Window |
                Qt.CustomizeWindowHint |
                Qt.WindowTitleHint |
                Qt.WindowMinimizeButtonHint |
                Qt.WindowCloseButtonHint
            )
        self.show()
        
    def _set_dynamic_max_size(self):
        screen = QGuiApplication.primaryScreen()
        if screen:
            available = screen.availableGeometry()
            self.setMaximumSize(available.width(), available.height())
        
    def _update_elapsed_label(self, value):
        if getattr(self, "_user_dragging", False) or self.is_playing:
            self.elapsed_label.setText(self.format_time(value))
        
    def _tick_seekbar(self):
        player = self.pitch_player.player
        if (
            player.playbackState() == QMediaPlayer.PlayingState
            and (not player.isAvailable() or not player.isAvailable())
        ):
            print("[Tick] Detected silent playback with pitch adjustment — restarting audio")
            self.seek(self.slider.value())
        if self._playback_start_time is None:
            return
        speed = float(self.speed_combo.currentText().replace("x", ""))
        elapsed_ms = int((monotonic() - self._playback_start_time) * 1000 * speed)
        elapsed_ms = min(elapsed_ms, self.current_duration)
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
                return  # No meaningful change, skip

            self.playback_rate = rate

            if self.preserve_pitch:
                # Use FFmpeg to reprocess the audio
                song = self.queue[self.current_index]
                path = get_audio_path(song)
                self.pitch_player.play(
                    str(path),
                    speed=rate,
                    preserve_pitch=True,
                    start_ms=self.slider.value(),
                    force_play=self.is_playing
                )
                self.current_duration = self.pitch_player.last_duration
                self.slider.setRange(0, self.current_duration)
                self.total_label.setText(self.format_time(self.current_duration))
            else:
                # Just change playback rate directly
                self.pitch_player.player.setPlaybackRate(rate)
                print(f"[Playback Speed] Set to {rate}x")
                if self.is_playing:
                    self.seek(self.slider.value())

            # Update the dropdown UI
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
            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Question)
            msg.setWindowTitle("Stable Release Available?")
            msg.setText("You're currently on a pre-release build. Would you like to return to the latest stable version?")
            msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
            show_modal(msg)
            choice = msg.result()
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
        self.slider.sliderReleased.connect(lambda: (setattr(self, "_user_dragging", False), self.seek(self.slider.value())))
        self.slider.valueChanged.connect(lambda v: self._update_elapsed_label(v))
        
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

    def apply_settings(self, folder, light, opacity, w, h, hue, video_on, autoplay, media_keys, preserve_pitch, allow_prerelease, allow_resizing=False):
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
            update_media_key_listener(self)
        self.preserve_pitch = preserve_pitch
        self.allow_prerelease = allow_prerelease
        if allow_resizing:
            self.resizable = True
            self.setMinimumSize(480, int(480 / self.aspect_ratio))
            self._set_dynamic_max_size()
            self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            self.setWindowFlags(
                Qt.Window |
                Qt.CustomizeWindowHint |
                Qt.WindowTitleHint |
                Qt.WindowMinMaxButtonsHint |
                Qt.WindowCloseButtonHint
            )
            self.show()
        else:
            self.resizable = False
            self.setMinimumSize(w, h)
            self.setMaximumSize(w, h)
            self.setWindowFlags(
            Qt.Window |
            Qt.CustomizeWindowHint |
            Qt.WindowTitleHint |
            Qt.WindowMinimizeButtonHint |
            Qt.WindowCloseButtonHint
        )
            self.resize(w, h)
            self.show()
            
        self.save_user_settings()

    def _apply_ui_settings(self, light, opacity, w, h, hue):
        self.light_mode = light
        self.apply_theme(light)
        self.ui_opacity = opacity
        self.ui_effect.setOpacity(opacity)
        if self.resizable:
            self.setMinimumSize(480, int(480 / self.aspect_ratio))
            self._set_dynamic_max_size()
            self.resize(w, h)
        else:
            self.setMinimumSize(w, h)
            self.setMaximumSize(w, h)
            
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
            icon = QIcon(str(IMG_PATH / "repeat-off.svg"))
            self.loop_btn.setIcon(icon)
            self.loop_btn.setText("")
            self.loop_btn.setIconSize(QSize(20, 20))
            self.loop_btn.setFixedHeight(24)
            self.loop_btn.setFixedWidth(34)
        elif self.loop_mode == 1:
            # Loop all
            icon = QIcon(str(IMG_PATH / "repeat.svg"))
            self.loop_btn.setIcon(icon)
            self.loop_btn.setText("")
            self.loop_btn.setIconSize(QSize(20, 20))
            self.loop_btn.setFixedHeight(24)
            self.loop_btn.setFixedWidth(34)
        elif self.loop_mode == 2:
            # Loop one
            icon = QIcon(str(IMG_PATH / "repeat-once.svg"))
            self.loop_btn.setIcon(icon)
            self.loop_btn.setText("")
            self.loop_btn.setIconSize(QSize(20, 20))
            self.loop_btn.setFixedHeight(24)
            self.loop_btn.setFixedWidth(34)

    def play_song(self, song):
        audio_path = get_audio_path(song)
        self.audio.setSource(QUrl.fromLocalFile(str(audio_path)))
        self.audio.play()
        self.now_lbl.setText(f"{song['artist']} - {song['title']}")
       
    def toggle_play(self):
        player = self.pitch_player.player
        state = player.playbackState()

        if state == QMediaPlayer.PlayingState:
            player.pause()
            self.playback_timer.stop()
            self.is_playing = False
        else:
            player.play()
            self.playback_timer.start(1000)
            self.is_playing = True

        self.update_play_pause_icon()
   
    def pause_song(self):
        self.pitch_player.player.pause()
        self.is_playing = False
        self.update_play_pause_icon()

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
        self.pitch_player.was_playing_before_seek = True
        self.pitch_player.play(str(path), speed=speed, preserve_pitch=self.preserve_pitch, force_play=True)
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
            QTimer.singleShot(0, lambda: self.play_song_at_index(self.current_index))
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
    
    def _finalize_seek_ui(self, pos):
        self.current_duration = self.pitch_player.last_duration
        self.slider.setRange(0, self.current_duration)
        self.slider.setValue(pos if pos <= self.current_duration else 0)
        self.elapsed_label.setText(self.format_time(pos if pos <= self.current_duration else 0))
        self.total_label.setText(self.format_time(self.current_duration))

    def seek(self, pos):

        song = self.queue[self.current_index]
        path = get_audio_path(song)
        speed = float(self.speed_combo.currentText().replace("x", ""))

        if self.preserve_pitch:
            adjusted_pos = int(pos / speed)
        else:
            adjusted_pos = pos

        self._playback_start_time = monotonic() - (pos / 1000)

        safe_pos = min(pos, self.pitch_player.last_duration or pos)
        self.pitch_player.play(str(path), speed=speed, preserve_pitch=self.preserve_pitch, start_ms=safe_pos, force_play=self.is_playing)

        QTimer.singleShot(1500, lambda: self._finalize_seek_ui(pos))

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
        osu_cache = load_cache(self.osu_folder)
        custom_cache = load_cache(BASE_PATH / "custom_songs")

        combined_cache = (osu_cache or []) + (custom_cache or [])
        if combined_cache:
            print("[reload_songs] ✅ Loaded from cache.")
            self.library = combined_cache
            self.queue = list(combined_cache)
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
            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Question)
            msg.setWindowTitle("Cancel Beatmap Scan?")
            msg.setText("Are you sure you want to cancel scanning for beatmaps?\n\n"
                        "To run it again, click Reload Maps in the top right.")
            msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
            show_modal(msg)
            reply = msg.result()
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
            "custom_width": "null",
            "custom_height": "null",
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
            "resolution": "Custom Resolution" if self.resizable else f"{self.width()}×{self.height()}",
            "custom_width": self.width() if self.resizable else None,
            "custom_height": self.height() if self.resizable else None,
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
        song = item.data(Qt.UserRole)

        if song in self.queue:
            self.queue.remove(song)

        insert_index = self.current_index + 1
        self.queue.insert(insert_index, song)

        self.populate_list(self.queue)
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
    
    update_media_key_listener(window)

    sys.exit(app.exec())
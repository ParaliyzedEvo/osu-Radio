import sys
import os
import json
import tempfile
import shutil
import tempfile
from pathlib import Path
from time import monotonic
from PySide6.QtCore import (
    Qt, QUrl, QTimer, Signal, QSize
)
from PySide6.QtGui import (
    QIcon, QKeySequence, QShortcut, QGuiApplication
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, QFileDialog,
    QHBoxLayout, QVBoxLayout, QListWidget,
    QPushButton, QLineEdit, QSlider, QStyle, QComboBox,
    QGraphicsOpacityEffect, QGridLayout, QSizePolicy,
    QMessageBox, QProgressDialog
)
from PySide6.QtMultimedia import QMediaPlayer, QVideoSink

from osuRadio import *
from osuRadio import __version__

class MainWindow(QMainWindow, UiMixin, PlayerMixin, SettingsMixin, CustomSongsMixin, LibraryMixin, ContextMenuMixin, UpdateMixin):
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
        self.brightness         = settings.get("brightness",255)
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
        video_file = Path(__file__).parent / "Background Video" / "Triangles.mp4"
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
            
        # Load from cache if available
        osu_cache = load_cache(self.osu_folder)
        custom_cache = load_cache(BASE_PATH / "custom_songs")
        combined_cache = (osu_cache or []) + (custom_cache or [])
        
        if combined_cache and not first_setup:
            is_valid, status_msg, missing_songs = validate_cache(self.osu_folder)
            print(f"[startup] Cache validation: {status_msg}")
            
            if is_valid and not missing_songs:
                print(f"[startup] ✅ Loaded {len(combined_cache)} maps from cache.")
                self.library = combined_cache
                self.queue = list(combined_cache)
                self.populate_list(self.queue)
                self.queue_lbl.setText(f"Queue: {len(self.queue)} songs")
            
            elif is_valid and missing_songs and len(missing_songs) < len(combined_cache) * 0.3:
                print(f"[startup] ⚠️ Cache has {len(missing_songs)} missing songs")
                
                msg = QMessageBox(self)
                msg.setIcon(QMessageBox.Question)
                msg.setWindowTitle("Cache Needs Attention")
                msg.setText(
                    f"Your song cache has {len(missing_songs)} missing songs.\n\n"
                    "Options:\n"
                    "• Clean Up: Remove missing songs (quick)\n"
                    "• Full Rescan: Scan entire folder (thorough)\n"
                    "• Use As-Is: Continue with current cache"
                )
                clean_btn = msg.addButton("Clean Up", QMessageBox.AcceptRole)
                rescan_btn = msg.addButton("Full Rescan", QMessageBox.ActionRole)
                use_btn = msg.addButton("Use As-Is", QMessageBox.RejectRole)
                show_modal(msg)
                
                clicked = msg.clickedButton()
                
                if clicked == clean_btn:
                    removed = remove_missing_songs(missing_songs)
                    osu_cache = load_cache(self.osu_folder)
                    custom_cache = load_cache(BASE_PATH / "custom_songs")
                    combined_cache = (osu_cache or []) + (custom_cache or [])
                    if combined_cache:
                        self.library = combined_cache
                        self.queue = list(combined_cache)
                        self.populate_list(self.queue)
                        self.queue_lbl.setText(f"Queue: {len(self.queue)} songs")
                        QMessageBox.information(
                            self, "Cleanup Complete", 
                            f"Removed {removed} missing songs.\n{len(combined_cache)} songs remaining."
                        )
                elif clicked == rescan_btn:
                    self.reload_songs(force_rescan=True)
                else:
                    self.library = combined_cache
                    self.queue = list(combined_cache)
                    self.populate_list(self.queue)
                    self.queue_lbl.setText(f"Queue: {len(self.queue)} songs")
            
            else:
                print("[startup] ❌ Cache is severely outdated or corrupted")
                
                msg = QMessageBox(self)
                msg.setIcon(QMessageBox.Warning)
                msg.setWindowTitle("Cache Outdated")
                msg.setText(
                    f"{status_msg}\n\n"
                    "A full rescan is strongly recommended.\n"
                    "Would you like to scan your songs folder now?"
                )
                msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
                show_modal(msg)
                
                if msg.result() == QMessageBox.Yes:
                    self.reload_songs(force_rescan=True)
                else:
                    self.library = combined_cache
                    self.queue = list(combined_cache)
                    self.populate_list(self.queue)
                    self.queue_lbl.setText(f"Queue: {len(self.queue)} songs")
        
        elif first_setup:
            print("[startup] 🛠 First setup, scanning without prompt.")
            self.reload_songs(force_rescan=True)
        
        else:
            print("[startup] ⚠️ No cache found")
            
            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Question)
            msg.setWindowTitle("Initial Setup")
            msg.setText(
                "No song cache was found.\n\n"
                "osu!Radio needs to scan your songs folder to build a library.\n"
                "This may take a few minutes depending on your library size.\n\n"
                "Would you like to scan now?"
            )
            msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
            show_modal(msg)
            
            if msg.result() == QMessageBox.Yes:
                json_path = BASE_PATH / "library_cache.json"
                if json_path.exists():
                    try:
                        print("[startup] Found legacy JSON cache. Importing to SQLite...")
                        with open(json_path, "r", encoding="utf-8") as f:
                            data = json.load(f)
                            maps = data.get("maps", []) if isinstance(data, dict) else []
                        
                        if isinstance(maps, list) and maps:
                            import_progress = QProgressDialog(
                                "Importing legacy cache...", 
                                None, 0, len(maps), self
                            )
                            import_progress.setWindowModality(Qt.ApplicationModal)
                            import_progress.setWindowTitle("osu!Radio - Importing")
                            import_progress.show()
                            
                            save_cache(self.osu_folder, maps)
                            
                            for i, s in enumerate(maps):
                                import_progress.setValue(i)
                                QApplication.processEvents()
                            
                            import_progress.close()
                            json_path.unlink()
                            
                            cached = load_cache(self.osu_folder)
                            if cached:
                                self.library = cached
                                self.queue = list(cached)
                                self.populate_list(self.queue)
                                self.queue_lbl.setText(f"Queue: {len(self.queue)} songs")
                                
                                QMessageBox.information(
                                    self, "Import Complete",
                                    f"Successfully imported {len(cached)} songs from legacy cache!"
                                )
                                return
                    except Exception as e:
                        print(f"[startup] Failed to import from legacy JSON: {e}")
                
                print("[startup] Starting full scan...")
                self.reload_songs(force_rescan=True)
            else:
                sys.exit()
            
        self.apply_settings(
            self.osu_folder, self.light_mode, self.ui_opacity,
            w, h, self.hue, self.brightness, self.video_enabled, self.autoplay,
            self.media_keys_enabled, self.preserve_pitch, self.allow_prerelease, 
            allow_resizing=self.resizable
        )
        
        QTimer.singleShot(1000, lambda: self.check_updates())
        QTimer.singleShot(0, self.apply_window_flags)
        QTimer.singleShot(0, self._set_dynamic_max_size)
        
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
        
    def set_volume(self, v):
        self.audio_out.setVolume(v / 100)
        self._update_volume_label(v)
        self.vol = v
        self.save_user_settings()

    def open_settings(self):
        SettingsDialog(self).exec()

    def closeEvent(self, event):
        # 0) Stop the scanner thread (if it's still running)
        if hasattr(self, "_scanner") and self._scanner.isRunning():
            print("[closeEvent] Requesting scanner thread interruption...")
            self._scanner.requestInterruption()
            self._scanner.wait(3000)

        # 1) Unregister global hotkeys
        try:
            if hasattr(self, 'media_key_listener') and self.media_key_listener:
                self.media_key_listener.stop()
                self.media_key_listener = None
        except Exception as e:
            print(f"[Cleanup] Failed to stop media key listener: {e}")

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
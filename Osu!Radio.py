import sys
import os
import re
from pathlib import Path
from mutagen.mp3 import MP3
import ctypes
from ctypes import wintypes
from PySide6.QtCore import QMetaObject
from PySide6.QtCore import QAbstractNativeEventFilter, QCoreApplication, QThread
import json, time

from PySide6.QtCore import (
    Qt, QSettings, QUrl, QTimer,
    QPropertyAnimation, QEasingCurve, Property,
    QSequentialAnimationGroup, QPauseAnimation
)

from PySide6.QtWidgets import QSizePolicy, QGraphicsColorizeEffect
from PySide6.QtGui import QImage, QIcon
from PySide6.QtGui import QPixmap, QPainter, QColor
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel,
)

from PySide6.QtCore import QPropertyAnimation, QEasingCurve, Property, Signal
from PySide6.QtGui  import QPainter

from PySide6.QtCore import Qt, QSettings, QUrl, QTimer
from PySide6.QtGui import (
    QPixmap, QPainter,
    QKeySequence, QShortcut, QGuiApplication, QColor,
    QCursor
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, QFileDialog,
    QHBoxLayout, QVBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLineEdit, QSlider, QStyle,
    QDialog, QDialogButtonBox, QCheckBox, QComboBox,
    QGraphicsOpacityEffect, QMenu, QGridLayout, QSplitter,
    QToolTip
)

from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput, QVideoSink
from pathlib import Path

if getattr(sys, "frozen", False):
    # Running in a PyInstaller bundle
    BASE_PATH = Path(sys.executable).parent
else:
    # Running as a normal .py
    BASE_PATH = Path(__file__).parent

# Replace CACHE_FILE = "library_cache.json"
CACHE_FILE = BASE_PATH / "library_cache.json"
SETTINGS_FILE = BASE_PATH / "settings.json"

def load_cache(osu_folder):
    """Return cached list or None if cache is invalid/missing."""
    try:
        with open(CACHE_FILE, "r") as f:
            data = json.load(f)
        # Has the folder changed since we last cached?
        if data.get("folder_mtime") == os.path.getmtime(osu_folder):
            return data["maps"]
    except Exception:
        pass
    return None

def save_cache(osu_folder, maps):
    data = {
        "folder_mtime": os.path.getmtime(osu_folder),
        "maps": maps
    }
    with open(CACHE_FILE, "w") as f:
        json.dump(data, f)

# Win32 constants
WM_HOTKEY            = 0x0312
MOD_NOREPEAT         = 0x4000
VK_MEDIA_PLAY_PAUSE  = 0xB3
VK_MEDIA_NEXT_TRACK  = 0xB0
VK_MEDIA_PREV_TRACK  = 0xB1

user32 = ctypes.windll.user32

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
    def parse(osu_path):
        """Parse the .osu file at osu_path and return a dict with audio, title, artist, etc."""
        data = {
            "audio":      "",
            "title":      "",
            "artist":     "",
            "mapper":     "",
            "background": "",
            "length":     0,
            "osu_file":   osu_path,
            "folder":     str(Path(osu_path).parent),
        }

        print(f"Parsing {osu_path!r}")  # debug

        for raw in read_osu_lines(osu_path):
            line = raw.strip()
            low  = line.lower()

            # audio filename (case‐insensitive, any spacing around colon)
            m = re.match(r'\s*audiofilename\s*:\s*(.+)', line, re.IGNORECASE)
            if m:
                data["audio"] = m.group(1).strip()
                print(f"  → Found AudioFilename: {data['audio']}")  # debug
                continue

            # metadata fields
            if low.startswith("title:"):
                data["title"] = line.split(":", 1)[1].strip()
            elif low.startswith("artist:"):
                data["artist"] = line.split(":", 1)[1].strip()
            elif low.startswith("creator:") or low.startswith("mapper:"):
                data["mapper"] = line.split(":", 1)[1].strip()

            # background image (first 0,0 event)
            if low.startswith("0,0"):
                bgm = re.search(r'0,0,"([^"]+)"', line)
                if bgm and not data["background"]:
                    data["background"] = bgm.group(1)

        # calculate length via Mutagen (if possible)
        try:
            audio_path = Path(data["folder"]) / data["audio"]
            mp = MP3(str(audio_path))
            data["length"] = int(mp.info.length * 1000)
        except:
            pass

        return data

class SettingsDialog(QDialog):
    def __init__(self, parent: "MainWindow"):
        super().__init__(parent)
        
        self.main = parent
        self.setWindowTitle("Settings")
        self.setFixedSize(400, 350)

        v = QVBoxLayout(self)

        # Songs folder
        h1 = QHBoxLayout()
        h1.addWidget(QLabel("Songs Folder:"))
        self.folderEdit = QLineEdit(self.main.osu_folder)
        h1.addWidget(self.folderEdit)
        b1 = QPushButton("Browse…")
        b1.clicked.connect(self.browse_folder)
        h1.addWidget(b1)
        v.addLayout(h1)

        # Light mode
        self.lightCheck = QCheckBox("Light Mode")
        self.lightCheck.setChecked(self.main.light_mode)
        v.addWidget(self.lightCheck)
        
        # Background Video toggle
        self.videoCheck = QCheckBox("Enable Background Video")
        self.videoCheck.setChecked(self.main.video_enabled)
        v.addWidget(self.videoCheck)
        
        # Autoplay
        self.autoplayCheck = QCheckBox("Autoplay on Startup")
        self.autoplayCheck.setChecked(self.main.autoplay)
        v.addWidget(self.autoplayCheck)

        # UI opacity
        h3 = QHBoxLayout()
        h3.addWidget(QLabel("UI Opacity:"))
        self.opacitySlider = QSlider(Qt.Horizontal)
        self.opacitySlider.setRange(10, 100)
        self.opacitySlider.setValue(int(self.main.ui_opacity * 100))
        h3.addWidget(self.opacitySlider)
        v.addLayout(h3)
        
        # Live-update UI opacity
        self.opacitySlider.valueChanged.connect(
            lambda val: self.main.ui_effect.setOpacity(val / 100.0)
        )

        # Hue adjustment
        h5 = QHBoxLayout()
        h5.addWidget(QLabel("Hue:"))
        self.hueSlider = QSlider(Qt.Horizontal)
        self.hueSlider.setRange(0, 360)
        self.hueSlider.setValue(self.main.hue)
        h5.addWidget(self.hueSlider)
        v.addLayout(h5)

        # Live‐update the background hue as you drag
        from PySide6.QtGui import QColor
        self.hueSlider.valueChanged.connect(
            lambda v: self.main.bg_widget.effect.setColor(QColor.fromHsv(v, 255, 255))
        )

        # Resolution presets
        h4 = QHBoxLayout()
        h4.addWidget(QLabel("Resolution:"))
        self.resCombo = QComboBox()
        self.resolutions = {
            "1920×1080": (1920, 1080),
            "1280×720":  (1280, 720),
            "854×480":   (854, 480),
            "640×360":   (640, 360),
            "480×270":   (480, 270),
        }
        self.resCombo.addItems(self.resolutions.keys())
        cw, ch = self.main.width(), self.main.height()
        for name, (rw, rh) in self.resolutions.items():
            if rw == cw and rh == ch:
                self.resCombo.setCurrentText(name)
                break
        h4.addWidget(self.resCombo)
        v.addLayout(h4)

        # OK / Cancel
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.apply)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def browse_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Select osu! Songs Folder")
        if d:
            self.folderEdit.setText(d)

    def apply(self):
        folder  = self.folderEdit.text()
        light   = self.lightCheck.isChecked()
        opacity = self.opacitySlider.value() / 100.0
        hue     = self.hueSlider.value()
        res     = self.resCombo.currentText()
        w, h    = self.resolutions[res]
        video_on = self.videoCheck.isChecked()
        autoplay = self.autoplayCheck.isChecked()

        # This single call saves all settings, including hue
        self.main.apply_settings(folder, light, opacity, w, h, hue, video_on, autoplay)

        # And immediately update the effect color one last time
        from PySide6.QtGui import QColor
        self.main.bg_widget.effect.setColor(QColor.fromHsv(hue, 255, 255))
        
        self.main.save_user_settings()

        self.accept()  
        
class BackgroundWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap = QPixmap()
        # INSTALL A COLORIZE EFFECT:
        self.effect = QGraphicsColorizeEffect(self)
        self.effect.setStrength(1.0)  # full colorize
        self.setGraphicsEffect(self.effect)

    def setFrame(self, frame):
        img = frame.toImage()
        pm = QPixmap.fromImage(img).scaled(
            self.size(),
            Qt.KeepAspectRatioByExpanding,
            Qt.SmoothTransformation
        )
        self._pixmap = pm
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.drawPixmap(0, 0, self._pixmap)
        p.end()
        
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
            # forward scroll
            a1 = QPropertyAnimation(self, b"offset", self)
            a1.setStartValue(0); a1.setEndValue(span)
            a1.setDuration(span * 20)
            a1.setEasingCurve(QEasingCurve.Linear)
            # pause
            p1 = QPauseAnimation(1000, self)
            # reverse scroll
            a2 = QPropertyAnimation(self, b"offset", self)
            a2.setStartValue(span); a2.setEndValue(0)
            a2.setDuration(span * 20)
            a2.setEasingCurve(QEasingCurve.Linear)
            # pause
            p2 = QPauseAnimation(1000, self)
            # build sequence
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
        p = QPainter(self)
        p.setClipRect(self.rect())
        p.drawText(-self._offset, self.height() - 5, self.text())
        p.end()

    def offset(self): return self._offset
    def setOffset(self, v): self._offset = v; self.update()
    offset = Property(int, offset, setOffset)

class LibraryScanner(QThread):
    done = Signal(list)

    def __init__(self, osu_folder):
        super().__init__()
        self.osu_folder = osu_folder

    def run(self):
        raw, uniq = [], {}
        for root, _, files in os.walk(self.osu_folder):
            for fn in files:
                if fn.lower().endswith(".osu"):
                    try:
                        s = OsuParser.parse(os.path.join(root, fn))
                        key = (s.get("title",""), s.get("artist",""), s.get("mapper",""))
                        if key not in uniq:
                            uniq[key] = s
                    except:
                        pass
        library = list(uniq.values())
        save_cache(self.osu_folder, library)
        self.done.emit(library)

class MainWindow(QMainWindow):
    def __init__(self):  
        super().__init__()
        
        self.library = []
        self.queue   = []
        self.current_index = 0
        
        base_path = getattr(sys, "_MEIPASS", os.path.abspath(os.path.dirname(__file__)))
        icon_path = os.path.join(base_path, "Osu!RadioIcon.ico")
        self.setWindowIcon(QIcon(icon_path))
        
        self.setWindowTitle("osu!Radio")
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

        self.light_mode     = settings.get("light_mode", False)
        self.ui_opacity     = settings.get("ui_opacity", 0.75)
        self.hue            = settings.get("hue", 240)
        self.loop_mode      = settings.get("loop_mode", 0)
        self.video_enabled  = settings.get("video_enabled", True)
        self.autoplay       = settings.get("autoplay", False)
        res                 = settings.get("resolution", "854×480")
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
        grid.setContentsMargins(0, 0, 0, 0)

        # Background video widget
        self.bg_widget = BackgroundWidget(central)
        self.bg_widget.main = self
        self.bg_widget.setAttribute(Qt.WA_TransparentForMouseEvents)
        grid.addWidget(self.bg_widget, 0, 0)

        # UI overlay
        self.ui = QWidget(central)
        self.ui_effect = QGraphicsOpacityEffect(self.ui)
        self.ui.setGraphicsEffect(self.ui_effect)
        self.ui_effect.setOpacity(self.ui_opacity)
        grid.addWidget(self.ui, 0, 0)
        self.bg_widget.stackUnder(self.ui)

        # Build UI
        ui_layout = QVBoxLayout(self.ui)
        ui_layout.setContentsMargins(5, 5, 5, 5)

        splitter = QSplitter(Qt.Horizontal, self.ui)
        left = QWidget(splitter)
        ll = QVBoxLayout(left)
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
        splitter.addWidget(left)

        self.bp_preview = QLabel(splitter)
        self.bp_preview.setAlignment(Qt.AlignCenter)
        splitter.addWidget(self.bp_preview)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        ui_layout.addWidget(splitter, 1)

        # Bottom controls
        bot = QHBoxLayout()
        vol = QSlider(Qt.Horizontal)
        vol.setRange(0, 100)
        vol.setValue(30)
        self.audio_out.setVolume(0.3)
        vol.valueChanged.connect(lambda v: self.audio_out.setVolume(v/100))
        bot.addWidget(vol, 1)
        
        self.loop_btn = QPushButton()
        self.loop_btn.setToolTip("Loop: Off")
        self.update_loop_icon()
        self.loop_btn.clicked.connect(self.toggle_loop_mode)
        bot.addWidget(self.loop_btn)

        b_shuf = QPushButton()
        b_shuf.setIcon(self.style().standardIcon(QStyle.SP_FileDialogNewFolder))
        b_shuf.clicked.connect(self.shuffle)
        bot.addWidget(b_shuf)

        for ico, fn in [
            (QStyle.SP_MediaSkipBackward, self.prev_song),
            (QStyle.SP_MediaPlay,         self.toggle_play),
            (QStyle.SP_MediaPause,        self.pause_song),
            (QStyle.SP_MediaSkipForward,  self.next_song),
        ]:
            b = QPushButton()
            b.setIcon(self.style().standardIcon(ico))
            b.clicked.connect(fn)
            bot.addWidget(b)

        # replaced sliderMoved with sliderReleased
        self.slider = QSlider(Qt.Horizontal)
        # Make the slider expand/shrink to fill available space
        self.slider.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.slider.sliderMoved.connect(self.seek)
        self.slider.sliderReleased.connect(lambda: self.seek(self.slider.value()))
        self.slider.sliderPressed.connect(self._slider_jump_to_click)
        # Use a stretch factor of 1 so it shares space proportionally
        bot.addWidget(self.slider, 1)

        self.now_lbl = MarqueeLabel("—")
        bot.addWidget(self.now_lbl, 1)
        # after creating self.now_lbl …
        self.now_lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        # ensure at least ~15 chars fit before scrolling
        min_w = self.now_lbl.fontMetrics().averageCharWidth() * 15
        self.now_lbl.setMinimumWidth(min_w)
        ui_layout.addLayout(bot)

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
        user32.RegisterHotKey(0, 1, MOD_NOREPEAT, VK_MEDIA_PLAY_PAUSE)
        user32.RegisterHotKey(0, 2, MOD_NOREPEAT, VK_MEDIA_NEXT_TRACK)
        user32.RegisterHotKey(0, 3, MOD_NOREPEAT, VK_MEDIA_PREV_TRACK)
        cached = load_cache(self.osu_folder)    
        if cached:
            self.library = cached
            self.queue   = list(cached)
            self.populate_list(self.queue)
            self.queue_lbl.setText(f"Queue: {len(self.queue)} songs")
        else:
            # no cache yet: this will do the scan and create the cache
            self.reload_songs()
            
        self.apply_settings(
            self.osu_folder, self.light_mode, self.ui_opacity,
            w, h, self.hue, self.video_enabled, self.autoplay
        )

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

    def apply_settings(self, folder, light, opacity, w, h, hue, video_on, autoplay):
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

        self.setFixedSize(w, h)
        self.save_user_settings()

    def _apply_ui_settings(self, light, opacity, w, h, hue):
        self.light_mode = light
        self.apply_theme(light)
        self.ui_opacity = opacity
        self.ui_effect.setOpacity(opacity)
        self.setFixedSize(w, h)
        self.hue = hue
        from PySide6.QtGui import QColor
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

    def apply_theme(self, light: bool):
        if light:
            self.ui.setStyleSheet("background-color: rgba(255,255,255,200); color:black;")
        else:
            self.ui.setStyleSheet("")

    def populate_list(self, songs):
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
            hits = [
                s for s in self.library
                if t in s['title'].lower()
                or t in s['artist'].lower()
                or t in s['mapper'].lower()
            ]
            self.populate_list(hits)
        # self.song_list.setCurrentRow(self.current_index)

    def toggle_loop_mode(self):
        self.loop_mode = (self.loop_mode + 1) % 3
        modes = ["Loop: Off", "Loop: All", "Loop: One"]
        self.loop_btn.setToolTip(modes[self.loop_mode])
        self.update_loop_icon()

    def update_loop_icon(self):
        if self.loop_mode == 0:
            self.loop_btn.setIcon(self.style().standardIcon(QStyle.SP_BrowserStop))
        elif self.loop_mode == 1:
            self.loop_btn.setIcon(self.style().standardIcon(QStyle.SP_BrowserReload))
        elif self.loop_mode == 2:
            self.loop_btn.setIcon(self.style().standardIcon(QStyle.SP_DialogResetButton))

    def play_song(self, song):
        audio_path = Path(song["folder"]) / song["audio"]
        self.audio.setSource(QUrl.fromLocalFile(str(audio_path)))
        self.audio.play()
        self.now_lbl.setText(f"{song['artist']} - {song['title']}")

    def toggle_play(self):
        """Play if paused/stopped, pause if playing, without resetting position."""
        state = self.audio.playbackState()
        if state == QMediaPlayer.PlayingState:
            self.audio.pause()
        else:
            self.audio.play()
   
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

        # Update beatmap background preview
        bg = song.get('background', '')
        p  = os.path.join(folder, bg)
        if bg and os.path.isfile(p):
            pix = QPixmap(p).scaled(
                self.bp_preview.size(),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
            self.bp_preview.setPixmap(pix)
        else:
            self.bp_preview.clear()

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
        if not self.slider.isSliderDown():
            self.slider.setValue(p)

    def update_duration(self, d):
        self.slider.setRange(0, d)

    def open_settings(self):
        SettingsDialog(self).exec()

    def reload_songs(self):
        """Populate immediately (sync if no cache), then always rescan in background."""
        cached = load_cache(self.osu_folder)
        if cached:
            # instant populate from cache
            self.library = cached
            self.queue   = list(cached)
        else:
            # no valid cache: do a quick synchronous scan so UI isn’t empty
            raw, uniq = [], {}
            for root, _, files in os.walk(self.osu_folder):
                for fn in files:
                    if fn.lower().endswith(".osu"):
                        try:
                            s = OsuParser.parse(os.path.join(root, fn))
                            key = (
                                s.get("title",   "<unknown>"),
                                s.get("artist",  "<unknown>"),
                                s.get("mapper",  "<unknown>")
                            )
                            if key not in uniq:
                                uniq[key] = s
                        except:
                            pass
            self.library = list(uniq.values())
            self.queue   = list(self.library)
            
            # ─── Right here we save the cache for next time ───
            save_cache(self.osu_folder, self.library)

        # Update UI immediately
        self.populate_list(self.queue)
        self.queue_lbl.setText(f"Queue: {len(self.queue)} songs")

        # Kick off a background thread to re-scan (and re-cache) later
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
            "resolution": f"{self.width()}×{self.height()}",
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
        # 0) stop the scanner thread (if it’s still running)
        try:
            if hasattr(self, "_scanner") and self._scanner.isRunning():
                self._scanner.quit()
                self._scanner.wait(500)  # wait up to 0.5s
        except:
            pass

        # 1) Unregister global hotkeys
        user32.UnregisterHotKey(0, 1)
        user32.UnregisterHotKey(0, 2)
        user32.UnregisterHotKey(0, 3)

        # 2) Stop your video loop cleanly
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
    w   = MainWindow()
    w.show()

    import keyboard
    from PySide6.QtCore       import QTimer
    from PySide6.QtMultimedia import QMediaPlayer

    # Global media‐key handler that re‐posts into the Qt thread
    def _on_key(e):
        if e.event_type != "down":
            return

        name = e.name
        if name == "next track":
            QMetaObject.invokeMethod(w, "next_song", Qt.QueuedConnection)

        elif name == "previous track":
            QMetaObject.invokeMethod(w, "prev_song", Qt.QueuedConnection)

        elif name == "play/pause media":
            QMetaObject.invokeMethod(w, "toggle_play", Qt.QueuedConnection)
    # Debug: print every media‐key event we catch
    def _debug_key(e):
        if e.name in ("next track", "previous track", "play/pause media") and e.event_type=="down":
            print(f"[HOOK] {e.name!r} detected")

    keyboard.hook(_debug_key)

    # Install the keyboard hook
    keyboard.hook(_on_key)

    sys.exit(app.exec())
import json
import os
from pathlib import Path
from PySide6.QtCore import (
    Qt, QUrl
)
from PySide6.QtGui import (
    QColor,
)
from PySide6.QtWidgets import (
    QLabel, QFileDialog,
    QHBoxLayout, QVBoxLayout,
    QPushButton, QLineEdit, QSlider,
    QDialog, QDialogButtonBox, QCheckBox, QComboBox,
    QSizePolicy
)
from PySide6.QtMultimedia import QMediaPlayer, QVideoSink
from osuRadio.config import SETTINGS_FILE
from osuRadio.media_keys import update_media_key_listener
from osuRadio import __version__

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
        self.pitch_checkbox = QCheckBox("Preserve Original Pitch (DT/NC)")
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

        # Brightness slider
        self.brightness_slider = QSlider(Qt.Horizontal)
        self.brightness_slider.setRange(50, 255)
        self.brightness_slider.setValue(getattr(parent, "brightness", 255))
        self.brightness_slider.valueChanged.connect(
            lambda v: parent.bg_widget.effect.setColor(
                QColor.fromHsv(parent.hue, 255, v)
            )
        )

        brightness_layout = QHBoxLayout()
        brightness_layout.addWidget(QLabel("Brightness:"))
        brightness_layout.addWidget(self.brightness_slider)
        layout.addLayout(brightness_layout)

        # Resolution dropdown
        self.res_combo = QComboBox()
        self.resolutions = {
            "1920×1080": (1920, 1080),
            "1280×720": (1280, 720),
            "854×480": (854, 480),
            "640×360": (640, 360),
            "480×270": (480, 270),
        }
        self.res_combo.addItems(list(self.resolutions.keys()) + ["Custom Resolution"])
        current_res = f"{parent.width()}×{parent.height()}"
        if current_res in self.resolutions:
            self.res_combo.setCurrentText(current_res)
        else:
            self.res_combo.setCurrentText("Custom Resolution")

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
        self._original_brightness = getattr(parent, "brightness", 255)

    def browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select osu! Songs Folder")
        if folder:
            self.folder_edit.setText(folder)

    def apply(self):
        folder = self.folder_edit.text()
        light = self.light_mode_checkbox.isChecked()
        opacity = self.opacity_slider.value() / 100
        hue = self.hue_slider.value()
        brightness = self.brightness_slider.value()
        res = self.res_combo.currentText()
        if res == "Custom Resolution":
            w, h = self.main.width(), self.main.height()
        else:
            w, h = self.resolutions.get(res, (854, 480))
        allow_resizing = res == "Custom Resolution"
        video_on = self.video_checkbox.isChecked()
        autoplay = self.autoplay_checkbox.isChecked()
        media_keys = self.media_key_checkbox.isChecked()
        preserve_pitch = self.pitch_checkbox.isChecked()
        allow_prerelease = self.prerelease_checkbox.isChecked()

        was_prerelease = self.main.allow_prerelease
        self.main.apply_settings(
            folder, light, opacity, w, h, hue, brightness, 
            video_on, autoplay, media_keys, preserve_pitch,
            allow_prerelease, allow_resizing
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
        self.main.brightness = self._original_brightness
        super().reject()

class SettingsMixin:
    def load_user_settings(self):
        defaults = {
            "osu_folder": None,
            "light_mode": False,
            "ui_opacity": 0.75,
            "window_width": 854,
            "window_height": 480,
            "hue": 240,
            "brightness": 255,
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
            "brightness": self.brightness,
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

    def apply_settings(self, folder, light, opacity, w, h, hue, brightness, video_on, autoplay, media_keys, preserve_pitch, allow_prerelease, allow_resizing=False):
        if folder != self.osu_folder and os.path.isdir(folder):
            self.osu_folder = folder
            self.reload_songs()

        self._apply_ui_settings(light, opacity, w, h, hue, brightness)
        self._apply_video_setting(video_on)

        self.light_mode = light
        self.ui_opacity = opacity
        self.hue = hue
        self.brightness = brightness
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

    def _apply_ui_settings(self, light, opacity, w, h, hue, brightness):
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
        self.brightness = brightness
        color = QColor.fromHsv(self.hue, 255, self.brightness)
        self.bg_widget.effect.setColor(color)
        if not self.video_enabled:  
            palette = self.bg_widget.palette()
            palette.setColor(self.bg_widget.backgroundRole(), color)
            self.bg_widget.setPalette(palette)
            self.bg_widget.update()

        self.save_user_settings()

    def _apply_video_setting(self, enabled):
        self.video_enabled = enabled
        self.bg_widget.setVisible(True)

        if enabled:
            # Restore hue effect
            self.bg_widget.setGraphicsEffect(self.bg_widget.effect)
            self.bg_widget.effect.setEnabled(True)
            self.bg_widget.effect.setColor(QColor.fromHsv(self.hue, 255, self.brightness))

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

            self.bg_widget.effect.setEnabled(False)
            
            # Apply the current hue and brightness as a static background color
            static_color = QColor.fromHsv(self.hue, 255, self.brightness)
            palette = self.bg_widget.palette()
            palette.setColor(self.bg_widget.backgroundRole(), static_color)
            self.bg_widget.setPalette(palette)
            self.bg_widget.update()
from PySide6.QtCore import (
    Qt
)
from PySide6.QtGui import (
    QColor,
)
from PySide6.QtWidgets import (
    QLabel, QFileDialog,
    QHBoxLayout, QVBoxLayout,
    QPushButton, QLineEdit, QSlider,
    QDialog, QDialogButtonBox, QCheckBox, QComboBox,
)
from .config import *

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
            folder, light, opacity, w, h, hue,
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
        super().reject()
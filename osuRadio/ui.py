from PySide6.QtCore import (
    Qt, QTimer,
    QPropertyAnimation, QEasingCurve, Property,
    QSequentialAnimationGroup, QPauseAnimation, QSize,
    QEvent
)
from PySide6.QtGui import (
    QPixmap, QPainter, QColor, QIcon, QGuiApplication,
    QCursor
)
from PySide6.QtWidgets import (
    QWidget, QLabel, QGraphicsColorizeEffect, QListWidgetItem,
    QSizePolicy, QToolTip
)
from osuRadio.config import IMG_PATH

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

class UiMixin:
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

    def toggle_loop_mode(self):
        self.loop_mode = (self.loop_mode + 1) % 3
        modes = ["Loop: Off", "Loop: All", "Loop: One"]
        self.loop_btn.setToolTip(modes[self.loop_mode])
        self.update_loop_icon()

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

    def apply_theme(self, light: bool):
        if light:
            style = """
                QWidget { background-color: rgba(255,255,255,200); color: black; }
                QPushButton { background-color: #e0e0e0; }
            """
        else:
            style = ""  # Use system default
        self.centralWidget().setStyleSheet(style)

    def _update_volume_label(self, v):
        self.volume_label.setText(f"{v}%")

    def slider_tooltip(self, event):
        if hasattr(self, "current_duration") and self.current_duration > 0:
            x = event.position().x() if hasattr(event, "position") else event.x()
            ratio = x / self.slider.width()
            pos = int(ratio * self.current_duration)
            mins, secs = divmod(pos // 1000, 60)
            QToolTip.showText(QCursor.pos(), f"{mins}:{secs:02d}")
    
    def eventFilter(self, source, event):
        if source == self.slider and event.type() == QEvent.MouseMove:
            self.slider_tooltip(event)
        return super().eventFilter(source, event)
    
    def format_time(self, ms):
        mins, secs = divmod(ms // 1000, 60)
        return f"{mins}:{secs:02d}"
    
    def _wrap_focus_out(self, old_handler):
        def new_handler(event):
            self.change_speed(self.speed_combo.currentText())
            if old_handler:
                old_handler(event)
        return new_handler
    
    def _update_elapsed_label(self, value):
        if getattr(self, "_user_dragging", False) or self.is_playing:
            self.elapsed_label.setText(self.format_time(value))
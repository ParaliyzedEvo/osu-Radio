from PySide6.QtCore import (
    Qt, QTimer,
    QPropertyAnimation, QEasingCurve, Property,
    QSequentialAnimationGroup, QPauseAnimation
)
from PySide6.QtGui import (
    QPixmap, QPainter, QColor,
)
from PySide6.QtWidgets import (
    QWidget, QLabel, QGraphicsColorizeEffect
)
from .config import *

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
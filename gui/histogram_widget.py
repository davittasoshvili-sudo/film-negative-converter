"""
histogram_widget.py
-------------------
A lightweight RGB histogram drawn with QPainter directly.
Updates whenever a new positive image is produced.
"""

import numpy as np
from PyQt5.QtWidgets import QWidget
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPainter, QPen, QColor, QBrush, QPainterPath, QFont


class HistogramWidget(QWidget):
    """Draws R/G/B histograms overlaid on a dark background."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._hists: list[np.ndarray] | None = None   # list of 3 arrays, 256 bins
        self.setMinimumHeight(80)
        self.setStyleSheet("background: #111; border: 1px solid #3c3c3c; border-radius: 4px;")

    def update_histogram(self, image: np.ndarray):
        """
        Compute and redraw histogram from a float [0,1] or uint8 image.
        """
        if image is None:
            return

        # Downsample for speed if image is large
        h, w = image.shape[:2]
        if h * w > 2_000_000:
            step = int(np.sqrt(h * w / 2_000_000))
            img = image[::step, ::step]
        else:
            img = image

        # Convert to uint8 for histogram binning
        if img.dtype in (np.float32, np.float64):
            arr = (np.clip(img, 0, 1) * 255).astype(np.uint8)
        else:
            arr = img.astype(np.uint8)

        self._hists = [
            np.bincount(arr[:, :, c].ravel(), minlength=256).astype(np.float64)
            for c in range(3)
        ]

        # Normalise each channel independently for display
        for i in range(3):
            peak = self._hists[i].max()
            if peak > 0:
                self._hists[i] /= peak

        self.update()   # trigger paintEvent

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()
        margin_left = 4
        margin_right = 4
        margin_top = 4
        margin_bottom = 16

        draw_w = w - margin_left - margin_right
        draw_h = h - margin_top - margin_bottom

        # Background
        painter.fillRect(0, 0, w, h, QColor("#111111"))

        if self._hists is None:
            painter.setPen(QColor("#444"))
            painter.drawText(0, 0, w, h, Qt.AlignCenter, "No image loaded")
            return

        colours = [QColor(255, 80, 80, 160), QColor(80, 220, 80, 160), QColor(80, 130, 255, 160)]

        for channel, (hist, colour) in enumerate(zip(self._hists, colours)):
            path = QPainterPath()
            path.moveTo(margin_left, margin_top + draw_h)

            for i, val in enumerate(hist):
                x = margin_left + (i / 255) * draw_w
                y = margin_top + draw_h - val * draw_h
                path.lineTo(x, y)

            path.lineTo(margin_left + draw_w, margin_top + draw_h)
            path.closeSubpath()

            fill_colour = QColor(colour)
            fill_colour.setAlpha(60)
            painter.fillPath(path, QBrush(fill_colour))

            painter.setPen(QPen(colour, 1.0))
            painter.drawPath(path)

        # Axis label
        painter.setPen(QColor("#555"))
        font = QFont()
        font.setPointSize(8)
        painter.setFont(font)
        painter.drawText(margin_left, h - margin_bottom + 2, draw_w, margin_bottom,
                         Qt.AlignLeft | Qt.AlignVCenter, "0")
        painter.drawText(margin_left, h - margin_bottom + 2, draw_w, margin_bottom,
                         Qt.AlignRight | Qt.AlignVCenter, "255")
        painter.drawText(margin_left, h - margin_bottom + 2, draw_w, margin_bottom,
                         Qt.AlignCenter | Qt.AlignVCenter, "RGB Histogram")

"""
preview_widget.py
-----------------
Split before/after preview.

New features:
  - Left (negative) panel is clickable — click any point to sample that
    pixel as the film base colour override (eyedropper / colour picker).
  - A small swatch + "Reset to Auto" button shows the current base.
  - Emits base_picked(r, g, b) in 0..65535 scale when user clicks.
"""

import numpy as np
from PyQt5.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QSplitter,
    QSizePolicy, QPushButton, QFrame,
)
from PyQt5.QtCore import Qt, pyqtSignal, QPoint
from PyQt5.QtGui import QImage, QPixmap, QCursor


class ClickableImageLabel(QLabel):
    """
    A QLabel that:
    - Scales its pixmap to fit (keep aspect ratio)
    - Emits clicked_pixel(norm_x, norm_y) in 0..1 image coordinates
      when the user clicks (only when picker mode is active)
    """
    clicked_pixel = pyqtSignal(float, float)   # normalised x, y

    def __init__(self, caption="", parent=None):
        super().__init__(parent)
        self._pixmap_raw: QPixmap | None = None
        self._caption = caption
        self._picker_mode = False
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(200, 150)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setStyleSheet("background:#111; border:1px solid #3c3c3c; border-radius:4px;")
        self.setText(f'<span style="color:#444;font-size:14px;">{caption}<br>No image loaded</span>')

    def set_numpy_image(self, img: np.ndarray):
        if img.dtype in (np.float32, np.float64):
            arr = (np.clip(img, 0, 1) * 255).astype(np.uint8)
        else:
            arr = img.astype(np.uint8)
        h, w, ch = arr.shape
        qimg = QImage(arr.data, w, h, ch * w, QImage.Format_RGB888)
        self._pixmap_raw = QPixmap.fromImage(qimg)
        self._update_scaled()
        self.setText("")

    def set_picker_mode(self, active: bool):
        self._picker_mode = active
        if active:
            self.setCursor(QCursor(Qt.CrossCursor))
            self.setStyleSheet(
                "background:#111; border:2px solid #e5c07b; border-radius:4px;"
            )
        else:
            self.setCursor(QCursor(Qt.ArrowCursor))
            self.setStyleSheet(
                "background:#111; border:1px solid #3c3c3c; border-radius:4px;"
            )

    def mousePressEvent(self, event):
        if not self._picker_mode or self._pixmap_raw is None:
            return
        if event.button() != Qt.LeftButton:
            return

        # Find where the scaled pixmap sits inside the label
        lw, lh = self.width(), self.height()
        pw, ph = self._pixmap_raw.width(), self._pixmap_raw.height()

        # Scaled size (same logic as Qt.KeepAspectRatio)
        scale = min(lw / pw, lh / ph)
        sw, sh = pw * scale, ph * scale
        ox = (lw - sw) / 2   # offset x
        oy = (lh - sh) / 2   # offset y

        mx, my = event.x() - ox, event.y() - oy
        if 0 <= mx <= sw and 0 <= my <= sh:
            nx = mx / sw   # normalised 0..1
            ny = my / sh
            self.clicked_pixel.emit(nx, ny)

    def _update_scaled(self):
        if self._pixmap_raw:
            scaled = self._pixmap_raw.scaled(
                self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            self.setPixmap(scaled)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_scaled()


class ImageLabel(ClickableImageLabel):
    """Alias kept for non-clickable right panel."""
    pass


class PreviewWidget(QWidget):
    """
    Side-by-side before/after preview with film base colour picker.

    Signals
    -------
    base_picked(r, g, b)   float values in 0..65535 — user sampled a base colour
    base_reset()           user clicked "Reset to Auto"
    """
    base_picked = pyqtSignal(float, float, float)
    base_reset  = pyqtSignal()
    rotate_cw   = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._raw_image: np.ndarray | None = None   # stored for pixel sampling
        self._picker_active = False
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        splitter = QSplitter(Qt.Horizontal)

        # ── Left: negative / before ───────────────────────────── #
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(2, 2, 2, 2)
        ll.setSpacing(2)

        before_header = QHBoxLayout()
        lbl = QLabel("BEFORE  (negative)")
        lbl.setStyleSheet("color:#888; font-size:10px; font-weight:bold;")
        before_header.addWidget(lbl)
        before_header.addStretch()

        # Rotate button
        self.rotate_btn = QPushButton("↻ Rotate")
        self.rotate_btn.setFixedHeight(22)
        self.rotate_btn.setStyleSheet("""
            QPushButton {
                background:#3c3c3c; color:#d4d4d4; border:none;
                border-radius:3px; padding:2px 8px; font-size:10px;
            }
            QPushButton:hover { background:#505050; }
        """)
        self.rotate_btn.clicked.connect(self.rotate_cw.emit)
        before_header.addWidget(self.rotate_btn)

        # Eyedropper button
        self.picker_btn = QPushButton("💧 Pick Film Base")
        self.picker_btn.setCheckable(True)
        self.picker_btn.setFixedHeight(22)
        self.picker_btn.setStyleSheet("""
            QPushButton {
                background:#3c3c3c; color:#d4d4d4; border:none;
                border-radius:3px; padding:2px 8px; font-size:10px;
            }
            QPushButton:checked {
                background:#e5c07b; color:#1e1e1e; font-weight:bold;
            }
            QPushButton:hover { background:#505050; }
        """)
        self.picker_btn.toggled.connect(self._on_picker_toggled)
        before_header.addWidget(self.picker_btn)

        ll.addLayout(before_header)

        self.before_label = ClickableImageLabel("← Negative")
        self.before_label.clicked_pixel.connect(self._on_pixel_clicked)
        ll.addWidget(self.before_label)

        # Film base swatch row
        swatch_row = QHBoxLayout()
        swatch_row.setContentsMargins(0, 2, 0, 0)

        base_lbl = QLabel("Film base:")
        base_lbl.setStyleSheet("color:#666; font-size:10px;")
        swatch_row.addWidget(base_lbl)

        self.base_swatch = QFrame()
        self.base_swatch.setFixedSize(28, 14)
        self.base_swatch.setStyleSheet("background:#555; border:1px solid #888; border-radius:2px;")
        swatch_row.addWidget(self.base_swatch)

        self.base_value_lbl = QLabel("Auto")
        self.base_value_lbl.setStyleSheet("color:#888; font-size:10px;")
        swatch_row.addWidget(self.base_value_lbl)

        swatch_row.addStretch()

        self.reset_base_btn = QPushButton("Reset to Auto")
        self.reset_base_btn.setFixedHeight(18)
        self.reset_base_btn.setStyleSheet("""
            QPushButton {
                background:#3c3c3c; color:#aaa; border:none;
                border-radius:3px; padding:1px 6px; font-size:10px;
            }
            QPushButton:hover { background:#505050; color:#d4d4d4; }
        """)
        self.reset_base_btn.clicked.connect(self._on_reset_base)
        self.reset_base_btn.setEnabled(False)
        swatch_row.addWidget(self.reset_base_btn)

        ll.addLayout(swatch_row)

        # ── Right: positive / after ───────────────────────────── #
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(2, 2, 2, 2)
        rl.setSpacing(2)

        rlbl = QLabel("AFTER  (positive)")
        rlbl.setStyleSheet("color:#4ec9b0; font-size:10px; font-weight:bold;")
        rlbl.setAlignment(Qt.AlignCenter)
        rl.addWidget(rlbl)

        self.after_label = ClickableImageLabel("Positive →")
        rl.addWidget(self.after_label)

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter)

        # Loading overlay
        self.loading_label = QLabel("Processing...")
        self.loading_label.setAlignment(Qt.AlignCenter)
        self.loading_label.setStyleSheet(
            "background:rgba(0,0,0,0.6); color:#4ec9b0; font-size:16px; border-radius:6px;"
        )
        self.loading_label.setVisible(False)
        layout.addWidget(self.loading_label)

    # ── Public API ────────────────────────────────────────────── #

    def set_images(self, before: np.ndarray, after: np.ndarray):
        """
        before : uint8 (H,W,3) — the negative thumbnail (for display + picking)
        after  : float64 (H,W,3) 0..1 — the positive
        """
        self._before_img = before   # uint8, used for pixel colour sampling
        self.before_label.set_numpy_image(before)
        self.after_label.set_numpy_image(after)

    def set_raw_image(self, raw_img: np.ndarray):
        """Store the full-range RAW (0..65535) for accurate base sampling."""
        self._raw_image = raw_img

    def set_loading(self, loading: bool):
        self.loading_label.setVisible(loading)

    def set_base_colour(self, rgb_65535: tuple | None):
        """Update the swatch display. Pass None to show Auto."""
        if rgb_65535 is None:
            self.base_swatch.setStyleSheet(
                "background:#555; border:1px solid #888; border-radius:2px;"
            )
            self.base_value_lbl.setText("Auto")
            self.reset_base_btn.setEnabled(False)
        else:
            r, g, b = [int(v / 65535 * 255) for v in rgb_65535]
            self.base_swatch.setStyleSheet(
                f"background:rgb({r},{g},{b}); border:1px solid #888; border-radius:2px;"
            )
            self.base_value_lbl.setText(
                f"R:{r} G:{g} B:{b}"
            )
            self.reset_base_btn.setEnabled(True)

    # ── Internal slots ────────────────────────────────────────── #

    def _on_picker_toggled(self, checked: bool):
        self._picker_active = checked
        self.before_label.set_picker_mode(checked)

    def _on_pixel_clicked(self, nx: float, ny: float):
        """User clicked on the negative — sample that pixel as film base."""
        if self._raw_image is not None:
            # Sample from the full-range RAW for maximum accuracy
            H, W = self._raw_image.shape[:2]
            px = int(np.clip(nx * W, 0, W - 1))
            py = int(np.clip(ny * H, 0, H - 1))
            r, g, b = self._raw_image[py, px]
        elif hasattr(self, '_before_img') and self._before_img is not None:
            # Fallback: sample from the 8-bit thumbnail, scale to 16-bit
            H, W = self._before_img.shape[:2]
            px = int(np.clip(nx * W, 0, W - 1))
            py = int(np.clip(ny * H, 0, H - 1))
            r8, g8, b8 = self._before_img[py, px]
            r, g, b = r8 / 255.0 * 65535, g8 / 255.0 * 65535, b8 / 255.0 * 65535
        else:
            return

        # Deactivate picker mode after sampling
        self.picker_btn.setChecked(False)
        self.set_base_colour((r, g, b))
        self.base_picked.emit(float(r), float(g), float(b))

    def _on_reset_base(self):
        self.set_base_colour(None)
        self.base_reset.emit()

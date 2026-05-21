"""
controls_panel.py
-----------------
Two-tab editor panel.

Tab 1 — Adjustments:
  Film Profile · White Balance (Temp/Tint/Blacks/Whites/Shadows/Highlights)
  Tone · S-Curve · Color Grading · Black/White Point · Dust · Export

Tab 2 — Colors:
  Red / Green / Blue selective Hue · Saturation · Luminance (HSL)
"""

import numpy as np
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QGroupBox,
    QScrollArea, QPushButton, QComboBox, QCheckBox, QSizePolicy,
    QTabWidget,
)
from PyQt5.QtCore import Qt, pyqtSignal, QRect, QPoint, QPointF, QRectF
from PyQt5.QtGui import (
    QPainter, QPen, QBrush, QColor, QLinearGradient,
    QPainterPath, QFont, QFontMetrics, QCursor,
)

from core.negative_inverter import InversionParams, FILM_PROFILES


# ═══════════════════════════════════════════════════════════════ #
#  SMOOTH CUSTOM SLIDER                                           #
# ═══════════════════════════════════════════════════════════════ #

class SmoothSlider(QWidget):
    """
    Custom-painted horizontal slider.
    - Anti-aliased track and handle
    - Gradient fill on active segment
    - Double-click to reset to default
    """
    value_changed = pyqtSignal(float)

    _TRACK_H  = 4
    _HANDLE_R = 7
    _PAD      = 12

    def __init__(self, label: str, min_val: float, max_val: float,
                 default: float, decimals: int = 2,
                 accent: str = "#4fc3f7", parent=None):
        super().__init__(parent)
        self._min      = min_val
        self._max      = max_val
        self._default  = default
        self._value    = default
        self._decimals = decimals
        self._accent   = QColor(accent)
        self._label    = label
        self._dragging = False
        self._hover    = False

        self.setFixedHeight(38)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMouseTracking(True)
        self.setCursor(QCursor(Qt.PointingHandCursor))

    # ── Geometry ──────────────────────────────────────────────── #

    def _track_rect(self) -> QRect:
        w  = self.width() - 2 * self._PAD
        cy = self.height() // 2 + 6
        return QRect(self._PAD, cy - self._TRACK_H // 2, w, self._TRACK_H)

    def _value_to_x(self, v: float) -> float:
        tr    = self._track_rect()
        ratio = (v - self._min) / max(self._max - self._min, 1e-9)
        return tr.left() + ratio * tr.width()

    def _x_to_value(self, x: float) -> float:
        tr    = self._track_rect()
        ratio = (x - tr.left()) / max(tr.width(), 1)
        return self._min + np.clip(ratio, 0.0, 1.0) * (self._max - self._min)

    # ── Paint ─────────────────────────────────────────────────── #

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)

        tr = self._track_rect()
        hx = self._value_to_x(self._value)
        hy = tr.center().y()
        hr = self._HANDLE_R

        # Label
        font = QFont("Segoe UI", 9)
        p.setFont(font)
        p.setPen(QColor("#aaaaaa"))
        p.drawText(QRect(self._PAD, 0, self.width() - self._PAD * 2, 18),
                   Qt.AlignLeft | Qt.AlignVCenter, self._label)

        # Value readout
        val_str = f"{self._value:.{self._decimals}f}"
        p.setPen(QColor("#9cdcfe"))
        p.drawText(QRect(self._PAD, 0, self.width() - self._PAD * 2, 18),
                   Qt.AlignRight | Qt.AlignVCenter, val_str)

        # Track background
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#2a2a2a"))
        p.drawRoundedRect(QRectF(tr), self._TRACK_H / 2, self._TRACK_H / 2)

        # Active fill
        active_w = hx - tr.left()
        if active_w > 0:
            grad = QLinearGradient(tr.left(), 0, hx, 0)
            dim  = QColor(self._accent); dim.setAlpha(120)
            grad.setColorAt(0.0, dim)
            grad.setColorAt(1.0, self._accent)
            p.setBrush(QBrush(grad))
            p.drawRoundedRect(
                QRectF(tr.left(), tr.top(), active_w, tr.height()),
                self._TRACK_H / 2, self._TRACK_H / 2,
            )

        # Centre tick for bi-directional sliders
        if self._min < 0 < self._max:
            zx = self._value_to_x(0.0)
            p.setPen(QPen(QColor("#555"), 1))
            p.drawLine(int(zx), tr.top() - 3, int(zx), tr.bottom() + 3)

        # Handle shadow
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 60))
        p.drawEllipse(QPointF(hx, hy + 1.5), hr + 0.5, hr + 0.5)

        # Handle body
        handle_col = self._accent.lighter(130) if (self._hover or self._dragging) else self._accent
        p.setBrush(QBrush(handle_col))
        p.setPen(QPen(handle_col.lighter(150), 1))
        p.drawEllipse(QPointF(hx, hy), float(hr), float(hr))

        # Highlight dot
        p.setBrush(QColor(255, 255, 255, 80))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(hx - hr * 0.25, hy - hr * 0.25), hr * 0.35, hr * 0.35)

    # ── Mouse ─────────────────────────────────────────────────── #

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._dragging = True
            self._set_from_x(e.x())

    def mouseMoveEvent(self, e):
        hx   = self._value_to_x(self._value)
        hy   = self._track_rect().center().y()
        dist = ((e.x() - hx) ** 2 + (e.y() - hy) ** 2) ** 0.5
        self._hover = dist < self._HANDLE_R * 2.5
        if self._dragging:
            self._set_from_x(e.x())
        self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._dragging = False
            self.update()

    def mouseDoubleClickEvent(self, e):
        self._set_value(self._default)

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def _set_from_x(self, x: float):
        self._set_value(self._x_to_value(x))

    def _set_value(self, v: float):
        v = round(float(np.clip(v, self._min, self._max)), self._decimals + 2)
        if v != self._value:
            self._value = v
            self.update()
            self.value_changed.emit(v)

    # ── Public API ────────────────────────────────────────────── #

    def get_value(self) -> float:
        return self._value

    def set_value(self, v: float):
        v = float(np.clip(v, self._min, self._max))
        if abs(v - self._value) > 1e-9:
            self._value = v
            self.update()


LabeledSlider = SmoothSlider   # alias kept for any external references


# ═══════════════════════════════════════════════════════════════ #
#  S-CURVE EDITOR                                                 #
# ═══════════════════════════════════════════════════════════════ #

class SCurveWidget(QWidget):
    """
    Interactive tone curve with 3 draggable handles.
    Displays and applies identical PCHIP cubic interpolation.
    Double-click to reset to straight line.
    """
    curve_changed = pyqtSignal(float, float, float)

    _DEFAULTS = (0.25, 0.50, 0.75)
    _PAD      = 16
    _HANDLE_R = 6

    def __init__(self, parent=None):
        super().__init__(parent)
        self.shadows    = 0.25
        self.midtones   = 0.50
        self.highlights = 0.75
        self._drag_idx  = -1
        self.setMinimumHeight(160)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMouseTracking(True)

    def _draw_rect(self) -> QRectF:
        p = self._PAD
        return QRectF(p, p, self.width() - 2*p, self.height() - 2*p)

    def _to_widget(self, nx: float, ny: float) -> QPointF:
        r = self._draw_rect()
        return QPointF(r.left() + nx * r.width(), r.bottom() - ny * r.height())

    def _to_norm(self, wx: float, wy: float):
        r  = self._draw_rect()
        nx = (wx - r.left()) / r.width()
        ny = (r.bottom() - wy) / r.height()
        return np.clip(nx, 0, 1), np.clip(ny, 0, 1)

    def _control_points(self):
        return [(0.25, self.shadows), (0.50, self.midtones), (0.75, self.highlights)]

    def _build_lut(self, n: int = 256):
        xs = np.array([0.0, 0.25, 0.50, 0.75, 1.0])
        ys = np.array([0.0, self.shadows, self.midtones, self.highlights, 1.0])
        ys = np.clip(ys, 0, 1)
        for i in range(1, len(ys)):
            ys[i] = max(ys[i], ys[i-1] + 1e-4)
        ys = np.clip(ys, 0, 1)
        t  = np.linspace(0, 1, n)
        try:
            from scipy.interpolate import PchipInterpolator
            return np.clip(PchipInterpolator(xs, ys)(t), 0, 1)
        except ImportError:
            return np.interp(t, xs, ys)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self._draw_rect()

        p.fillRect(self.rect(), QColor("#1a1a1a"))

        # Grid
        p.setPen(QPen(QColor("#2a2a2a"), 1))
        for i in range(1, 4):
            t = i / 4
            x = r.left() + t * r.width()
            y = r.top()  + t * r.height()
            p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))
            p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))

        # Diagonal reference
        p.setPen(QPen(QColor("#383838"), 1, Qt.DashLine))
        p.drawLine(self._to_widget(0, 0), self._to_widget(1, 1))

        # Border
        p.setPen(QPen(QColor("#3c3c3c"), 1))
        p.drawRect(r)

        # Curve
        lut  = self._build_lut(200)
        path = QPainterPath()
        for i, y in enumerate(lut):
            pt = self._to_widget(i / (len(lut)-1), float(y))
            path.moveTo(pt) if i == 0 else path.lineTo(pt)
        p.setPen(QPen(QColor("#4fc3f7"), 2))
        p.drawPath(path)

        # Handles
        for i, (nx, ny) in enumerate(self._control_points()):
            wp = self._to_widget(nx, ny)
            p.setPen(QPen(QColor("#333"), 1, Qt.DotLine))
            p.drawLine(self._to_widget(nx, nx), wp)
            col = QColor("#e5c07b") if self._drag_idx == i else QColor("#4fc3f7")
            p.setBrush(QBrush(col))
            p.setPen(QPen(col.lighter(150), 1))
            p.drawEllipse(wp, self._HANDLE_R, self._HANDLE_R)

        # Labels
        font = QFont("Segoe UI", 8)
        p.setFont(font)
        p.setPen(QColor("#555"))
        for label, nx in [("Shadows", 0.25), ("Mids", 0.5), ("Highs", 0.75)]:
            lp = self._to_widget(nx, 0)
            p.drawText(QRectF(lp.x()-20, r.bottom()+2, 40, 12), Qt.AlignCenter, label)

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        for i, (nx, ny) in enumerate(self._control_points()):
            wp = self._to_widget(nx, ny)
            if ((e.x()-wp.x())**2 + (e.y()-wp.y())**2)**0.5 < self._HANDLE_R * 3.5:
                self._drag_idx = i
                return
        self._drag_idx = -1

    def mouseMoveEvent(self, e):
        if self._drag_idx < 0:
            return
        _, ny = self._to_norm(e.x(), e.y())
        ny = round(float(ny), 3)
        if   self._drag_idx == 0: self.shadows    = ny
        elif self._drag_idx == 1: self.midtones   = ny
        else:                      self.highlights = ny
        self.update()
        self.curve_changed.emit(self.shadows, self.midtones, self.highlights)

    def mouseReleaseEvent(self, e):
        self._drag_idx = -1

    def mouseDoubleClickEvent(self, e):
        self.shadows, self.midtones, self.highlights = self._DEFAULTS
        self.update()
        self.curve_changed.emit(*self._DEFAULTS)

    def set_values(self, shadows: float, midtones: float, highlights: float):
        self.shadows    = shadows
        self.midtones   = midtones
        self.highlights = highlights
        self.update()

    def get_values(self):
        return self.shadows, self.midtones, self.highlights


# ═══════════════════════════════════════════════════════════════ #
#  CONTROLS PANEL                                                 #
# ═══════════════════════════════════════════════════════════════ #

class ControlsPanel(QWidget):
    params_changed = pyqtSignal(InversionParams)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._block_signals = False
        self._build_ui()

    # ── Layout construction ───────────────────────────────────── #

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 4, 4, 4)
        outer.setSpacing(4)

        header = QLabel("🎛  Adjustments")
        header.setStyleSheet("font-weight:bold; font-size:13px; color:#ccc;")
        outer.addWidget(header)

        self._tabs = QTabWidget()
        self._tabs.setStyleSheet(_TAB_STYLE)

        # ── Tab 1: Adjustments ─────────────────────────────────── #
        adj_scroll = QScrollArea()
        adj_scroll.setWidgetResizable(True)
        adj_scroll.setStyleSheet("QScrollArea{border:none;background:transparent;}")
        adj_widget = QWidget()
        self._layout = QVBoxLayout(adj_widget)
        self._layout.setContentsMargins(2, 2, 2, 2)
        self._layout.setSpacing(6)
        adj_scroll.setWidget(adj_widget)
        self._tabs.addTab(adj_scroll, "Adjustments")

        # ── Tab 2: Colors ──────────────────────────────────────── #
        col_scroll = QScrollArea()
        col_scroll.setWidgetResizable(True)
        col_scroll.setStyleSheet("QScrollArea{border:none;background:transparent;}")
        col_widget = QWidget()
        self._colors_layout = QVBoxLayout(col_widget)
        self._colors_layout.setContentsMargins(2, 2, 2, 2)
        self._colors_layout.setSpacing(6)
        col_scroll.setWidget(col_widget)
        self._tabs.addTab(col_scroll, "Colors")

        outer.addWidget(self._tabs)

        # Populate tabs
        self._build_profile_section()
        self._build_wb_section()
        self._build_tone_section()
        self._build_color_grading_section()
        self._build_clip_section()
        self._build_dust_section()
        self._build_export_section()
        self._layout.addStretch()

        self._build_colors_tab()
        self._colors_layout.addStretch()

        reset_btn = QPushButton("↺  Reset All")
        reset_btn.setStyleSheet("""
            QPushButton {
                background:#3c3c3c; color:#d4d4d4; border:none;
                border-radius:4px; padding:6px; font-size:12px;
            }
            QPushButton:hover { background:#505050; }
        """)
        reset_btn.clicked.connect(self._reset_all)
        outer.addWidget(reset_btn)

    # ── Group-box helper ──────────────────────────────────────── #

    def _group(self, title: str, target=None):
        """Create a styled group box and add it to `target` layout (default: Adjustments tab)."""
        if target is None:
            target = self._layout
        box = QGroupBox(title)
        box.setStyleSheet("""
            QGroupBox {
                color:#9cdcfe; font-size:11px; font-weight:bold;
                border:1px solid #333; border-radius:5px;
                margin-top:8px; padding-top:8px;
            }
            QGroupBox::title { subcontrol-origin:margin; left:8px; padding:0 4px; }
        """)
        layout = QVBoxLayout(box)
        layout.setContentsMargins(8, 12, 8, 8)
        layout.setSpacing(2)
        target.addWidget(box)
        return box, layout

    def _slider(self, label, lo, hi, default, decimals=2, accent="#4fc3f7"):
        s = SmoothSlider(label, lo, hi, default, decimals, accent)
        s.value_changed.connect(self._emit)
        return s

    # ── Section builders ──────────────────────────────────────── #

    def _build_profile_section(self):
        _, layout = self._group("Film Profile")
        row = QHBoxLayout()
        row.addWidget(QLabel("Profile:"))
        self.profile_combo = QComboBox()
        self.profile_combo.addItems(list(FILM_PROFILES.keys()))
        self.profile_combo.setStyleSheet(_COMBO_STYLE)
        self.profile_combo.currentTextChanged.connect(self._emit)
        row.addWidget(self.profile_combo, 1)
        layout.addLayout(row)

    def _build_wb_section(self):
        """
        White Balance: Temp / Tint
        plus tone range controls: Blacks / Whites / Shadows / Highlights
        R/G/B multipliers have moved to the Colors tab as HSL.
        """
        _, layout = self._group("White Balance")
        self.temp         = self._slider("Temp",       -1.0,  1.0, 0.0, accent="#e5c07b")
        self.tint         = self._slider("Tint",       -1.0,  1.0, 0.0, accent="#c678dd")
        self.s_blacks     = self._slider("Blacks",     -1.0,  1.0, 0.0, accent="#888888")
        self.s_whites     = self._slider("Whites",     -1.0,  1.0, 0.0, accent="#dddddd")
        self.s_shadows    = self._slider("Shadows",    -1.0,  1.0, 0.0, accent="#6699cc")
        self.s_highlights = self._slider("Highlights", -1.0,  1.0, 0.0, accent="#ffcc66")
        for s in [self.temp, self.tint, self.s_blacks, self.s_whites,
                  self.s_shadows, self.s_highlights]:
            layout.addWidget(s)

    def _build_tone_section(self):
        _, layout = self._group("Tone")
        self.exposure = self._slider("Exposure", -3.0, 3.0, 0.0, accent="#e5c07b")
        self.contrast = self._slider("Contrast",  0.5, 2.0, 1.0)
        self.lift     = self._slider("Lift",     -0.3, 0.3, 0.0)
        self.gain     = self._slider("Gain",      0.5, 2.0, 1.0)
        self.gamma    = self._slider("Gamma",     1.0, 3.0, 2.2)
        for s in [self.exposure, self.contrast, self.lift, self.gain, self.gamma]:
            layout.addWidget(s)

    def _build_curve_section(self):
        _, layout = self._group("S-Curve")
        hint = QLabel("Drag handles  •  Double-click to reset")
        hint.setStyleSheet("color:#555; font-size:9px;")
        hint.setAlignment(Qt.AlignCenter)
        layout.addWidget(hint)
        self.curve = SCurveWidget()
        self.curve.curve_changed.connect(self._emit)
        layout.addWidget(self.curve)

    def _build_color_grading_section(self):
        """
        Replaces the old CMY sliders.
        Vibrance (intelligent sat) · Saturation (global) · Split Toning.
        """
        _, layout = self._group("Color Grading")

        hint = QLabel("Double-click any slider to reset")
        hint.setStyleSheet("color:#555; font-size:9px;")
        layout.addWidget(hint)

        self.cg_vibrance       = self._slider("Vibrance",       -1.0, 1.0, 0.0, accent="#e5c07b")
        self.cg_saturation     = self._slider("Saturation",     -1.0, 1.0, 0.0, accent="#c678dd")
        self.cg_shadow_tint    = self._slider("Shadow Tint",    -1.0, 1.0, 0.0, accent="#61afef")
        self.cg_highlight_tint = self._slider("Highlight Tint", -1.0, 1.0, 0.0, accent="#e06c75")

        for s in [self.cg_vibrance, self.cg_saturation,
                  self.cg_shadow_tint, self.cg_highlight_tint]:
            layout.addWidget(s)

        row = QHBoxLayout()
        for text, col in [("← Cool", "#61afef"), ("Warm →", "#e5c07b")]:
            lbl = QLabel(text)
            lbl.setStyleSheet(f"color:{col}; font-size:9px;")
            lbl.setAlignment(Qt.AlignCenter)
            row.addWidget(lbl)
        layout.addLayout(row)

    def _build_clip_section(self):
        _, layout = self._group("Black / White Point")
        self.black_clip = self._slider("Shadow clip",    0.0,  5.0,  0.5)
        self.white_clip = self._slider("Highlight clip", 95.0, 100.0, 99.5)
        layout.addWidget(self.black_clip)
        layout.addWidget(self.white_clip)

    def _build_dust_section(self):
        _, layout = self._group("Dust & Scratch Removal")
        self.dust_check = QCheckBox("Enable median filter")
        self.dust_check.setStyleSheet("color:#d4d4d4;")
        self.dust_check.stateChanged.connect(self._emit)
        layout.addWidget(self.dust_check)
        self.dust_radius = self._slider("Radius (px)", 1, 10, 3, decimals=0)
        layout.addWidget(self.dust_radius)

    def _build_export_section(self):
        _, layout = self._group("Export")
        row = QHBoxLayout()
        row.addWidget(QLabel("Compression:"))
        self.compression_combo = QComboBox()
        self.compression_combo.addItems(["lzw", "deflate", "none"])
        self.compression_combo.setStyleSheet(_COMBO_STYLE)
        row.addWidget(self.compression_combo, 1)
        layout.addLayout(row)

    def _build_colors_tab(self):
        """
        Per-colour HSL (Hue · Saturation · Luminance) for Red, Green, Blue.

        These operate on their respective hue ranges (±50° around 0°, 120°, 225°)
        using smooth falloff so adjustments blend naturally into adjacent colours.
        """
        hint = QLabel(
            "Hue shifts the colour, Saturation boosts or mutes it,\n"
            "Luminance brightens or darkens that colour range.\n"
            "Double-click any slider to reset."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#555; font-size:9px; padding:4px 2px;")
        self._colors_layout.addWidget(hint)

        for name, accent, prefix in [
            ("Red",   "#e06c75", "red"),
            ("Green", "#98c379", "green"),
            ("Blue",  "#61afef", "blue"),
        ]:
            _, layout = self._group(name, target=self._colors_layout)
            hue = self._slider("Hue",        -30.0, 30.0, 0.0, decimals=1, accent=accent)
            sat = self._slider("Saturation", -1.0,  1.0,  0.0, accent=accent)
            lum = self._slider("Luminance",  -1.0,  1.0,  0.0, accent=accent)
            setattr(self, f"{prefix}_hue", hue)
            setattr(self, f"{prefix}_sat", sat)
            setattr(self, f"{prefix}_lum", lum)
            for s in [hue, sat, lum]:
                layout.addWidget(s)

    # ── Public API ────────────────────────────────────────────── #

    def get_params(self) -> InversionParams:
        return InversionParams(
            film_profile     = self.profile_combo.currentText(),
            wb_red           = 1.0,
            wb_green         = 1.0,
            wb_blue          = 1.0,
            temp_shift       = self.temp.get_value(),
            tint_shift       = self.tint.get_value(),
            blacks           = self.s_blacks.get_value(),
            whites           = self.s_whites.get_value(),
            shadows          = self.s_shadows.get_value(),
            highlights       = self.s_highlights.get_value(),
            exposure_stops   = self.exposure.get_value(),
            contrast         = self.contrast.get_value(),
            lift             = self.lift.get_value(),
            gain             = self.gain.get_value(),
            gamma            = self.gamma.get_value(),
            black_clip_pct   = self.black_clip.get_value(),
            white_clip_pct   = self.white_clip.get_value(),
            dust_removal     = self.dust_check.isChecked(),
            dust_radius      = max(1, int(self.dust_radius.get_value())),
            curve_shadows    = 0.25,
            curve_midtones   = 0.50,
            curve_highlights = 0.75,
            red_hue          = self.red_hue.get_value(),
            red_sat          = self.red_sat.get_value(),
            red_lum          = self.red_lum.get_value(),
            green_hue        = self.green_hue.get_value(),
            green_sat        = self.green_sat.get_value(),
            green_lum        = self.green_lum.get_value(),
            blue_hue         = self.blue_hue.get_value(),
            blue_sat         = self.blue_sat.get_value(),
            blue_lum         = self.blue_lum.get_value(),
            vibrance         = self.cg_vibrance.get_value(),
            color_sat        = self.cg_saturation.get_value(),
            shadow_tint      = self.cg_shadow_tint.get_value(),
            highlight_tint   = self.cg_highlight_tint.get_value(),
        )

    def set_params(self, params: InversionParams):
        self._block_signals = True
        self.profile_combo.setCurrentText(params.film_profile)
        self.temp.set_value(params.temp_shift)
        self.tint.set_value(params.tint_shift)
        self.s_blacks.set_value(getattr(params, 'blacks',     0.0))
        self.s_whites.set_value(getattr(params, 'whites',     0.0))
        self.s_shadows.set_value(getattr(params, 'shadows',   0.0))
        self.s_highlights.set_value(getattr(params, 'highlights', 0.0))
        self.exposure.set_value(params.exposure_stops)
        self.contrast.set_value(params.contrast)
        self.lift.set_value(params.lift)
        self.gain.set_value(params.gain)
        self.gamma.set_value(params.gamma)
        self.black_clip.set_value(params.black_clip_pct)
        self.white_clip.set_value(params.white_clip_pct)
        self.dust_check.setChecked(params.dust_removal)
        self.dust_radius.set_value(params.dust_radius)
        self.red_hue.set_value(getattr(params, 'red_hue',   0.0))
        self.red_sat.set_value(getattr(params, 'red_sat',   0.0))
        self.red_lum.set_value(getattr(params, 'red_lum',   0.0))
        self.green_hue.set_value(getattr(params, 'green_hue', 0.0))
        self.green_sat.set_value(getattr(params, 'green_sat', 0.0))
        self.green_lum.set_value(getattr(params, 'green_lum', 0.0))
        self.blue_hue.set_value(getattr(params, 'blue_hue',  0.0))
        self.blue_sat.set_value(getattr(params, 'blue_sat',  0.0))
        self.blue_lum.set_value(getattr(params, 'blue_lum',  0.0))
        self.cg_vibrance.set_value(getattr(params, 'vibrance',       0.0))
        self.cg_saturation.set_value(getattr(params, 'color_sat',    0.0))
        self.cg_shadow_tint.set_value(getattr(params, 'shadow_tint', 0.0))
        self.cg_highlight_tint.set_value(getattr(params, 'highlight_tint', 0.0))
        self._block_signals = False
        self._emit()

    def get_compression(self) -> str:
        return self.compression_combo.currentText()

    def _emit(self, *_):
        if not self._block_signals:
            self.params_changed.emit(self.get_params())

    def _reset_all(self):
        self.set_params(InversionParams())


# ── Shared styles ─────────────────────────────────────────────── #

_COMBO_STYLE = """
QComboBox {
    background:#2d2d2d; color:#d4d4d4; border:1px solid #444;
    border-radius:4px; padding:3px 8px; font-size:11px;
}
QComboBox::drop-down { border:none; width:16px; }
QComboBox::down-arrow { width:8px; height:8px; }
QComboBox QAbstractItemView {
    background:#2d2d30; color:#d4d4d4; border:1px solid #555;
    selection-background-color:#094771;
}
"""

_TAB_STYLE = """
QTabWidget::pane {
    border: 1px solid #3c3c3c; background: transparent;
}
QTabBar::tab {
    background: #2a2a2a; color: #888; padding: 5px 14px;
    border: 1px solid #333; border-bottom: none;
    border-top-left-radius: 3px; border-top-right-radius: 3px;
    font-size: 11px;
}
QTabBar::tab:selected {
    background: #1e1e1e; color: #d4d4d4;
    border-bottom: 1px solid #1e1e1e;
}
QTabBar::tab:hover:!selected { background: #333; color: #bbb; }
"""

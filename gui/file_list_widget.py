"""
file_list_widget.py
-------------------
File queue with per-file settings memory.

Each file stores its own InversionParams so adjustments made on one
frame are remembered when you switch to another and correctly applied
during batch export.
"""

from pathlib import Path
from copy import deepcopy

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QHBoxLayout,
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QDragEnterEvent, QDropEvent, QColor

from core.negative_inverter import InversionParams


_ICON_PENDING  = "⏳"
_ICON_MODIFIED = "✏️"
_ICON_DONE     = "✅"
_ICON_ERROR    = "❌"

_SUPPORTED_EXTENSIONS = {".arw", ".cr2", ".nef", ".dng", ".raf", ".rw2", ".orf", ".pef"}


class FileListWidget(QWidget):
    """
    Signals
    -------
    file_selected(Path)          user clicked a file
    files_dropped(list[Path])    files dragged in
    """
    file_selected = pyqtSignal(Path)
    files_dropped = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._files: list[Path] = []
        self._status: dict[Path, str] = {}
        # Per-file InversionParams storage
        self._params: dict[Path, InversionParams] = {}
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        header = QHBoxLayout()
        title = QLabel("📷  Files")
        title.setStyleSheet("font-weight:bold; font-size:13px; color:#ccc;")
        header.addWidget(title)
        header.addStretch()

        # Small indicator legend
        legend = QLabel(f"{_ICON_MODIFIED}=edited")
        legend.setStyleSheet("color:#666; font-size:9px;")
        header.addWidget(legend)
        layout.addLayout(header)

        self.list_widget = _DropListWidget()
        self.list_widget.setStyleSheet("""
            QListWidget {
                background:#252526; border:1px solid #3c3c3c;
                border-radius:4px; color:#d4d4d4; font-size:11px;
            }
            QListWidget::item { padding:4px 6px; border-bottom:1px solid #2d2d30; }
            QListWidget::item:selected { background:#094771; }
            QListWidget::item:hover { background:#2a2d2e; }
        """)
        self.list_widget.files_dropped.connect(self._on_dropped)
        self.list_widget.currentItemChanged.connect(self._on_selection_changed)
        layout.addWidget(self.list_widget)

        self.drop_hint = QLabel("Drop .ARW files here")
        self.drop_hint.setAlignment(Qt.AlignCenter)
        self.drop_hint.setStyleSheet("color:#555; font-size:11px; font-style:italic;")
        layout.addWidget(self.drop_hint)

        btn_row = QHBoxLayout()
        for label, slot in [("Clear All", self.clear_all),
                             ("Remove Selected", self._remove_selected)]:
            btn = QPushButton(label)
            btn.setStyleSheet(self._btn_style())
            btn.clicked.connect(slot)
            btn_row.addWidget(btn)
        layout.addLayout(btn_row)

    def _btn_style(self):
        return """
            QPushButton {
                background:#3c3c3c; color:#d4d4d4; border:none;
                border-radius:3px; padding:4px 6px; font-size:11px;
            }
            QPushButton:hover { background:#505050; }
        """

    # ── Public API ─────────────────────────────────────────────── #

    def add_files(self, paths: list[Path]):
        new = [p for p in paths
               if p.suffix.lower() in _SUPPORTED_EXTENSIONS and p not in self._files]
        for p in new:
            self._files.append(p)
            self._status[p] = "pending"
            self._params[p] = InversionParams()   # default params per file
            item = QListWidgetItem(f"{_ICON_PENDING}  {p.name}")
            item.setData(Qt.UserRole, p)
            item.setToolTip(str(p))
            self.list_widget.addItem(item)
        if new:
            self.drop_hint.setVisible(False)

    def select_file(self, path: Path):
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.data(Qt.UserRole) == path:
                self.list_widget.setCurrentItem(item)
                break

    def selected_files(self) -> list[Path]:
        return [item.data(Qt.UserRole) for item in self.list_widget.selectedItems()]

    def all_files(self) -> list[Path]:
        return list(self._files)

    def get_params(self, path: Path) -> InversionParams:
        """Return the stored InversionParams for a file."""
        return self._params.get(path, InversionParams())

    def save_params(self, path: Path, params: InversionParams):
        """
        Save InversionParams for a file and mark it as edited.
        A deep copy is stored so future slider changes don't affect the saved state.
        """
        if path not in self._params:
            return
        is_default = self._is_default(params)
        self._params[path] = deepcopy(params)

        # Update icon: show pencil if modified from defaults
        status = self._status.get(path, "pending")
        if status not in ("done", "error"):
            icon = _ICON_PENDING if is_default else _ICON_MODIFIED
            colour = QColor("#d4d4d4") if is_default else QColor("#e5c07b")
            self._update_icon(path, status, icon, colour)

    def all_params(self) -> dict[Path, InversionParams]:
        """Return a copy of the full path→params mapping (for batch export)."""
        return {p: deepcopy(params) for p, params in self._params.items()}

    def mark_done(self, path: Path):
        self._update_icon(path, "done", _ICON_DONE, QColor("#4ec9b0"))

    def mark_error(self, path: Path):
        self._update_icon(path, "error", _ICON_ERROR, QColor("#f44747"))

    def clear_all(self):
        self._files.clear()
        self._status.clear()
        self._params.clear()
        self.list_widget.clear()
        self.drop_hint.setVisible(True)

    # ── Internal ───────────────────────────────────────────────── #

    def _is_default(self, params: InversionParams) -> bool:
        """True if params are identical to a freshly constructed default."""
        default = InversionParams(film_profile=params.film_profile)
        # Compare a few key fields
        return (
            params.wb_red == default.wb_red and
            params.wb_green == default.wb_green and
            params.wb_blue == default.wb_blue and
            params.exposure_stops == default.exposure_stops and
            params.film_base_rgb == default.film_base_rgb
        )

    def _update_icon(self, path: Path, status: str, icon: str, colour: QColor):
        self._status[path] = status
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.data(Qt.UserRole) == path:
                item.setText(f"{icon}  {path.name}")
                item.setForeground(colour)
                break

    def _remove_selected(self):
        for item in self.list_widget.selectedItems():
            path = item.data(Qt.UserRole)
            self._files.remove(path)
            self._status.pop(path, None)
            self._params.pop(path, None)
            self.list_widget.takeItem(self.list_widget.row(item))
        if not self._files:
            self.drop_hint.setVisible(True)

    def _on_dropped(self, paths: list[Path]):
        self.add_files(paths)
        self.files_dropped.emit(paths)

    def _on_selection_changed(self, current, _previous):
        if current:
            path = current.data(Qt.UserRole)
            if path:
                self.file_selected.emit(path)


class _DropListWidget(QListWidget):
    files_dropped = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setSelectionMode(QListWidget.ExtendedSelection)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        paths = [Path(u.toLocalFile()) for u in event.mimeData().urls()]
        raw_paths = [p for p in paths if p.suffix.lower() in _SUPPORTED_EXTENSIONS]
        if raw_paths:
            self.files_dropped.emit(raw_paths)
        event.acceptProposedAction()

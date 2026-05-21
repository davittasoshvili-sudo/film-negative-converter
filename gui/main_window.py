"""
main_window.py
--------------
Main application window.

Changes in this version:
  - Per-image settings: saves current params when switching files,
    restores them when returning to a file.
  - Film base colour picker: clicking the negative preview samples a pixel
    as the film base override; "Reset to Auto" clears it.
  - Batch export uses each file's stored params, not a single global set.
"""

import sys
import numpy as np
from pathlib import Path
from copy import deepcopy

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QSplitter, QVBoxLayout, QHBoxLayout,
    QAction, QFileDialog, QStatusBar, QProgressBar, QLabel,
    QMessageBox, QToolBar,
)
from PyQt5.QtCore import Qt, pyqtSignal, QTimer
from PyQt5.QtGui import QDragEnterEvent, QDropEvent, QFont

from core.negative_inverter import InversionParams
from core.batch_processor import BatchWorker
from core.presets import save_preset, load_preset_from_file

from gui.file_list_widget import FileListWidget
from gui.preview_widget import PreviewWidget
from gui.controls_panel import ControlsPanel
from gui.histogram_widget import HistogramWidget
from gui.preview_worker import PreviewWorker


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("FilmScan - Film Negative Converter")
        self.setMinimumSize(1100, 700)
        self.resize(1400, 850)

        self._output_dir: Path    = Path.home() / "FilmScan_Output"
        self._current_file: Path | None = None
        self._batch_worker: BatchWorker | None = None
        self._preview_worker: PreviewWorker | None = None

        # Debounce timer for slider changes
        self._preview_timer = QTimer()
        self._preview_timer.setSingleShot(True)
        self._preview_timer.timeout.connect(self._start_preview)

        # RAW/thumb caches: keyed by Path, populated after first load.
        # Subsequent parameter changes skip the 3-5 s RAW decode entirely.
        self._raw_cache:   dict = {}
        self._thumb_cache: dict = {}
        self._preview_gen: int  = 0   # incremented each time a preview starts

        # Flag: suppress saving params while we're loading them for a new file
        self._loading_file = False

        self._build_ui()
        self._build_menu()
        self._build_toolbar()
        self._connect_signals()
        self._apply_stylesheet()

    # ── UI construction ───────────────────────────────────────── #

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(4)

        splitter = QSplitter(Qt.Horizontal)

        # Left: file list + controls
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(4)

        self.file_list = FileListWidget()
        self.file_list.setMinimumWidth(220)
        self.file_list.setMaximumWidth(300)

        self.controls = ControlsPanel()

        ll.addWidget(self.file_list, 2)
        ll.addWidget(self.controls, 3)

        # Right: preview + histogram
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(4)

        self.preview = PreviewWidget()
        self.histogram = HistogramWidget()
        self.histogram.setMaximumHeight(130)

        rl.addWidget(self.preview, 3)
        rl.addWidget(self.histogram, 1)

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        root.addWidget(splitter)

        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximumWidth(250)
        self.progress_bar.setVisible(False)
        self.status_bar.addPermanentWidget(self.progress_bar)

        self.status_label = QLabel("Ready - drag & drop .ARW files to begin")
        self.status_bar.addWidget(self.status_label)

    def _build_menu(self):
        mb = self.menuBar()

        fm = mb.addMenu("&File")
        for label, shortcut, slot in [
            ("&Open RAW Files...",    "Ctrl+O",       self._open_files),
            ("Set &Output Folder...", "",              self._set_output_dir),
            (None, None, None),
            ("Export &Selected",      "Ctrl+E",       self._export_selected),
            ("Export &All (Batch)",   "Ctrl+Shift+E", self._export_all),
            (None, None, None),
            ("&Quit",                 "Ctrl+Q",       self.close),
        ]:
            if label is None:
                fm.addSeparator()
            else:
                act = QAction(label, self)
                if shortcut:
                    act.setShortcut(shortcut)
                act.triggered.connect(slot)
                fm.addAction(act)

        pm = mb.addMenu("&Presets")
        for label, slot in [
            ("&Save Preset...", self._save_preset),
            ("&Load Preset...", self._load_preset),
        ]:
            act = QAction(label, self)
            act.triggered.connect(slot)
            pm.addAction(act)

        hm = mb.addMenu("&Help")
        about = QAction("&About FilmScan", self)
        about.triggered.connect(self._show_about)
        hm.addAction(about)

    def _build_toolbar(self):
        tb = QToolBar("Main Toolbar")
        tb.setMovable(False)
        self.addToolBar(tb)

        for label, slot in [
            ("📂  Open Files",      self._open_files),
            (None, None),
            ("📁  Output Folder",   self._set_output_dir),
            (None, None),
            ("⬆  Export Selected", self._export_selected),
            ("⚡  Batch Export All", self._export_all),
        ]:
            if label is None:
                tb.addSeparator()
            else:
                act = QAction(label, self)
                act.triggered.connect(slot)
                tb.addAction(act)

        tb.addSeparator()
        self.out_label = QLabel(f"  Output: {self._output_dir}")
        self.out_label.setStyleSheet("color:#aaa; font-size:11px;")
        tb.addWidget(self.out_label)

    def _connect_signals(self):
        self.file_list.file_selected.connect(self._on_file_selected)
        self.file_list.files_dropped.connect(self._on_files_dropped)

        # Controls: save params to current file and trigger preview
        self.controls.params_changed.connect(self._on_params_changed)

        # Film base picker
        self.preview.base_picked.connect(self._on_base_picked)
        self.preview.base_reset.connect(self._on_base_reset)

        # Rotate
        self.preview.rotate_cw.connect(self._on_rotate_cw)

    def _apply_stylesheet(self):
        self.setStyleSheet("""
            QMainWindow, QWidget {
                background-color: #1e1e1e; color: #d4d4d4;
                font-family: 'Segoe UI', system-ui, sans-serif; font-size: 12px;
            }
            QMenuBar { background:#252526; border-bottom:1px solid #3c3c3c; }
            QMenuBar::item:selected { background:#094771; }
            QMenu { background:#2d2d30; border:1px solid #3c3c3c; }
            QMenu::item:selected { background:#094771; }
            QToolBar {
                background:#252526; border-bottom:1px solid #3c3c3c;
                spacing:4px; padding:2px 6px;
            }
            QToolBar QToolButton {
                background:transparent; border:none;
                padding:4px 8px; border-radius:3px;
            }
            QToolBar QToolButton:hover { background:#3c3c3c; }
            QSplitter::handle { background:#3c3c3c; width:1px; }
            QStatusBar { background:#007acc; color:white; font-size:11px; }
            QProgressBar {
                border:none; background:rgba(255,255,255,0.2);
                border-radius:3px; text-align:center; color:white;
            }
            QProgressBar::chunk { background:white; border-radius:3px; }
        """)

    # ── Slots ─────────────────────────────────────────────────── #

    def _open_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Open RAW Files", str(Path.home()),
            "RAW Files (*.ARW *.arw *.CR2 *.cr2 *.NEF *.nef *.DNG *.dng *.RAF *.raf);;All Files (*)",
        )
        if paths:
            self.file_list.add_files([Path(p) for p in paths])

    def _set_output_dir(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Select Output Folder", str(self._output_dir)
        )
        if folder:
            self._output_dir = Path(folder)
            self.out_label.setText(f"  Output: {self._output_dir}")
            self._set_status(f"Output folder: {self._output_dir}")

    def _on_files_dropped(self, paths: list[Path]):
        self.file_list.add_files(paths)
        if paths:
            self.file_list.select_file(paths[0])

    def _on_file_selected(self, filepath: Path):
        """
        User switched to a different file.
        1. Save current controls state back to the PREVIOUS file.
        2. Load the new file's stored params into the controls.
        3. Trigger a preview.
        """
        # Step 1: save params for the file we're leaving
        if self._current_file and not self._loading_file:
            params = self.controls.get_params()
            # Preserve fields not represented by sliders (rotation, film_base_rgb)
            stored = self.file_list.get_params(self._current_file)
            params.rotation       = getattr(stored, 'rotation', 0)
            params.film_base_rgb  = stored.film_base_rgb
            self.file_list.save_params(self._current_file, params)

        # Step 2: load stored params for the newly selected file
        self._loading_file = True
        self._current_file = filepath
        stored = self.file_list.get_params(filepath)
        self.controls.set_params(stored)

        # Update the film base swatch to match stored params
        self.preview.set_base_colour(stored.film_base_rgb)

        self._loading_file = False

        # Step 3: trigger preview
        self._preview_timer.start(80)
        self._set_status(f"Selected: {filepath.name}")

    def _on_params_changed(self, params: InversionParams):
        """Controls changed — save to current file and re-preview."""
        if self._loading_file or not self._current_file:
            return
        # Preserve rotation — it's not a slider so get_params() always returns 0
        stored = self.file_list.get_params(self._current_file)
        params.rotation = getattr(stored, 'rotation', 0)
        self.file_list.save_params(self._current_file, params)
        self._preview_timer.start(300)

    def _on_rotate_cw(self):
        if not self._current_file:
            return
        params = self.file_list.get_params(self._current_file)
        params.rotation = (getattr(params, 'rotation', 0) + 90) % 360
        self.file_list.save_params(self._current_file, params)
        self._preview_timer.start(80)

    def _on_base_picked(self, r: float, g: float, b: float):
        """User clicked the negative to pick a film base colour."""
        if not self._current_file:
            return
        # Update current params with the picked base colour
        params = self.controls.get_params()
        params.film_base_rgb = (r, g, b)
        self._loading_file = True          # prevent double-save
        self.controls.set_params(params)
        self._loading_file = False
        self.file_list.save_params(self._current_file, params)
        self._set_status(
            f"Film base set to R:{int(r/655)} G:{int(g/655)} B:{int(b/655)}  (0-100 scale)"
        )
        self._preview_timer.start(100)

    def _on_base_reset(self):
        """User clicked 'Reset to Auto'."""
        if not self._current_file:
            return
        params = self.controls.get_params()
        params.film_base_rgb = None
        self._loading_file = True
        self.controls.set_params(params)
        self._loading_file = False
        self.file_list.save_params(self._current_file, params)
        self._set_status("Film base reset to auto-detect")
        self._preview_timer.start(100)

    def _start_preview(self):
        if not self._current_file:
            return

        # Signal the running worker to stop at its next checkpoint.
        # We do NOT wait here — the generation counter discards its result.
        if self._preview_worker and self._preview_worker.isRunning():
            self._preview_worker.abort()

        self._preview_gen += 1
        gen          = self._preview_gen
        params       = self.file_list.get_params(self._current_file)
        cached_raw   = self._raw_cache.get(self._current_file)
        cached_thumb = self._thumb_cache.get(self._current_file)

        # If the raw is already cached, arm the film-base picker immediately
        # so it doesn't need to wait for the worker to emit raw_loaded.
        if cached_raw is not None:
            self.preview.set_raw_image(cached_raw)

        self.preview.set_loading(True)
        self._preview_worker = PreviewWorker(
            self._current_file, params,
            generation=gen,
            raw_image=cached_raw,
            thumb_image=cached_thumb,
        )
        self._preview_worker.preview_ready.connect(self._on_preview_ready)
        self._preview_worker.raw_loaded.connect(self._on_raw_loaded)
        self._preview_worker.error.connect(self._on_preview_error)
        self._preview_worker.start()

    def _on_preview_ready(self, raw_thumb: np.ndarray, positive: np.ndarray, generation: int):
        if generation != self._preview_gen:
            return   # stale result from a superseded worker — discard
        if self._current_file and self._current_file not in self._thumb_cache:
            self._thumb_cache[self._current_file] = raw_thumb
        self.preview.set_images(raw_thumb, positive)
        self.histogram.update_histogram(positive)
        self.preview.set_loading(False)

    def _on_preview_error(self, msg: str, generation: int):
        if generation != self._preview_gen:
            return
        self.preview.set_loading(False)
        self._set_status(f"Preview error: {msg.splitlines()[0]}")

    def _on_raw_loaded(self, raw_img: np.ndarray):
        if self._current_file:
            self._raw_cache[self._current_file] = raw_img
        self.preview.set_raw_image(raw_img)

    # ── Export ─────────────────────────────────────────────────── #

    def _export_selected(self):
        # Save current controls before exporting
        if self._current_file:
            self.file_list.save_params(self._current_file, self.controls.get_params())
        selected = self.file_list.selected_files()
        if not selected:
            QMessageBox.warning(self, "No Selection", "Please select files to export.")
            return
        self._run_batch(selected)

    def _export_all(self):
        # Save current controls before exporting
        if self._current_file:
            self.file_list.save_params(self._current_file, self.controls.get_params())
        all_files = self.file_list.all_files()
        if not all_files:
            QMessageBox.warning(self, "No Files", "No files in the queue.")
            return
        self._run_batch(all_files)

    def _run_batch(self, files: list[Path]):
        if self._batch_worker and self._batch_worker.isRunning():
            QMessageBox.warning(self, "Busy", "A batch job is already running.")
            return

        compression  = self.controls.get_compression()
        params_map   = self.file_list.all_params()          # per-file params
        default_params = InversionParams()                   # fallback

        self._batch_worker = BatchWorker(
            files, self._output_dir, params_map, default_params, compression
        )
        self._batch_worker.progress.connect(self._on_batch_progress)
        self._batch_worker.file_done.connect(lambda s, d: self.file_list.mark_done(Path(s)))
        self._batch_worker.file_error.connect(self._on_file_error)
        self._batch_worker.all_done.connect(self._on_batch_done)

        self.progress_bar.setMaximum(len(files))
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        self._batch_worker.start()
        self._set_status(f"Processing {len(files)} file(s)...")

    def _on_batch_progress(self, current: int, total: int, name: str):
        self.progress_bar.setValue(current)
        self._set_status(f"Processing {current}/{total}: {name}")

    def _on_file_error(self, src: str, msg: str):
        self.file_list.mark_error(Path(src))
        self._set_status(f"Error: {Path(src).name} - {msg}")

    def _on_batch_done(self, n_ok: int, n_err: int):
        self.progress_bar.setVisible(False)
        self._set_status(f"Done - {n_ok} exported" + (f", {n_err} error(s)" if n_err else ""))
        QMessageBox.information(
            self, "Batch Complete",
            f"Exported {n_ok} file(s) to:\n{self._output_dir}"
            + (f"\n\n{n_err} file(s) failed." if n_err else ""),
        )

    # ── Presets ────────────────────────────────────────────────── #

    def _save_preset(self):
        from PyQt5.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "Save Preset", "Preset name:")
        if ok and name.strip():
            path = save_preset(name.strip(), self.controls.get_params())
            self._set_status(f"Preset saved: {path}")

    def _load_preset(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Preset", str(Path.home()), "Preset files (*.json)"
        )
        if path:
            try:
                params = load_preset_from_file(path)
                self.controls.set_params(params)
                self._set_status(f"Preset loaded: {Path(path).name}")
            except Exception as e:
                QMessageBox.warning(self, "Load Error", str(e))

    def _show_about(self):
        QMessageBox.about(
            self, "About FilmScan",
            "<b>FilmScan</b> - Film Negative Converter<br><br>"
            "Converts scanned colour film negatives to positive images.<br>"
            "Supports Sony ARW and other RAW formats.<br><br>"
            "Built with Python, rawpy, NumPy, OpenCV, and PyQt5.",
        )

    def _set_status(self, msg: str):
        self.status_label.setText(msg)

    # ── Drag & drop ────────────────────────────────────────────── #

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        paths = [Path(u.toLocalFile()) for u in event.mimeData().urls()]
        raw_paths = [p for p in paths
                     if p.suffix.lower() in {".arw",".cr2",".nef",".dng",".raf",".rw2"}]
        if raw_paths:
            self.file_list.add_files(raw_paths)

    def closeEvent(self, event):
        for w in [self._batch_worker, self._preview_worker]:
            if w and w.isRunning():
                w.abort()
                if not w.wait(2000):   # 2 s grace period
                    w.terminate()
                    w.wait()
        event.accept()

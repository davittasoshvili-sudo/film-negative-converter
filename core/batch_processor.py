"""
batch_processor.py
------------------
Batch processing engine.

Each file can now carry its own InversionParams so per-image adjustments
(exposure, WB, film base override, etc.) are correctly applied during export.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable
from copy import deepcopy

from PyQt5.QtCore import QThread, pyqtSignal

from core.raw_processor import load_raw
from core.negative_inverter import invert_negative, InversionParams
from core.exporter import export_tiff, ensure_output_dir


class BatchWorker(QThread):
    """
    QThread worker that processes a list of RAW files.

    Parameters
    ----------
    files        : list of file paths
    output_dir   : destination folder
    params_map   : dict mapping Path -> InversionParams (per-file settings).
                   If a file is not in the map, falls back to default_params.
    default_params : fallback InversionParams for files without per-file settings
    compression  : "lzw" | "deflate" | "none"

    Signals
    -------
    progress(current, total, filename)
    file_done(src_path, dst_path)
    file_error(src_path, error_msg)
    all_done(n_ok, n_err)
    """

    progress   = pyqtSignal(int, int, str)
    file_done  = pyqtSignal(str, str)
    file_error = pyqtSignal(str, str)
    all_done   = pyqtSignal(int, int)

    def __init__(
        self,
        files: list[Path],
        output_dir: Path,
        params_map: dict[Path, InversionParams],
        default_params: InversionParams,
        compression: str = "lzw",
        parent=None,
    ):
        super().__init__(parent)
        self.files          = files
        self.output_dir     = output_dir
        self.params_map     = params_map
        self.default_params = default_params
        self.compression    = compression
        self._abort         = False

    def abort(self):
        self._abort = True

    def run(self):
        ensure_output_dir(self.output_dir)
        total = len(self.files)
        n_ok = n_err = 0

        for idx, filepath in enumerate(self.files, 1):
            if self._abort:
                break

            self.progress.emit(idx, total, filepath.name)

            # Use per-file params if available, else fall back to default
            params = deepcopy(self.params_map.get(filepath, self.default_params))

            try:
                out_path = self._process_one(filepath, params)
                self.file_done.emit(str(filepath), str(out_path))
                n_ok += 1
            except Exception as exc:
                self.file_error.emit(str(filepath), f"{type(exc).__name__}: {exc}")
                n_err += 1

        self.all_done.emit(n_ok, n_err)

    def _process_one(self, filepath: Path, params: InversionParams) -> Path:
        image, meta = load_raw(filepath)
        positive    = invert_negative(image, params)

        out_name = filepath.stem + "_positive.tiff"
        out_path = self.output_dir / out_name

        meta["film_profile"] = params.film_profile
        export_tiff(positive, out_path, compression=self.compression, metadata=meta)
        return out_path

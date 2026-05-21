"""
preview_worker.py
-----------------
Background thread for generating previews.

Caching: if raw_image is provided, the expensive RAW decode is skipped and
only invert_negative() runs (~100-300 ms vs 3-5 s for a full ARW load).

Each result carries a generation number so the caller can discard stale
results when the user adjusts controls faster than the worker can respond.
"""

import numpy as np
from pathlib import Path

from PyQt5.QtCore import QThread, pyqtSignal

from core.raw_processor import load_raw, load_raw_thumbnail
from core.negative_inverter import invert_negative, InversionParams

_MAX_PREVIEW_DIM = 1200


class PreviewWorker(QThread):
    """
    Signals
    -------
    preview_ready(raw_thumb_uint8, positive_float, generation)
    raw_loaded(raw_linear_float64)   — only emitted on a fresh load (not cache)
    error(message, generation)
    """
    preview_ready = pyqtSignal(object, object, int)
    raw_loaded    = pyqtSignal(object)
    error         = pyqtSignal(str, int)

    def __init__(
        self,
        filepath: Path,
        params: InversionParams,
        generation: int = 0,
        raw_image: np.ndarray | None = None,
        thumb_image: np.ndarray | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.filepath      = filepath
        self.params        = params
        self.generation    = generation
        self._cached_raw   = raw_image
        self._cached_thumb = thumb_image
        self._abort        = False

    def abort(self):
        """Ask the worker to stop at the next safe checkpoint."""
        self._abort = True

    def run(self):
        try:
            # ── Step 1: get the linear RAW (cache hit = instant) ─────── #
            if self._cached_raw is not None:
                raw_small = self._cached_raw
            else:
                raw_img, _meta = load_raw(self.filepath)
                if self._abort:
                    return
                raw_small = _downsample(raw_img, _MAX_PREVIEW_DIM)
                self.raw_loaded.emit(raw_small)

            if self._abort:
                return

            # ── Step 2: invert ───────────────────────────────────────── #
            positive = invert_negative(raw_small, self.params)

            if self._abort:
                return

            # ── Step 3: before-panel thumbnail ───────────────────────── #
            if self._cached_thumb is not None:
                before_thumb = self._cached_thumb
            else:
                try:
                    before_thumb = load_raw_thumbnail(self.filepath, _MAX_PREVIEW_DIM)
                except Exception:
                    before_thumb = (
                        np.clip(raw_small / 65535.0, 0, 1) * 255
                    ).astype(np.uint8)

            self.preview_ready.emit(before_thumb, positive, self.generation)

        except Exception as exc:
            import traceback
            self.error.emit(
                f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}",
                self.generation,
            )


def _downsample(image: np.ndarray, max_dim: int) -> np.ndarray:
    h, w = image.shape[:2]
    longest = max(h, w)
    if longest <= max_dim:
        return image
    step = int(np.ceil(longest / max_dim))
    return image[::step, ::step].copy()

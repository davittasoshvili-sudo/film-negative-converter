"""
exporter.py
-----------
Exports processed images as 16-bit TIFF files.

Supports:
  - Uncompressed TIFF (maximum compatibility)
  - LZW lossless compression (smaller file, still lossless)
  - Metadata embedding (description, software tag)
"""

import numpy as np
from pathlib import Path
from PIL import Image
import tifffile          # pip install tifffile — better 16-bit TIFF support
import datetime


_SOFTWARE_TAG = "FilmScan - Film Negative Converter"


def export_tiff(
    image_float: np.ndarray,       # float64, shape (H,W,3), range 0..1
    output_path: str | Path,
    compression: str = "lzw",     # "none" | "lzw" | "deflate"
    metadata: dict | None = None,
) -> Path:
    """
    Save a processed image as a 16-bit TIFF.

    Parameters
    ----------
    image_float  : numpy array in 0..1 float64
    output_path  : destination file path (will be suffixed .tiff if needed)
    compression  : "none" → uncompressed, "lzw" → LZW (lossless),
                   "deflate" → ZIP lossless (smaller but slower)
    metadata     : optional dict with keys like 'camera', 'filename', etc.

    Returns
    -------
    Path of the written file.
    """
    output_path = Path(output_path)
    if output_path.suffix.lower() not in (".tif", ".tiff"):
        output_path = output_path.with_suffix(".tiff")

    # ── Convert float64 [0,1] → uint16 [0,65535] ──────────────────────── #
    image_16 = np.clip(image_float * 65535.0, 0, 65535).astype(np.uint16)

    # ── Build image description string ────────────────────────────────── #
    desc = _build_description(metadata)

    # ── Compression mapping ───────────────────────────────────────────── #
    comp_map = {
        "none":    None,
        "lzw":     "lzw",
        "deflate": "deflate",
    }
    comp = comp_map.get(compression.lower(), "lzw")

    # ── Write with tifffile (robust 16-bit support) ───────────────────── #
    _write_tifffile(image_16, output_path, comp, desc)

    return output_path


def _write_tifffile(
    image_16: np.ndarray,
    output_path: Path,
    compression: str | None,
    description: str,
) -> None:
    """Write using tifffile for proper 16-bit TIFF with metadata."""
    try:
        import tifffile as tf

        # Build minimal EXIF-style metadata
        software = _SOFTWARE_TAG
        datetime_str = datetime.datetime.now().strftime("%Y:%m:%d %H:%M:%S")

        kwargs = dict(
            photometric="rgb",
            compression=compression or "none",
            description=description,
            software=software,
            datetime=datetime_str,
            # Resolution: 600 dpi (typical for film scans)
            resolution=(600, 600),
            resolutionunit="inch",
        )

        tf.imwrite(str(output_path), image_16, **kwargs)

    except ImportError:
        # Fallback to Pillow (less metadata support but reliable)
        _write_pillow(image_16, output_path, compression)


def _write_pillow(
    image_16: np.ndarray,
    output_path: Path,
    compression: str | None,
) -> None:
    """Fallback TIFF writer using Pillow."""
    img = Image.fromarray(image_16, mode="RGB")

    save_kwargs: dict = {"format": "TIFF"}
    if compression == "lzw":
        save_kwargs["compression"] = "tiff_lzw"
    elif compression == "deflate":
        save_kwargs["compression"] = "tiff_deflate"
    # else: no compression

    img.save(str(output_path), **save_kwargs)


def _build_description(metadata: dict | None) -> str:
    """Compose a human-readable TIFF image description."""
    lines = [
        f"Processed by {_SOFTWARE_TAG}",
        f"Date: {datetime.datetime.now().isoformat(timespec='seconds')}",
    ]
    if metadata:
        if "camera" in metadata:
            lines.append(f"Camera: {metadata['camera']}")
        if "filename" in metadata:
            lines.append(f"Source: {metadata['filename']}")
        if "film_profile" in metadata:
            lines.append(f"Film Profile: {metadata['film_profile']}")
    return "\n".join(lines).encode("ascii", errors="replace").decode("ascii")


def ensure_output_dir(path: str | Path) -> Path:
    """Create output directory if it doesn't exist, return as Path."""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p

"""
raw_processor.py
----------------
Loads Sony .ARW (and other RAW) files via rawpy/LibRaw.

Key insight for negative scanning
----------------------------------
We use use_camera_wb=True for demosaicing. This is correct because:
  1. The camera WB multipliers balance the RGGB Bayer sensor channels properly.
     Without this, green is ~2x over-represented (it appears twice per 2x2 block)
     which completely destroys the orange mask detection.
  2. We keep linear gamma=(1,1) and no_auto_bright=True so the output is still
     a physically linear representation of the film density.
  3. The camera WB does introduce a colour cast, but our inversion pipeline
     detects and removes the film base colour anyway, so this is harmless.

Full bit depth is preserved by reading white_level/black_level from the RAW
header and explicitly remapping to [0, 65535] after postprocessing.
"""

import rawpy
import numpy as np
from pathlib import Path


def _make_params(**kwargs) -> rawpy.Params:
    """Build rawpy.Params by setting attributes individually (version-safe)."""
    p = rawpy.Params()
    for k, v in kwargs.items():
        setattr(p, k, v)
    return p


def load_raw(filepath: str | Path) -> tuple[np.ndarray, dict]:
    """
    Load a RAW file and return float64 linear RGB (0..65535) + metadata.

    Returns
    -------
    image : np.ndarray  shape (H, W, 3), dtype float64, range 0..65535
    meta  : dict
    """
    filepath = Path(filepath)
    if not filepath.exists():
        raise FileNotFoundError(f"RAW file not found: {filepath}")

    with rawpy.imread(str(filepath)) as raw:
        try:
            white_level = float(raw.white_level)
        except Exception:
            white_level = 16383.0

        try:
            black_level = float(max(raw.black_level_per_channel))
        except Exception:
            black_level = 512.0

        # Use camera WB so Bayer channels are balanced during demosaicing.
        # This is essential — flat [1,1,1,1] causes green channel imbalance
        # (green appears twice per 2x2 Bayer block) which breaks inversion.
        params = _make_params(
            use_camera_wb=True,   # balance Bayer channels correctly
            gamm=(1.0, 1.0),      # linear output, no gamma
            no_auto_bright=True,  # no brightness normalisation
            output_bps=16,        # uint16 output
            user_qual=3,          # AHD demosaicing (highest quality)
            output_color=1,       # sRGB (integer, not enum — version safe)
            med_passes=0,
        )

        image = raw.postprocess(params)
        meta  = _extract_metadata(raw, filepath, white_level, black_level)

    # Remap [black_level, white_level] -> [0, 65535] to use full bit depth.
    # For a 14-bit Sony sensor (0..16383), this correctly expands to uint16 range.
    img = image.astype(np.float64)
    usable = white_level - black_level
    if usable > 0:
        img = (img - black_level) / usable * 65535.0
    img = np.clip(img, 0.0, 65535.0)

    return img, meta


def _extract_metadata(raw, filepath, white_level, black_level):
    meta = {
        "filename": filepath.name,
        "filepath": str(filepath),
        "white_level": white_level,
        "black_level": black_level,
    }
    try:
        meta["camera"] = raw.camera_model.strip()
    except Exception:
        meta["camera"] = "Unknown"
    try:
        meta["color_desc"] = raw.color_desc.decode()
    except Exception:
        meta["color_desc"] = ""
    try:
        meta["camera_wb"] = list(raw.camera_whitebalance)
    except Exception:
        meta["camera_wb"] = [1.0, 1.0, 1.0, 1.0]
    return meta


def load_raw_thumbnail(filepath: str | Path, max_dim: int = 800) -> np.ndarray:
    """Fast 8-bit RGB thumbnail for UI preview."""
    filepath = Path(filepath)
    try:
        with rawpy.imread(str(filepath)) as raw:
            try:
                thumb = raw.extract_thumb()
                if thumb.format == rawpy.ThumbFormat.JPEG:
                    import io
                    from PIL import Image
                    img = Image.open(io.BytesIO(thumb.data))
                    img = img.convert("RGB")
                    img.thumbnail((max_dim, max_dim), Image.LANCZOS)
                    return np.array(img)
            except Exception:
                pass
            return raw.postprocess(_make_params(
                use_camera_wb=True,
                half_size=True,
                output_bps=8,
                no_auto_bright=False,
            ))
    except Exception as e:
        raise RuntimeError(f"Could not load thumbnail for {filepath}: {e}")

"""
negative_inverter.py
--------------------
Converts a linear-light scan of a colour film negative into a positive.

Pipeline
--------
 1.  Normalise RAW values to 0..1
 2.  Dust filter (optional)
 3.  Detect film base from centre of frame
 4.  Log optical density relative to base
 5.  Invert: dense negative -> bright positive
 6.  Per-channel percentile stretch (black/white points)
 7.  White balance multipliers  (from profile + user)
 8.  Exposure stops
 9.  Temperature / tint
10.  Film-profile contrast / lift / gain
11.  Legacy CMY grading (backward-compat with saved presets)
12.  B&W desaturation (if profile calls for it)
13.  Gamma encoding

Perceptual-space adjustments (after gamma):
14.  Tone controls: Blacks / Whites / Shadows / Highlights
15.  S-curve (PCHIP cubic LUT)
16.  HSL per-colour (Red / Green / Blue ranges)
17.  Color grading: Vibrance / Saturation / Shadow Tint / Highlight Tint
"""

import numpy as np
from dataclasses import dataclass

_EPS   = 1e-9
_MAX16 = 65535.0


# ─────────────────────────────────────────────────────────── #
# Parameters                                                  #
# ─────────────────────────────────────────────────────────── #

@dataclass
class InversionParams:
    """All controls for the negative->positive pipeline."""

    film_base_rgb:  tuple | None = None   # None = auto-detect

    black_clip_pct: float = 0.5
    white_clip_pct: float = 99.5

    # Internal WB multipliers (used by film profiles; no longer user-facing)
    wb_red:   float = 1.0
    wb_green: float = 1.0
    wb_blue:  float = 1.0

    exposure_stops: float = 0.0
    gamma:          float = 2.2
    contrast:       float = 1.0
    lift:           float = 0.0
    gain:           float = 1.0

    film_profile: str   = "neutral"
    temp_shift:   float = 0.0
    tint_shift:   float = 0.0

    dust_removal: bool = False
    dust_radius:  int  = 3

    # Legacy CMY (kept for backward compat with saved presets; no longer in UI)
    cyan_magenta:   float = 0.0
    cyan_yellow:    float = 0.0
    magenta_yellow: float = 0.0

    # Tone controls (applied in perceptual / gamma-encoded space)
    blacks:     float = 0.0    # -0.3..+0.3  lift / crush darkest tones
    whites:     float = 0.0    # -0.3..+0.3  lift / crush brightest tones
    shadows:    float = 0.0    # -1..+1      brighten / darken shadow range
    highlights: float = 0.0    # -1..+1      brighten / darken highlight range

    # S-curve control points  (output at input = 0.25 / 0.5 / 0.75)
    curve_shadows:    float = 0.25
    curve_midtones:   float = 0.50
    curve_highlights: float = 0.75

    # HSL selective colour (Red / Green / Blue hue ranges)
    red_hue:   float = 0.0    # -30..+30 degrees
    red_sat:   float = 0.0    # -1..+1
    red_lum:   float = 0.0    # -1..+1
    green_hue: float = 0.0
    green_sat: float = 0.0
    green_lum: float = 0.0
    blue_hue:  float = 0.0
    blue_sat:  float = 0.0
    blue_lum:  float = 0.0

    # Color grading (replaces CMY)
    vibrance:       float = 0.0   # -1..+1  intelligent saturation
    color_sat:      float = 0.0   # -1..+1  global saturation
    shadow_tint:    float = 0.0   # -1 cool .. +1 warm in shadows
    highlight_tint: float = 0.0   # -1 cool .. +1 warm in highlights

    # Image orientation (degrees clockwise: 0, 90, 180, 270)
    rotation: int = 0


# ─────────────────────────────────────────────────────────── #
# Film profiles                                               #
# ─────────────────────────────────────────────────────────── #

FILM_PROFILES: dict[str, dict] = {
    "neutral": {},

    "kodak_gold": {
        "wb_red":         1.10,
        "wb_green":        0.97,
        "wb_blue":         0.82,
        "contrast":        1.10,
        "lift":            0.04,
        "gain":            0.80,
        "black_clip_pct":  1.0,
        "white_clip_pct": 98.5,
    },

    "kodak_portra": {
        "wb_red":    1.04,
        "wb_green":  0.99,
        "wb_blue":   0.92,
        "contrast":  0.95,
        "lift":      0.03,
        "gain":      0.96,
        "black_clip_pct": 1.0,
        "white_clip_pct": 98.5,
    },

    "fuji_velvia": {
        "wb_red":    0.96,
        "wb_blue":   1.08,
        "contrast":  1.18,
        "lift":      -0.01,
    },

    "fuji_400h": {
        "wb_blue":   1.06,
        "contrast":  0.93,
        "lift":      0.04,
    },

    "ilford_hp5": {
        "contrast":    1.12,
        "_desaturate": True,
    },
}


# ─────────────────────────────────────────────────────────── #
# Main entry point                                            #
# ─────────────────────────────────────────────────────────── #

def invert_negative(image: np.ndarray, params: InversionParams) -> np.ndarray:
    """
    Convert a linear RAW negative scan to a positive.

    Parameters
    ----------
    image  : float64 (H, W, 3), values 0..65535 (linear light)
    params : InversionParams

    Returns
    -------
    float64 (H, W, 3), values 0..1, gamma-encoded
    """

    # ── 1. Normalise ─────────────────────────────────────────────────────── #
    img = np.clip(image / _MAX16, _EPS, 1.0 - _EPS)

    # ── 2. Dust removal ───────────────────────────────────────────────────── #
    if params.dust_removal:
        img = _median_filter(img, params.dust_radius)

    # ── 3. Profile defaults ───────────────────────────────────────────────── #
    profile    = FILM_PROFILES.get(params.film_profile, {})
    black_clip = profile.get("black_clip_pct", params.black_clip_pct)
    white_clip = profile.get("white_clip_pct", params.white_clip_pct)

    # ── 4. Film base detection (centre crop avoids sprocket holes) ─────────── #
    base = _detect_film_base(img, params.film_base_rgb)

    # ── 5. Log density → inversion ────────────────────────────────────────── #
    density = np.log10(base[np.newaxis, np.newaxis, :] / img)
    density  = np.clip(density, 0.0, None)
    d_max    = np.maximum(
        np.array([np.percentile(density[:, :, c], 99.5) for c in range(3)]),
        _EPS,
    )
    positive = np.clip(density / d_max[np.newaxis, np.newaxis, :], 0.0, 1.0)

    # ── 6. Per-channel percentile stretch ─────────────────────────────────── #
    positive = _percentile_stretch(positive, black_clip, white_clip)

    # ── 7. White balance ──────────────────────────────────────────────────── #
    wb_r = params.wb_red   * profile.get("wb_red",   1.0)
    wb_g = params.wb_green * profile.get("wb_green", 1.0)
    wb_b = params.wb_blue  * profile.get("wb_blue",  1.0)
    positive[:, :, 0] = np.clip(positive[:, :, 0] * wb_r, 0, 1)
    positive[:, :, 1] = np.clip(positive[:, :, 1] * wb_g, 0, 1)
    positive[:, :, 2] = np.clip(positive[:, :, 2] * wb_b, 0, 1)

    # ── 8. Exposure ───────────────────────────────────────────────────────── #
    if params.exposure_stops != 0.0:
        positive = np.clip(positive * (2.0 ** params.exposure_stops), 0, 1)

    # ── 9. Temperature / tint ─────────────────────────────────────────────── #
    if params.temp_shift != 0.0 or params.tint_shift != 0.0:
        positive = _apply_temp_tint(positive, params.temp_shift, params.tint_shift)

    # ── 10. Contrast / lift / gain ────────────────────────────────────────── #
    contrast = params.contrast * profile.get("contrast", 1.0)
    lift     = params.lift     + profile.get("lift",     0.0)
    gain     = params.gain     * profile.get("gain",     1.0)
    positive = _contrast_curve(positive, contrast, lift, gain)

    # ── 11. Legacy CMY (non-zero only in old presets) ─────────────────────── #
    positive = _apply_cmy(positive, params)

    # ── 12. B&W desaturation ──────────────────────────────────────────────── #
    if profile.get("_desaturate"):
        lum = (0.2126 * positive[:, :, 0] +
               0.7152 * positive[:, :, 1] +
               0.0722 * positive[:, :, 2])
        positive = np.stack([lum, lum, lum], axis=-1)

    # ── 13. Gamma ─────────────────────────────────────────────────────────── #
    positive = np.clip(positive, 0.0, 1.0) ** (1.0 / params.gamma)

    # ── Perceptual-space adjustments (after gamma) ─────────────────────────── #

    # ── 14. Tone controls ─────────────────────────────────────────────────── #
    positive = _apply_tone_controls(positive, params)

    # ── 15. S-curve (PCHIP, handles map to perceived shadows/mids/highlights) #
    positive = _apply_scurve(positive, params)

    # ── 16. HSL per-colour ────────────────────────────────────────────────── #
    positive = _apply_hsl_colors(positive, params)

    # ── 17. Color grading ─────────────────────────────────────────────────── #
    positive = _apply_color_grading(positive, params)

    positive = np.clip(positive, 0.0, 1.0)

    # ── 18. Rotation ──────────────────────────────────────────────────────── #
    rot = getattr(params, 'rotation', 0)
    if rot:
        # np.rot90 rotates CCW; convert CW degrees to CCW k
        k = (4 - (rot // 90) % 4) % 4
        if k:
            # .copy() ensures C-contiguous memory — rot90 returns a view with
            # negative strides that confuses QImage's buffer pointer
            positive = np.rot90(positive, k=k).copy()

    return positive


# ─────────────────────────────────────────────────────────── #
# Step helpers                                                #
# ─────────────────────────────────────────────────────────── #

def _detect_film_base(img: np.ndarray, override: tuple | None) -> np.ndarray:
    if override is not None:
        base = np.array(override, dtype=np.float64) / _MAX16
        return np.clip(base, _EPS, 1.0)
    H, W = img.shape[:2]
    centre = img[H // 6 : 5 * H // 6, W // 8 : 7 * W // 8]
    base = np.array([np.percentile(centre[:, :, c], 95) for c in range(3)])
    return np.maximum(base, 0.1)


def _percentile_stretch(img: np.ndarray, lo_pct: float, hi_pct: float) -> np.ndarray:
    out = np.empty_like(img)
    for c in range(3):
        lo  = np.percentile(img[:, :, c], lo_pct)
        hi  = np.percentile(img[:, :, c], hi_pct)
        rng = max(hi - lo, _EPS)
        out[:, :, c] = (img[:, :, c] - lo) / rng
    return np.clip(out, 0.0, 1.0)


def _apply_temp_tint(img: np.ndarray, temp: float, tint: float) -> np.ndarray:
    TEMP_STR = 0.10
    TINT_STR = 0.08
    out = img.copy()
    out[:, :, 0] = np.clip(img[:, :, 0] + temp * TEMP_STR, 0, 1)
    out[:, :, 2] = np.clip(img[:, :, 2] - temp * TEMP_STR, 0, 1)
    out[:, :, 1] = np.clip(img[:, :, 1] + tint * TINT_STR, 0, 1)
    out[:, :, 0] = np.clip(out[:, :, 0] - tint * (TINT_STR * 0.5), 0, 1)
    return out


def _contrast_curve(img: np.ndarray, contrast: float, lift: float, gain: float) -> np.ndarray:
    out = np.clip(img * gain + lift, 0.0, 1.0)
    if abs(contrast - 1.0) > 0.001:
        x   = out - 0.5
        out = np.clip(np.sign(x) * (np.abs(x) ** (1.0 / contrast)) + 0.5, 0, 1)
    return out


def _apply_cmy(img: np.ndarray, params) -> np.ndarray:
    """Legacy CMY grading — only active when loaded from an old preset."""
    cm = getattr(params, 'cyan_magenta',   0.0)
    cy = getattr(params, 'cyan_yellow',    0.0)
    my = getattr(params, 'magenta_yellow', 0.0)
    if abs(cm) < 0.001 and abs(cy) < 0.001 and abs(my) < 0.001:
        return img
    S   = 0.40
    out = img.copy()
    out[:, :, 0] = np.clip(out[:, :, 0] - cm * S,       0, 1)
    out[:, :, 2] = np.clip(out[:, :, 2] + cm * S * 0.4, 0, 1)
    out[:, :, 2] = np.clip(out[:, :, 2] + cy * S,       0, 1)
    out[:, :, 0] = np.clip(out[:, :, 0] - cy * S * 0.3, 0, 1)
    out[:, :, 1] = np.clip(out[:, :, 1] - cy * S * 0.3, 0, 1)
    out[:, :, 1] = np.clip(out[:, :, 1] - my * S,       0, 1)
    return out


def _apply_tone_controls(img: np.ndarray, params) -> np.ndarray:
    """
    Blacks / Whites / Shadows / Highlights — applied in perceptual space.

    Each control uses a luminance-weighted mask so the adjustment fades
    in/out smoothly at the boundary of the affected tonal range.
    All masks are computed from the INPUT image so controls are independent.
    """
    blacks     = getattr(params, 'blacks',     0.0)
    whites     = getattr(params, 'whites',     0.0)
    shadows    = getattr(params, 'shadows',    0.0)
    highlights = getattr(params, 'highlights', 0.0)

    if abs(blacks) < 1e-4 and abs(whites) < 1e-4 and abs(shadows) < 1e-4 and abs(highlights) < 1e-4:
        return img

    # Perceptual luminance for masking — keep as (H,W,1) for broadcasting
    lum = (0.2126 * img[:, :, 0] +
           0.7152 * img[:, :, 1] +
           0.0722 * img[:, :, 2])[:, :, np.newaxis]
    out = img.copy()

    # Blacks: quadratic falloff — strongest at pure black, fades smoothly into mids
    if abs(blacks) > 1e-4:
        w = (1.0 - lum) ** 2
        out = np.clip(out + blacks * w, 0.0, 1.0)

    # Whites: quadratic falloff — strongest at pure white, fades smoothly into mids
    if abs(whites) > 1e-4:
        w = lum ** 2
        out = np.clip(out + whites * w, 0.0, 1.0)

    # Shadows: affects lower half of range (0 → 0.5), max shift ±0.4
    if abs(shadows) > 1e-4:
        w = np.clip(1.0 - lum * 2.0, 0.0, 1.0)
        out = np.clip(out + shadows * 0.4 * w, 0.0, 1.0)

    # Highlights: affects upper half of range (0.5 → 1.0), max shift ±0.4
    if abs(highlights) > 1e-4:
        w = np.clip(lum * 2.0 - 1.0, 0.0, 1.0)
        out = np.clip(out + highlights * 0.4 * w, 0.0, 1.0)

    return out


def _apply_scurve(img: np.ndarray, params) -> np.ndarray:
    """
    PCHIP tone curve through 5 points applied as a 4096-point LUT.
    Operates in gamma-encoded (perceptual) space so handles map to
    perceived shadows / midtones / highlights.
    """
    cs   = getattr(params, 'curve_shadows',    0.25)
    cm_v = getattr(params, 'curve_midtones',   0.50)
    ch   = getattr(params, 'curve_highlights', 0.75)

    if abs(cs - 0.25) < 0.001 and abs(cm_v - 0.50) < 0.001 and abs(ch - 0.75) < 0.001:
        return img

    xs = np.array([0.0, 0.25, 0.50, 0.75, 1.0])
    ys = np.array([0.0,  cs,  cm_v,  ch,  1.0])
    ys = np.clip(ys, 0.0, 1.0)
    for i in range(1, len(ys)):
        ys[i] = max(ys[i], ys[i - 1] + 1e-4)
    ys = np.clip(ys, 0.0, 1.0)

    LUT_SIZE = 4096
    lut_x    = np.linspace(0.0, 1.0, LUT_SIZE)
    try:
        from scipy.interpolate import PchipInterpolator
        lut_y = PchipInterpolator(xs, ys)(lut_x)
    except ImportError:
        lut_y = _catmull_rom_lut(xs, ys, lut_x)
    lut_y = np.clip(lut_y, 0.0, 1.0)

    idx = np.clip((img * (LUT_SIZE - 1)).astype(np.int32), 0, LUT_SIZE - 1)
    return lut_y[idx].astype(np.float64)


# ─────────────────────────────────────────────────────────── #
# HSV utilities (vectorised)                                  #
# ─────────────────────────────────────────────────────────── #

def _rgb_to_hsv(img: np.ndarray) -> np.ndarray:
    """(H,W,3) float64 RGB 0..1 → HSV, hue in 0..360."""
    r, g, b = img[:, :, 0], img[:, :, 1], img[:, :, 2]
    cmax  = np.maximum(np.maximum(r, g), b)
    cmin  = np.minimum(np.minimum(r, g), b)
    delta = cmax - cmin

    s = np.where(cmax > 1e-10, delta / cmax, 0.0)

    d_safe  = np.where(delta > 1e-10, delta, 1.0)
    r_is_max = (cmax == r)
    g_is_max = (cmax == g) & ~r_is_max

    h_r = (60.0 * ((g - b) / d_safe)) % 360.0
    h_g =  60.0 * ((b - r) / d_safe + 2.0)
    h_b =  60.0 * ((r - g) / d_safe + 4.0)

    h = np.where(r_is_max, h_r, np.where(g_is_max, h_g, h_b))
    h = np.where(delta > 1e-10, h % 360.0, 0.0)

    return np.stack([h, s, cmax], axis=-1)


def _hsv_to_rgb(hsv: np.ndarray) -> np.ndarray:
    """(H,W,3) HSV (hue 0..360, s/v 0..1) → RGB float64 0..1."""
    h, s, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    hi = np.floor(h / 60.0).astype(np.int32) % 6
    f  = h / 60.0 - np.floor(h / 60.0)
    p  = v * (1.0 - s)
    q  = v * (1.0 - f * s)
    t  = v * (1.0 - (1.0 - f) * s)

    conds = [hi == 0, hi == 1, hi == 2, hi == 3, hi == 4, hi == 5]
    r = np.select(conds, [v, q, p, p, t, v])
    g = np.select(conds, [t, v, v, q, p, p])
    b = np.select(conds, [p, p, t, v, v, q])
    return np.stack([r, g, b], axis=-1)


def _hue_weight(h: np.ndarray, center: float, half_width: float) -> np.ndarray:
    """Smooth weight mask (0..1) for pixels whose hue is near `center`."""
    dist = np.abs(((h - center + 180.0) % 360.0) - 180.0)
    return np.clip(1.0 - dist / half_width, 0.0, 1.0)


# ─────────────────────────────────────────────────────────── #
# HSL per-colour                                              #
# ─────────────────────────────────────────────────────────── #

def _apply_hsl_colors(img: np.ndarray, params) -> np.ndarray:
    """
    Selective hue / saturation / luminance adjustments for the
    Red, Green, and Blue hue ranges.

    Hue shift  : degrees (-30..+30)
    Saturation : multiplicative boost (-1 = desaturate, +1 = 2× saturation)
    Luminance  : additive value shift, max ±0.5 in HSV value channel
    """
    rh = getattr(params, 'red_hue',   0.0)
    rs = getattr(params, 'red_sat',   0.0)
    rl = getattr(params, 'red_lum',   0.0)
    gh = getattr(params, 'green_hue', 0.0)
    gs = getattr(params, 'green_sat', 0.0)
    gl = getattr(params, 'green_lum', 0.0)
    bh = getattr(params, 'blue_hue',  0.0)
    bs = getattr(params, 'blue_sat',  0.0)
    bl = getattr(params, 'blue_lum',  0.0)

    if all(abs(v) < 1e-4 for v in [rh, rs, rl, gh, gs, gl, bh, bs, bl]):
        return img

    hsv = _rgb_to_hsv(np.clip(img, 0.0, 1.0))
    h = hsv[:, :, 0].copy()
    s = hsv[:, :, 1].copy()
    v = hsv[:, :, 2].copy()

    # (hue_center°, half_width°, hue_shift°, sat_adj, lum_adj)
    for center, hw, hue_shift, sat_adj, lum_adj in [
        (  0.0, 50.0, rh, rs, rl),   # Red   (wraps around 0°/360°)
        (120.0, 50.0, gh, gs, gl),   # Green
        (225.0, 50.0, bh, bs, bl),   # Blue
    ]:
        if abs(hue_shift) < 1e-4 and abs(sat_adj) < 1e-4 and abs(lum_adj) < 1e-4:
            continue
        w = _hue_weight(h, center, hw)
        h = (h + hue_shift * w) % 360.0
        # Additive saturation: works on low-saturation film images too
        s = np.clip(s + sat_adj * w, 0.0, 1.0)
        v = np.clip(v + lum_adj * 0.5 * w, 0.0, 1.0)

    return np.clip(_hsv_to_rgb(np.stack([h, s, v], axis=-1)), 0.0, 1.0)


# ─────────────────────────────────────────────────────────── #
# Color grading                                               #
# ─────────────────────────────────────────────────────────── #

def _apply_color_grading(img: np.ndarray, params) -> np.ndarray:
    """
    Vibrance, Saturation, Shadow Tint, Highlight Tint.

    Vibrance    : boosts less-saturated pixels more than already-vivid ones.
    Saturation  : global multiplicative saturation shift.
    Shadow/Highlight Tint : warm (+) / cool (-) additive split toning,
                            weighted by luminance so it only affects the
                            relevant tonal zone.
    """
    vibrance       = getattr(params, 'vibrance',       0.0)
    color_sat      = getattr(params, 'color_sat',      0.0)
    shadow_tint    = getattr(params, 'shadow_tint',    0.0)
    highlight_tint = getattr(params, 'highlight_tint', 0.0)

    if (abs(vibrance) < 1e-4 and abs(color_sat) < 1e-4 and
            abs(shadow_tint) < 1e-4 and abs(highlight_tint) < 1e-4):
        return img

    out = np.clip(img, 0.0, 1.0)

    # Vibrance + global saturation in HSV space
    if abs(vibrance) > 1e-4 or abs(color_sat) > 1e-4:
        hsv = _rgb_to_hsv(out)
        s   = hsv[:, :, 1]
        if abs(color_sat) > 1e-4:
            # Multiplicative: +1 doubles saturation, -1 desaturates fully
            s = np.clip(s * (1.0 + color_sat), 0.0, 1.0)
        if abs(vibrance) > 1e-4:
            # Boost less-saturated pixels more (protects already vivid colours)
            s = np.clip(s + vibrance * (1.0 - s) * 0.6, 0.0, 1.0)
        hsv[:, :, 1] = s
        out = np.clip(_hsv_to_rgb(hsv), 0.0, 1.0)

    # Split toning: warm / cool tint in shadows and highlights separately
    TINT_STR = 0.12
    if abs(shadow_tint) > 1e-4 or abs(highlight_tint) > 1e-4:
        lum = (0.2126 * out[:, :, 0] +
               0.7152 * out[:, :, 1] +
               0.0722 * out[:, :, 2])[:, :, np.newaxis]
        if abs(shadow_tint) > 1e-4:
            # Weight peaks at black, falls to 0 at ~40% luminance
            w    = np.clip(1.0 - lum * 2.5, 0.0, 1.0)
            tint = np.array([[[shadow_tint * TINT_STR,
                                shadow_tint * TINT_STR * 0.15,
                               -shadow_tint * TINT_STR]]])
            out  = np.clip(out + w * tint, 0.0, 1.0)
        if abs(highlight_tint) > 1e-4:
            # Weight peaks at white, falls to 0 at ~60% luminance
            w    = np.clip(lum * 2.5 - 1.5, 0.0, 1.0)
            tint = np.array([[[highlight_tint * TINT_STR,
                                highlight_tint * TINT_STR * 0.15,
                               -highlight_tint * TINT_STR]]])
            out  = np.clip(out + w * tint, 0.0, 1.0)

    return out


# ─────────────────────────────────────────────────────────── #
# Remaining helpers (unchanged)                               #
# ─────────────────────────────────────────────────────────── #

def _catmull_rom_lut(xs, ys, lut_x):
    xs_ext = np.concatenate([[xs[0] - (xs[1] - xs[0])], xs, [xs[-1] + (xs[-1] - xs[-2])]])
    ys_ext = np.concatenate([[ys[0]], ys, [ys[-1]]])
    out = np.empty_like(lut_x)
    for i, x in enumerate(lut_x):
        seg = np.clip(np.searchsorted(xs, x, side='right') - 1, 0, len(xs) - 2)
        t   = (x - xs[seg]) / max(xs[seg + 1] - xs[seg], 1e-9)
        p0, p1, p2, p3 = ys_ext[seg], ys_ext[seg+1], ys_ext[seg+2], ys_ext[seg+3]
        out[i] = 0.5 * ((2*p1) + (-p0+p2)*t + (2*p0-5*p1+4*p2-p3)*t**2
                         + (-p0+3*p1-3*p2+p3)*t**3)
    return out


def _median_filter(img: np.ndarray, radius: int) -> np.ndarray:
    try:
        from scipy.ndimage import median_filter
        size = 2 * radius + 1
        return np.stack([median_filter(img[:, :, c], size=size) for c in range(3)], axis=-1)
    except ImportError:
        import cv2
        ksize = max(3, 2 * radius + 1) | 1
        return np.stack([
            cv2.medianBlur((img[:, :, c] * 65535).astype(np.uint16), ksize).astype(np.float64) / 65535.0
            for c in range(3)
        ], axis=-1)


def detect_film_base(image: np.ndarray) -> tuple:
    """Public helper: return (R, G, B) film base in 0..65535 range."""
    img    = np.clip(image / _MAX16, _EPS, 1.0)
    H, W   = img.shape[:2]
    centre = img[H // 6 : 5 * H // 6, W // 8 : 7 * W // 8]
    base   = np.array([np.percentile(centre[:, :, c], 95) for c in range(3)])
    return tuple((base * _MAX16).tolist())

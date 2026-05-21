# CLAUDE.md — AI agent context for Film Negative Converter

This file gives an AI coding assistant everything it needs to understand the codebase and continue development without re-reading every file from scratch.

---

## What this project is

A Python + PyQt5 desktop app that converts scanned colour film negatives (Sony ARW and other RAW formats) into 16-bit TIFF positive images. The user scans film negatives with a digital camera and this app inverts, colour-corrects, and exports them.

**Run the app:** `python main.py` from the project root.

---

## Tech stack

| Layer | Library | Version |
|---|---|---|
| GUI | PyQt5 | 5.15+ |
| RAW decoding | rawpy (LibRaw) | 0.18+ |
| Numerical processing | numpy | 1.24+ |
| TIFF export | tifffile | 2023+ |
| Curve interpolation | scipy (PchipInterpolator) | 1.11+ |
| Dust removal | scipy.ndimage / OpenCV | — |
| Image codecs | imagecodecs | 2023+ |

Python 3.10+ required (uses `match`, `X | Y` union types).

---

## Architecture overview

```
main.py
  └── gui/main_window.py  (MainWindow)
        ├── gui/file_list_widget.py   (FileListWidget)    — file queue + per-file params
        ├── gui/preview_widget.py     (PreviewWidget)     — before/after split view
        ├── gui/controls_panel.py     (ControlsPanel)     — all adjustment sliders
        ├── gui/histogram_widget.py   (HistogramWidget)   — RGB histogram
        └── gui/preview_worker.py     (PreviewWorker)     — QThread for background preview
              └── core/negative_inverter.py  (invert_negative)
              └── core/raw_processor.py      (load_raw, load_raw_thumbnail)
```

### Key data flow

1. User selects a file → `MainWindow._on_file_selected`
2. `PreviewWorker` is spawned with current `InversionParams`
3. Worker decodes RAW once → caches the downsampled linear float64 array in `MainWindow._raw_cache[path]`
4. On subsequent slider changes → worker reuses the cached RAW, only runs `invert_negative()` again
5. Result (`positive` float64 0..1) is emitted via signal → `MainWindow._on_preview_ready` → updates preview + histogram
6. On export → `BatchWorker` in `core/batch_processor.py` runs the full pipeline at full resolution

### Thread safety

- **Generation counter** (`_preview_gen: int`): incremented every time a new preview starts. Workers embed their generation at creation time; stale results are silently discarded in `_on_preview_ready`.
- **Cooperative abort**: `PreviewWorker.abort()` sets `_abort = True`; the worker checks this flag between its 3 main steps (load → invert → thumb). No `terminate()` calls.
- **No Qt calls from worker threads** — only signals are emitted, never widget methods called directly.

---

## The processing pipeline (`core/negative_inverter.py`)

`invert_negative(image, params)` takes a `float64 (H, W, 3)` linear RAW array (values 0..65535) and returns a `float64 (H, W, 3)` gamma-encoded image (values 0..1).

Steps in order:

| # | Step | Notes |
|---|---|---|
| 1 | Normalise to 0..1 | `clip(image / 65535, eps, 1-eps)` |
| 2 | Dust removal | Optional median filter |
| 3 | Film base detection | 95th percentile of centre crop, or manual override |
| 4 | Log-density inversion | `density = log10(base / pixel)` |
| 5 | Percentile stretch | Per-channel clip at `black_clip_pct` / `white_clip_pct` |
| 6 | White balance | R/G/B multipliers from profile + `wb_red/green/blue` |
| 7 | Exposure | `pixel * 2^stops` |
| 8 | Temp / Tint | Small additive RGB shifts — TEMP_STR=0.10, TINT_STR=0.08 |
| 9 | Contrast / Lift / Gain | Power-law contrast curve |
| 10 | Legacy CMY | Only active for old presets with non-zero CMY fields |
| 11 | B&W desaturation | For profiles with `_desaturate: True` |
| 12 | Gamma encoding | `pixel ^ (1/gamma)`, default gamma=2.2 |
| 13 | Tone controls | Blacks/Whites (quadratic falloff), Shadows/Highlights (linear) |
| 14 | HSL per-colour | Red/Green/Blue selective Hue/Saturation/Luminance |
| 15 | Color grading | Vibrance + Saturation + Shadow/Highlight Tint |
| 16 | Rotation | `np.rot90(...).copy()` — copy is REQUIRED, rot90 returns a non-contiguous view |

**Important:** Steps 13–16 operate in **perceptual (gamma-encoded) space**, not linear light. This is intentional — it matches how photo editors work and makes the controls feel intuitive.

---

## InversionParams dataclass

All controls live in `core/negative_inverter.py` as a `@dataclass`. Key fields:

```python
film_base_rgb:  tuple | None   # None = auto-detect each frame
wb_red/green/blue: float       # Internal WB (used by profiles; not user-facing sliders)
exposure_stops: float
gamma:          float          # default 2.2
contrast:       float          # 1.0 = neutral
lift:           float          # 0.0 = neutral
gain:           float          # 1.0 = neutral
film_profile:   str            # key into FILM_PROFILES dict
temp_shift:     float          # -1..+1, applied as ±0.10 on R/B channels
tint_shift:     float          # -1..+1, applied as ±0.08 on G channel
blacks:         float          # -1..+1, quadratic mask (affects dark tones)
whites:         float          # -1..+1, quadratic mask (affects bright tones)
shadows:        float          # -1..+1, linear mask (lower half of range)
highlights:     float          # -1..+1, linear mask (upper half of range)
curve_shadows/midtones/highlights: float  # S-curve — removed from UI but kept for preset compat
red/green/blue_hue/sat/lum: float         # HSL selective colour
vibrance:       float          # intelligent saturation
color_sat:      float          # global saturation
shadow_tint:    float          # -1 cool .. +1 warm
highlight_tint: float
rotation:       int            # 0, 90, 180, or 270 degrees CW
# Legacy CMY fields (backward compat with old presets, not in UI):
cyan_magenta, cyan_yellow, magenta_yellow: float
```

**Backward compatibility:** `core/presets.py` uses `dataclasses.fields()` to filter valid keys when loading JSON presets, so old presets without new fields simply use the dataclass defaults.

---

## Controls panel (`gui/controls_panel.py`)

Two-tab `QTabWidget`:

- **Adjustments tab**: Film Profile → White Balance (Temp/Tint/Blacks/Whites/Shadows/Highlights) → Tone → Color Grading → Black/White Point → Dust → Export
- **Colors tab**: Red/Green/Blue groups, each with Hue/Saturation/Luminance sliders

**Important:** `get_params()` does NOT set `rotation` or `film_base_rgb` — these are not sliders. `MainWindow._on_params_changed` manually copies `rotation` and `film_base_rgb` from the stored params before saving, to prevent overwriting them every time a slider moves.

`SmoothSlider` is a fully custom-painted slider widget — double-click resets to default. Do not replace with `QSlider` without redoing the paint logic.

---

## Preview worker (`gui/preview_worker.py`)

```python
PreviewWorker(filepath, params, generation, raw_image=None, thumb_image=None)
```

- `raw_image` provided → skip `load_raw()`, use cached downsampled array directly
- `thumb_image` provided → skip `load_raw_thumbnail()`
- Signals: `preview_ready(raw_thumb_uint8, positive_float, generation)`, `raw_loaded(raw_linear_float64)`, `error(str, generation)`
- Abort with `.abort()` — sets `_abort` flag, checked between the 3 steps

---

## File list / per-file state (`gui/file_list_widget.py`)

- `_params: dict[Path, InversionParams]` — per-file settings
- `get_params(path)` returns the stored object directly (not a copy)
- `save_params(path, params)` stores a `deepcopy`
- When adding files, each gets a fresh `InversionParams()` default

---

## Known issues / gotchas

1. **`np.rot90` returns a non-C-contiguous view** — the rotation step MUST call `.copy()` after `np.rot90` or QImage will read garbage memory and segfault. This is already in place.

2. **Saturation in HSL is additive, not multiplicative** — changed from `s * (1 + adj)` to `s + adj` because film inversions often produce low-saturation images where multiplicative changes are invisible.

3. **S-curve widget exists but is not shown** — `SCurveWidget` class is still in `controls_panel.py` and `curve_*` fields are still in `InversionParams` (preset compatibility). The widget is just not instantiated. To re-enable: add `self._build_curve_section()` back to `_build_ui()` and update `get_params()` / `set_params()`.

4. **`film_base_rgb` and `rotation` are not in `get_params()`** — they are preserved explicitly in `MainWindow._on_params_changed` and `_on_file_selected`. Any new fields that are not sliders need the same treatment.

5. **rawpy config matters** — in `core/raw_processor.py`: `use_camera_wb=True` prevents green-channel blowout during Bayer demosaicing. Do NOT change to `use_auto_wb=True`. The `output_color=1` must be an integer (not the `rawpy.ColorSpace` enum) for compatibility.

---

## What's been done (session history)

1. **Performance** — added RAW cache + thumbnail cache; removed `QThread.terminate()` in favour of `abort()` flag + generation counter. Preview is now ~30× faster after first load.

2. **S-curve fixed then removed** — was applied in linear space (did nothing visible); moved to perceptual space; then removed from UI at user request (left in codebase for compat).

3. **UI restructure** — added Blacks/Whites/Shadows/Highlights to White Balance section; added two-tab layout; replaced CMY sliders with Color Grading (Vibrance/Saturation/Split Toning); added Colors tab with R/G/B HSL.

4. **Bug fixes** — Temp/Tint strength reduced (was 3× too strong); Blacks/Whites mask widened to quadratic falloff; HSL saturation changed to additive; rotate crash fixed (.copy() after rot90).

---

## Suggested next tasks

- **PyInstaller packaging** — bundle as `.exe` for Windows. Key gotchas: rawpy needs its LibRaw `.dll` included; a `.spec` file is needed for data files. See `CLAUDE.md` section below.
- **Debounce tuning** — sliders currently fire after 300ms. Could be reduced to 150ms now that the pipeline is fast.
- **Grain simulation** — add `grain_amount: float` to `InversionParams` and apply Gaussian noise in the Color Grading step.
- **Lens correction** — integrate `lensfunpy` for vignetting/distortion removal.
- **Auto white balance** — add a "Match grey point" button that adjusts Temp/Tint to neutralise a user-clicked patch.

### PyInstaller packaging notes

```bash
pip install pyinstaller
pyinstaller --onefile --windowed main.py --name "FilmNegativeConverter"
```

Rawpy ships with a native DLL. If the `.exe` fails to load rawpy, add to the `.spec` file:
```python
datas=[('path/to/libraw.dll', '.')]  # Windows
```

Or use `--collect-all rawpy` flag. The bundled `.exe` will be ~150–200 MB.

---

## File locations

| File | Purpose |
|---|---|
| `core/negative_inverter.py` | All processing logic. Edit this to change the pipeline. |
| `core/raw_processor.py` | RAW loading config. Edit rawpy params here. |
| `gui/controls_panel.py` | All UI controls. Add new sliders here + in `InversionParams`. |
| `gui/main_window.py` | Wiring between UI and processing. Edit signal connections here. |
| `gui/preview_worker.py` | Background thread. Edit the 3-step run() method here. |
| `~/.filmscan/presets/` | User preset JSON files |
| `~/FilmScan_Output/` | Default export destination |

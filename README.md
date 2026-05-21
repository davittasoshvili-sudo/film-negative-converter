# Film Negative Converter

A desktop application for converting scanned colour film negatives (Sony ARW and other RAW formats) into finished 16-bit TIFF positive images. Built with Python, PyQt5, rawpy, and NumPy.

---

## Features

- **Non-destructive RAW processing** — decodes directly from ARW/CR2/NEF/DNG/RAF using LibRaw
- **Split before/after preview** with live RGB histogram
- **Per-file settings** — every image in the queue remembers its own adjustments
- **Film profiles** — Kodak Gold, Kodak Portra, Fuji Velvia, Fuji 400H, Ilford HP5, Neutral
- **White Balance** — Temp/Tint, Blacks/Whites, Shadows/Highlights
- **Tone controls** — Exposure, Contrast, Lift, Gain, Gamma
- **Color Grading** — Vibrance, Saturation, Shadow Tint / Highlight Tint (split toning)
- **Colors tab** — per-colour HSL (Hue/Saturation/Luminance) for Red, Green, Blue ranges
- **Image rotation** — 90° clockwise per click, remembered per file
- **Film base eyedropper** — click the orange border of the negative to set the mask colour manually
- **Dust & scratch removal** — optional median filter
- **Batch export** — queue multiple files, export all as 16-bit TIFF at once
- **Preset save/load** — save your settings as JSON and reload anytime
- **Fast preview** — RAW is decoded once and cached; all subsequent slider changes are near-instant

---

## Installation

**Requirements:** Python 3.10+, pip

```bash
git clone https://github.com/davittasoshvili-sudo/film-negative-converter.git
cd film-negative-converter

# Optional but recommended
python -m venv .venv
.venv\Scripts\activate        # Windows
source .venv/bin/activate     # macOS / Linux

pip install -r requirements.txt
```

> **Windows note:** if `rawpy` fails, try `pip install rawpy --pre`

---

## Running

```bash
python main.py
```

---

## Workflow

### 1. Load files

Drag `.ARW` (or `.CR2`, `.NEF`, `.DNG`, `.RAF`) files onto the file list on the left, or use **File → Open RAW Files** / the toolbar button.

### 2. Set output folder

**File → Set Output Folder** — defaults to `~/FilmScan_Output`.

### 3. Adjust the image

Click a file to load its preview. All changes are live with a short debounce.

| Control | What it does |
|---|---|
| **Film Profile** | Colour/contrast base for common film stocks. Pick this first. |
| **Temp / Tint** | Overall colour cast correction. Full slider = subtle shift by design. |
| **Blacks / Whites** | Pull the shadow and highlight endpoints. Range is −1 to +1. |
| **Shadows / Highlights** | Lift or crush the lower/upper tonal ranges. |
| **Exposure** | Compensate for over/underexposed scans (in stops). |
| **Contrast / Lift / Gain** | Shape the overall tonal response. |
| **Gamma** | Encoding gamma — 2.2 is standard. |
| **Vibrance** | Boosts under-saturated colours more than already-vivid ones. |
| **Saturation** | Global saturation adjustment. |
| **Shadow / Highlight Tint** | Warm (+) or cool (−) tint applied only to shadows/highlights. |
| **Black / White Point** | Percentile clip used during negative inversion itself. |
| **Colors tab** | Selective Hue/Saturation/Luminance for Red, Green, Blue hue ranges. |
| **Dust & Scratch Removal** | Median filter — enable only if needed, it slows export significantly. |

**Tips:**
- Double-click any slider to reset it to its default.
- Use **↻ Rotate** (top of the before panel) to rotate 90° CW.
- Click **💧 Pick Film Base** then click any unexposed border of the negative to lock the orange mask colour. Click **Reset to Auto** to go back to automatic detection.

### 4. Export

- **Export Selected** (`Ctrl+E`) — exports selected file(s) with their individual settings.
- **Batch Export All** (`Ctrl+Shift+E`) — exports every file in the queue.

Output files are named `<original_name>_positive.tif` and written to the output folder as 16-bit TIFF.

### 5. Presets

- **Presets → Save Preset** — saves current settings under a name to `~/.filmscan/presets/`.
- **Presets → Load Preset** — loads any `.json` preset file.

---

## Command-line interface

```bash
# Single file
python cli.py scan.ARW --output ./output

# Whole folder
python cli.py ./negatives/*.ARW --output ./positives

# With options
python cli.py *.ARW --profile kodak_portra --exposure 0.3

# From a saved preset
python cli.py *.ARW --preset my_settings.json

python cli.py --help
```

---

## Processing pipeline

```
RAW file  →  rawpy (LibRaw, AHD demosaicing, linear gamma, 16-bit)
          →  Film base detection (95th percentile of centre crop)
          →  Log-density inversion  (density = log10(base/pixel))
          →  Per-channel percentile stretch (black/white point clip)
          →  White balance multipliers
          →  Exposure compensation
          →  Colour temperature / tint
          →  Film profile contrast/lift/gain
          →  Gamma encoding (default 2.2)
          →  Tone controls: Blacks / Whites / Shadows / Highlights
          →  HSL selective colour (Red / Green / Blue ranges)
          →  Color grading: Vibrance / Saturation / Split Toning
          →  Rotation (if set)
          →  16-bit TIFF export
```

---

## Film profiles

| Profile | Characteristics |
|---|---|
| `neutral` | No adjustment — mathematically pure output |
| `kodak_gold` | Warm, gentle contrast boost, lifted shadows |
| `kodak_portra` | Natural skin tones, low contrast, subtle warmth |
| `fuji_velvia` | Cool, saturated, punchy contrast |
| `fuji_400h` | Flat, cool, pastel |
| `ilford_hp5` | Desaturated to luminance-weighted greyscale |

To add a profile, open `core/negative_inverter.py` and add an entry to `FILM_PROFILES`.

---

## Project structure

```
film-negative-converter/
├── main.py                     Entry point
├── cli.py                      Headless CLI
├── requirements.txt
├── CLAUDE.md                   Context file for AI coding assistants
├── core/
│   ├── negative_inverter.py    Full processing pipeline + InversionParams dataclass
│   ├── raw_processor.py        rawpy RAW decoding helpers
│   ├── batch_processor.py      QThread batch export worker
│   ├── exporter.py             16-bit TIFF writing
│   └── presets.py              JSON preset save/load
└── gui/
    ├── main_window.py          Main window, orchestration, file management
    ├── controls_panel.py       Two-tab adjustment panel (Adjustments + Colors)
    ├── preview_widget.py       Split before/after view, eyedropper, rotate button
    ├── preview_worker.py       QThread preview generator with RAW cache + abort
    ├── file_list_widget.py     File queue with per-file params storage
    └── histogram_widget.py     RGB histogram overlay
```

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| Cyan/green cast | Raise Temp, lower Blue Tint; or manually pick film base |
| Very dark output | Increase Exposure |
| Washed-out colours | Increase Contrast; lower Shadow clip in Black/White Point |
| `rawpy` import error | `pip install rawpy` |
| PyQt5 import error | `pip install PyQt5` |
| Slow export | Disable Dust Removal; it's the most expensive step |

---

## Licence

MIT
